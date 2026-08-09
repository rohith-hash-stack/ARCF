"""DrpIndex — bundles every DRP stage's precomputed structure for one
workspace snapshot, mirroring `code_intelligence.index.CodeIntelligenceIndex`'s
own role for the classic pipeline. Built once per resolve call from an
already-built `CodeIntelligenceIndex` (no re-parsing); DRP introduces no
persistence layer of its own, matching the rest of ARCF's in-memory,
rebuilt-per-request indexing model (see engine.py's own docstring on why
there is no on-disk cache today).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from code_intelligence.drp.pmi_expansion import PmiWordGraph, build_pmi_word_graph
from code_intelligence.drp.subsystem_graph import SubsystemGraphResult, build_subsystem_graph
from code_intelligence.drp.taxonomy import SubsystemTaxonomy, build_taxonomy
from code_intelligence.drp.text_corpus import (
    gather_doc_prose,
    gather_file_text,
    gather_scoring_units,
)
from code_intelligence.drp.tfidf import SubsystemTfIdfIndex, build_tfidf_index
from code_intelligence.index import CodeIntelligenceIndex
from workspace.permissions import PermissionManager


@dataclass
class DrpIndex:
    taxonomy: SubsystemTaxonomy
    file_tfidf: SubsystemTfIdfIndex
    """TF-IDF over one document per SCORING UNIT — a whole file for most
    files, or one document per top-level symbol for a file with too many
    unrelated top-level symbols pooled together (see text_corpus.py's
    `gather_scoring_units`). `.profiles`/`.score()` are keyed by unit,
    not necessarily by file path — use `file_to_units` to reconstitute a
    file's own score. Stage 4 aggregates UP from these scores to
    subsystem/community relevance (see query_router.py), rather than
    scoring against one document pooled per subsystem or per file —
    pooling was tried first, at both the subsystem level and (later) the
    file level, and found to systematically favor whatever was smallest/
    least diluted over whatever was correct."""
    file_to_units: dict[str, list[str]]
    """Every file's own scoring-unit key(s) — a single-element list (the
    file path itself) for a file that wasn't split, or one key per top-
    level symbol for one that was. See `gather_scoring_units`."""
    subsystem_graph: SubsystemGraphResult
    pmi_graph: PmiWordGraph | None = None
    """Only built when `DrpIndexBuilder.build(..., enable_pmi_expansion=
    True)` — None otherwise, so the default build path pays zero extra
    cost (no O(n^2)-per-file co-occurrence pass) when this experimental
    extension isn't requested. See pmi_expansion.py."""


class DrpIndexBuilder:
    @staticmethod
    def build(
        index: CodeIntelligenceIndex,
        workspace_root: Path,
        enable_pmi_expansion: bool = False,
        max_files_per_subsystem: int | None = None,
    ) -> DrpIndex:
        """`max_files_per_subsystem` is passed straight through to
        `taxonomy.build_taxonomy` — `None` (the default) uses that
        module's own empirically-calibrated constant; overriding it here
        is mainly useful for tests exercising Stage 1's recursive
        splitting against small synthetic fixtures."""
        taxonomy = (
            build_taxonomy(index, max_files_per_subsystem)
            if max_files_per_subsystem is not None
            else build_taxonomy(index)
        )
        subsystem_graph = build_subsystem_graph(index)

        permissions = PermissionManager(workspace_root)
        unit_texts, file_to_units, unit_usage = gather_scoring_units(index, permissions)

        pmi_graph = None
        if enable_pmi_expansion:
            # Deliberately wider than file_tfidf's own corpus, and
            # deliberately whole-file (not split per-symbol) — see
            # gather_doc_prose's docstring for why doc/README text is
            # safe to use for word-association learning even though
            # it's unsafe to use for direct file-selection scoring, and
            # gather_file_text's own contract for why PMI's co-occurrence
            # window stays file-granularity regardless of how finely
            # file_tfidf itself scores.
            file_texts = gather_file_text(index, permissions)
            doc_texts = gather_doc_prose(index, permissions)
            pmi_graph = build_pmi_word_graph({**file_texts, **doc_texts})

        return DrpIndex(
            taxonomy=taxonomy,
            file_tfidf=build_tfidf_index(unit_texts, unit_usage),
            file_to_units=file_to_units,
            subsystem_graph=subsystem_graph,
            pmi_graph=pmi_graph,
        )
