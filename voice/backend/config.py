"""Configuration for the ASTRA voice wrapper.

Every external dependency (the ``whisper.cpp`` binary, the ``piper`` binary, the
model files, the audio device) is resolved here — environment variable first,
sensible default second — so no other module hard-codes a location.

Environment variables (all optional, prefix ``ASTRA_VOICE_``):

- ``ASTRA_VOICE_WHISPER_BIN``  — path to the whisper.cpp CLI (``whisper-cli``/``main``)
- ``ASTRA_VOICE_PIPER_BIN``    — path to the ``piper`` binary
- ``ASTRA_VOICE_STT_MODEL``    — path to a ``ggml-*.bin`` whisper model
- ``ASTRA_VOICE_TTS_MODEL``    — path to a ``*.onnx`` piper voice
- ``ASTRA_VOICE_MODELS_DIR``   — where models live (default ``voice/models``)
- ``ASTRA_VOICE_LANG``         — whisper language code (default ``en``)
- ``ASTRA_VOICE_THREADS``      — whisper thread count (default: whisper's own)
- ``ASTRA_VOICE_INPUT_DEVICE`` / ``ASTRA_VOICE_OUTPUT_DEVICE`` — audio device hint
- ``ASTRA_VOICE_AUDIO_BACKEND``— ``auto`` (default), ``sounddevice`` or ``cli``
- ``ASTRA_VOICE_KEEP_AUDIO``   — keep temporary WAVs for debugging
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# --- Repository-relative locations -------------------------------------------
VOICE_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = VOICE_DIR.parent
CORE_DIR = REPO_DIR / "core"
WEB_DIR = REPO_DIR / "web"
DEFAULT_MODELS_DIR = VOICE_DIR / "models"

ENV_PREFIX = "ASTRA_VOICE_"


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    value = os.environ.get(ENV_PREFIX + name)
    if value is None or value == "":
        return default
    return value


def _env_bool(name: str, default: bool = False) -> bool:
    raw = _env(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int = 0) -> int:
    raw = _env(name)
    if raw is None:
        return default
    try:
        return int(str(raw).strip())
    except ValueError:
        return default


def _first_existing(candidates) -> Optional[str]:
    """Return the first candidate that is an existing path or on ``PATH``."""
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate).expanduser()
        if path.exists():
            return str(path)
        found = shutil.which(str(candidate))
        if found:
            return found
    return None


@dataclass
class VoiceConfig:
    """Resolved locations and preferences for one voice session."""

    models_dir: Path = DEFAULT_MODELS_DIR
    whisper_bin: Optional[str] = None
    piper_bin: Optional[str] = None
    stt_model: Optional[str] = None
    tts_model: Optional[str] = None

    language: str = "en"
    threads: int = 0
    input_device: Optional[str] = None
    output_device: Optional[str] = None
    audio_backend: str = "auto"
    keep_audio: bool = False

    @classmethod
    def from_env(cls) -> "VoiceConfig":
        models_dir = Path(_env("MODELS_DIR", str(DEFAULT_MODELS_DIR))).expanduser()
        cfg = cls(models_dir=models_dir)

        # Binaries: explicit env, then a project-local build, then PATH.
        cfg.whisper_bin = _first_existing([
            _env("WHISPER_BIN"),
            models_dir / "whisper.cpp" / "build" / "bin" / "whisper-cli",
            models_dir / "whisper.cpp" / "build" / "bin" / "main",
            "whisper-cli",
            "whisper-cpp",
        ])
        cfg.piper_bin = _first_existing([
            _env("PIPER_BIN"),
            models_dir / "piper" / "piper",
            "piper",
        ])

        # Models: explicit env, else the first matching file under models_dir.
        explicit_stt = _env("STT_MODEL")
        cfg.stt_model = (
            str(Path(explicit_stt).expanduser()) if explicit_stt
            else cls._discover(models_dir, "ggml-*.bin", prefer=".en.")
        )
        explicit_tts = _env("TTS_MODEL")
        cfg.tts_model = (
            str(Path(explicit_tts).expanduser()) if explicit_tts
            else cls._discover(models_dir, "*.onnx")
        )

        cfg.language = _env("LANG", "en")
        cfg.threads = _env_int("THREADS", 0)
        cfg.input_device = _env("INPUT_DEVICE")
        cfg.output_device = _env("OUTPUT_DEVICE")
        cfg.audio_backend = (_env("AUDIO_BACKEND", "auto") or "auto").lower()
        cfg.keep_audio = _env_bool("KEEP_AUDIO", False)
        return cfg

    @staticmethod
    def _discover(models_dir: Path, pattern: str, prefer: str = "") -> Optional[str]:
        """Find a model file under ``models_dir`` (recursively)."""
        try:
            candidates = sorted(models_dir.rglob(pattern))
        except OSError:
            return None
        if not candidates:
            return None
        if prefer:
            preferred = [p for p in candidates if prefer in p.name]
            if preferred:
                return str(preferred[0])
        return str(candidates[0])
