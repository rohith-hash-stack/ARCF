"""Per-language LanguageAnalyzer implementations.

Each module here is the only place in the codebase allowed to know
anything about a specific language's syntax. Add a new language by
adding a new module here that satisfies LanguageAnalyzer, then register
an instance with LanguageRegistry — nothing outside this directory
needs to change.
"""
