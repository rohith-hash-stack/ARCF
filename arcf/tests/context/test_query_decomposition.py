from context.query_decomposition import decompose_query


def test_decomposes_on_differs_from() -> None:
    axes = decompose_query(
        "Explain how lazy loading differs from eager loading internally "
        "and what SQL each strategy generates."
    )

    assert len(axes) == 2
    assert axes[0].text == "Explain how lazy loading"
    assert axes[1].text.startswith("eager loading internally")


def test_decomposes_on_versus() -> None:
    axes = decompose_query("Compare joined loading versus subquery loading")

    assert len(axes) == 2
    assert axes[0].text == "Compare joined loading"
    assert axes[1].text == "subquery loading"


def test_no_marker_returns_single_axis_unchanged() -> None:
    query = "Explain how request context locals are implemented."

    axes = decompose_query(query)

    assert len(axes) == 1
    assert axes[0].text == query


def test_uses_leftmost_marker_when_multiple_present() -> None:
    # "differs from" appears before "and what" — the split must happen at
    # the leftmost marker, not an arbitrary or later one.
    axes = decompose_query("X differs from Y and what Z does")

    assert axes[0].text == "X"
    assert axes[1].text == "Y and what Z does"


def test_empty_side_after_split_falls_back_to_single_axis() -> None:
    axes = decompose_query("differs from eager loading")

    assert len(axes) == 1
