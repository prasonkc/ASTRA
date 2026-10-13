"""Audio capture, playback and format conversion.

The voice wrapper supports two interchangeable audio backends and picks one at
runtime:

* **sounddevice** — pure-Python (``sounddevice`` + ``numpy``), cross-platform,
  clean start/stop, and the only backend that can do continuous listening.
* **cli** — shell out to ``arecord``/``ffmpeg``/``rec`` for recording and
  ``aplay``/``ffplay``/``play`` for playback. No Python packages needed.

whisper.cpp requires 16 kHz mono 16-bit PCM WAV, so every recording is converted
with :func:`ensure_wav16k` (a no-op when it is already in the right format).
"""
from __future__ import annotations

import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import wave
from array import array
from pathlib import Path
from typing import Optional, Tuple

# Populated by _has_sounddevice() on demand.
_SD_AVAILABLE: Optional[bool] = None


class AudioError(RuntimeError):
    """Raised when audio cannot be captured, converted or played."""


# --- backend discovery --------------------------------------------------------

def _has_sounddevice() -> bool:
    global _SD_AVAILABLE
    if _SD_AVAILABLE is None:
        try:
            import sounddevice  # noqa: F401
            import numpy  # noqa: F401
            _SD_AVAILABLE = True
        except Exception:
            _SD_AVAILABLE = False
    return _SD_AVAILABLE


def find_recorder() -> Optional[str]:
    """First available command-line recorder."""
    for name in ("arecord", "ffmpeg", "rec"):
        if shutil.which(name):
            return name
    return None


def find_player() -> Optional[str]:
    """First available command-line player."""
    for name in ("aplay", "ffplay", "play"):
        if shutil.which(name):
            return name
    return None


def select_backend(preference: str = "auto") -> str:
    """Resolve the audio backend name: ``sounddevice``, ``cli`` or ``none``."""
    preference = (preference or "auto").lower()
    sd = _has_sounddevice()
    cli = find_recorder() is not None and find_player() is not None
    if preference == "sounddevice":
        return "sounddevice" if sd else "none"
    if preference == "cli":
        return "cli" if cli else "none"
    if sd:
        return "sounddevice"
    if cli:
        return "cli"
    return "none"


def describe_audio(preference: str = "auto") -> dict:
    """Human-readable snapshot of the audio capabilities (for ``--status``)."""
    return {
        "backend": select_backend(preference),
        "sounddevice": _has_sounddevice(),
        "recorder": find_recorder(),
        "player": find_player(),
    }


# --- format helpers -----------------------------------------------------------

def _wav_format(path: Path) -> Optional[Tuple[int, int, int]]:
    try:
        with wave.open(str(path), "rb") as handle:
            return (handle.getnchannels(), handle.getframerate(), handle.getsampwidth())
    except Exception:
        return None


def ensure_wav16k(path: Path, workdir: Optional[Path] = None) -> Path:
    """Return a 16 kHz mono 16-bit WAV version of ``path``.

    A no-op when the file already has the right shape; otherwise converts with
    ``ffmpeg`` (preferred) or ``sox``. Raises :class:`AudioError` when neither
    converter is available.
    """
    path = Path(path)
    if _wav_format(path) == (1, 16000, 2):
        return path

    out = Path(workdir or path.parent) / (path.stem + ".16k.wav")
    if shutil.which("ffmpeg"):
        _run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(path), "-ar", "16000", "-ac", "1", "-sample_fmt", "s16",
            str(out),
        ])
        return out
    if shutil.which("sox"):
        _run(["sox", str(path), "-r", "16000", "-c", "1", "-b", "16", str(out)])
        return out

    raise AudioError(
        "Audio is not 16 kHz mono WAV and neither ffmpeg nor sox is installed to "
        "convert it (install one, or feed a 16 kHz mono WAV)."
    )


def _run(cmd) -> None:
    proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        detail = (proc.stderr or b"").decode("utf-8", "replace").strip()
        raise AudioError(f"Command failed ({cmd[0]}): {detail or proc.returncode}")


def _write_wav(path: Path, data, samplerate: int) -> None:
    import numpy as np

    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(samplerate)
        handle.writeframes(np.ascontiguousarray(data, dtype="int16").tobytes())


def _write_wav_bytes(path: Path, pcm: bytes, samplerate: int) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(samplerate)
        handle.writeframes(pcm)


def _rms(chunk: bytes) -> float:
    """Root-mean-square of little-endian int16 PCM, using only the stdlib.

    The command-line recorder path must not depend on numpy (that is the whole
    point of the fallback), so endpoint detection decodes PCM with ``array``.
    """
    if len(chunk) < 2:
        return 0.0
    samples = array("h")
    samples.frombytes(chunk[: len(chunk) - (len(chunk) % 2)])
    if sys.byteorder == "big":
        samples.byteswap()
    if not samples:
        return 0.0
    total = 0
    for value in samples:
        total += value * value
    return (total / len(samples)) ** 0.5


def _threshold_from(samples) -> float:
    """Speech threshold from a list of ambient RMS readings."""
    if not samples:
        return 250.0
    ordered = sorted(samples)
    noise = ordered[len(ordered) // 2]
    return max(250.0, noise * 3.0)


# --- the audio device ---------------------------------------------------------

class AudioIO:
    """Record from and play back through the machine's audio device(s)."""

    def __init__(self, config):
        self.config = config
        self.backend = select_backend(getattr(config, "audio_backend", "auto"))
        self.workdir = Path(tempfile.mkdtemp(prefix="astra-voice-"))
        self._sd = None
        if self.backend == "sounddevice":
            import sounddevice as sd
            self._sd = sd

    # ---- recording ----------------------------------------------------------
    def record(self, seconds: Optional[float] = None, stop_event: Optional[threading.Event] = None) -> Path:
        """Record audio and return a 16 kHz mono WAV path.

        ``seconds`` records a fixed length. Otherwise recording runs until
        ``stop_event`` is set (pretty-please pass one).
        """
        if self.backend == "none":
            raise AudioError(
                "No audio backend available. Install sounddevice+numpy, or a "
                "command-line recorder/player (arecord+aplay, or ffmpeg)."
            )

        raw = self.workdir / "input.wav"
        if self.backend == "sounddevice":
            self._record_sounddevice(raw, seconds, stop_event)
        else:
            self._record_cli(raw, seconds, stop_event)

        if not raw.exists() or raw.stat().st_size == 0:
            raise AudioError("Recording produced no audio.")
        return ensure_wav16k(raw, self.workdir)

    def _record_sounddevice(self, out: Path, seconds, stop_event) -> None:
        sd = self._sd
        import numpy as np

        device = self.config.input_device
        device_index = int(device) if (device and str(device).isdigit()) else device

        samplerate = 16000
        try:
            data = self._sd_capture(samplerate, seconds, stop_event, device_index)
        except Exception:
            # Some devices refuse 16 kHz; capture at the device default and let
            # ensure_wav16k() resample afterwards.
            info = sd.query_devices(device_index, "input")
            samplerate = int(info.get("default_samplerate") or 48000)
            data = self._sd_capture(samplerate, seconds, stop_event, device_index)

        _write_wav(out, data, samplerate)

    def _sd_capture(self, samplerate: int, seconds, stop_event, device):
        sd = self._sd
        import numpy as np

        if seconds:
            data = sd.rec(int(seconds * samplerate), samplerate=samplerate,
                          channels=1, dtype="int16", device=device)
            sd.wait()
            return data

        frames = []
        with sd.InputStream(samplerate=samplerate, channels=1, dtype="int16",
                            device=device) as stream:
            while not (stop_event and stop_event.is_set()):
                block, _overflowed = stream.read(int(samplerate * 0.1))
                frames.append(block.copy())
        if frames:
            return np.concatenate(frames, axis=0)
        return np.zeros((0, 1), dtype="int16")

    def _record_cli(self, out: Path, seconds, stop_event) -> None:
        recorder = find_recorder()
        if recorder is None:
            raise AudioError("No command-line recorder (arecord/ffmpeg/rec) found.")

        if recorder == "arecord":
            if seconds:
                _run(["arecord", "-q", "-f", "S16_LE", "-r", "16000", "-c", "1",
                      "-d", str(int(seconds)), "-t", "wav", str(out)])
                return
            cmd = ["arecord", "-q", "-f", "S16_LE", "-r", "16000", "-c", "1",
                   "-t", "wav", str(out)]
        elif recorder == "ffmpeg":
            cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error",
                   "-f", "alsa", "-i", self.config.input_device or "default",
                   "-ar", "16000", "-ac", "1"]
            if seconds:
                cmd += ["-t", str(seconds)]
            cmd += ["-y", str(out)]
        else:  # rec (sox)
            cmd = ["rec", "-q", "-r", "16000", "-c", "1", "-b", "16", str(out)]
            if seconds:
                cmd += ["trim", "0", str(seconds)]

        if seconds:
            _run(cmd)
            return

        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            while proc.poll() is None and not (stop_event and stop_event.is_set()):
                try:
                    if stop_event is not None:
                        stop_event.wait(0.1)
                    else:
                        threading.Event().wait(0.1)
                except Exception:
                    break
        finally:
            _stop_process(proc)

    # ---- continuous listening -----------------------------------------------
    def supports_vad(self) -> bool:
        """True when energy-gated endpoint detection is available."""
        return self.backend != "none"

    def record_utterance(
        self,
        stop_event: Optional[threading.Event] = None,
        *,
        silence_seconds: Optional[float] = None,
        max_seconds: Optional[float] = None,
        min_speech_seconds: float = 0.25,
        block_seconds: float = 0.03,
        force_event: Optional[threading.Event] = None,
    ) -> Optional[Path]:
        """Block until one spoken utterance is captured, then return its WAV.

        Endpoint detection is a simple energy gate: ambient noise is measured,
        then the recorder waits for an above-noise burst and stops after a short
        silence. Setting ``force_event`` commits the utterance early (e.g. the
        user pressed Enter), even before a pause. Returns ``None`` when
        ``stop_event`` fires before any speech is heard. Works on both audio
        backends; tunables default to the :class:`VoiceConfig` values
        (``ASTRA_VOICE_SILENCE`` / ``ASTRA_VOICE_MAX_UTTERANCE`` /
        ``ASTRA_VOICE_VAD_THRESHOLD``).
        """
        if not self.supports_vad():
            raise AudioError(
                "Continuous listening needs an audio backend (sounddevice, or a "
                "command-line recorder such as arecord/ffmpeg)."
            )

        silence_seconds = float(
            getattr(self.config, "silence_seconds", 0.8) if silence_seconds is None else silence_seconds
        )
        max_seconds = float(
            getattr(self.config, "max_utterance_seconds", 15.0) if max_seconds is None else max_seconds
        )
        threshold = float(getattr(self.config, "vad_threshold", 0) or 0)

        if self.backend == "sounddevice":
            return self._record_utterance_sounddevice(
                stop_event, silence_seconds, max_seconds, min_speech_seconds, block_seconds,
                threshold, force_event)
        return self._record_utterance_cli(
            stop_event, silence_seconds, max_seconds, min_speech_seconds, block_seconds,
            threshold, force_event)

    def _record_utterance_sounddevice(self, stop_event, silence_seconds, max_seconds,
                                      min_speech_seconds, block_seconds, threshold,
                                      force_event) -> Optional[Path]:
        sd = self._sd
        import numpy as np

        device = self.config.input_device
        device_index = int(device) if (device and str(device).isdigit()) else device
        samplerate = 16000

        threshold = threshold or self._calibrate_noise(device_index, samplerate, block_seconds)

        frames = []
        speaking = False
        speech_seconds = 0.0
        silence = 0.0

        with sd.InputStream(samplerate=samplerate, channels=1, dtype="int16",
                            device=device_index) as stream:
            while not (stop_event and stop_event.is_set()):
                if force_event is not None and force_event.is_set():
                    break
                data, _overflowed = stream.read(max(1, int(samplerate * block_seconds)))
                rms = float(np.sqrt(np.mean(np.square(data.astype(np.float32))))) if len(data) else 0.0

                if not speaking:
                    if rms > threshold:
                        speaking = True
                        speech_seconds = block_seconds
                        silence = 0.0
                        frames = [data.copy()]
                    continue

                frames.append(data.copy())
                speech_seconds += block_seconds
                silence = silence + block_seconds if rms < threshold else 0.0
                if silence >= silence_seconds or speech_seconds >= max_seconds:
                    break

        forced = force_event is not None and force_event.is_set()
        if not speaking or (speech_seconds < min_speech_seconds and not forced):
            return None

        raw = self.workdir / "utterance.wav"
        _write_wav(raw, np.concatenate(frames, axis=0), samplerate)
        return ensure_wav16k(raw, self.workdir)

    def _record_utterance_cli(self, stop_event, silence_seconds, max_seconds,
                              min_speech_seconds, block_seconds, threshold,
                              force_event) -> Optional[Path]:
        samplerate = 16000
        block_bytes = max(1, int(samplerate * block_seconds)) * 2  # int16 mono

        proc = subprocess.Popen(self._capture_raw_cmd(),
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        frames = []
        speaking = False
        speech_seconds = 0.0
        silence = 0.0
        try:
            threshold = threshold or self._calibrate_noise_cli(proc.stdout, block_bytes)

            while not (stop_event and stop_event.is_set()):
                if force_event is not None and force_event.is_set():
                    break
                chunk = proc.stdout.read(block_bytes)
                if not chunk or len(chunk) < 2:
                    break
                rms = _rms(chunk)

                if not speaking:
                    if rms > threshold:
                        speaking = True
                        speech_seconds = block_seconds
                        silence = 0.0
                        frames = [chunk]
                    continue

                frames.append(chunk)
                speech_seconds += block_seconds
                silence = silence + block_seconds if rms < threshold else 0.0
                if silence >= silence_seconds or speech_seconds >= max_seconds:
                    break
        except (OSError, ValueError) as exc:
            raise AudioError(f"Microphone capture failed: {exc}") from exc
        finally:
            _stop_process(proc)

        forced = force_event is not None and force_event.is_set()
        if not speaking or (speech_seconds < min_speech_seconds and not forced):
            return None

        raw = self.workdir / "utterance.wav"
        _write_wav_bytes(raw, b"".join(frames), samplerate)
        return ensure_wav16k(raw, self.workdir)

    def _capture_raw_cmd(self):
        """Raw 16 kHz mono int16 PCM on stdout for the active CLI recorder."""
        recorder = find_recorder()
        if recorder == "arecord":
            return ["arecord", "-q", "-f", "S16_LE", "-r", "16000", "-c", "1", "-t", "raw"]
        if recorder == "ffmpeg":
            return ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "alsa",
                    "-i", self.config.input_device or "default",
                    "-ar", "16000", "-ac", "1", "-f", "s16le", "-"]
        if recorder == "rec":
            return ["rec", "-q", "-r", "16000", "-c", "1", "-b", "16", "-t", "raw", "-"]
        raise AudioError("No command-line recorder (arecord/ffmpeg/rec) found.")

    def _calibrate_noise(self, device, samplerate: int, block_seconds: float) -> float:
        """Measure ambient RMS for a moment and return a speech threshold."""
        import numpy as np

        samples = []
        with self._sd.InputStream(samplerate=samplerate, channels=1, dtype="int16",
                                  device=device) as stream:
            for _ in range(20):  # ~0.6 s
                data, _ = stream.read(max(1, int(samplerate * block_seconds)))
                if len(data):
                    samples.append(float(np.sqrt(np.mean(np.square(data.astype(np.float32))))))
        return _threshold_from(samples)

    def _calibrate_noise_cli(self, stream, block_bytes: int, blocks: int = 20) -> float:
        """Ambient-noise calibration for the raw-pipe CLI recorder."""
        samples = []
        for _ in range(blocks):  # ~0.6 s
            chunk = stream.read(block_bytes)
            if not chunk or len(chunk) < 2:
                break
            samples.append(_rms(chunk))
        return _threshold_from(samples)

    # ---- playback -----------------------------------------------------------
    def play(self, path: Path) -> None:
        path = Path(path)
        if self.backend == "sounddevice":
            self._play_sounddevice(path)
        else:
            self._play_cli(path)

    def _play_sounddevice(self, path: Path) -> None:
        sd = self._sd
        import numpy as np

        with wave.open(str(path), "rb") as handle:
            rate = handle.getframerate()
            frames = handle.readframes(handle.getnframes())
        data = np.frombuffer(frames, dtype="int16")
        device = self.config.output_device
        device_index = int(device) if (device and str(device).isdigit()) else device
        sd.play(data, rate, device=device_index)
        sd.wait()

    def _play_cli(self, path: Path) -> None:
        player = find_player()
        if player is None:
            raise AudioError("No command-line player (aplay/ffplay/play) found.")
        if player == "aplay":
            _run(["aplay", "-q", str(path)])
        elif player == "ffplay":
            _run(["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(path)])
        else:  # play (sox)
            _run(["play", "-q", str(path)])

    # ---- lifecycle ----------------------------------------------------------
    def cleanup(self) -> None:
        if getattr(self.config, "keep_audio", False):
            return
        shutil.rmtree(self.workdir, ignore_errors=True)


def _stop_process(proc: subprocess.Popen) -> None:
    """Ask a recorder to finalise its file and exit, then clean up."""
    if proc.poll() is not None:
        return
    try:
        proc.send_signal(signal.SIGINT)  # finalises WAV for arecord/ffmpeg/sox
    except Exception:
        proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()
        try:
            proc.wait(timeout=2)
        except Exception:
            pass
