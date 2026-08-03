"""Benchmark's own domain models — separate from ARCF's domain/, since
this is measurement data about ARCF, not ARCF pipeline data itself.

RunResult embeds ARCF's actual Contract/ContextResolutionResult/
ContextPackage objects directly (imported from ARCF, not re-declared)
for the ARCF mode — per the explicit instruction to reuse existing ARCF
data structures rather than create parallel ones.
"""
