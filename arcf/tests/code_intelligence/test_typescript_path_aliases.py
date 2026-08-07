from pathlib import Path

from code_intelligence.typescript_path_aliases import load_path_aliases, resolve_with_aliases


def test_no_tsconfig_returns_empty_aliases(tmp_path: Path) -> None:
    assert load_path_aliases(tmp_path) == {}


def test_loads_paths_from_compiler_options(tmp_path: Path) -> None:
    (tmp_path / "tsconfig.json").write_text(
        '{"compilerOptions": {"paths": {"@app/*": ["src/app/*"]}}}'
    )
    assert load_path_aliases(tmp_path) == {"@app/*": ["src/app/*"]}


def test_tolerates_comments_in_tsconfig(tmp_path: Path) -> None:
    (tmp_path / "tsconfig.json").write_text(
        "{\n"
        "  // comment\n"
        '  "compilerOptions": {\n'
        "    /* block comment */\n"
        '    "paths": {"@app/*": ["src/app/*"]}\n'
        "  }\n"
        "}\n"
    )
    assert load_path_aliases(tmp_path) == {"@app/*": ["src/app/*"]}


def test_malformed_tsconfig_returns_empty(tmp_path: Path) -> None:
    (tmp_path / "tsconfig.json").write_text("{not valid json")
    assert load_path_aliases(tmp_path) == {}


def test_missing_paths_key_returns_empty(tmp_path: Path) -> None:
    (tmp_path / "tsconfig.json").write_text('{"compilerOptions": {}}')
    assert load_path_aliases(tmp_path) == {}


def test_resolve_with_wildcard_alias() -> None:
    aliases = {"@app/*": ["src/app/*"]}
    files = frozenset({"src/app/utils.ts"})
    assert resolve_with_aliases("@app/utils", aliases, files) == "src/app/utils.ts"


def test_resolve_with_exact_alias() -> None:
    aliases = {"@config": ["src/config/index"]}
    files = frozenset({"src/config/index.ts"})
    assert resolve_with_aliases("@config", aliases, files) == "src/config/index.ts"


def test_resolve_tries_multiple_target_candidates() -> None:
    aliases = {"@app/*": ["src/app/*", "lib/app/*"]}
    files = frozenset({"lib/app/utils.ts"})
    assert resolve_with_aliases("@app/utils", aliases, files) == "lib/app/utils.ts"


def test_resolve_returns_none_when_nothing_matches() -> None:
    aliases = {"@app/*": ["src/app/*"]}
    files = frozenset({"src/other/utils.ts"})
    assert resolve_with_aliases("@app/utils", aliases, files) is None


def test_resolve_returns_none_for_unrelated_specifier() -> None:
    aliases = {"@app/*": ["src/app/*"]}
    files = frozenset({"src/app/utils.ts"})
    assert resolve_with_aliases("react", aliases, files) is None


def test_resolve_index_suffix_candidate() -> None:
    aliases = {"@app/*": ["src/app/*"]}
    files = frozenset({"src/app/utils/index.ts"})
    assert resolve_with_aliases("@app/utils", aliases, files) == "src/app/utils/index.ts"
