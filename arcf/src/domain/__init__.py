"""Pure data models shared across every ARCF layer.

No I/O, no business logic — behavior lives in the layer that owns it
(contracts/, code_intelligence/, etc.), introduced in later phases.
"""

from domain.artifact import Artifact
from domain.code_intelligence import (
    CallReference,
    FileAnalysis,
    ImportReference,
    SourceLocation,
    Symbol,
    SymbolKind,
)
from domain.comparison_result import ComparisonResult
from domain.complexity import ComplexityScore
from domain.context_package import ContextPackage, PackagedFile
from domain.context_resolution import (
    CallEdge,
    ContextResolutionResult,
    DependencyEdge,
    FileReference,
    SymbolReference,
    TokenEstimate,
)
from domain.contract import Contract
from domain.enums import ArtifactKind, ComplexityLevel, ContractStatus
from domain.execution_context import ExecutionContext, TokenBudget
from domain.execution_ledger import (
    ExecutionLedgerEntry,
    ExecutionMode,
    ExecutionStatus,
    VerificationResult,
)
from domain.intent import UserIntent
from domain.predicted_response import PredictedResponseHint
from domain.principal import Principal
from domain.versioning import LivingContract
from domain.workspace import (
    FrameworkMatch,
    LanguageStat,
    ProjectStructure,
    RepositoryMetadata,
    WorkspaceMetadata,
)

__all__ = [
    "Artifact",
    "ArtifactKind",
    "CallEdge",
    "CallReference",
    "ComparisonResult",
    "ComplexityLevel",
    "ComplexityScore",
    "Contract",
    "ContextPackage",
    "ContextResolutionResult",
    "ContractStatus",
    "DependencyEdge",
    "ExecutionContext",
    "ExecutionLedgerEntry",
    "ExecutionMode",
    "ExecutionStatus",
    "FileAnalysis",
    "FileReference",
    "FrameworkMatch",
    "ImportReference",
    "LanguageStat",
    "LivingContract",
    "PackagedFile",
    "PredictedResponseHint",
    "Principal",
    "ProjectStructure",
    "RepositoryMetadata",
    "SourceLocation",
    "Symbol",
    "SymbolKind",
    "SymbolReference",
    "TokenBudget",
    "TokenEstimate",
    "UserIntent",
    "VerificationResult",
    "WorkspaceMetadata",
]
