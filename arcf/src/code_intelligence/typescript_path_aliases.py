"""TypeScript tsconfig.json `compilerOptions.paths` alias resolution
(ARCF architecture hardening §6).

Deliberately a post-processing pass over already-extracted
ImportReferences (applied by CodeIntelligenceEngine.build_index) rather
than a change to TypeScriptLanguageAnalyzer.analyze_file's signature —
that signature is the LanguageAnalyzer Protocol every one of the six
analyzers implements identically (code_intelligence/language_analyzer.py),
and giving TypeScript a tsconfig-reading side channel there would break
that "adding a language changes only which analyzer is registered"
architectural boundary for no real benefit, since alias remapping is
just another way to compute `resolved_file_path` from already-known
facts (the raw specifier + the workspace file set).

No build-tool execution: tsconfig.json is read and JSON-parsed only
(with a minimal `//`/`/* */` comment strip, since tsconfig commonly
isn't strict JSON) — never invoked as a program, matching the hardening
brief's "no runtime execution" boundary.
"""

import json
import re
from pathlib import Path

_RESOLUTION_SUFFIXES = (
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    "/index.ts",
    "/index.tsx",
    "/index.js",
    "/index.jsx",
)

_COMMENT_RE = re.compile(r"//[^\n]*|/\*.*?\*/", re.DOTALL)


def load_path_aliases(workspace_root: Path) -> dict[str, list[str]]:
    """Reads tsconfig.json's compilerOptions.paths at the workspace root,
    if present, returning {alias_pattern: [target_pattern, ...]} exactly
    as tsconfig expresses it (e.g. {"@app/*": ["src/app/*"]}). Returns {}
    on any missing/malformed config — deterministic best-effort, never
    raises."""
    tsconfig_path = workspace_root / "tsconfig.json"
    if not tsconfig_path.is_file():
        return {}
    try:
        text = _COMMENT_RE.sub("", tsconfig_path.read_text(encoding="utf-8"))
        data = json.loads(text)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    compiler_options = data.get("compilerOptions", {})
    if not isinstance(compiler_options, dict):
        return {}
    paths = compiler_options.get("paths", {})
    if not isinstance(paths, dict):
        return {}
    return {
        str(alias): [str(target) for target in targets]
        for alias, targets in paths.items()
        if isinstance(targets, list)
    }


def resolve_with_aliases(
    raw_module: str, aliases: dict[str, list[str]], workspace_files: frozenset[str]
) -> str | None:
    """Applies tsconfig path-alias remapping to `raw_module` (a bare
    specifier — relative imports are already resolved by the analyzer
    itself), trying each candidate target pattern in declaration order
    until one names a real workspace file."""
    for alias_pattern, targets in aliases.items():
        matched_wildcard = _match_wildcard_prefix(alias_pattern, raw_module)
        if matched_wildcard is None:
            continue
        for target_pattern in targets:
            candidate_base = target_pattern.replace("*", matched_wildcard)
            for suffix in _RESOLUTION_SUFFIXES:
                candidate = candidate_base + suffix
                if candidate in workspace_files:
                    return candidate
    return None


def _match_wildcard_prefix(pattern: str, raw_module: str) -> str | None:
    """Returns the substring `raw_module` matched against `pattern`'s
    single `*` wildcard, or None if it doesn't match. Supports both
    tsconfig shapes: exact ("@app/config") and single-wildcard
    ("@app/*")."""
    if "*" not in pattern:
        return "" if raw_module == pattern else None
    prefix, _, suffix = pattern.partition("*")
    if not raw_module.startswith(prefix) or not raw_module.endswith(suffix):
        return None
    if len(raw_module) < len(prefix) + len(suffix):
        return None
    end = len(raw_module) - len(suffix) if suffix else len(raw_module)
    return raw_module[len(prefix) : end]
