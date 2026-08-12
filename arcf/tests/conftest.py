"""Checklist item #13 (arcf/CHECKLIST.md) — opt-in, env-var-gated
TelemetryCollector wrapper for a one-time, full-suite validation run.

Default (ARCF_TELEMETRY_VALIDATE unset): this file installs nothing.
Every existing test gets today's exact behavior and timing, unchanged —
same discipline as every opt-in flag added this session (enable_ups_
suppression, origin_stage tagging, etc.): a feature that changes nothing
for a caller/test that doesn't explicitly opt in.

ARCF_TELEMETRY_VALIDATE=1: wraps ContextResolver.resolve and
ContextPackager.package as pure pass-throughs (identical return value,
identical side effects — see _wrapped_resolve/_wrapped_package's own
docstrings) plus telemetry recording, for the DURATION OF THE TEST
SESSION ONLY (restored at session end). A schema/recording failure is
caught and appended to a module-level violations list rather than
allowed to propagate into the calling test — the whole point of this
run is to prove telemetry recording doesn't validate to catch a
violation without also EVER corrupting behavior across the entire real,
already-existing 947+-test corpus. At session end, prints a real
summary and asserts zero violations were recorded, so the deliberate
"one-time verification pass" (see this item's own CHECKLIST.md entry)
actually fails loudly if reality didn't match the claim.
"""

import os
import time

import pytest

_ENABLED = os.environ.get("ARCF_TELEMETRY_VALIDATE") == "1"

if _ENABLED:
    from code_intelligence.context_resolver import ContextResolver
    from context.packager import ContextPackager
    from infrastructure.telemetry import TelemetryCollector

    _collector = TelemetryCollector()
    _violations: list[str] = []
    _untagged_observations: list[str] = []
    _original_resolve = ContextResolver.resolve
    _original_package = ContextPackager.package

    def _note_if_untagged(result, event, label: str) -> None:
        """Real finding from the first run of this wrapper (2026-08-12):
        untagged candidates DO occur, but every instance traced to
        tests/context/test_packager.py's hand-built ContextResolutionResult
        fixtures, which construct FileReference objects directly to test
        ContextPackager's own ranking/budgeting logic in isolation --
        bypassing the real resolver entirely. Not a regression in item
        #10's coverage (verified 100% on real Consul,
        symbol_identity_audit_trail_verification.py) -- a hand-built test
        double for a FileReference was never claimed to carry real
        provenance, same as any mock. Recorded, not silenced, so a FUTURE
        untagged source (a real gap) doesn't get lost among expected ones."""
        if event.origin_breakdown.untagged:
            untagged_files = [f.file_path for f in result.candidate_files if f.origin_stage is None]
            _untagged_observations.append(
                f"{label} in {os.environ.get('PYTEST_CURRENT_TEST')}: {untagged_files}"
            )

    def _wrapped_resolve(self, *args, **kwargs):
        """Pure pass-through: calls the real resolve() unchanged, times
        it, records telemetry, returns the exact same result. A
        record() failure is caught here (not left to propagate) so this
        validation run can never change any other test's pass/fail
        outcome -- it can only ever ADD an entry to _violations."""
        start = time.perf_counter()
        result = _original_resolve(self, *args, **kwargs)
        elapsed_ms = (time.perf_counter() - start) * 1000
        try:
            event = _collector.record(result, resolve_latency_ms=elapsed_ms)
            _note_if_untagged(result, event, "resolve()")
        except Exception as exc:  # noqa: BLE001 - deliberately broad, see docstring
            _violations.append(f"resolve() telemetry failure: {type(exc).__name__}: {exc}")
        return result

    async def _wrapped_package(self, result, *args, **kwargs):
        start = time.perf_counter()
        package_result = await _original_package(self, result, *args, **kwargs)
        elapsed_ms = (time.perf_counter() - start) * 1000
        try:
            package, llm_response = package_result
            event = _collector.record(
                result, resolve_latency_ms=0.0, package=package, package_latency_ms=elapsed_ms
            )
            _note_if_untagged(result, event, "package()")
        except Exception as exc:  # noqa: BLE001
            _violations.append(f"package() telemetry failure: {type(exc).__name__}: {exc}")
        return package_result

    @pytest.fixture(autouse=True, scope="session")
    def _install_telemetry_validation_wrapper():
        ContextResolver.resolve = _wrapped_resolve
        ContextPackager.package = _wrapped_package
        yield
        ContextResolver.resolve = _original_resolve
        ContextPackager.package = _original_package

        summary = _collector.get_run_summary()
        print(f"\n\n=== ARCF_TELEMETRY_VALIDATE summary ===")
        print(f"events recorded: {summary['event_count']}")
        print(f"schema/recording violations: {len(_violations)}")
        if _violations:
            for v in _violations[:20]:
                print(f"  {v}")
        print(f"origin_breakdown_totals: {summary['origin_breakdown_totals']}")
        if _untagged_observations:
            print(f"untagged observations ({len(_untagged_observations)}) -- expected source is "
                  f"test_packager.py's hand-built fixtures, see _note_if_untagged's own docstring:")
            for obs in _untagged_observations:
                print(f"  {obs}")
        assert not _violations, (
            f"{len(_violations)} telemetry schema/recording violation(s) across "
            f"{summary['event_count']} real resolve()/package() calls in the test suite -- "
            f"see printed detail above."
        )
