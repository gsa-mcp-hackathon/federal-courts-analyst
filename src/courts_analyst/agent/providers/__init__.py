"""Model providers behind one streaming interface (``base.Provider``)."""

from __future__ import annotations

from courts_analyst.agent.providers.base import Provider


def make_provider(spec: str) -> Provider:
    """``anthropic:<model>``, ``openai:<model>`` or a bare Claude model id.

    The SDK modules are imported only for the provider asked for."""
    kind, _, model = spec.partition(":")
    if not model:
        kind, model = "anthropic", spec
    if kind == "anthropic":
        from courts_analyst.agent.providers.anthropic import AnthropicProvider

        return AnthropicProvider(model)
    if kind == "openai":
        from courts_analyst.agent.providers.openai import OpenAIProvider

        return OpenAIProvider(model)
    raise ValueError(f"unknown provider {kind!r} (use anthropic: or openai:)")


__all__ = ["Provider", "make_provider"]
