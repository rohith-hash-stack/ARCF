"""ArcfExecutionOrchestrator -- the application-level orchestration
boundary (architecture closure, 2026-08-16).

Ties the previously disconnected pipeline stages together into one real
execution path: Code Intelligence (retrieval) -> Context Packaging ->
Generation -> Deterministic Grounding Verification -> bounded
deterministic Recovery -> canonical execution result -> Execution
Ledger. Before this, `/api/v1/contracts/{id}/context-package` returned a
ContextPackage directly to the HTTP caller and nothing server-side ever
consumed it; `/api/v1/execute` took a raw prompt with no way to carry a
ContextPackage at all. See ARCF_ARCHITECTURE_CLOSURE_PLAN_2026-08-16.md
Sec. K for why these had to close together, not as separate phases.

Lives in `application/` -- the reserved-but-until-now-empty stub package
the codebase's own docstrings already named as where this belongs:
`interfaces/api/routes/execution_ledger.py`'s own module docstring says
entries are written by "whatever runs the Context + Goal Composer /
FinalGenerationRunner... wiring that end-to-end orchestration is
application/execute_use_case.py's job... not yet built." This is that.

Recovery design (closure plan Sec. J): one MAX_RECOVERY_ATTEMPTS-bounded
loop, a single shared counter across both trigger points --
evidence-categories-missing (checked before spending an LLM call on
generation) and grounding-verification-failure (checked after). The one
allowed alternate strategy is resolver_strategy="drp": ARCF's own
existing, independently-tested DRP resolver (TF-IDF/subsystem taxonomy),
not a new retrieval algorithm and not a blind repeat of the same
strategy -- and, as a direct side effect, DRP finally gets a real
production consumer (closing a separate, previously-flagged gap: DRP was
fully built and wired into code_intelligence/service.py but unreachable
from the live API). Recovery never touches ContextResolver/CallGraph/
SymbolIndex internals -- it only re-invokes the same three already-
public methods (attach_code_intelligence, package, generate) any HTTP
caller could already call individually. No LLM decides whether to
retry, how many times, or which strategy -- both are fixed, hardcoded
control flow in this class.
"""

import asyncio
import time
from uuid import UUID

import logging

from code_intelligence.service import CodeIntelligenceContractService
from context.packager import ContextPackager
from context.task_profile import RANKING_PROFILES, classify_retrieval_task
from contracts.repository_scope_classifier import RepositoryScopeClassifier
from contracts.task_classifier import TaskClassifier
from domain.artifact import Artifact
from domain.context_package import ContextPackage
from domain.context_resolution import ContextResolutionResult
from domain.execution_ledger import ExecutionLedgerEntry, ExecutionStatus
from domain.execution_result import ArcfExecutionResult, ResolverStrategy
from domain.verification_result import GroundingVerificationResult, GroundingVerificationStatus
from execution.final_generation import FinalGenerationRunner
from execution.verification import verify_grounding
from infrastructure.cost import CostEstimator
from infrastructure.execution_ledger_db import ExecutionLedgerStore
from infrastructure.llm_client import LLMInvocationError, LLMResponse
from shared.errors import ContractNotFoundError, NoWorkspaceAttachedError, WorkspacePathError

_logger = logging.getLogger(__name__)

MAX_RECOVERY_ATTEMPTS = 1

# 2026-08-17 hardening (adversarial re-verification): real exceptions
# the retrieval/packaging/generation calls below can actually raise,
# mapped to the closest existing ExecutionStatus value -- not a new
# taxonomy, reusing domain/execution_ledger.py's own vocabulary.
_EXCEPTION_STATUS: dict[type[Exception], ExecutionStatus] = {
    ContractNotFoundError: "validation_error",
    NoWorkspaceAttachedError: "validation_error",
    WorkspacePathError: "validation_error",
    LLMInvocationError: "provider_error",
}


class ArcfExecutionOrchestrator:
    def __init__(
        self,
        code_intelligence_service: CodeIntelligenceContractService,
        context_packager: ContextPackager,
        generation_runner: FinalGenerationRunner,
        execution_ledger_store: ExecutionLedgerStore,
        cost_estimator: CostEstimator,
        generation_model: str,
        max_recovery_attempts: int = MAX_RECOVERY_ATTEMPTS,
        repository_scope_classifier: RepositoryScopeClassifier | None = None,
        task_classifier: TaskClassifier | None = None,
    ) -> None:
        self._code_intelligence_service = code_intelligence_service
        self._context_packager = context_packager
        self._generation_runner = generation_runner
        self._execution_ledger_store = execution_ledger_store
        self._cost_estimator = cost_estimator
        self._generation_model = generation_model
        self._max_recovery_attempts = max_recovery_attempts
        # DI consistency (2026-08-17, independent verification report):
        # these two were previously constructed fresh on every single loop
        # iteration inside run() below -- both are genuinely stateless
        # (no constructor args, pure classification functions), so that
        # was never a correctness bug, but it was inconsistent with "the
        # composition root remains the architectural construction
        # boundary": TaskClassifier is already a DI-injected, composition-
        # root-constructed collaborator for ExecutionContractManager
        # elsewhere in this same app.py, so constructing a second,
        # separate instance here, per-iteration, broke that same
        # single-construction-site discipline for no functional reason.
        # Defaults to a fresh instance only so existing callers/tests that
        # construct this class directly (without wiring these two
        # explicitly) keep working unchanged -- production composition
        # root (interfaces/api/app.py) always passes its own instances.
        self._repository_scope_classifier = repository_scope_classifier or RepositoryScopeClassifier()
        self._task_classifier = task_classifier or TaskClassifier()

    async def run(
        self,
        contract_id: UUID,
        target_names: list[str] | None = None,
        workspace_root: str | None = None,
        max_tokens: int = 8000,
    ) -> ArcfExecutionResult:
        """Raises ContractNotFoundError / NoWorkspaceAttachedError /
        WorkspacePathError / LLMInvocationError exactly like the three
        individual routes this replaces already do -- callers (the new
        HTTP route) convert these to HTTPExceptions the same way
        `code_intelligence.py`/`context_package.py`/`execute.py` already
        do. These are real request/infrastructure failures, not
        grounding-quality outcomes -- conflating them with
        final_status="low_confidence" would misrepresent, e.g., "no such
        contract" as "we tried and weren't confident."
        """
        started_at = time.monotonic()
        attempt = 0
        strategy: ResolverStrategy = "classic"
        llm_responses: list[LLMResponse] = []
        effective_target_names = target_names or []

        # 2026-08-17 hardening (adversarial re-verification): initialized
        # up front, before the loop, so that if an exception interrupts a
        # RETRY iteration -- after attempt 0 already made real, costed LLM
        # calls -- these still hold attempt 0's real values for a
        # best-effort failure ledger entry below, rather than being
        # undefined. resolution/package/raw_request are never actually
        # read from these initial values: llm_responses only becomes
        # non-empty after context_packager.package() has already assigned
        # a real `package` (and, transitively, `resolution`/`raw_request`)
        # this same run, so the "if llm_responses" guard below is what
        # makes reading them safe.
        resolution: ContextResolutionResult | None = None
        package: ContextPackage | None = None
        raw_request = ""
        artifact: Artifact | None = None
        verification: GroundingVerificationResult | None = None
        # G12 (2026-08-17 independent verification report): task-type
        # classification is computed independently in three places across
        # this codebase (here, code_intelligence/service.py's own
        # attach_code_intelligence for its internal traversal_depth
        # choice, and interfaces/api/routes/context_package.py's separate
        # lower-level debug route). All three call the SAME authoritative
        # function (context/task_profile.py's classify_retrieval_task) --
        # no algorithmic drift risk -- so this was never an inconsistent-
        # answer bug, only a call-count one. Fully consolidating across
        # all three would require threading the computed value through
        # ContextResolutionResult/Contract's durable, cross-request
        # contract (the /context-package route runs as a genuinely
        # separate HTTP request, possibly after a restart), a bigger
        # decision this closure pass documents rather than makes silently
        # -- see the closure checklist's G12 entry. WITHIN this
        # orchestrator's own scope, though, the value is a pure function
        # of raw_request, which never changes across a single run()
        # call's own recovery retry -- cached below (None on first
        # iteration) so a retry reuses it instead of recomputing the
        # identical answer a second time.
        retrieval_task_type = None
        ranking_profile = None

        try:
            while True:
                living, resolution = await self._code_intelligence_service.attach_code_intelligence(
                    contract_id, effective_target_names, workspace_root, resolver_strategy=strategy
                )
                raw_request = living.contract.intent.raw_request
                if retrieval_task_type is None:
                    scope_classification = self._repository_scope_classifier.classify(raw_request)
                    task_classifier_task = self._task_classifier.classify(raw_request)
                    retrieval_task_type = classify_retrieval_task(
                        raw_request, task_classifier_task, scope_classification.task_type
                    )
                    ranking_profile = RANKING_PROFILES[retrieval_task_type]

                # Case B (candidates exist, evidence insufficient) --
                # checked BEFORE spending an LLM call on generation, using
                # the already-computed evidence_categories_missing field
                # (context/evidence_validator.py's validate_sufficiency,
                # already run inside attach_code_intelligence).
                if (
                    resolution.evidence_categories_missing
                    and attempt < self._max_recovery_attempts
                ):
                    attempt += 1
                    strategy = "drp"
                    continue

                package, packaging_llm_response = await self._context_packager.package(
                    resolution,
                    raw_request,
                    max_tokens,
                    ranking_profile=ranking_profile,
                    task_type=retrieval_task_type,
                )
                if packaging_llm_response is not None:
                    llm_responses.append(packaging_llm_response)

                artifact, generation_llm_response = await self._generation_runner.generate(
                    living.contract, package, resolution
                )
                llm_responses.append(generation_llm_response)

                # Case C (evidence exists, generation ungrounded) --
                # checked after generation, via the deterministic
                # grounding check.
                verification = verify_grounding(artifact, package, resolution)

                if verification.recovery_eligible and attempt < self._max_recovery_attempts:
                    attempt += 1
                    strategy = "drp"
                    continue

                break
        except Exception as exc:
            # Deliberately broad, not just the 4 named types this method's
            # own docstring documents: an unexpected exception (a
            # transient DB/network error, anything not in
            # _EXCEPTION_STATUS's mapping) is exactly the case real money
            # already spent on a discarded attempt must not go unrecorded
            # for -- it's mapped to "execution_error" below, the same
            # fallback domain/execution_ledger.py's own taxonomy already
            # reserves for "anything else." The original exception is
            # always re-raised unchanged; this never swallows or replaces
            # it.
            if llm_responses:
                # Real money was already spent on a now-discarded attempt
                # -- PS-2 (stored artifacts must correspond to the actual
                # execution) means that spend must still be recorded, not
                # silently lost because the retry that would have
                # completed the run failed. resolution/raw_request are
                # guaranteed set here (see the comment above).
                assert resolution is not None and raw_request
                await self._persist_failure_ledger_entry(
                    exc, contract_id, resolution, package, raw_request,
                    llm_responses, attempt, strategy, started_at,
                )
            raise

        # The loop only reaches `break` after a full iteration completes,
        # which always (re)assigns all five of these -- narrows the type
        # checker's view from `X | None` to `X` and doubles as a runtime
        # sanity check that the loop's own invariant actually held.
        assert resolution is not None
        assert package is not None
        assert artifact is not None
        assert verification is not None

        final_status = (
            "success" if verification.status == GroundingVerificationStatus.SUFFICIENT
            else "low_confidence"
        )

        result = ArcfExecutionResult(
            contract_id=str(contract_id),
            context_resolution_id=resolution.id,
            context_package_id=package.id,
            artifact=artifact,
            verification=verification,
            recovery_attempts=attempt,
            strategy_used=strategy,
            final_status=final_status,
            resolution_confidence=resolution.confidence,
            resolution_confidence_source=strategy,
            llm_responses=tuple(llm_responses),
        )

        await self._persist_ledger_entry(result, resolution, package, raw_request, started_at)
        return result

    async def _persist_ledger_entry(
        self,
        result: ArcfExecutionResult,
        resolution: ContextResolutionResult,
        package: ContextPackage,
        raw_request: str,
        started_at: float,
    ) -> None:
        """G-new-5 (2026-08-17 independent verification): entry
        CONSTRUCTION below (the token/cost aggregation and the
        ExecutionLedgerEntry(...) call itself) previously sat outside any
        try/except, asymmetric with `_save_ledger_entry`'s own store-write
        guard -- an exception raised here (e.g. a future field-validation
        change) would propagate out of `run()` on an otherwise genuinely
        SUCCESSFUL execution, turning a real, complete, correctly-verified
        result into an unhandled 500 for the caller. Ledger persistence is
        audit/observability infrastructure (PS-4, see `_save_ledger_entry`
        below): it must never be able to invalidate an execution that
        already succeeded. Construction is now guarded by the same
        log-and-continue contract already established for the store write
        -- `result` (the actual, already-fully-computed execution outcome,
        including its own real llm_responses for the caller's own cost
        accounting) is unaffected either way; only the ledger's *own*
        durable copy of that accounting is ever at risk here, and its loss
        is now always logged, never silent."""
        try:
            prompt_tokens = sum(r.prompt_tokens for r in result.llm_responses)
            completion_tokens = sum(r.completion_tokens for r in result.llm_responses)
            total_tokens = sum(r.total_tokens for r in result.llm_responses)
            estimated_cost = sum(
                self._cost_estimator.actual_cost(r.prompt_tokens, r.completion_tokens, r.model)
                for r in result.llm_responses
            )
            entry = ExecutionLedgerEntry(
                request_id=result.request_id,
                workspace_id=resolution.workspace_id,
                contract_id=result.contract_id,
                mode="arcf",
                model=self._generation_model,
                repository_root=resolution.repository_root,
                prompt=raw_request,
                selected_files=[f.file_path for f in package.relevant_files],
                selected_symbols=[s.name for s in resolution.entry_points],
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                latency_ms=(time.monotonic() - started_at) * 1000,
                estimated_cost_usd=estimated_cost,
                artifact_content=result.artifact.content if result.artifact is not None else "",
                execution_status="success",
                metadata={
                    "recovery_attempts": result.recovery_attempts,
                    "strategy_used": result.strategy_used,
                    "final_status": result.final_status,
                    "verification_status": (
                        result.verification.status.value
                        if result.verification is not None
                        else None
                    ),
                },
            )
        except Exception:
            _logger.exception(
                "Failed to construct execution ledger entry for successful run %s -- "
                "continuing without persisting it; the execution result itself is unaffected",
                result.request_id,
            )
            return
        await self._save_ledger_entry(entry)

    async def _persist_failure_ledger_entry(
        self,
        exc: Exception,
        contract_id: UUID,
        resolution: ContextResolutionResult,
        package: ContextPackage | None,
        raw_request: str,
        llm_responses: list[LLMResponse],
        attempt: int,
        strategy: ResolverStrategy,
        started_at: float,
    ) -> None:
        """Best-effort record of real spend that happened before a
        request/infrastructure exception interrupted a recovery retry.
        Not the same shape as the success path's ArcfExecutionResult --
        there is no final artifact/verification to report, only the real
        cost already incurred. See run()'s own docstring: the exception
        itself still propagates to the caller unchanged after this.

        Execution-to-ledger contract re-audit (2026-08-17, following
        G-new-5): construction below is guarded the same way the success
        path's `_persist_ledger_entry` now is. This matters more here,
        not less -- this method is called from inside `run()`'s own
        `except Exception as exc:` handler, immediately before `raise`
        re-raises `exc` unchanged. Before this guard, a second exception
        raised during THIS method's own construction (unguarded) would
        propagate instead of the `raise` ever executing, replacing the
        real, original failure reason with an unrelated ledger-construction
        bug -- exactly the "inconsistent audit state" this re-audit exists
        to rule out. `run()`'s own re-raise of the original `exc` is
        unaffected either way now."""
        try:
            prompt_tokens = sum(r.prompt_tokens for r in llm_responses)
            completion_tokens = sum(r.completion_tokens for r in llm_responses)
            total_tokens = sum(r.total_tokens for r in llm_responses)
            estimated_cost = sum(
                self._cost_estimator.actual_cost(r.prompt_tokens, r.completion_tokens, r.model)
                for r in llm_responses
            )
            entry = ExecutionLedgerEntry(
                workspace_id=resolution.workspace_id,
                contract_id=str(contract_id),
                mode="arcf",
                model=self._generation_model,
                repository_root=resolution.repository_root,
                prompt=raw_request,
                selected_files=[f.file_path for f in package.relevant_files] if package else [],
                selected_symbols=[s.name for s in resolution.entry_points],
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                latency_ms=(time.monotonic() - started_at) * 1000,
                estimated_cost_usd=estimated_cost,
                artifact_content="",
                execution_status=_EXCEPTION_STATUS.get(type(exc), "execution_error"),
                metadata={
                    "recovery_attempts": attempt,
                    "strategy_used": strategy,
                    "final_status": None,
                    "verification_status": None,
                    "failure_reason": f"{type(exc).__name__}: {exc}",
                },
            )
        except Exception:
            _logger.exception(
                "Failed to construct failure-path execution ledger entry for contract %s -- "
                "continuing without persisting it; the original exception still propagates "
                "unchanged",
                contract_id,
            )
            return
        await self._save_ledger_entry(entry)

    async def _save_ledger_entry(self, entry: ExecutionLedgerEntry) -> None:
        # PS-4 (persistence failures must not silently corrupt the main
        # execution result): a store write failure here must not turn an
        # otherwise-successful grounded execution into a 500 -- log and
        # continue rather than propagate. This is a narrow, local
        # decision for this specific new call site, not an attempt to fix
        # the pre-existing, unguarded-persistence pattern found elsewhere
        # in this codebase (contracts/manager.py, code_intelligence/
        # service.py, etc.) -- that is a separate, larger, out-of-scope
        # cleanup (see the architecture closure checklist's own
        # "Remaining Genuine Gaps" section).
        try:
            await asyncio.to_thread(self._execution_ledger_store.save, entry)
        except Exception:
            _logger.exception(
                "Failed to persist execution ledger entry %s -- continuing without it",
                entry.request_id,
            )
