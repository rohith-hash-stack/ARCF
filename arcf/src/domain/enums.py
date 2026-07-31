"""Enumerations shared by the domain models.

Kept intentionally small: only values Phase 1 models need to reference
directly. Layer-specific taxonomies (e.g. task/domain classification
labels) belong to the phase that introduces the classifier, not here.
"""

from enum import StrEnum


class ComplexityLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ArtifactKind(StrEnum):
    CODE_CHANGE = "code_change"
    EXPLANATION = "explanation"
    TEST_CASE = "test_case"
    DOCUMENTATION = "documentation"
    STRUCTURED_DATA = "structured_data"


class ContractStatus(StrEnum):
    DRAFT = "draft"
    NEEDS_CLARIFICATION = "needs_clarification"
    APPROVED = "approved"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
