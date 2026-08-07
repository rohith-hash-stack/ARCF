"""Python `src/`-layout import resolution (ARCF architecture hardening
§6) — a deterministic post-processing pass over already-extracted
ImportReferences, applied by CodeIntelligenceEngine.build_index for the
same reason typescript_path_aliases.py is: PythonLanguageAnalyzer's
analyze_file signature stays identical to every other LanguageAnalyzer's,
so this lives outside it rather than inside.

Absolute imports (`import mypackage.utils`, `from mypackage import
utils`) are written against the *package* name, not the workspace-
relative file path — in a `src/` layout (`src/mypackage/utils.py`) that
resolves for free once "src/" is tried as an extra prefix.
PythonLanguageAnalyzer's own relative-import resolution (`from . import
x`) is already layout-independent (computed from the importing file's
own directory), so this only ever needs to help absolute imports.
"""

_RESOLUTION_SUFFIXES = (".py", "/__init__.py")


def resolve_with_src_layout(
    raw_module: str, imported_names: list[str], workspace_files: frozenset[str]
) -> str | None:
    if raw_module.startswith("."):
        return None  # Relative import — already resolved correctly, or genuinely missing.

    base_parts = [part for part in raw_module.split(".") if part]
    if not base_parts:
        return None

    candidate_part_lists = [base_parts]
    if len(imported_names) == 1 and imported_names[0] not in ("*", ""):
        candidate_part_lists.append([*base_parts, *imported_names[0].split(".")])

    for parts in candidate_part_lists:
        candidate = "src/" + "/".join(parts)
        for suffix in _RESOLUTION_SUFFIXES:
            candidate_path = candidate + suffix
            if candidate_path in workspace_files:
                return candidate_path
    return None
