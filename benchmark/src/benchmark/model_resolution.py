"""resolve_model — the one place a (provider, model) pair from a CLI
flag or an API request becomes the model string passed to a runner.
Shared by cli.py and api/routes.py so the same optional, backward-
compatible resolution rule applies everywhere: with no provider, model
(or a caller-supplied default) is used exactly as given, unchanged from
before BenchmarkProvider existed; with a provider, model is treated as
a provider-scoped alias resolved through that registry entry.
"""

from benchmark.providers.registry import default_provider_registry


def resolve_model(
    provider: str | None,
    model: str | None,
    default_model: str,
    local_slm_base_url: str,
) -> str:
    alias = model or default_model
    if provider is None:
        return alias
    registry = default_provider_registry(local_slm_base_url)
    return registry.get(provider).resolve_model(alias)
