"""``/voice`` — hands-free speech for the terminal application.

The standalone ``voice/`` wrapper is a *separate process* (a frontend like
``web/``) that embeds the core. This controller instead runs the speech layer
**inside the terminal process** and drives the terminal's own agent model, so a
spoken turn continues the very same session and history that is already open in
the REPL.

Only the pure speech pieces are reused from ``voice/backend`` — ``audio`` (mic +
VAD), ``stt`` (whisper.cpp) and ``tts`` (piper) — via the shared ``voice_loop``
orchestrator. Nothing here pulls in the web service: the terminal already owns
its model and turn lock.

Modes (all local, all optional):

    /voice          continuous listening (default) — speak, then pause
    /voice once     record a single utterance, then return to the prompt
    /voice push     push-to-talk REPL (Enter records, type to send, q quits)
    /voice status   show which speech components are installed
    /voice help     this help
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from utils.colors import error, info, warning, dim


class TerminalAgentAdapter:
    """Adapts the terminal's :class:`~ai.model.AgentModel` to the voice agent API.

    :class:`~voice.backend.voice_loop.VoiceLoop` expects an object with ``ask``
    (streaming a turn) and ``describe`` (provider/model for the banner). The
    terminal model already streams chunks and reports tool activity through its
    ``on_event`` callback, so the adapter is a thin translation layer.
    """

    def __init__(self, model, turn_lock):
        self.model = model
        self.turn_lock = turn_lock

    def ask(
        self,
        prompt: str,
        on_delta: Optional[Callable[[str], None]] = None,
        on_tool: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        """Run one agent turn, streaming content and surfacing tool calls."""
        parts: List[str] = []
        error_text: Optional[str] = None

        def on_event(event: dict) -> None:
            try:
                if event.get("type") == "tool_call" and on_tool:
                    on_tool(event.get("name") or "tool")
            except Exception:
                pass

        # Serialize with the REPL and the browser bridge: all three share one
        # model/history and must not interleave.
        with self.turn_lock:
            try:
                for chunk in self.model.generate(prompt, on_event=on_event):
                    message = getattr(chunk, "message", None)
                    content = getattr(message, "content", None) if message else None
                    if content:
                        parts.append(content)
                        if on_delta:
                            on_delta(content)
            except Exception as exc:  # noqa: BLE001 - surfaced to the voice loop
                error_text = str(exc)

        return {
            "reply": "".join(parts).strip(),
            "error": error_text,
            "session_id": getattr(self.model, "session_id", None),
        }

    def describe(self) -> Dict[str, Any]:
        """Return provider/model info for the voice banner (never raises)."""
        try:
            return self.model.describe()
        except Exception:
            return {}


class VoiceController:
    """Dispatches ``/voice`` and runs the speech loop against the terminal model."""

    _HELP = (
        "Voice mode (local speech — optional):",
        "  /voice          Continuous listening: speak, then pause (Ctrl-C stops)",
        "  /voice once     Record one utterance, then return to the prompt",
        "  /voice push     Push-to-talk REPL (Enter records, type to send, q quits)",
        "  /voice status   Show which speech components are installed",
        "  /voice help     Show this help",
        "  Setup: ./voice/astra-voice --setup   (whisper.cpp + piper — see voice/README.md)",
    )

    def __init__(self, model, turn_lock):
        self.model = model
        self.turn_lock = turn_lock
        self._speech: Optional[Dict[str, Any]] = None
        self._load_error: Optional[str] = None

    # ---- /voice dispatch ----------------------------------------------------
    def handle(self, command: str) -> None:
        """Handle a ``/voice ...`` line typed at the terminal prompt."""
        tokens = (command or "").strip().split()
        sub = tokens[1].lower() if len(tokens) > 1 else ""

        if sub in ("", "on", "start", "listen", "continuous"):
            self.listen()
        elif sub in ("once", "one", "single"):
            self.listen_once()
        elif sub in ("push", "ptt", "talk"):
            self.push_to_talk()
        elif sub in ("status", "check"):
            self.status()
        elif sub in ("help", "-h", "--help", "?"):
            self.help()
        else:
            print(warning(f"Unknown /voice option: {sub}"))
            self.help()

    # ---- modes --------------------------------------------------------------
    def listen(self) -> None:
        """Continuous hands-free listening (the default ``/voice`` mode)."""
        loop = self._build_loop()
        if loop is None:
            return
        try:
            loop.run_continuous()
        finally:
            self._close(loop)

    def listen_once(self) -> None:
        """Record and process a single utterance, then return to the prompt."""
        loop = self._build_loop()
        if loop is None:
            return
        try:
            loop.listen_once()
        finally:
            self._close(loop)

    def push_to_talk(self) -> None:
        """Nested push-to-talk REPL; returns on 'q', EOF or Ctrl-C."""
        loop = self._build_loop()
        if loop is None:
            return
        try:
            loop.run_interactive()
        except KeyboardInterrupt:
            print()
        finally:
            self._close(loop)

    def status(self) -> None:
        """Print the readiness report from the shared dependency checker."""
        speech = self._load()
        if speech is None:
            return
        config = speech["VoiceConfig"].from_env()
        report = speech["build_status"](config)
        print(speech["format_status"](report, config))

    def help(self) -> None:
        for line in self._HELP:
            print(line if line.startswith("  ") else info(line))

    # ---- construction -------------------------------------------------------
    def _load(self) -> Optional[Dict[str, Any]]:
        """Import the speech layer from ``voice/backend`` (lazily, once)."""
        if self._speech is not None:
            return self._speech
        if self._load_error is not None:
            print(error(f"Voice layer unavailable: {self._load_error}"))
            return None

        # core/controller/voice_controller.py -> core -> repository root.
        repo_dir = Path(__file__).resolve().parents[2]
        if str(repo_dir) not in sys.path:
            sys.path.insert(0, str(repo_dir))
        try:
            from voice.backend.audio import AudioIO
            from voice.backend.config import VoiceConfig
            from voice.backend.deps import build_status, format_status
            from voice.backend.stt import WhisperCppSTT
            from voice.backend.tts import PiperTTS
            from voice.backend.voice_loop import VoiceLoop
        except Exception as exc:  # noqa: BLE001 - degrade gracefully
            self._load_error = str(exc)
            print(error(f"Voice layer unavailable: {exc}"))
            print(dim("Run ./voice/astra-voice --setup to install the local speech layer."))
            return None

        self._speech = {
            "AudioIO": AudioIO,
            "VoiceConfig": VoiceConfig,
            "build_status": build_status,
            "format_status": format_status,
            "WhisperCppSTT": WhisperCppSTT,
            "PiperTTS": PiperTTS,
            "VoiceLoop": VoiceLoop,
        }
        return self._speech

    def _build_loop(self):
        """Wire config/audio/stt/tts + the terminal agent into a ``VoiceLoop``."""
        speech = self._load()
        if speech is None:
            return None

        config = speech["VoiceConfig"].from_env()
        report = speech["build_status"](config)
        if not report.conversation_ready:
            print(error("Voice is not ready yet — missing pieces:"))
            for problem in report.problems:
                print(f"  - {problem}")
            print(dim("Run ./voice/astra-voice --setup (see voice/README.md)."))
            return None

        audio = speech["AudioIO"](config)
        stt = speech["WhisperCppSTT"](
            config.whisper_bin, config.stt_model,
            language=config.language, threads=config.threads,
        )
        tts = speech["PiperTTS"](config.piper_bin, config.tts_model) if report.tts_ready else None
        if tts is None:
            print(dim("(text-to-speech off — replies are printed only)"))

        agent = TerminalAgentAdapter(self.model, self.turn_lock)
        return speech["VoiceLoop"](
            config, agent, stt, tts, audio,
            continuous_hint="Ctrl-C returns to the terminal prompt.",
        )

    @staticmethod
    def _close(loop) -> None:
        """Release the microphone/temp files after a voice session."""
        try:
            loop.audio.cleanup()
        except Exception:
            pass
