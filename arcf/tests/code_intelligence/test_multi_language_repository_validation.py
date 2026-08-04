"""v2.3 Validation Baseline, item 2: confirms the multi-language
analyzer framework is operational and correctly registered for every
supported language (Python, TypeScript, Java, C#, Go, Kotlin), by
actually running repository indexing (CodeIntelligenceEngine.build_index)
and context resolution (ContextResolver.resolve) end to end against a
real two-file fixture repository per language — not just exercising
each analyzer in isolation the way tests/code_intelligence/languages/
already does.

Each fixture repo has the same shape: a "definer" file with one
function/method, and a "caller" file in a different package/module
that imports the definer and calls it. This exercises the full Phase 5
pipeline together — SymbolIndex, ImportGraph, DependencyGraph,
CallGraph, CandidateFileSelector, and ContextResolver — for each
language, using one CodeIntelligenceEngine registered with all six
analyzers at once, the same way interfaces/api/app.py wires them in
production.

See arcf/docs/ARCF_V2.3_VALIDATION_READINESS_REPORT.md for how this
evidence is reported.
"""

from pathlib import Path

from code_intelligence.context_resolver import ContextResolver
from code_intelligence.engine import CodeIntelligenceEngine
from code_intelligence.index import CodeIntelligenceIndex
from code_intelligence.languages.csharp_analyzer import CSharpLanguageAnalyzer
from code_intelligence.languages.go_analyzer import GoLanguageAnalyzer
from code_intelligence.languages.java_analyzer import JavaLanguageAnalyzer
from code_intelligence.languages.kotlin_analyzer import KotlinLanguageAnalyzer
from code_intelligence.languages.python_analyzer import PythonLanguageAnalyzer
from code_intelligence.languages.typescript_analyzer import TypeScriptLanguageAnalyzer
from code_intelligence.registry import LanguageRegistry
from infrastructure.cost import CostEstimator
from workspace.scanner import RepositoryScanner


def _full_registry_engine() -> CodeIntelligenceEngine:
    return CodeIntelligenceEngine(
        LanguageRegistry(
            [
                PythonLanguageAnalyzer(),
                TypeScriptLanguageAnalyzer(),
                JavaLanguageAnalyzer(),
                CSharpLanguageAnalyzer(),
                GoLanguageAnalyzer(),
                KotlinLanguageAnalyzer(),
            ]
        ),
        CostEstimator(),
    )


def _build_index(tmp_path: Path) -> CodeIntelligenceIndex:
    scan = RepositoryScanner().scan(tmp_path)
    return _full_registry_engine().build_index(tmp_path, scan.files)


def _write(tmp_path: Path, relative_path: str, content: str) -> None:
    path = tmp_path / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def test_python_repository_indexing_and_context_resolution(tmp_path: Path) -> None:
    _write(tmp_path, "auth.py", "def authenticate(user):\n    return True\n")
    _write(
        tmp_path,
        "login.py",
        "from .auth import authenticate\n\ndef login(user):\n    return authenticate(user)\n",
    )
    index = _build_index(tmp_path)

    assert any(s.name == "authenticate" for s in index.symbol_index.functions())
    assert index.import_graph.imports_of("login.py") == {"auth.py"}
    assert index.candidate_selector.callers_of("authenticate") == {"auth.py", "login.py"}

    result = ContextResolver(index).resolve("ws", "c1", str(tmp_path), ["authenticate"])
    assert result.language == "python"
    assert {f.file_path for f in result.candidate_files} == {"auth.py", "login.py"}
    assert result.confidence == 1.0


def test_typescript_repository_indexing_and_context_resolution(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "auth.ts",
        "export function authenticate(user: string): boolean {\n  return true;\n}\n",
    )
    _write(
        tmp_path,
        "login.ts",
        "import { authenticate } from './auth';\n\n"
        "export function login(user: string): boolean {\n  return authenticate(user);\n}\n",
    )
    index = _build_index(tmp_path)

    assert any(s.name == "authenticate" for s in index.symbol_index.functions())
    assert index.import_graph.imports_of("login.ts") == {"auth.ts"}
    assert index.candidate_selector.callers_of("authenticate") == {"auth.ts", "login.ts"}

    result = ContextResolver(index).resolve("ws", "c1", str(tmp_path), ["authenticate"])
    assert result.language == "typescript"
    assert {f.file_path for f in result.candidate_files} == {"auth.ts", "login.ts"}
    assert result.confidence == 1.0


def test_java_repository_indexing_and_context_resolution(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "com/example/auth/Auth.java",
        "package com.example.auth;\n\n"
        "public class Auth {\n"
        "    public boolean authenticate() {\n        return true;\n    }\n"
        "}\n",
    )
    _write(
        tmp_path,
        "com/example/login/Login.java",
        "package com.example.login;\n\n"
        "import com.example.auth.Auth;\n\n"
        "public class Login {\n"
        "    public boolean login() {\n"
        "        Auth a = new Auth();\n"
        "        return a.authenticate();\n"
        "    }\n"
        "}\n",
    )
    index = _build_index(tmp_path)

    auth_file = "com/example/auth/Auth.java"
    login_file = "com/example/login/Login.java"
    assert any(s.name == "authenticate" for s in index.symbol_index.methods())
    assert index.import_graph.imports_of(login_file) == {auth_file}
    assert index.candidate_selector.callers_of("authenticate") == {auth_file, login_file}

    result = ContextResolver(index).resolve("ws", "c1", str(tmp_path), ["authenticate"])
    assert result.language == "java"
    assert {f.file_path for f in result.candidate_files} == {auth_file, login_file}
    assert result.confidence == 1.0


def test_csharp_repository_indexing_and_context_resolution(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "MyApp/Auth/Authenticator.cs",
        "namespace MyApp.Auth\n{\n"
        "    public class Authenticator\n    {\n"
        "        public bool Authenticate()\n        {\n            return true;\n        }\n"
        "    }\n}\n",
    )
    _write(
        tmp_path,
        "MyApp/Login/LoginService.cs",
        "using MyApp.Auth;\n\n"
        "namespace MyApp.Login\n{\n"
        "    public class LoginService\n    {\n"
        "        public bool Login()\n        {\n"
        "            var auth = new Authenticator();\n"
        "            return auth.Authenticate();\n"
        "        }\n    }\n}\n",
    )
    index = _build_index(tmp_path)

    auth_file = "MyApp/Auth/Authenticator.cs"
    login_file = "MyApp/Login/LoginService.cs"
    assert any(s.name == "Authenticate" for s in index.symbol_index.methods())
    assert index.import_graph.imports_of(login_file) == {auth_file}
    assert index.candidate_selector.callers_of("Authenticate") == {auth_file, login_file}

    result = ContextResolver(index).resolve("ws", "c1", str(tmp_path), ["Authenticate"])
    assert result.language == "csharp"
    assert {f.file_path for f in result.candidate_files} == {auth_file, login_file}
    assert result.confidence == 1.0


def test_go_repository_indexing_and_context_resolution(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "myapp/auth/auth.go",
        "package auth\n\nfunc Authenticate() bool {\n\treturn true\n}\n",
    )
    _write(
        tmp_path,
        "myapp/login/login.go",
        'package login\n\nimport "myapp/auth"\n\n'
        "func Login() bool {\n\treturn auth.Authenticate()\n}\n",
    )
    index = _build_index(tmp_path)

    auth_file = "myapp/auth/auth.go"
    login_file = "myapp/login/login.go"
    assert any(s.name == "Authenticate" for s in index.symbol_index.functions())
    assert index.import_graph.imports_of(login_file) == {auth_file}
    assert index.candidate_selector.callers_of("Authenticate") == {auth_file, login_file}

    result = ContextResolver(index).resolve("ws", "c1", str(tmp_path), ["Authenticate"])
    assert result.language == "go"
    assert {f.file_path for f in result.candidate_files} == {auth_file, login_file}
    assert result.confidence == 1.0


def test_kotlin_repository_indexing_and_context_resolution(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "com/example/auth/Auth.kt",
        "package com.example.auth\n\n"
        "class Auth {\n    fun authenticate(): Boolean {\n        return true\n    }\n}\n",
    )
    _write(
        tmp_path,
        "com/example/login/Login.kt",
        "package com.example.login\n\n"
        "import com.example.auth.Auth\n\n"
        "class Login {\n    fun login(): Boolean {\n"
        "        val auth = Auth()\n        return auth.authenticate()\n    }\n}\n",
    )
    index = _build_index(tmp_path)

    auth_file = "com/example/auth/Auth.kt"
    login_file = "com/example/login/Login.kt"
    assert any(s.name == "authenticate" for s in index.symbol_index.methods())
    assert index.import_graph.imports_of(login_file) == {auth_file}
    assert index.candidate_selector.callers_of("authenticate") == {auth_file, login_file}

    result = ContextResolver(index).resolve("ws", "c1", str(tmp_path), ["authenticate"])
    assert result.language == "kotlin"
    assert {f.file_path for f in result.candidate_files} == {auth_file, login_file}
    assert result.confidence == 1.0


def test_all_six_languages_coexist_in_one_registry_without_cross_contamination(
    tmp_path: Path,
) -> None:
    """Every language registered simultaneously (production's real
    wiring, per interfaces/api/app.py) — proves registration dispatch
    picks the right analyzer per extension with no leakage between
    them, over one repository containing all six languages at once."""
    _write(tmp_path, "a.py", "def python_only():\n    pass\n")
    _write(tmp_path, "b.ts", "export function typescript_only(): void {}\n")
    _write(tmp_path, "C.java", "class C {\n    void javaOnly() {}\n}\n")
    _write(tmp_path, "D.cs", "public class D\n{\n    public void CSharpOnly() {}\n}\n")
    _write(tmp_path, "e.go", "package main\n\nfunc GoOnly() {}\n")
    _write(tmp_path, "F.kt", "class F {\n    fun kotlinOnly() {}\n}\n")

    index = _build_index(tmp_path)

    assert {a.language for a in index.file_analyses.values()} == {
        "python",
        "typescript",
        "java",
        "csharp",
        "go",
        "kotlin",
    }
    assert index.file_analyses["a.py"].language == "python"
    assert index.file_analyses["b.ts"].language == "typescript"
    assert index.file_analyses["C.java"].language == "java"
    assert index.file_analyses["D.cs"].language == "csharp"
    assert index.file_analyses["e.go"].language == "go"
    assert index.file_analyses["F.kt"].language == "kotlin"
