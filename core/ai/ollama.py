"""Backwards-compatibility shim.

The agent implementation used to live here as ``OllamaModel``. It now lives in
:mod:`ai.model` as the provider-agnostic :class:`~ai.model.AgentModel`, and the
Ollama-specific wire code moved to :mod:`ai.providers.ollama_provider`.

``OllamaModel`` is still importable from here so existing code (and any external
scripts) keep working.
"""
from __future__ import annotations

from ai.model import AgentModel
from ai.providers.base import ProviderError

# Historical name.
OllamaModel = AgentModel

__all__ = ["AgentModel", "OllamaModel", "ProviderError"]
