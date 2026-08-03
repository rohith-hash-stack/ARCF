class UnknownProviderError(Exception):
    """Raised by ProviderRegistry.get() for a name with no registered
    BenchmarkProvider."""
