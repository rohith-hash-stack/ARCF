"""CodeIntelligenceIndex — the Phase 5 deliverable "Code Intelligence
Index" itself: the aggregate of everything CodeIntelligenceEngine
builds for one workspace snapshot.

Not a pydantic domain model like Contract/WorkspaceMetadata: this holds
query-service objects (graphs, indexes) built FROM the IR, not the IR
itself, and isn't meant to be embedded in a Contract or round-tripped
through JSON. It is also not meant to be queried directly by Phase 6 —
that boundary is domain.context_resolution.ContextResolutionResult,
produced by code_intelligence/context_resolver.py, which is the only
other file allowed to hold a reference to this index.

content_hashes is what makes incremental indexing possible: passing a
previous CodeIntelligenceIndex back into
CodeIntelligenceEngine.build_index() lets unchanged files skip
re-parsing entirely. token_counts (per-file, via tiktoken) is computed
alongside content_hashes for the same reason — it's what lets
ContextResolver compute TokenEstimate without re-reading every file.
"""

from dataclasses import dataclass

from code_intelligence.call_graph import CallGraph
from code_intelligence.candidate_selector import CandidateFileSelector
from code_intelligence.dependency_graph import DependencyGraph
from code_intelligence.import_graph import ImportGraph
from code_intelligence.inheritance_graph import InheritanceGraph
from code_intelligence.symbol_index import SymbolIndex
from domain.code_intelligence import FileAnalysis


@dataclass
class CodeIntelligenceIndex:
    file_analyses: dict[str, FileAnalysis]
    content_hashes: dict[str, str]
    token_counts: dict[str, int]
    symbol_index: SymbolIndex
    import_graph: ImportGraph
    dependency_graph: DependencyGraph
    inheritance_graph: InheritanceGraph
    call_graph: CallGraph
    candidate_selector: CandidateFileSelector
