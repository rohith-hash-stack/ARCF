"""Batch 2 diagnostic runner (held-out validation, per the 2026-08-06 handoff
§7 step 5 — "held out, similar-shaped queries across the same/different
repos", run after the classifier-gap fix layers 1-3 and the ambiguity-cap/
tiktoken crash fixes, all validated against Batch 1).

Same cheap, no-final-LLM-call pipeline as scripts/batch1_diagnostic.py: real
SLM-1 intent extraction (small, real cost) + the deterministic Phase 5/6
pipeline via CodeIntelligenceContractService, exactly as production code
does. Never calls a "final generation" LLM.

Batch 2 intentionally uses an entirely different repository set (browsers,
infrastructure, compilers, game engines, networking, security, databases,
package managers, blockchain, developer tools) spanning the same task
shapes (summarize/explain/trace/debug/refactor/implement/optimize/test) —
no repository overlap with Batch 1, so this is a genuine held-out check on
whether the classifier fix generalizes rather than having been tuned to
Batch 1's specific repos.

EpicGames/UnrealEngine is excluded: confirmed private (git ls-remote
returns "Repository not found") — it requires a Epic-linked, approved
GitHub account, so it's not accessible for anonymous cloning. Not a
language-coverage or classifier finding, just an inaccessible source.

Usage (one repo at a time, per the same protocol as Batch 1 — clone, test,
delete, move to next):

    uv run python scripts/batch2_diagnostic.py --repo-key chromium --repo-path <path>

Appends one row per query to docs/BATCH2_RESULTS.md (created if missing).
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from code_intelligence.engine import CodeIntelligenceEngine
from code_intelligence.languages.csharp_analyzer import CSharpLanguageAnalyzer
from code_intelligence.languages.go_analyzer import GoLanguageAnalyzer
from code_intelligence.languages.java_analyzer import JavaLanguageAnalyzer
from code_intelligence.languages.kotlin_analyzer import KotlinLanguageAnalyzer
from code_intelligence.languages.python_analyzer import PythonLanguageAnalyzer
from code_intelligence.languages.typescript_analyzer import TypeScriptLanguageAnalyzer
from code_intelligence.registry import LanguageRegistry
from code_intelligence.service import CodeIntelligenceContractService
from contracts.intent_extraction import IntentExtractor
from domain.contract import Contract
from domain.intent import UserIntent
from domain.versioning import LivingContract
from infrastructure.context_resolution_store import InMemoryContextResolutionStore
from infrastructure.contract_store import InMemoryContractStore
from infrastructure.cost import CostEstimator
from infrastructure.llm_client import LiteLLMClient

RESULTS_FILE = Path(__file__).resolve().parent.parent / "docs" / "BATCH2_RESULTS.md"

# repo_key -> list of task prompts, transcribed verbatim from the user's Batch 2.
# GitHub URLs (needed for cloning, not stored here):
#   chromium https://github.com/chromium/chromium
#   firefox https://github.com/mozilla/gecko-dev
#   electron https://github.com/electron/electron
#   docker https://github.com/moby/moby
#   containerd https://github.com/containerd/containerd
#   caddy https://github.com/caddyserver/caddy
#   traefik https://github.com/traefik/traefik
#   envoy https://github.com/envoyproxy/envoy
#   haproxy https://github.com/haproxy/haproxy
#   openssl https://github.com/openssl/openssl
#   git https://github.com/git/git
#   neovim https://github.com/neovim/neovim
#   emacs https://github.com/emacs-mirror/emacs
#   helix https://github.com/helix-editor/helix
#   godot https://github.com/godotengine/godot
#   blender https://github.com/blender/blender
#   ffmpeg https://github.com/FFmpeg/FFmpeg
#   vlc https://github.com/videolan/vlc
#   obs-studio https://github.com/obsproject/obs-studio
#   homebrew https://github.com/Homebrew/brew
#   pnpm https://github.com/pnpm/pnpm
#   yarn-berry https://github.com/yarnpkg/berry
#   bun https://github.com/oven-sh/bun
#   deno https://github.com/denoland/deno
#   zig https://github.com/ziglang/zig
#   nushell https://github.com/nushell/nushell
#   jq https://github.com/jqlang/jq
#   ripgrep https://github.com/BurntSushi/ripgrep
#   fd https://github.com/sharkdp/fd
#   wasmtime https://github.com/bytecodealliance/wasmtime
#   wasm-bindgen https://github.com/rustwasm/wasm-bindgen
#   solana https://github.com/solana-labs/solana
#   go-ethereum https://github.com/ethereum/go-ethereum
#   fabric https://github.com/hyperledger/fabric
#   cockroachdb https://github.com/cockroachdb/cockroach
#   tidb https://github.com/pingcap/tidb
#   etcd https://github.com/etcd-io/etcd
#   consul https://github.com/hashicorp/consul
#   vault https://github.com/hashicorp/vault
#   opentofu https://github.com/opentofu/opentofu
#   ansible https://github.com/ansible/ansible
#   celery https://github.com/celery/celery
QUERIES: dict[str, list[str]] = {
    "chromium": [
        "Explain the lifecycle of a browser navigation from entering a URL until the first paint. Include process creation and IPC.",
        "A recent change causes page startup latency to increase by 15%. Identify likely bottlenecks and propose optimizations.",
    ],
    "firefox": [
        "Explain how Gecko's rendering pipeline differs from Chromium's Blink architecture.",
        "Refactor a DOM traversal utility to reduce allocations while preserving observable behavior.",
    ],
    "electron": [
        "Trace how an IPC message travels from the renderer process to the main process and back.",
        "Add support for collecting IPC latency metrics without affecting production performance.",
    ],
    "docker": [
        "Explain what happens internally when docker run starts a container from an image.",
        "Debug a regression where container startup time increased after networking changes.",
    ],
    "containerd": [
        "Explain how containerd manages snapshots, images, and runtime execution.",
    ],
    "caddy": [
        "Implement middleware that records request processing time while minimizing allocations.",
    ],
    "traefik": [
        "Explain how dynamic configuration updates propagate without restarting the server.",
    ],
    "envoy": [
        "Trace an HTTP request through Envoy filters and explain how routing decisions are made.",
    ],
    "haproxy": [
        "Investigate why connection throughput dropped after introducing a new load-balancing algorithm.",
    ],
    "openssl": [
        "Explain the TLS 1.3 handshake implementation from ClientHello through key establishment.",
        "Add a debugging hook that logs negotiated cipher suites without exposing secret material.",
    ],
    "git": [
        "Explain what happens internally during git rebase and how commits are rewritten.",
        "Refactor commit graph traversal code to improve readability while maintaining performance.",
    ],
    "neovim": [
        "Trace how a keystroke results in a screen update. Include Lua plugin interaction.",
    ],
    "emacs": [
        "Explain how buffer modifications propagate to redisplay.",
    ],
    "helix": [
        "Implement incremental syntax highlighting for a newly supported language.",
    ],
    "godot": [
        "Explain how the scene tree processes input, physics updates, and rendering each frame.",
        "Debug a memory leak introduced in the resource cache after a recent optimization.",
    ],
    # "unreal" excluded — EpicGames/UnrealEngine is private (confirmed via
    # git ls-remote), not accessible for anonymous cloning.
    "blender": [
        "Trace the execution path when importing an OBJ model until it appears in the viewport.",
    ],
    "ffmpeg": [
        "Explain how video decoding flows from packet parsing to decoded frames.",
        "Optimize a color conversion routine that regressed after SIMD refactoring.",
    ],
    "vlc": [
        "Explain how VLC selects demuxers and decoders when opening a media file.",
    ],
    "obs-studio": [
        "Add a performance metric reporting dropped frames per source during recording.",
    ],
    "homebrew": [
        "Explain how dependency resolution and formula installation are orchestrated.",
    ],
    "pnpm": [
        "Explain how pnpm's content-addressable store avoids package duplication.",
    ],
    "yarn-berry": [
        "Debug a workspace resolution issue introduced after updating Plug'n'Play logic.",
    ],
    "bun": [
        "Trace an HTTP request handled by Bun's built-in server from socket accept to response write.",
    ],
    "deno": [
        "Explain how permissions are enforced during filesystem and network operations.",
    ],
    "zig": [
        "Explain how Zig's compile-time execution works and where it differs from C++ templates.",
    ],
    "nushell": [
        "Implement a new built-in command that streams structured data instead of buffering it.",
    ],
    "jq": [
        "Explain how jq parses and evaluates filter expressions internally.",
    ],
    "ripgrep": [
        "Investigate a regex search regression that only appears on very large repositories.",
    ],
    "fd": [
        "Add an option to report directory traversal statistics without impacting normal searches.",
    ],
    "wasmtime": [
        "Explain how WebAssembly modules are compiled, instantiated, and executed.",
    ],
    "wasm-bindgen": [
        "Explain how JavaScript bindings are generated for exported Rust functions.",
    ],
    "solana": [
        "Trace the lifecycle of a transaction from submission through confirmation.",
    ],
    "go-ethereum": [
        "Explain how a transaction is validated, executed in the EVM, and committed to state.",
    ],
    "fabric": [
        "Explain how endorsement, ordering, and validation interact during transaction processing.",
    ],
    "cockroachdb": [
        "Explain how distributed transactions achieve consistency across multiple nodes.",
    ],
    "tidb": [
        "Investigate a distributed query planner regression introduced by a recent optimizer change.",
    ],
    "etcd": [
        "Explain how Raft log replication ensures consistency after leader election.",
    ],
    "consul": [
        "Add request latency instrumentation for service discovery queries while minimizing overhead.",
    ],
    "vault": [
        "Explain how the seal/unseal workflow protects encrypted storage.",
    ],
    "opentofu": [
        "Trace how a plan is generated from configuration through provider interactions.",
    ],
    "ansible": [
        "Refactor module loading to reduce duplicated initialization logic while preserving compatibility.",
    ],
    "celery": [
        "Explain how task scheduling, brokers, and workers coordinate to execute asynchronous jobs.",
    ],
}


def _full_registry() -> LanguageRegistry:
    return LanguageRegistry(
        [
            PythonLanguageAnalyzer(),
            TypeScriptLanguageAnalyzer(),
            JavaLanguageAnalyzer(),
            GoLanguageAnalyzer(),
            CSharpLanguageAnalyzer(),
            KotlinLanguageAnalyzer(),
        ]
    )


@dataclass(frozen=True)
class QueryResult:
    repo: str
    prompt: str
    files_scanned: int
    files_analyzed: int
    candidate_files: int
    languages_detected: tuple[str, ...]
    languages_unsupported: tuple[str, ...]
    repository_scope: bool
    scope_task_type: str
    evidence_satisfied: tuple[str, ...]
    evidence_missing: tuple[str, ...]
    entities_extracted: tuple[str, ...]
    resolution_reason: str


async def _run_one(root: Path, repo_key: str, prompt: str) -> QueryResult:
    engine = CodeIntelligenceEngine(_full_registry(), CostEstimator())
    contract_store = InMemoryContractStore()
    service = CodeIntelligenceContractService(
        engine, contract_store, InMemoryContextResolutionStore()
    )

    # Real SLM-1 call — small, cheap, extracts entities the same way production
    # contract creation does. This is the only real LLM cost this script incurs.
    extractor = IntentExtractor(
        LiteLLMClient(max_retries=3, base_delay_seconds=0.5), model="gpt-4o-mini"
    )
    raw, _llm_response = await extractor.extract(prompt)
    entities = tuple(raw.entities)

    intent = UserIntent(
        raw_request=prompt,
        intent=raw.intent_summary,
        domain=raw.domain,
        task=raw.task,
        entities=list(entities),
        confidence=raw.self_reported_confidence,
    )
    living = LivingContract(contract=Contract(intent=intent))
    contract_store.save(living)

    _, resolution = await service.attach_code_intelligence(
        UUID(str(living.contract_id)), target_names=list(entities), workspace_root=str(root)
    )

    from contracts.evidence_contract import detect_task_type_for_evidence
    from contracts.repository_scope_classifier import RepositoryScopeClassifier

    scope = RepositoryScopeClassifier().classify(prompt)
    evidence_type = detect_task_type_for_evidence(prompt) or scope.task_type

    return QueryResult(
        repo=repo_key,
        prompt=prompt,
        files_scanned=resolution.files_scanned,
        files_analyzed=resolution.files_analyzed,
        candidate_files=len(resolution.candidate_files),
        languages_detected=resolution.languages_detected,
        languages_unsupported=resolution.languages_unsupported,
        repository_scope=scope.repository_scope,
        scope_task_type=scope.task_type,
        evidence_satisfied=resolution.evidence_categories_satisfied,
        evidence_missing=resolution.evidence_categories_missing,
        entities_extracted=entities,
        resolution_reason=resolution.resolution_reason,
    )


def _append_results(results: list[QueryResult]) -> None:
    is_new = not RESULTS_FILE.exists()
    with RESULTS_FILE.open("a", encoding="utf-8") as f:
        if is_new:
            f.write("# Batch 2 Results\n\n")
            f.write(
                "| Repo | Prompt (60ch) | Files scanned | Analyzed | Candidates | "
                "Languages detected | Unsupported | Entities | Reason |\n"
            )
            f.write("|---|---|---|---|---|---|---|---|---|\n")
        for r in results:
            f.write(
                f"| {r.repo} | {r.prompt[:60].replace(chr(10), ' ')}... | "
                f"{r.files_scanned} | {r.files_analyzed} | {r.candidate_files} | "
                f"{', '.join(r.languages_detected) or '-'} | "
                f"{', '.join(r.languages_unsupported) or '-'} | "
                f"{', '.join(r.entities_extracted) or '(none)'} | "
                f"{r.resolution_reason[:120].replace(chr(10), ' ')} |\n"
            )


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-key", required=True, choices=sorted(QUERIES.keys()))
    parser.add_argument("--repo-path", required=True)
    args = parser.parse_args()

    root = Path(args.repo_path)
    prompts = QUERIES[args.repo_key]
    results = []
    for prompt in prompts:
        result = await _run_one(root, args.repo_key, prompt)
        results.append(result)
        print(f"[{args.repo_key}] candidates={result.candidate_files} "
              f"scanned={result.files_scanned} analyzed={result.files_analyzed} "
              f"unsupported={result.languages_unsupported} entities={result.entities_extracted}")
        print(f"  reason: {result.resolution_reason}")

    _append_results(results)
    print(f"Appended {len(results)} row(s) to {RESULTS_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
