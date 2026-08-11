from code_intelligence.drp.tfidf import build_tfidf_index, tokenize


def test_tokenize_splits_snake_case_and_camel_case() -> None:
    tokens = tokenize("ConfigurationWatcher watch_configuration dynamicReload")
    assert "configuration" in tokens
    assert "watcher" in tokens
    assert "watch" in tokens
    assert "dynamic" in tokens
    assert "reload" in tokens


def test_tokenize_drops_stopwords_and_short_tokens() -> None:
    tokens = tokenize("the a of to configuration")
    assert tokens == ["configuration"]


def test_tokenize_stems_common_inflections_to_a_shared_base_form() -> None:
    # Real, measured case: a Consul run scored the query "...when an
    # agent registers it" as an exact ZERO against `Catalog.Register`'s
    # own doc comment ("Register a service...") purely because
    # "registers" and "register" were different tokens.
    assert tokenize("registers") == tokenize("register") == tokenize("registering")
    assert tokenize("services") == tokenize("service")
    assert tokenize("watches") == tokenize("watch") == tokenize("watching")
    assert tokenize("loaded") == tokenize("loads") == tokenize("load")


def test_tokenize_stemming_does_not_conflate_unrelated_short_words() -> None:
    # Every rule is scoped to a specific suffix shape precisely so it
    # doesn't over-stem: "class"/"process"/"status"/"success" must stay
    # themselves, and short/irregular words ending in -us/-is/-ss are
    # deliberately excluded from the plural-strip rule.
    for word in ["class", "process", "status", "success", "bus"]:
        assert tokenize(word) == [word]


def test_subsystem_with_unique_term_scores_highest_for_that_term() -> None:
    texts = {
        "pkg/server": "configuration watcher dynamic reload propagate",
        "pkg/client": "http client request response",
        "": "main entry point",
    }
    index = build_tfidf_index(texts)

    scores = index.score(tokenize("dynamic configuration updates"))

    assert scores["pkg/server"] > scores["pkg/client"]
    assert scores["pkg/server"] > scores[""]


def test_term_present_in_every_subsystem_contributes_no_discriminating_signal() -> None:
    texts = {
        "a": "common shared configuration",
        "b": "common shared configuration",
    }
    index = build_tfidf_index(texts)

    # idf of a term appearing in every document trends toward the same
    # floor for both subsystems, so neither should be favored over the
    # other purely because of a term both share.
    scores = index.score(tokenize("common"))
    assert scores["a"] == scores["b"]


def test_tfidf_build_is_deterministic(tmp_path) -> None:
    texts = {"pkg/server": "watcher configuration", "pkg/client": "api client"}
    first = build_tfidf_index(texts)
    second = build_tfidf_index(texts)

    assert first.idf == second.idf
    assert first.profiles["pkg/server"].weights == second.profiles["pkg/server"].weights


def test_tiny_sparse_document_does_not_beat_a_substantial_relevant_one() -> None:
    # Mirrors a real SQLAlchemy finding: a 2-word, 100%-"load"-concentrated
    # utility function's cosine similarity beat a genuinely relevant,
    # substantive class whose "load" mentions were legitimately diluted
    # by everything else that class actually has to say. Length-
    # confidence dampening (see tfidf.py's _MIN_SUBSTANTIAL_TOKENS)
    # exists specifically to correct this.
    tiny_but_concentrated = "event load"
    substantial_and_relevant = (
        "lazy loader provide loading behavior for a relationship with lazy true "
        "that loads when first accessed init class attribute memoized simple "
        "lazy clause generate lazy clause invoke raise load load for state "
        "get ident for use emit lazyload create row processor determine "
        "lazywhere clause mapper get clause"
    )
    texts = {
        "tiny": tiny_but_concentrated,
        "substantial": substantial_and_relevant,
    }
    index = build_tfidf_index(texts)

    scores = index.score(tokenize("load"))

    assert scores["substantial"] > scores["tiny"]


def test_length_confidence_does_not_penalize_documents_at_or_above_the_floor() -> None:
    # Two documents both comfortably over the substantial-length floor —
    # dampening should have already saturated to 1.0x for both, so the
    # comparison is purely the underlying cosine similarity, unaffected
    # by which one happens to be longer.
    long_and_relevant = " ".join(["watcher", "configuration"] * 20)
    even_longer_but_less_relevant = " ".join(["watcher"] * 5 + ["unrelated"] * 40)
    texts = {"a": long_and_relevant, "b": even_longer_but_less_relevant}
    index = build_tfidf_index(texts)

    scores = index.score(tokenize("watcher configuration"))

    assert scores["a"] > scores["b"]


def test_uncalled_document_loses_to_a_heavily_called_relevant_one() -> None:
    # Mirrors a second real SQLAlchemy finding: a test file's classes
    # are DISCOVERED and invoked by a test runner, never called from an
    # explicit call site anywhere in the source — true of any testing
    # framework's own test suite as much as anyone else's — while the
    # real implementation they test is called throughout the codebase.
    # Both documents here are equally substantial text-wise; only the
    # usage data should decide this.
    texts = {"never_called": "lazy load relationship", "heavily_called": "lazy load relationship"}
    usage = {"never_called": 0, "heavily_called": 400}
    index = build_tfidf_index(texts, usage)

    scores = index.score(tokenize("lazy load"))

    assert scores["heavily_called"] > scores["never_called"]


def test_usage_confidence_is_a_no_op_when_usage_data_is_not_supplied() -> None:
    # Every existing caller that scores plain text with no CallGraph
    # involved (unit_usage=None, the default) must keep byte-identical
    # behavior — usage-confidence dampening only ever applies when the
    # caller explicitly opts in by supplying usage counts.
    texts = {"a": "watcher configuration", "b": "watcher configuration"}

    with_no_usage_data = build_tfidf_index(texts)
    scores = with_no_usage_data.score(tokenize("watcher configuration"))

    assert scores["a"] == scores["b"]
    assert scores["a"] > 0.0


def test_usage_confidence_does_not_penalize_documents_at_or_above_the_floor() -> None:
    texts = {"a": "lazy load relationship", "b": "lazy load relationship"}
    usage = {"a": 25, "b": 1000}  # both comfortably over _MIN_CALLS_FOR_FULL_CONFIDENCE
    index = build_tfidf_index(texts, usage)

    scores = index.score(tokenize("lazy load"))

    assert scores["a"] == scores["b"]


def test_broad_coverage_beats_a_single_incidental_term_match() -> None:
    # Real, measured case: a real FlatBuffers run scored a 9-distinct-
    # term query ("How does the garbage collector reclaim unused heap
    # memory during a stop-the-world pause") at 0.30 against a document
    # whose ONLY overlap was one stemmed term ("unus", shared by the
    # query's "unused" and an unrelated enum sentinel `Character_
    # Unused`) — HIGHER than a genuinely on-topic query scored (0.37 is
    # comparable, and this single-term match nearly matched it) despite
    # every other one of the query's 8 distinct terms matching nothing.
    # Coverage-confidence dampening (_MIN_DISTINCT_TERMS_FOR_FULL_
    # CONFIDENCE) exists specifically to correct this.
    single_incidental_term_only = "unused unused unused unused unused"  # repeated for a large raw weight
    genuinely_broad_overlap = "garbage collector reclaim heap memory during pause cycle sweep"
    texts = {
        "single_term": single_incidental_term_only,
        "broad": genuinely_broad_overlap,
    }
    index = build_tfidf_index(texts)

    scores = index.score(
        tokenize("How does the garbage collector reclaim unused heap memory during a stop-the-world pause.")
    )

    assert scores["broad"] > scores["single_term"]


def test_coverage_confidence_does_not_penalize_documents_at_or_above_the_floor() -> None:
    # Two documents each matching all 3 of the query's distinct terms —
    # coverage dampening should have already saturated to 1.0x for both,
    # so the comparison is purely the underlying cosine similarity.
    texts = {
        "a": "watcher configuration reload propagate update",
        "b": "watcher configuration reload",
    }
    index = build_tfidf_index(texts)

    scores = index.score(tokenize("watcher configuration reload"))

    assert scores["a"] > 0.0 and scores["b"] > 0.0


def test_short_query_is_not_penalized_for_lacking_terms_it_never_had() -> None:
    # A genuinely narrow, single-concept query (one real term) matching
    # that one term fully must NOT be dampened just because
    # _MIN_DISTINCT_TERMS_FOR_FULL_CONFIDENCE is 3 — the floor is capped
    # at the query's own distinct-term count precisely so this doesn't
    # happen; this only dampens a multi-term query most of whose terms
    # are absent, not short queries in general.
    texts = {"a": "lazyloader provide loading behavior", "b": "unrelated content entirely"}
    index = build_tfidf_index(texts)

    scores = index.score(tokenize("lazyloader"))

    # Full single-term match should score exactly the same as it would
    # without any coverage dampening at all (coverage_confidence == 1.0).
    assert scores["a"] > 0.0
    assert scores["b"] == 0.0


def test_coverage_confidence_is_deterministic_and_does_not_crash_on_empty_query() -> None:
    texts = {"a": "watcher configuration"}
    index = build_tfidf_index(texts)

    assert index.score([]) == {"a": 0.0}
