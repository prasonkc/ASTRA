# astra-voice

A local speech wrapper around the standalone **ASTRA** terminal application — talk
to your agent and hear it answer, entirely on your machine. ASTRA core stays a
fully standalone app (`core/`); `voice/` only adds ears and a mouth.

```
voice/
├── astra-voice          # single launcher script (start with one command)
├── requirements.txt     # OPTIONAL Python audio extras (sounddevice, numpy)
├── README.md            # this file
├── ARCHITECTURE.md      # design: pipeline, config, degradation, roadmap
├── models/              # local models (git-ignored; created by --setup)
└── backend/
    ├── run.py           # entrypoint (arg parsing, mode dispatch)
    ├── config.py        # env-first resolution of binaries/models/devices
    ├── deps.py          # readiness detection ("what is missing?")
    ├── audio.py         # record / VAD / play / 16 kHz conversion
    ├── stt.py           # whisper.cpp wrapper (speech → text)
    ├── tts.py           # piper wrapper (text → speech)
    ├── agent.py         # bridge to the ASTRA core (reuses astra_service)
    ├── voice_loop.py    # record → transcribe → ask → speak
    └── install.py       # --setup downloads/builds local models
```

## What it does

```
microphone ─▶ whisper.cpp (STT) ─▶ ASTRA agent ─▶ piper (TTS) ─▶ speaker
              local model           your provider    local voice
```

Everything is local and optional:

* **Speech-to-text** — [whisper.cpp](https://github.com/ggerganov/whisper.cpp).
* **Text-to-speech** — [piper](https://github.com/rhasspy/piper) voices.
* **No new service** — the voice layer embeds the same core the terminal and web
  apps use; it talks to whatever provider/model you have configured.

If only *part* of the stack is installed, the wrapper degrades gracefully: with
whisper but no piper, you talk and read the replies; with neither, `--status`
tells you exactly what to install.

## Start

```bash
./voice/astra-voice --setup          # one-time: fetch models + build whisper.cpp
./voice/astra-voice                  # push-to-talk conversation
./voice/astra-voice --listen         # hands-free (needs the sounddevice extras)
./voice/astra-voice --file clip.wav  # process one audio file, then exit
./voice/astra-voice --text "hello"   # send text (no microphone)
./voice/astra-voice --say "hello"    # speak text only (no agent)
./voice/astra-voice --status         # show readiness / what is missing
```

The launcher reuses `core/.venv`, installing the core dependencies if missing and
the **optional** audio extras on a best-effort basis.

In the default **push-to-talk** mode you press Enter to start recording and Enter
again to stop. You can also type a message directly at the `voice>` prompt, and
`q` quits.

## Setup & prerequisites

### 1. whisper.cpp (speech-to-text)

`--setup` clones and builds whisper.cpp if `git` and `cmake` are available
(binary at `voice/models/whisper.cpp/build/bin/whisper-cli`). Otherwise build it
yourself:

```bash
git clone https://github.com/ggerganov/whisper.cpp voice/models/whisper.cpp
cmake -B voice/models/whisper.cpp/build -DCMAKE_BUILD_TYPE=Release
cmake --build voice/models/whisper.cpp/build --config Release -j
```

Then point the wrapper at the binary if it is somewhere unusual:

```bash
export ASTRA_VOICE_WHISPER_BIN=/path/to/whisper-cli
```

### 2. A whisper model

`--setup` downloads `ggml-base.en.bin` (about 140 MB) into `voice/models/`. A
larger model (`small`, `medium`) is more accurate but slower:

```bash
./voice/astra-voice --setup --stt-model small
```

### 3. piper (text-to-speech)

`--setup` downloads the piper release binary into `voice/models/piper/` and a
voice (`en_US-lessac-medium`) into `voice/models/`. If a prebuilt binary is not
available for your platform, [build piper](https://github.com/rhasspy/piper) and
set:

```bash
export ASTRA_VOICE_PIPER_BIN=/path/to/piper
export ASTRA_VOICE_TTS_MODEL=/path/to/en_US-lessac-medium.onnx
```

### 4. Audio I/O (optional but recommended)

The voice layer records and plays through either:

* **sounddevice + numpy** — `pip install -r voice/requirements.txt`. On Linux you
  also need PortAudio: `sudo apt-get install libportaudio2`. This is the cleanest
  backend and is **required for `--listen`** (hands-free).
* **command-line tools** — `arecord`/`aplay` (ALSA) or `ffmpeg`/`ffplay`. Nothing
  to install in Python. Push-to-talk and `--seconds` work with these.

`--status` reports which backend was selected.

## Configuration

Every location is environment-first, with a sensible default. All variables are
optional and prefixed `ASTRA_VOICE_`.

| Variable | Default | Purpose |
|----------|---------|---------|
| `ASTRA_VOICE_WHISPER_BIN` | autodetect | whisper.cpp CLI (`whisper-cli`/`main`) |
| `ASTRA_VOICE_STT_MODEL` | autodetect | `ggml-*.bin` speech model |
| `ASTRA_VOICE_PIPER_BIN` | autodetect | `piper` binary |
| `ASTRA_VOICE_TTS_MODEL` | autodetect | piper `.onnx` voice |
| `ASTRA_VOICE_MODELS_DIR` | `voice/models` | where models live |
| `ASTRA_VOICE_LANG` | `en` | whisper language code |
| `ASTRA_VOICE_THREADS` | whisper default | whisper thread count |
| `ASTRA_VOICE_INPUT_DEVICE` | system default | mic device (name or index) |
| `ASTRA_VOICE_OUTPUT_DEVICE` | system default | speaker device (name or index) |
| `ASTRA_VOICE_AUDIO_BACKEND` | `auto` | `auto`, `sounddevice` or `cli` |
| `ASTRA_VOICE_KEEP_AUDIO` | off | keep temporary WAVs for debugging |

Model/provider selection for the **agent** is shared with the terminal and web
apps (see [`web/README.md`](../web/README.md) and
[`documentation.md`](../documentation.md)), so a voice session uses the same
brain as everything else.

## Command-line reference

| Flag | Meaning |
|------|---------|
| `--status` | Print a readiness report and exit (code `0` if ready). |
| `--setup` | Build/download whisper.cpp + models and piper + voice. |
| `--stt-model NAME` | whisper model size to fetch during `--setup` (e.g. `tiny.en`, `base.en`, `small`). |
| `--tts-voice NAME` | piper voice to fetch during `--setup` (e.g. `en_US-lessac-medium`). |
| `--file PATH` | Transcribe and answer one WAV file, then exit. |
| `--text TEXT` | Send a text message to the agent (no mic), then exit. |
| `--say TEXT` | Speak `TEXT` with piper only, then exit. |
| `--seconds N` | Record a fixed `N` seconds instead of push-to-talk. |
| `--listen` | Hands-free continuous listening (needs sounddevice). |
| `--stt-only` | With `--file`/`--seconds`, transcribe without calling the agent. |
| `--no-tts` | Do not speak replies. |
| `--no-stream` | Print replies when complete instead of streaming. |
| `--model NAME` | Override the agent model for this session. |
| `--models-dir PATH` | Where speech models live (default `voice/models`). |

## Notes & limitations

* **One conversation.** The voice layer is another frontend embedding the core;
  if you also run the terminal or web app at the same time, they are separate
  processes with separate in-memory sessions (though they share the same SQLite
  history file). Run one frontend at a time for a single coherent session.
* **`--listen` needs sounddevice.** The command-line backend has no reliable
  silence detection, so hands-free mode requires the Python extras.
* **First whisper call is slowest.** The model is loaded per invocation; larger
  models add noticeable latency.
* **Piper is a subprocess.** Each reply is a fresh process; this keeps the code
  dependency-free and the models swappable.

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for the full design.
