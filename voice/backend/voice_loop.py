"""The voice conversation loop.

Ties the speech layer together:

    microphone ─▶ whisper.cpp (STT) ─▶ ASTRA agent ─▶ piper (TTS) ─▶ speaker

The loop is deliberately UI-light: it prints the transcript and the streamed
reply, and speaks the reply when text-to-speech is available. It never raises for
a single failed utterance — a bad recording or a TTS hiccup is reported and the
loop continues.
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Callable, Dict, Optional


def _supports_color() -> bool:
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def _paint(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _supports_color() else text


class VoiceLoop:
    """Orchestrates one voice conversation with ASTRA."""

    def __init__(self, config, agent, stt, tts, audio, *,
                 speak: bool = True, stream: bool = True,
                 out: Optional[Callable[..., None]] = None):
        self.config = config
        self.agent = agent
        self.stt = stt
        self.tts = tts
        self.audio = audio
        self.speak = speak and tts is not None
        self.stream = stream
        self._out = out or print

    # ---- presentation -------------------------------------------------------
    def banner(self) -> None:
        try:
            info = self.agent.describe() if self.agent else {}
        except Exception:
            info = {}
        provider = info.get("provider") or "?"
        model = info.get("model") or "?"
        self._out(_paint("ASTRA voice", "1;36") + f"  ·  {provider}/{model}")
        if not self.speak:
            self._out(_paint("  (text-to-speech off — replies are printed only)", "33"))

    # ---- core pipeline ------------------------------------------------------
    def handle_wav(self, wav: Path) -> Optional[Dict]:
        """Transcribe a WAV, ask the agent, speak the reply."""
        try:
            transcript = self.stt.transcribe(wav, workdir=self.audio.workdir)
        except Exception as exc:  # noqa: BLE001 - one bad utterance is not fatal
            self._out(_paint(f"! transcription failed: {exc}", "31"))
            return None

        transcript = transcript.strip()
        if not transcript:
            self._out(_paint("(heard nothing)", "33"))
            return None
        return self.handle_text(transcript)

    def handle_text(self, text: str) -> Optional[Dict]:
        """Send text to the agent, print the reply, speak it."""
        text = (text or "").strip()
        if not text:
            return None

        self._out(f"{_paint('You', '36')}: {text}")
        self._out(f"{_paint('ASTRA', '35')}: ", end="")
        emitted = {"any": False}

        def on_delta(delta: str) -> None:
            emitted["any"] = True
            self._out(delta, end="")

        def on_tool(name: str) -> None:
            self._out("\n" + _paint(f"  · tool: {name}", "33"), end="")

        result = self.agent.ask(
            text,
            on_delta=on_delta if self.stream else None,
            on_tool=on_tool,
        )

        if not emitted["any"]:
            self._out(result.get("reply") or "", end="")
        self._out("")  # finish the line

        if result.get("error"):
            self._out(_paint(f"! {result['error']}", "31"))

        reply = result.get("reply") or ""
        if self.speak and reply:
            self._speak(reply)
        return result

    def _speak(self, text: str) -> None:
        try:
            wav = self.tts.synthesize(text, workdir=self.audio.workdir)
            self.audio.play(wav)
        except Exception as exc:  # noqa: BLE001
            self._out(_paint(f"  (speech unavailable: {exc})", "33"))

    # ---- interaction modes --------------------------------------------------
    def listen_once(self, seconds: Optional[float] = None) -> Optional[Dict]:
        """Record one utterance (fixed length or Enter-terminated) and process it."""
        if seconds:
            self._out(_paint(f"⏺ recording {seconds:g}s…", "32"))
            wav = self.audio.record(seconds=seconds)
        else:
            stop = threading.Event()
            holder: Dict[str, object] = {}

            def worker() -> None:
                try:
                    holder["wav"] = self.audio.record(stop_event=stop)
                except Exception as exc:  # noqa: BLE001
                    holder["error"] = exc

            thread = threading.Thread(target=worker, name="astra-voice-record", daemon=True)
            thread.start()
            self._out(_paint("⏺ recording… press Enter to stop", "32"))
            try:
                input()
            except (EOFError, KeyboardInterrupt):
                pass
            stop.set()
            thread.join()
            if "error" in holder:
                raise holder["error"]
            wav = holder.get("wav")

        if wav is None:
            self._out(_paint("(no audio captured)", "33"))
            return None
        return self.handle_wav(wav)

    def run_interactive(self, seconds: Optional[float] = None) -> None:
        """Push-to-talk REPL: Enter records, typed text is sent directly, q quits."""
        self.banner()
        self._out(_paint("Press Enter to talk, type a message, or 'q' to quit.", "2"))
        while True:
            try:
                entry = input(_paint("voice> ", "36")).strip()
            except (EOFError, KeyboardInterrupt):
                break
            if entry.lower() in ("q", "quit", "exit"):
                break
            if entry:
                self.handle_text(entry)
                continue
            self.listen_once(seconds=seconds)

    def run_listen(self) -> None:
        """Hands-free loop: wait for speech, answer, repeat until Ctrl-C."""
        if not self.audio.supports_vad():
            raise RuntimeError(
                "Continuous listening needs the sounddevice backend "
                "(install voice/requirements.txt), or use push-to-talk instead."
            )
        self.banner()
        self._out(_paint("Listening… speak any time (Ctrl-C to stop).", "2"))
        try:
            while True:
                wav = self.audio.record_utterance()
                if wav is not None:
                    self.handle_wav(wav)
        except KeyboardInterrupt:
            self._out("")
            self._out(_paint("Stopped.", "2"))
