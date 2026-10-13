"""Local text-to-speech via **piper**.

A thin wrapper around the ``piper`` binary. Text is fed on stdin and a WAV is
written to disk, ready for the audio layer to play.

Typical CLI shape:

    echo "hello" | piper -m en_US-lessac-medium.onnx -f reply.wav
"""
from __future__ import annotations

import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Optional


class PiperError(RuntimeError):
    """Raised when piper is missing or fails."""


class PiperTTS:
    """Synthesise speech locally with a piper voice model."""

    def __init__(self, binary: str, model: str, speaker: Optional[str] = None):
        self.binary = str(binary)
        self.model = str(model)
        self.speaker = speaker

    def synthesize(
        self,
        text: str,
        out_path: Optional[Path] = None,
        workdir: Optional[Path] = None,
    ) -> Path:
        """Render ``text`` to a WAV file and return its path."""
        text = (text or "").strip()
        if not text:
            raise PiperError("Cannot synthesise empty text.")

        if out_path is not None:
            out = Path(out_path)
        else:
            base = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="astra-voice-"))
            out = base / f"reply-{uuid.uuid4().hex}.wav"

        cmd = [self.binary, "-m", self.model, "-f", str(out)]
        if self.speaker is not None:
            cmd += ["-s", str(self.speaker)]

        try:
            proc = subprocess.run(cmd, input=text.encode("utf-8"), capture_output=True)
        except OSError as exc:
            raise PiperError(f"could not run piper binary {self.binary}: {exc}") from exc

        if proc.returncode != 0 or not out.exists() or out.stat().st_size == 0:
            detail = (proc.stderr or b"").decode("utf-8", "replace").strip().splitlines()
            tail = detail[-1] if detail else f"exit code {proc.returncode}"
            raise PiperError(f"piper failed to synthesise speech ({tail})")

        return out
