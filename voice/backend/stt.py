"""Local speech-to-text via **whisper.cpp**.

This is a thin, dependency-free wrapper around the ``whisper-cli`` (formerly
``main``) binary. The binary does the heavy lifting; we only normalise the audio
to the 16 kHz mono WAV it expects and clean the transcript it writes.

Typical CLI shape:

    whisper-cli -m ggml-base.en.bin -f input.wav -otxt -of out -nt -l en
"""
from __future__ import annotations

import re
import subprocess
import uuid
from pathlib import Path
from typing import Optional

from .audio import ensure_wav16k

# Segment timestamps (only seen if -nt was ignored) and whisper's bracketed
# non-speech tokens, e.g. [BLANK_AUDIO], [Music], [ Silence ].
_TIMESTAMP_RE = re.compile(r"\[\d{2}:\d{2}:\d{2}\.\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}\.\d{3}\]")
_NONSPEECH_RE = re.compile(r"^[\[\(]\s*[A-Za-z_ ]{2,}\s*[\]\)]$")


class WhisperError(RuntimeError):
    """Raised when whisper.cpp is missing or fails."""


def clean_transcript(raw: str) -> str:
    """Strip timestamps / blank-audio markers and collapse whitespace."""
    parts = []
    for line in (raw or "").splitlines():
        line = _TIMESTAMP_RE.sub("", line).strip()
        if not line or _NONSPEECH_RE.match(line):
            continue
        parts.append(line)
    return " ".join(parts).strip()


class WhisperCppSTT:
    """Transcribe WAV audio to text with a local whisper.cpp model."""

    def __init__(self, binary: str, model: str, language: str = "en", threads: int = 0):
        self.binary = str(binary)
        self.model = str(model)
        self.language = language or "en"
        self.threads = int(threads or 0)

    def transcribe(self, audio_path, workdir: Optional[Path] = None) -> str:
        """Return the transcript for ``audio_path`` (any format ffmpeg/sox reads)."""
        workdir = Path(workdir) if workdir else Path(audio_path).parent
        wav = ensure_wav16k(Path(audio_path), workdir)

        out_base = workdir / f"transcript-{uuid.uuid4().hex}"
        cmd = [
            self.binary,
            "-m", self.model,
            "-f", str(wav),
            "-otxt",
            "-of", str(out_base),
            "-nt",  # no timestamps: stdout / file is just the text
            "-l", self.language,
        ]
        if self.threads > 0:
            cmd += ["-t", str(self.threads)]

        try:
            proc = subprocess.run(cmd, capture_output=True, text=True)
        except OSError as exc:
            raise WhisperError(f"could not run whisper.cpp binary {self.binary}: {exc}") from exc

        # Prefer the .txt file; fall back to stdout (older verbose behaviour).
        txt_path = Path(str(out_base) + ".txt")
        if txt_path.exists():
            raw = txt_path.read_text(encoding="utf-8", errors="replace")
        elif proc.stdout.strip():
            raw = proc.stdout
        else:
            detail = (proc.stderr or "").strip().splitlines()
            tail = detail[-1] if detail else f"exit code {proc.returncode}"
            raise WhisperError(f"whisper.cpp produced no transcript ({tail})")

        return clean_transcript(raw)
