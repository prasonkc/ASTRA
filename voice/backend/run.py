#!/usr/bin/env python3
"""astra-voice entrypoint.

Runs the ASTRA voice wrapper: a local speech layer (whisper.cpp for
speech-to-text, piper for text-to-speech) that lets you talk to the agent.

The default mode listens **continuously**: the microphone stays open, and the
moment you stop talking the utterance is transcribed, answered and spoken. You
can also press **Enter** to send what you have said so far without waiting for
the pause (disable with ``--no-enter``).

Usage:
    ./voice/astra-voice                     # continuous listening (default)
    ./voice/astra-voice --push-to-talk      # press Enter to talk, Enter to stop
    ./voice/astra-voice --file clip.wav     # process one audio file
    ./voice/astra-voice --text "hello"      # send text (no microphone)
    ./voice/astra-voice --say "hello"       # speak text, don't talk to the agent
    ./voice/astra-voice --status            # show readiness / what is missing
    ./voice/astra-voice --setup             # download local models
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

VOICE_DIR = Path(__file__).resolve().parents[1]
if str(VOICE_DIR) not in sys.path:
    sys.path.insert(0, str(VOICE_DIR))

from backend import install  # noqa: E402
from backend.agent import AgentError, VoiceAgent  # noqa: E402
from backend.audio import AudioIO  # noqa: E402
from backend.config import VoiceConfig  # noqa: E402
from backend.deps import build_status, format_status  # noqa: E402
from backend.stt import WhisperCppSTT  # noqa: E402
from backend.tts import PiperTTS  # noqa: E402
from backend.voice_loop import VoiceLoop, _paint  # noqa: E402


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="astra-voice",
        description="Talk to ASTRA with your voice, fully locally.",
    )
    parser.add_argument("--status", action="store_true",
                        help="Show whether the speech layer is ready, then exit.")
    parser.add_argument("--setup", action="store_true",
                        help="Download whisper.cpp models and a piper voice, then exit.")
    parser.add_argument("--stt-model", metavar="NAME", default=None,
                        help="whisper.cpp model size to fetch during --setup "
                             "(e.g. tiny.en, base.en, small).")
    parser.add_argument("--tts-voice", metavar="NAME", default=None,
                        help="piper voice to fetch during --setup "
                             "(e.g. en_US-lessac-medium).")

    parser.add_argument("--file", metavar="PATH",
                        help="Transcribe and answer a single WAV file, then exit.")
    parser.add_argument("--text", metavar="TEXT",
                        help="Send a text message to the agent (no microphone), then exit.")
    parser.add_argument("--say", metavar="TEXT",
                        help="Speak TEXT with piper only (does not call the agent), then exit.")
    parser.add_argument("--listen", action="store_true",
                        help="Continuous listening (this is the default; kept for "
                             "compatibility).")
    parser.add_argument("--push-to-talk", action="store_true",
                        help="Press Enter to record and Enter again to send, instead "
                             "of continuous listening.")
    parser.add_argument("--seconds", type=float, default=None, metavar="N",
                        help="With --push-to-talk, record a fixed N seconds per turn.")
    parser.add_argument("--stt-only", action="store_true",
                        help="With --file/--seconds, only transcribe (no agent/reply).")
    parser.add_argument("--no-enter", action="store_true",
                        help="In continuous mode, ignore the Enter key and only send "
                             "on a pause.")

    parser.add_argument("--no-tts", action="store_true",
                        help="Do not speak replies (print them only).")
    parser.add_argument("--no-stream", action="store_true",
                        help="Print replies when complete instead of streaming them.")
    parser.add_argument("--model", metavar="NAME", default=None,
                        help="Override the agent model for this session.")
    parser.add_argument("--models-dir", metavar="PATH", default=None,
                        help="Where speech models live (default: voice/models).")
    return parser.parse_args()


def _config(args: argparse.Namespace) -> VoiceConfig:
    if args.models_dir:
        os.environ["ASTRA_VOICE_MODELS_DIR"] = str(Path(args.models_dir).expanduser())
    config = VoiceConfig.from_env()
    if getattr(args, "no_enter", False):
        config.enter_to_send = False
    return config


def _build_stt(config: VoiceConfig) -> WhisperCppSTT:
    return WhisperCppSTT(config.whisper_bin, config.stt_model,
                         language=config.language, threads=config.threads)


def _build_tts(config: VoiceConfig) -> PiperTTS:
    return PiperTTS(config.piper_bin, config.tts_model)


def _build_agent(config: VoiceConfig, model_name) -> VoiceAgent:
    return VoiceAgent(model_name=model_name)


def main() -> int:
    args = _parse_args()
    config = _config(args)

    if args.setup:
        return install.main(stt_model=args.stt_model, tts_voice=args.tts_voice,
                            models_dir=config.models_dir)

    status = build_status(config)
    if args.status:
        print(format_status(status, config))
        return 0 if status.conversation_ready else 1

    # --- Speech-only helper: synthesise and play, no agent -------------------
    if args.say:
        if not status.tts_ready or not status.audio_ready:
            print(_paint("Text-to-speech is not available:", "31"))
            for problem in status.problems:
                print(f"  - {problem}")
            return 2
        audio = AudioIO(config)
        try:
            wav = _build_tts(config).synthesize(args.say, workdir=audio.workdir)
            audio.play(wav)
        finally:
            audio.cleanup()
        return 0

    # --- Validate what this mode actually needs ------------------------------
    needs_audio = not (args.text)
    missing_audio = needs_audio and not status.audio_ready
    missing_stt = needs_audio and not status.stt_ready
    if not args.stt_only and not status.conversation_ready and not args.text:
        _print_problems(status)
        return 2
    if args.stt_only and (missing_audio or missing_stt):
        _print_problems(status)
        return 2

    audio = AudioIO(config)
    stt = _build_stt(config)
    tts = None if args.no_tts else (_build_tts(config) if status.tts_ready else None)
    if not args.no_tts and tts is None:
        print(_paint("note: text-to-speech unavailable — replies will be printed only.", "33"))

    agent = None
    try:
        # Transcription-only mode never needs the agent.
        if args.stt_only:
            return _run_stt_only(args, stt, audio)

        try:
            agent = _build_agent(config, args.model)
        except AgentError as exc:
            print(_paint(f"! {exc}", "31"))
            return 3

        loop = VoiceLoop(config, agent, stt, tts, audio,
                         speak=not args.no_tts, stream=not args.no_stream)

        if args.text:
            loop.handle_text(args.text)
            return 0
        if args.file:
            loop.handle_wav(Path(args.file))
            return 0
        # Interactive-by-request: push-to-talk, or a fixed capture window.
        if args.push_to_talk or args.seconds is not None:
            loop.run_interactive(seconds=args.seconds)
            return 0
        # Default: keep listening and answer when the user pauses.
        loop.run_continuous()
        return 0
    except FileNotFoundError as exc:
        print(_paint(f"! {exc}", "31"))
        return 2
    except RuntimeError as exc:
        print(_paint(f"! {exc}", "31"))
        return 2
    finally:
        if agent is not None:
            agent.close()
        audio.cleanup()


def _run_stt_only(args, stt, audio) -> int:
    if args.file:
        text = stt.transcribe(Path(args.file), workdir=audio.workdir)
    else:
        wav = audio.record(seconds=args.seconds or 5.0)
        text = stt.transcribe(wav, workdir=audio.workdir)
    print(text)
    return 0


def _print_problems(status) -> None:
    print(_paint("The voice layer is not ready yet:", "31"))
    for problem in status.problems:
        print(f"  - {problem}")
    print("\nRun './voice/astra-voice --setup' to download local models, "
          "or './voice/astra-voice --status' for details.")


if __name__ == "__main__":
    raise SystemExit(main())
