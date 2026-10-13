"""Dependency detection for the voice wrapper.

Centralises "is the voice layer usable, and if not, what is missing?" so both the
``--status`` command and the voice loop can give the same, actionable answer.
Nothing here raises: a missing optional piece is reported, not fatal.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from .audio import describe_audio
from .config import VoiceConfig


@dataclass
class VoiceStatus:
    """Readiness report for the speech layer."""

    stt_ready: bool
    tts_ready: bool
    audio_ready: bool
    whisper_bin: Optional[str]
    piper_bin: Optional[str]
    stt_model: Optional[str]
    tts_model: Optional[str]
    audio: dict
    problems: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    @property
    def conversation_ready(self) -> bool:
        """True when we can at least hear the user and answer in text."""
        return self.stt_ready and self.audio_ready


def _is_executable(path: Optional[str]) -> bool:
    if not path:
        return False
    candidate = Path(path)
    return candidate.is_file() and os.access(candidate, os.X_OK)


def _is_file(path: Optional[str]) -> bool:
    return bool(path) and Path(path).is_file()


def build_status(config: VoiceConfig) -> VoiceStatus:
    audio = describe_audio(config.audio_backend)

    whisper_ok = _is_executable(config.whisper_bin)
    stt_model_ok = _is_file(config.stt_model)
    piper_ok = _is_executable(config.piper_bin)
    tts_model_ok = _is_file(config.tts_model)
    audio_ok = audio.get("backend") != "none"

    problems: List[str] = []
    notes: List[str] = []

    if not whisper_ok:
        problems.append(
            "whisper.cpp binary not found — build it (see voice/README.md) or set "
            "ASTRA_VOICE_WHISPER_BIN / run './voice/astra-voice --setup'."
        )
    if not stt_model_ok:
        problems.append(
            "whisper model not found — download one with './voice/astra-voice --setup' "
            "or set ASTRA_VOICE_STT_MODEL."
        )
    if not audio_ok:
        problems.append(
            "no audio backend — install the optional Python extras "
            "('pip install -r voice/requirements.txt') or a recorder+player "
            "(arecord/aplay, or ffmpeg)."
        )
    if not piper_ok:
        problems.append(
            "piper binary not found — install it (see voice/README.md) or set "
            "ASTRA_VOICE_PIPER_BIN."
        )
    if not tts_model_ok:
        problems.append(
            "piper voice model not found — download one with "
            "'./voice/astra-voice --setup' or set ASTRA_VOICE_TTS_MODEL."
        )

    if not (piper_ok and tts_model_ok):
        notes.append("Text-to-speech is unavailable: replies will be printed, not spoken.")

    return VoiceStatus(
        stt_ready=whisper_ok and stt_model_ok,
        tts_ready=piper_ok and tts_model_ok,
        audio_ready=audio_ok,
        whisper_bin=config.whisper_bin,
        piper_bin=config.piper_bin,
        stt_model=config.stt_model,
        tts_model=config.tts_model,
        audio=audio,
        problems=problems,
        notes=notes,
    )


def _mark(ok: bool) -> str:
    return "ok" if ok else "--"


def format_status(status: VoiceStatus, config: VoiceConfig) -> str:
    """Render a human-readable readiness report (used by ``--status``)."""
    audio = status.audio
    lines = [
        "ASTRA voice — readiness",
        "",
        f"  whisper.cpp binary : {_mark(_is_executable(status.whisper_bin))}  {status.whisper_bin or '(not found)'}",
        f"  whisper model      : {_mark(_is_file(status.stt_model))}  {status.stt_model or '(not found)'}",
        f"  piper binary       : {_mark(_is_executable(status.piper_bin))}  {status.piper_bin or '(not found)'}",
        f"  piper voice model  : {_mark(_is_file(status.tts_model))}  {status.tts_model or '(not found)'}",
        f"  audio backend      : {_mark(status.audio_ready)}  {audio.get('backend')}"
        f"  (recorder={audio.get('recorder') or '-'}, player={audio.get('player') or '-'})",
        f"  speech-to-text     : {_mark(status.stt_ready)}",
        f"  text-to-speech     : {_mark(status.tts_ready)}",
        f"  models dir         : {config.models_dir}",
    ]
    if status.problems:
        lines += ["", "  Missing:"]
        lines += [f"    - {p}" for p in status.problems]
    if status.notes:
        lines += [""] + [f"  note: {n}" for n in status.notes]
    return "\n".join(lines)
