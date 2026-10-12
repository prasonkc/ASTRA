"""Provider registry / factory.

``get_provider`` builds a ready-to-use backend for a provider id, pulling the
API key and base URL from :mod:`ai.settings` unless overridden.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from ai import settings as settings_module
from ai.providers.anthropic_provider import AnthropicProvider
from ai.providers.base import Provider, ProviderError
from ai.providers.gemini_provider import GeminiProvider
from ai.providers.ollama_provider import OllamaProvider
from ai.providers.openai_provider import OpenAIProvider

_PROVIDER_CLASSES = {
    "ollama": OllamaProvider,
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "gemini": GeminiProvider,
}

# Providers that authenticate with an API key (everything except local Ollama).
KEYED_PROVIDERS = ("openai", "anthropic", "gemini")


def get_provider(
    name: Optional[str] = None,
    *,
    settings: Optional[settings_module.Settings] = None,
    **overrides: Any,
) -> Provider:
    settings = settings or settings_module.get_settings()
    provider = settings_module.normalize_provider(name or settings.active_provider())
    provider_cls = _PROVIDER_CLASSES.get(provider)
    if provider_cls is None:
        raise ProviderError(
            f"Unknown provider '{provider}'. Known providers: "
            f"{', '.join(_PROVIDER_CLASSES)}."
        )

    options = settings.provider_options(provider)
    config: Dict[str, Any] = {}
    base_url = overrides.pop("base_url", None) or options.get("base_url")
    if base_url:
        config["base_url"] = base_url
    api_key = overrides.pop("api_key", None)
    if api_key is None:
        api_key = options.get("api_key")
    if provider in KEYED_PROVIDERS:
        config["api_key"] = api_key or ""
    config.update(overrides)
    return provider_cls(**config)


__all__ = [
    "Provider",
    "ProviderError",
    "AnthropicProvider",
    "GeminiProvider",
    "OllamaProvider",
    "OpenAIProvider",
    "get_provider",
    "KEYED_PROVIDERS",
]
