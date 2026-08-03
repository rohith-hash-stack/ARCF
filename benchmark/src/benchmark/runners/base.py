"""Shared generation step both runners use identically — same prompt
template, same LiteLLMClient call — so the only difference between a
Direct result and an ARCF result is what context each mode selected,
never how the final call itself was made.
"""

from dataclasses import dataclass

from infrastructure.cost import CostEstimator
from infrastructure.llm_client import LiteLLMClient, LLMResponse

_PROMPT_TEMPLATE = """You are a software engineering assistant working in an existing \
repository. Complete the following task using ONLY the file context provided below — do not \
invent files or assume content you have not been shown.

Task:
\"\"\"
{task}
\"\"\"

Repository context:
{file_sections}

Provide the code changes needed to complete the task, as a unified diff or complete file \
contents for each file you modify.
"""


@dataclass(frozen=True)
class FileContext:
    file_path: str
    content: str


def compile_prompt(task: str, files: list[FileContext]) -> str:
    if files:
        sections = "\n\n".join(f"### {f.file_path}\n```\n{f.content}\n```" for f in files)
    else:
        sections = "(no file context available)"
    return _PROMPT_TEMPLATE.format(task=task, file_sections=sections)


async def generate(
    llm_client: LiteLLMClient,
    cost_estimator: CostEstimator,
    prompt: str,
    model: str,
    max_output_tokens: int,
) -> tuple[LLMResponse, float, float]:
    """Returns (llm_response, estimated_cost_usd, actual_cost_usd)."""
    estimate = cost_estimator.estimate(prompt, model, max_output_tokens)
    response = await llm_client.complete(prompt, model, max_tokens=max_output_tokens)
    actual_cost = cost_estimator.actual_cost(
        response.prompt_tokens, response.completion_tokens, model
    )
    return response, estimate.estimated_cost_usd, actual_cost
