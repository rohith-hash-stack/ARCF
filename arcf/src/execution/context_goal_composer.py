"""ContextGoalComposer — Phase 8's prompt assembly, given a name and an
explicit no-forced-schema constraint per the v2.3 brief (see
arcf/docs/ARCF_v2.3_ARCHITECTURE_REVIEW.md Sec. 2.1/6/7).

Takes a Contract (already carrying UserIntent + success_criteria), the
ContextPackage Phase 6 built for it, and the ContextResolutionResult
that ContextPackage was itself built from (for symbol-level detail
ContextPackage doesn't carry directly) — all three unchanged, Phase
1-6 inputs. Assembles ONE final prompt: task goal, selected repository
context, relevant symbols, dependency relationships, and success
criteria. Nothing here imposes a response schema on the LLM — it is
free to answer in prose, a diff, or full file contents, whichever it
judges best for the task; that freedom is enforced by
final_generation.py never passing response_format to the completion
call, not by anything in this module.

Structural constraint: this module must NEVER import execution.prhl.
PRHL (Sec. 2.2) is a sibling output over the same ContextPackage, not
an input to prompt assembly — giving it no import path here is what
makes "PRHL never influences the final prompt" a structural fact
rather than a convention, verified by
tests/execution/test_context_goal_composer.py.

ARCF-DI wiring (BLUEPRINT.md Phase 0's boundary contract: "ARCF-DI owns
evidence production; contracts/ and execution/ only read it"): once
context/packager.py is given a symbol_index/call_graph/file_analyses
(context/packager.py's own docstring), ContextPackage carries
citation-verified `behavioral_summaries` and per-file `citations`/
`ambiguous_evidence_ids` — this module is the first and only place in
execution/ that reads them, appending them as one additional, clearly-
labeled prompt section. Deliberately gated on `package.behavioral_summaries`
being non-empty: every caller that doesn't populate it (every caller
today — that wiring is a separate, not-yet-done follow-up) gets a
byte-identical prompt to before this change, verified by
test_prompt_is_byte_identical_when_behavioral_summaries_absent. This
section is additive evidence for the model to use, same as
`file_sections`/`symbol_list`/`dependency_list` above it — it does not
change final_generation.py's own no-`response_format` guarantee, and
the evidence itself is exactly what ARCF-DI already verified (citation-
checked, never invented); this module doesn't re-verify it, only
renders it.
"""

from context.evidence_fallback import build_repository_summary
from domain.context_package import ContextPackage, PackagedFile
from domain.context_resolution import ContextResolutionResult
from domain.contract import Contract

_PROMPT_TEMPLATE = """You are assisting with a software engineering task. Use the goal, \
selected repository context, relevant symbols, dependency relationships, and success \
criteria below to produce your response. Answer however best fits the task — prose, a \
unified diff, or complete file contents are all acceptable; nothing here constrains your \
output format.

Goal:
{goal}

Success criteria:
{success_criteria}
{repository_summary}
Selected repository context (already chosen deterministically):
{file_sections}

Relevant symbols:
{symbol_list}

Dependency relationships among the selected files:
{dependency_list}
{evidence_section}"""


class ContextGoalComposer:
    def compose(
        self,
        contract: Contract,
        package: ContextPackage,
        resolution: ContextResolutionResult,
    ) -> str:
        success_criteria = (
            "\n".join(f"- {c}" for c in contract.success_criteria) or "(none specified)"
        )
        symbol_list = (
            "\n".join(f"- {s.qualified_name} ({s.kind})" for s in resolution.entry_points)
            or "(none)"
        )
        dependency_list = (
            "\n".join(f"- {e.from_file} -> {e.to_file}" for e in package.dependency_chain)
            or "(none)"
        )
        summary = build_repository_summary(package.relevant_files)
        return _PROMPT_TEMPLATE.format(
            goal=contract.intent.intent,
            success_criteria=success_criteria,
            repository_summary=f"\n{summary}\n" if summary else "",
            file_sections=self._file_sections(package.relevant_files),
            symbol_list=symbol_list,
            dependency_list=dependency_list,
            evidence_section=self._evidence_section(package),
        )

    @staticmethod
    def _file_sections(files: list[PackagedFile]) -> str:
        if not files:
            return "(none)"
        return "\n\n".join(
            f"### {f.file_path} ({f.reason})\n```\n{f.content}\n```" for f in files
        )

    @staticmethod
    def _evidence_section(package: ContextPackage) -> str:
        """Empty string when `package.behavioral_summaries` is empty —
        the exact condition every caller before this change satisfies,
        so the composed prompt is byte-identical to before for them.
        Never re-derives or re-verifies anything: every value rendered
        here already passed context/evidence_summarizer.py's
        citation/denylist verification or context/evidence_attribution.py's
        BehavioralRecordBuilder-backed attribution before reaching this
        module."""
        if not package.behavioral_summaries:
            return ""

        lines = [
            "",
            "Deterministic evidence (ARCF-DI — compressed and citation-verified; "
            "never invented, only ever compressed from real static-analysis facts):",
        ]
        for evidence_summary in package.behavioral_summaries:
            if evidence_summary.insufficient_evidence or not evidence_summary.text:
                continue
            cites = (
                ", ".join(evidence_summary.citations) if evidence_summary.citations else "(none)"
            )
            lines.append(
                f"- {evidence_summary.symbol_id}: {evidence_summary.text} [cites: {cites}]"
            )

        cited_files = [f for f in package.relevant_files if f.citations]
        if cited_files:
            lines.append("")
            lines.append("Evidence citations by file:")
            for f in cited_files:
                lines.append(f"- {f.file_path}: {', '.join(f.citations)}")

        ambiguous_files = [f for f in package.relevant_files if f.ambiguous_evidence_ids]
        if ambiguous_files:
            lines.append("")
            lines.append(
                "Ambiguity warnings (call could not be resolved to a single definition — "
                "treat with appropriate caution):"
            )
            for f in ambiguous_files:
                lines.append(f"- {f.file_path}: {', '.join(f.ambiguous_evidence_ids)}")

        return "\n".join(lines) + "\n"
