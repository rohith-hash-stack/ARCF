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
"""

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

Selected repository context (already chosen deterministically):
{file_sections}

Relevant symbols:
{symbol_list}

Dependency relationships among the selected files:
{dependency_list}
"""


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
        return _PROMPT_TEMPLATE.format(
            goal=contract.intent.intent,
            success_criteria=success_criteria,
            file_sections=self._file_sections(package.relevant_files),
            symbol_list=symbol_list,
            dependency_list=dependency_list,
        )

    @staticmethod
    def _file_sections(files: list[PackagedFile]) -> str:
        if not files:
            return "(none)"
        return "\n\n".join(
            f"### {f.file_path} ({f.reason})\n```\n{f.content}\n```" for f in files
        )
