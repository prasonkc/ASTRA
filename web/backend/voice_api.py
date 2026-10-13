"""
Local speech endpoints for the web app.

The browser already owns the microphone and the speakers, so the web app only
needs the two *pure* halves of the ASTRA voice layer:

* **speech-to-text** — ``whisper.cpp`` (``voice/backend/stt.py``)
* **text-to-speech** — ``piper`` (``voice/backend/tts.py``)

This mirrors ``core/controller/voice_controller.py`` (the terminal ``/voice``
command), which reuses the exact same modules. Nothing here pulls in the web
service or the core agent: the caller transcribes a clip, sends the transcript
through the normal ``/api/chat`` stream, then asks us to synthesise the reply.

Everything is imported lazily and every failure is reported as data, so a
machine without the voice stack simply gets a clear "not ready" status instead
of a broken import (voice is optional and must degrade gracefully).
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict, Optional

# web/backend/voice_api.py -> web/backend -> web -> repository root.
REPO_DIR = Path(__file__).resolve().parents[2]
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

# Longest reply we will speak back; keeps a runaway answer from droning on.
MAX_SPEECH_CHARS = 1500


class VoiceService:
    """Lazy, thread-safe wrapper around the shared ``voice/backend`` speech layer."""

    def __init__(self, config: Optional[Any] = None):
        self._lock = threading.Lock()
        self._speech: Optional[Dict[str, Any]] = None
        self._load_error: Optional[str] = None
        self._config = config

    # ---- loading ------------------------------------------------------------
    def _load(self) -> Optional[Dict[str, Any]]:
        """Import the speech pieces once. Returns ``None`` (and records why) on failure."""
        if self._speech is not None:
            return self._speech
        if self._load_error is not None:
            return None
        try:
            from voice.backend.config import VoiceConfig
            from voice.backend.deps import build_status, format_status
            from voice.backend.stt import WhisperCppSTT
            from voice.backend.tts import PiperTTS
        except Exception as exc:  # noqa: BLE001 - report, never crash the server
            self._load_error = str(exc)
            return None

        self._speech = {
            "VoiceConfig": VoiceConfig,
            "build_status": build_status,
            "format_status": format_status,
            "WhisperCppSTT": WhisperCppSTT,
            "PiperTTS": PiperTTS,
        }
        return self._speech

    def _resolved_config(self, speech: Dict[str, Any]):
        if self._config is not None:
            return self._config
        return speech["VoiceConfig"].from_env()

    # ---- status -------------------------------------------------------------
    def status(self) -> Dict[str, Any]:
        """Readiness report for the browser voice mode (never raises)."""
        speech = self._load()
        if speech is None:
            return {
                "available": False,
                "ready": False,
                "stt_ready": False,
                "tts_ready": False,
                "audio_ready": False,
                "problems": [
                    "The voice layer could not be imported: "
                    + (self._load_error or "unknown error")
                ],
                "notes": [],
            }

        config = self._resolved_config(speech)
        report = speech["build_status"](config)
        return {
            "available": True,
            # The browser provides the audio device, so "ready" only needs STT.
            "ready": bool(report.stt_ready),
            "stt_ready": bool(report.stt_ready),
            "tts_ready": bool(report.tts_ready),
            "audio_ready": bool(report.audio_ready),
            "stt_model": Path(config.stt_model).name if config.stt_model else None,
            "tts_model": Path(config.tts_model).name if config.tts_model else None,
            "problems": list(report.problems),
            "notes": list(report.notes),
        }

    # ---- speech-to-text -----------------------------------------------------
    def transcribe_bytes(self, data: bytes, suffix: str = ".webm") -> str:
        """Transcribe an encoded audio clip (webm/ogg/wav/…) to text."""
        if not data:
            raise RuntimeError("No audio was uploaded.")

        speech = self._load()
        if speech is None:
            raise RuntimeError(
                "The voice layer is unavailable: " + (self._load_error or "unknown error")
            )

        config = self._resolved_config(speech)
        report = speech["build_status"](config)
        if not report.stt_ready:
            detail = "; ".join(report.problems) or "whisper.cpp / model not found"
            raise RuntimeError("Speech-to-text is not ready — " + detail)

        stt = speech["WhisperCppSTT"](
            config.whisper_bin,
            config.stt_model,
            language=config.language,
            threads=config.threads,
        )

        workdir = Path(tempfile.mkdtemp(prefix="astra-web-stt-"))
        try:
            source = workdir / ("clip" + (suffix or ".webm"))
            source.write_bytes(data)
            return stt.transcribe(source, workdir)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    # ---- text-to-speech -----------------------------------------------------
    def synthesize_wav(self, text: str) -> bytes:
        """Render ``text`` to 16-bit PCM WAV bytes with the local piper voice."""
        text = _speech_text(text)
        if not text:
            raise RuntimeError("Nothing to speak.")

        speech = self._load()
        if speech is None:
            raise RuntimeError(
                "The voice layer is unavailable: " + (self._load_error or "unknown error")
            )

        config = self._resolved_config(speech)
        report = speech["build_status"](config)
        if not report.tts_ready:
            detail = "; ".join(p for p in report.problems if "piper" in p.lower() or "voice" in p.lower())
            raise RuntimeError("Text-to-speech is not ready — " + (detail or "piper / voice model not found"))

        tts = speech["PiperTTS"](config.piper_bin, config.tts_model)
        workdir = Path(tempfile.mkdtemp(prefix="astra-web-tts-"))
        try:
            out = tts.synthesize(text, workdir=workdir)
            return Path(out).read_bytes()
        finally:
            shutil.rmtree(workdir, ignore_errors=True)


def _speech_text(text: str) -> str:
    """Flatten a reply into something worth reading aloud."""
    import re

    text = (text or "").strip()
    if not text:
        return ""
    # Drop fenced code blocks, then strip the most common markdown markers.
    text = re.sub(r"```.*?```", " (code omitted) ", text, flags=re.DOTALL)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)  # links / images
    text = re.sub(r"https?://\S+", "link", text)
    text = re.sub(r"[*_#>]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    if len(text) > MAX_SPEECH_CHARS:
        clipped = text[:MAX_SPEECH_CHARS]
        cut = max(clipped.rfind(". "), clipped.rfind("! "), clipped.rfind("? "))
        text = (clipped[: cut + 1] if cut > 200 else clipped).strip() + " …"
    return text


# --- process-wide singleton --------------------------------------------------
_voice_service: Optional[VoiceService] = None
_voice_lock = threading.Lock()


def get_voice_service() -> VoiceService:
    global _voice_service
    with _voice_lock:
        if _voice_service is None:
            _voice_service = VoiceService()
        return _voice_service
