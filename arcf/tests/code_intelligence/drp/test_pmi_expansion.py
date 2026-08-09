from code_intelligence.drp.pmi_expansion import (
    PmiWordGraph,
    build_pmi_word_graph,
    expand_query_terms,
)
from code_intelligence.drp.tfidf import SubsystemTfIdfIndex


def _hub_and_pair_fixture() -> dict[str, str]:
    # "config" is a hub — present in every file, carries no information.
    # "watcher"/"apply" co-occur ONLY with each other (and the hub),
    # in a small, distinct subset of files.
    texts = {
        "f1.py": "config watcher apply reload",
        "f2.py": "config watcher apply reload",
        "f3.py": "config watcher apply reload",
    }
    for i in range(4, 11):
        texts[f"f{i}.py"] = f"config filler{i}"
    return texts


def test_genuinely_associated_words_get_positive_ppmi() -> None:
    graph = build_pmi_word_graph(_hub_and_pair_fixture())
    neighbors = dict(graph.top_neighbors("watcher", 10))
    assert "apply" in neighbors
    assert neighbors["apply"] > 0.0


def test_hub_word_never_becomes_a_neighbor_despite_high_raw_co_occurrence() -> None:
    # "config" co-occurs with "watcher" in exactly the same 3 files as
    # "apply" does — same raw count — but config's own document
    # frequency is 10/10, so its PPMI with anything is exactly 0
    # (log(1) == 0) and gets clipped, never surfacing as a neighbor.
    # This is the actual mechanism, not just an assertion on the number.
    graph = build_pmi_word_graph(_hub_and_pair_fixture())
    watcher_neighbors = {term for term, _ in graph.top_neighbors("watcher", 10)}
    assert "config" not in watcher_neighbors
    assert "apply" in watcher_neighbors


def test_single_file_coincidence_is_excluded_by_min_co_document_frequency() -> None:
    texts = {
        "only.py": "raretermone raretermtwo",
        "other.py": "unrelated words entirely",
    }
    graph = build_pmi_word_graph(texts)
    neighbors = {term for term, _ in graph.top_neighbors("raretermone", 10)}
    assert "raretermtwo" not in neighbors


def test_pair_repeated_across_two_files_clears_the_min_frequency_bar() -> None:
    texts = {
        "a.py": "raretermone raretermtwo",
        "b.py": "raretermone raretermtwo",
        "c.py": "unrelated words entirely",
    }
    graph = build_pmi_word_graph(texts)
    neighbors = {term for term, _ in graph.top_neighbors("raretermone", 10)}
    assert "raretermtwo" in neighbors


def test_build_is_deterministic_across_repeated_runs() -> None:
    texts = _hub_and_pair_fixture()
    first = build_pmi_word_graph(texts)
    second = build_pmi_word_graph(texts)
    assert first.neighbors == second.neighbors
    assert first.document_count == second.document_count


def test_empty_corpus_yields_empty_graph() -> None:
    graph = build_pmi_word_graph({})
    assert graph.neighbors == {}
    assert graph.document_count == 0


def test_expand_query_terms_skips_words_already_covered_by_file_tfidf() -> None:
    graph = build_pmi_word_graph(_hub_and_pair_fixture())
    file_tfidf = SubsystemTfIdfIndex(profiles={}, idf={"watcher": 1.5})

    expansion = expand_query_terms(["watcher", "restarting"], file_tfidf, graph)

    assert "watcher" not in expansion.expanded_terms
    assert "restarting" not in expansion.expanded_terms  # not in the PMI graph at all either


def test_expand_query_terms_expands_uncovered_words_found_in_the_pmi_graph() -> None:
    graph = build_pmi_word_graph(_hub_and_pair_fixture())
    file_tfidf = SubsystemTfIdfIndex(profiles={}, idf={})  # nothing covered

    expansion = expand_query_terms(["watcher"], file_tfidf, graph, top_k=2)

    assert "watcher" in expansion.expanded_terms
    neighbor_terms = {term for term, _ in expansion.expanded_terms["watcher"]}
    assert "apply" in neighbor_terms
    assert "apply" in expansion.all_tokens()
    assert "watcher" in expansion.all_tokens()


def test_expand_query_terms_uncovered_word_with_no_pmi_data_expands_to_nothing() -> None:
    graph = PmiWordGraph()
    file_tfidf = SubsystemTfIdfIndex(profiles={}, idf={})

    expansion = expand_query_terms(["restarting"], file_tfidf, graph)

    assert expansion.expanded_terms == {}
    assert expansion.all_tokens() == ["restarting"]
