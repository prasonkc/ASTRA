"""The voice conversation loop.

Ties the speech layer together:

    microphone ─▶ whisper.cpp (STT) ─▶ ASTRA agent ─▶ piper (TTS) ─▶ speaker

The default mode is **continuous listening**: the microphone stays open, an
energy gate detects when you start and (more importantly) stop speaking, and the
utterance is processed the moment you pause. Push-to-talk remains available for
noisy environments or when endpoint detection is unreliable.

The loop is deliberately UI-light: it prints the transcript and the streamed
reply, and speaks the reply when text-to-speech is available. It never raises for
a single failed utterance — a bad recording or a TTS hiccup is reported and the
loop continues.
"""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Dict, Optional

from .audio import AudioError


def _supports_color() -> bool:
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def _is_tty() -> bool:
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def _paint(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _supports_color() else text


class _NoEcho:
    """Context manager that turns off terminal echo while active (POSIX only).

    Used during continuous listening so the Enter that commits an utterance does
    not smudge the ``🎤 listening…`` indicator. Best-effort: if the terminal is
    not a TTY or ``termios`` is unavailable (e.g. Windows), it does nothing.
    """

    def __enter__(self) -> "_NoEcho":
        self._fd = None
        self._saved = None
        try:
            import termios

            fd = sys.stdin.fileno()
            if not sys.stdin.isatty():
                return self
            saved = termios.tcgetattr(fd)
            attrs = list(saved)
            attrs[3] &= ~termios.ECHO  # keep ISIG so Ctrl-C still works
            termios.tcsetattr(fd, termios.TCSADRAIN, attrs)
            self._fd, self._saved = fd, saved
        except Exception:
            self._fd = None
        return self

    def __exit__(self, *exc) -> bool:
        if self._fd is not None:
            try:
                import termios

                termios.tcsetattr(self._fd, termios.TCSADRAIN, self._saved)
            except Exception:
                pass
        return False


class VoiceLoop:
    """Orchestrates one voice conversation with ASTRA."""

    def __init__(self, config, agent, stt, tts, audio, *,
                 speak: bool = True, stream: bool = True, cooldown: float = 0.4,
                 out: Optional[Callable[..., None]] = None,
                 continuous_hint: Optional[str] = None):
        self.config = config
        self.agent = agent
        self.stt = stt
        self.tts = tts
        self.audio = audio
        self.speak = speak and tts is not None
        self.stream = stream
        self.cooldown = cooldown
        self.enter_to_send = bool(getattr(config, "enter_to_send", True))
        self._tty = _is_tty()
        self._out = out or print
        # Trailing note shown when continuous listening starts. Overridable so a
        # host that is not the standalone launcher (e.g. the terminal's /voice)
        # can drop the launcher-specific --push-to-talk pointer.
        self.continuous_hint = continuous_hint or (
            "Ctrl-C to stop (--push-to-talk disables this)."
        )

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

    def run_continuous(self) -> None:
        """Hands-free loop: keep listening; answer when the user stops talking.

        The microphone is opened per utterance, so nothing is captured while a
        reply is generated or spoken (no self-hearing). This is the default mode.
        On an interactive terminal, pressing **Enter** sends whatever has been
        said so far without waiting for the pause (see ``enter_to_send``).
        """
        if not self.audio.supports_vad():
            raise RuntimeError(
                "Continuous listening needs an audio backend (sounddevice, or a "
                "command-line recorder such as arecord/ffmpeg). "
                "Use --push-to-talk instead."
            )
        stdin_tty = hasattr(sys.stdin, "isatty") and sys.stdin.isatty()
        manual = threading.Event() if (self.enter_to_send and self._tty and stdin_tty) else None
        stop = threading.Event() if manual is not None else None
        watcher = self._start_enter_watcher(manual, stop) if manual is not None else None
        self.banner()
        hint = (" — or press Enter to send." if manual is not None else ".")
        self._out(_paint("Listening continuously — just speak, then pause" + hint +
                         "  " + self.continuous_hint, "2"))
        failures = 0
        try:
            with _NoEcho():
                while True:
                    if manual is not None:
                        manual.clear()
                    self._show_listening(enter=manual is not None)
                    try:
                        wav = self.audio.record_utterance(force_event=manual)
                    except AudioError as exc:
                        self._clear_line()
                        failures += 1
                        self._out(_paint(f"! microphone error: {exc}", "31"))
                        if failures >= 3:
                            raise
                        time.sleep(1.0)
                        continue
                    failures = 0
                    sent = manual.is_set() if manual is not None else False
                    self._clear_line()
                    if wav is None:
                        if sent:
                            self._out(_paint("  (nothing captured yet — keep talking)", "2"))
                        time.sleep(0.05)  # recorder exited with no audio: avoid a hot loop
                        continue
                    self.handle_wav(wav)
                    if self.cooldown > 0:
                        time.sleep(self.cooldown)  # let any speaker tail decay
        except KeyboardInterrupt:
            self._clear_line()
            self._out("")
            self._out(_paint("Stopped.", "2"))
        finally:
            # Stop the stdin watcher before returning, so it never competes with
            # a host REPL's input() for the next line (the terminal's /voice).
            if stop is not None:
                stop.set()
            if watcher is not None:
                watcher.join(timeout=1.0)

    # ---- terminal helpers ---------------------------------------------------
    def _show_listening(self, enter: bool = False) -> None:
        if self._tty:
            hint = "🎤 listening…  (Enter to send)" if enter else "🎤 listening…"
            self._out(_paint(hint, "32"), end="", flush=True)

    def _clear_line(self) -> None:
        if self._tty:
            self._out("\r\033[K", end="", flush=True)

    def _start_enter_watcher(self, event: threading.Event,
                             stop: Optional[threading.Event] = None) -> "threading.Thread":
        """Set ``event`` whenever the user presses Enter (interactive TTY only).

        Returns the watcher thread. When ``stop`` is given, the thread polls with
        a short timeout and exits once it is set, so a host REPL can safely reuse
        stdin after continuous listening ends.
        """
        def watch() -> None:
            fd = None
            try:
                fd = sys.stdin.fileno()
            except Exception:
                fd = None
            while not (stop is not None and stop.is_set()):
                if fd is not None:
                    # POSIX: wait for input without blocking forever, reading raw
                    # bytes so a stop request is honoured within the timeout.
                    try:
                        import select as _select

                        ready, _, _ = _select.select([fd], [], [], 0.1)
                    except Exception:
                        fd = None  # select unavailable: fall back to readline
                        continue
                    if not ready:
                        continue
                    try:
                        data = os.read(fd, 4096)
                    except OSError:
                        return
                    if not data:  # EOF
                        return
                    if b"\n" in data or b"\r" in data:
                        event.set()
                    continue
                try:
                    line = sys.stdin.readline()
                except Exception:
                    return
                if line == "":  # stdin closed / EOF
                    return
                event.set()

        thread = threading.Thread(target=watch, name="voice-enter", daemon=True)
        thread.start()
        return thread
