"""
Provider and model configuration for ASTRA.

ASTRA is provider-agnostic: it can run against a local Ollama server or a cloud
provider (OpenAI, Anthropic/Claude, Google Gemini). The active provider, model,
API keys and base URLs are resolved from, in order of precedence:

1. Environment variables (always win — ideal for deployments and CI),
2. ``core/config/settings.json`` (written by the ``/provider`` command and the
   web settings panel; contains secrets, so it is git-ignored),
3. Built-in defaults.

Nothing about the model is hard-coded in the agent: the chat loop asks
:class:`Settings` which provider/model to use.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict, Optional

# Providers ASTRA knows how to talk to.
PROVIDERS = ("ollama", "openai", "anthropic", "gemini")

DEFAULT_PROVIDER = "ollama"

DEFAULT_MODELS: Dict[str, str] = {
    "ollama": "qwen3:14b",
    "openai": "gpt-4o-mini",
    "anthropic": "claude-3-5-sonnet-latest",
    "gemini": "gemini-2.0-flash",
}

DEFAULT_BASE_URLS: Dict[str, str] = {
    "ollama": "http://localhost:11434",
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com",
    "gemini": "https://generativelanguage.googleapis.com",
}

# Human-friendly labels for the CLI / web UI.
PROVIDER_LABELS: Dict[str, str] = {
    "ollama": "Local (Ollama)",
    "openai": "OpenAI",
    "anthropic": "Anthropic (Claude)",
    "gemini": "Google (Gemini)",
}

# Env vars consulted for each provider's API key (first match wins).
_KEY_ENV: Dict[str, tuple] = {
    "openai": ("ASTRA_OPENAI_API_KEY", "OPENAI_API_KEY"),
    "anthropic": ("ASTRA_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"),
    "gemini": ("ASTRA_GEMINI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"),
}

# Env vars consulted for each provider's base URL (first match wins).
_BASE_ENV: Dict[str, tuple] = {
    "ollama": ("ASTRA_OLLAMA_HOST", "OLLAMA_HOST"),
    "openai": ("ASTRA_OPENAI_BASE_URL", "OPENAI_BASE_URL"),
    "anthropic": ("ASTRA_ANTHROPIC_BASE_URL",),
    "gemini": ("ASTRA_GEMINI_BASE_URL",),
}

_ENV_PROVIDER = "ASTRA_PROVIDER"
_ENV_MODEL = "ASTRA_MODEL"
_ENV_THINKING = "ASTRA_THINKING"

# Whether the model reasons ("thinks") before answering. Only backends that
# support reasoning (e.g. Ollama models like qwen3) act on this; others ignore
# it. Default preserves ASTRA's historical behaviour of asking for thinking.
DEFAULT_THINKING = True

_TRUE_WORDS = ("1", "true", "yes", "on", "enable", "enabled", "y")
_FALSE_WORDS = ("0", "false", "no", "off", "disable", "disabled", "n")


def _parse_bool(value) -> Optional[bool]:
    """Coerce common truthy/falsey spellings to ``bool`` (or ``None``)."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in _TRUE_WORDS:
        return True
    if text in _FALSE_WORDS:
        return False
    return None


def default_settings_path() -> Path:
    """Return the default settings file (``core/config/settings.json``).

    ``ASTRA_SETTINGS_PATH`` overrides the location (handy for tests and for
    keeping per-instance configuration separate).
    """
    override = os.environ.get("ASTRA_SETTINGS_PATH")
    if override:
        return Path(override).expanduser()
    return Path(__file__).resolve().parents[1] / "config" / "settings.json"


def _first_env(names) -> Optional[str]:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return None


def normalize_provider(name: Optional[str]) -> str:
    """Coerce a user-supplied provider name to a known provider id."""
    if not name:
        return DEFAULT_PROVIDER
    cleaned = str(name).strip().lower()
    aliases = {
        "local": "ollama",
        "ollama": "ollama",
        "openai": "openai",
        "open_ai": "openai",
        "gpt": "openai",
        "anthropic": "anthropic",
        "claude": "anthropic",
        "gemini": "gemini",
        "google": "gemini",
        "google-gemini": "gemini",
    }
    return aliases.get(cleaned, cleaned)


def default_model(provider: str) -> str:
    return DEFAULT_MODELS.get(normalize_provider(provider), "")


def default_base_url(provider: str) -> str:
    return DEFAULT_BASE_URLS.get(normalize_provider(provider), "")


class Settings:
    """Read/write access to ASTRA's provider configuration."""

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else default_settings_path()
        self._lock = threading.RLock()
        self._data: Dict[str, Any] = {}
        self.load()

    # ---- file I/O -----------------------------------------------------------
    def load(self) -> Dict[str, Any]:
        with self._lock:
            data: Dict[str, Any] = {}
            try:
                if self.path.exists():
                    with self.path.open("r", encoding="utf-8") as fh:
                        loaded = json.load(fh)
                    if isinstance(loaded, dict):
                        data = loaded
            except Exception:
                data = {}
            data.setdefault("provider", DEFAULT_PROVIDER)
            data.setdefault("providers", {})
            if not isinstance(data.get("providers"), dict):
                data["providers"] = {}
            self._data = data
            return data

    def save(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(self._data, indent=2, sort_keys=False)
            # Write atomically and lock the file down (it may hold API keys).
            fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix=".settings-", suffix=".json")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    fh.write(payload + "\n")
                try:
                    os.chmod(tmp, 0o600)
                except Exception:
                    pass
                os.replace(tmp, self.path)
            finally:
                if os.path.exists(tmp):
                    try:
                        os.remove(tmp)
                    except Exception:
                        pass

    # ---- raw provider config ------------------------------------------------
    def _provider_config(self, provider: str) -> Dict[str, Any]:
        provider = normalize_provider(provider)
        cfg = self._data.get("providers", {}).get(provider, {})
        return dict(cfg) if isinstance(cfg, dict) else {}

    # ---- active provider / model -------------------------------------------
    def active_provider(self) -> str:
        return normalize_provider(os.environ.get(_ENV_PROVIDER) or self._data.get("provider") or DEFAULT_PROVIDER)

    def active_model(self, provider: Optional[str] = None) -> str:
        provider = normalize_provider(provider or self.active_provider())
        if provider == self.active_provider():
            env_model = os.environ.get(_ENV_MODEL)
            if env_model:
                return env_model
        stored = self._data.get("model")
        cfg_model = self._provider_config(provider).get("model")
        # Prefer the explicitly stored model when it belongs to the active provider.
        if provider == self.active_provider() and stored:
            return stored
        if cfg_model:
            return cfg_model
        return default_model(provider)

    def set_active(self, provider: str, model: Optional[str] = None) -> None:
        provider = normalize_provider(provider)
        with self._lock:
            self._data["provider"] = provider
            cfg = self._data.setdefault("providers", {}).setdefault(provider, {})
            if model:
                self._data["model"] = model
                cfg["model"] = model
            else:
                self._data["model"] = cfg.get("model") or default_model(provider)
            self.save()

    # ---- keys / base urls ---------------------------------------------------
    def api_key(self, provider: str) -> Optional[str]:
        provider = normalize_provider(provider)
        env = _first_env(_KEY_ENV.get(provider, ()))
        if env:
            return env
        value = self._provider_config(provider).get("api_key")
        return value or None

    def api_key_source(self, provider: str) -> Optional[str]:
        provider = normalize_provider(provider)
        if _first_env(_KEY_ENV.get(provider, ())):
            return "env"
        if self._provider_config(provider).get("api_key"):
            return "file"
        return None

    def base_url(self, provider: str) -> str:
        provider = normalize_provider(provider)
        env = _first_env(_BASE_ENV.get(provider, ()))
        if env:
            return env.rstrip("/")
        value = self._provider_config(provider).get("base_url")
        if value:
            return str(value).rstrip("/")
        return default_base_url(provider)

    def set_api_key(self, provider: str, api_key: Optional[str]) -> None:
        provider = normalize_provider(provider)
        with self._lock:
            cfg = self._data.setdefault("providers", {}).setdefault(provider, {})
            if api_key:
                cfg["api_key"] = api_key.strip()
            else:
                cfg.pop("api_key", None)
            self.save()

    def set_base_url(self, provider: str, base_url: Optional[str]) -> None:
        provider = normalize_provider(provider)
        with self._lock:
            cfg = self._data.setdefault("providers", {}).setdefault(provider, {})
            if base_url:
                cfg["base_url"] = base_url.strip().rstrip("/")
            else:
                cfg.pop("base_url", None)
            self.save()

    # ---- thinking / reasoning ----------------------------------------------
    def thinking(self) -> bool:
        """Whether the active model should emit reasoning ("thinking") tokens.

        Precedence matches the rest of the settings: ``ASTRA_THINKING`` wins,
        then the saved value, then :data:`DEFAULT_THINKING`.
        """
        env = _parse_bool(os.environ.get(_ENV_THINKING))
        if env is not None:
            return env
        stored = _parse_bool(self._data.get("thinking"))
        return DEFAULT_THINKING if stored is None else stored

    def thinking_source(self) -> str:
        """Where :meth:`thinking` resolved from: ``"env"``, ``"file"`` or ``"default"``."""
        if _parse_bool(os.environ.get(_ENV_THINKING)) is not None:
            return "env"
        if _parse_bool(self._data.get("thinking")) is not None:
            return "file"
        return "default"

    def set_thinking(self, enabled: bool) -> None:
        with self._lock:
            self._data["thinking"] = bool(enabled)
            self.save()

    def provider_options(self, provider: str) -> Dict[str, Any]:
        provider = normalize_provider(provider)
        cfg = self._provider_config(provider)
        return {
            "model": self.active_model(provider) if provider == self.active_provider()
            else (cfg.get("model") or default_model(provider)),
            "base_url": cfg.get("base_url") or default_base_url(provider),
            "api_key": self.api_key(provider) or "",
            "api_key_source": self.api_key_source(provider),
        }

    # ---- public snapshot (secrets masked) ----------------------------------
    @staticmethod
    def _mask(secret: Optional[str]) -> str:
        if not secret:
            return ""
        if len(secret) <= 8:
            return "•" * len(secret)
        return f"{secret[:4]}…{secret[-4:]}"

    def to_public(self) -> Dict[str, Any]:
        provider = self.active_provider()
        providers = {}
        for name in PROVIDERS:
            key = self.api_key(name)
            providers[name] = {
                "label": PROVIDER_LABELS.get(name, name),
                "model": self.active_model(name) if name == provider
                else (self._provider_config(name).get("model") or default_model(name)),
                "default_model": default_model(name),
                "base_url": self.base_url(name),
                "default_base_url": default_base_url(name),
                "api_key_masked": self._mask(key),
                "api_key_source": self.api_key_source(name),
                "api_key_from_env": self.api_key_source(name) == "env",
                "configured": bool(key) if name != "ollama" else True,
                "requires_key": name != "ollama",
            }
        return {
            "provider": provider,
            "model": self.active_model(),
            "providers": providers,
            "thinking": self.thinking(),
            "thinking_from_env": self.thinking_source() == "env",
            "env_provider_locked": bool(os.environ.get(_ENV_PROVIDER)),
            "env_model_locked": bool(os.environ.get(_ENV_MODEL)),
        }


# --- process-wide singleton (used by the CLI and the web backend) ------------
_settings: Optional[Settings] = None
_settings_lock = threading.Lock()


def get_settings() -> Settings:
    global _settings
    with _settings_lock:
        if _settings is None:
            _settings = Settings()
        return _settings
