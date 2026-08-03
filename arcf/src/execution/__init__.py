"""Execution layer (Phase 8 of the original playbook; Stage 2+ of the
v2.3 migration plan — see arcf/docs/ARCF_v2.3_ARCHITECTURE_REVIEW.md).

- prhl.py: PRHLAnalyzer, an advisory-only predictive hint over a Phase
  6 ContextPackage, modeled on SLM-2's pattern.
- context_goal_composer.py: ContextGoalComposer, pure prompt assembly
  from Contract + ContextPackage + ContextResolutionResult — no LLM
  call, no forced response schema, and structurally forbidden from
  importing prhl.py (PRHL is a sibling output, never a prompt input).
- final_generation.py: FinalGenerationRunner, the actual "final LLM
  call" this pipeline never had before v2.3 — invokes the Composer's
  prompt with no response_format and wraps the result in an Artifact.
"""
