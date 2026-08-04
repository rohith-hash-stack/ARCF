"""Benchmark domain models.

RunResult's headline token/latency/cost metrics describe the FINAL
generation call only (apples-to-apples: Direct makes exactly one LLM
call, so ARCF's comparable figure is its own final call, not the sum
of every LLM call in its pipeline). ARCF's unavoidable SLM-1 (intent
extraction) cost/latency is real and not hidden — it's tracked
separately as pipeline_overhead so it's visible without distorting the
headline "is the final prompt smaller/cheaper/faster" comparison.

contract/context_resolution/context_package (ARCF mode only) are the
actual ARCF domain objects, imported from ARCF and reused directly —
not summarized into new fields. TokenEstimate is already reused this
way too: it lives inside context_resolution.token_estimate.
"""

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from domain.context_package import ContextPackage
from domain.context_resolution import ContextResolutionResult
from domain.contract import Contract
from pydantic import BaseModel, ConfigDict, Field
from shared.clock import utc_now


class BenchmarkMode(StrEnum):
    DIRECT = "direct"
    ARCF = "arcf"
    ARCF_LOCAL = "arcf_local"
    """Mode C: identical ARCF pipeline to ARCF, but SLM-1 (intent
    extraction) runs against a local model instead of a remote one.
    Produced by the exact same ArcfRunner class as ARCF — only the
    slm_model/intent_extractor it's constructed with differs."""


class TokenMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)


class StageLatencies(BaseModel):
    """Per-stage wall time within one ARCF pipeline run (ARCF/ARCF_LOCAL
    modes only — Direct has no deterministic pipeline stages, so its
    RunResult.latency_metrics.stages is None).

    code_intelligence_ms and context_resolution_ms report the SAME
    measured span: ARCF's CodeIntelligenceContractService.attach_code_
    intelligence (arcf/src/code_intelligence/service.py) builds the
    index and resolves context in one atomic call — there is no
    internal seam to split those two timings without modifying Phase 5
    code, which is out of scope here. Reporting a fake split would be
    less honest than reporting the real, single measurement twice.
    """

    model_config = ConfigDict(frozen=True)

    intent_extraction_ms: float = Field(ge=0.0)
    workspace_scan_ms: float = Field(ge=0.0)
    code_intelligence_ms: float = Field(ge=0.0)
    context_resolution_ms: float = Field(ge=0.0)
    context_packaging_ms: float = Field(ge=0.0)
    final_llm_ms: float = Field(ge=0.0)
    total_pipeline_ms: float = Field(ge=0.0)


class QualityMetrics(BaseModel):
    """Structural quality signals computed identically for every mode,
    so they're directly comparable. compilation_success/test_success
    are None ("not attempted") rather than False: auto-applying a
    generated diff to a working tree and running build/test commands
    means executing model-generated code, which is a materially larger
    and riskier scope than this benchmark currently covers — left as an
    explicit, visible gap rather than a silently faked signal.
    """

    model_config = ConfigDict(frozen=True)

    answer_length: int = Field(ge=0)
    modified_files: list[str] = Field(default_factory=list)
    lines_changed: int = Field(default=0, ge=0)
    """Count of added/removed lines when generated_output is unified-
    diff-formatted (quality.count_changed_lines) — 0 for the suite's
    full-file-block output format, since counting there requires
    diffing against the original file content, which this signal
    doesn't have access to. See quality.py's module docstring."""
    compilation_success: bool | None = None
    test_success: bool | None = None


class LatencyMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_ms: float = Field(ge=0.0)
    llm_ms: float = Field(ge=0.0)
    """Wall time of the final generation call only."""
    deterministic_ms: float = Field(ge=0.0)
    """ARCF: workspace attach + code intelligence build (both
    self-documented by ARCF's own routes as making no LLM call). 0 for
    Direct — there is no deterministic pipeline in Direct mode."""
    pipeline_overhead_ms: float = Field(ge=0.0)
    """ARCF: SLM-1 intent extraction (+ context packaging, which may or
    may not include SLM-2). 0 for Direct."""
    stages: StageLatencies | None = None
    """Fine-grained per-stage breakdown (ARCF/ARCF_LOCAL only). None
    for Direct. Additive: total_ms/llm_ms/deterministic_ms/
    pipeline_overhead_ms above are unchanged and still the source of
    truth for BenchmarkAnalyzer's reduction percentages."""


class CostMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    estimated_cost_usd: float = Field(ge=0.0)
    actual_cost_usd: float = Field(ge=0.0)
    """From real provider usage (LLMResponse), via ARCF's own
    CostEstimator.actual_cost — not re-derived."""
    pipeline_overhead_cost_usd: float = Field(ge=0.0)


class ContextMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    repository_files: int = Field(ge=0)
    candidate_files: int = Field(ge=0)
    """Direct: same as repository_files (no candidate selection exists
    in Direct mode). ARCF: len(context_resolution.candidate_files)."""
    files_sent_to_llm: int = Field(ge=0)
    """Files actually present in the final compiled prompt, after any
    budget cap."""


class RunResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    mode: BenchmarkMode
    model: str
    prompt: str = ""
    """The exact compiled prompt sent to the final LLM call — the same
    text LedgerRecorder records, exposed here too so a caller (the
    dashboard) doesn't need a second round-trip to the Execution Ledger
    just to show what was actually asked."""
    generated_output: str
    token_metrics: TokenMetrics
    latency_metrics: LatencyMetrics
    cost_metrics: CostMetrics
    context_metrics: ContextMetrics
    quality_metrics: QualityMetrics

    referenced_files: list[str] = Field(default_factory=list)
    """Relative paths actually placed in the compiled prompt — the same
    files context_metrics.files_sent_to_llm only counts. Populated
    identically by DirectLLMRunner (the files it fit under
    max_context_tokens) and ArcfRunner (context_package.relevant_files),
    so both modes expose what a dashboard would call "files referenced"
    without having to re-derive it from generated_output's text."""

    contract: Contract | None = None
    context_resolution: ContextResolutionResult | None = None
    context_package: ContextPackage | None = None


class ComparisonResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID = Field(default_factory=uuid4)
    task: str
    repository: str
    model: str

    direct: RunResult | None = None
    arcf: RunResult | None = None
    arcf_local: RunResult | None = None
    """Mode C: ARCF + local SLM (see BenchmarkMode.ARCF_LOCAL)."""

    token_reduction_pct: float | None = None
    latency_reduction_pct: float | None = None
    cost_reduction_pct: float | None = None
    context_efficiency_ratio: float | None = None
    """CER = arcf.files_sent_to_llm / direct.files_sent_to_llm."""
    prompt_compression_ratio: float | None = None
    """PCR = direct.input_tokens / arcf.input_tokens."""

    local_token_reduction_pct: float | None = None
    local_latency_reduction_pct: float | None = None
    local_cost_reduction_pct: float | None = None
    local_context_efficiency_ratio: float | None = None
    """CER = arcf_local.files_sent_to_llm / direct.files_sent_to_llm."""
    local_prompt_compression_ratio: float | None = None
    """PCR = direct.input_tokens / arcf_local.input_tokens."""
    local_vs_remote_latency_reduction_pct: float | None = None
    """The hypothesis this benchmark exists to test: positive means
    local SLM intent extraction made the ARCF pipeline faster than the
    remote SLM did, for an identical context/quality outcome."""

    generated_at: datetime = Field(default_factory=utc_now)
