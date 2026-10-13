# astra-voice

A local speech wrapper for **ASTRA** — talk to your agent and hear it answer,
entirely on your machine. It works two ways: as a standalone process
(`./voice/astra-voice`, described here) and as the terminal's built-in
**`/voice`** command, which runs the same speech layer inside the terminal app.
ASTRA core stays a fully standalone app (`core/`); `voice/` only adds ears and a
mouth.

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

## Ways to use it

There are three hosts for the same speech layer:

* **Standalone** — `./voice/astra-voice` runs its own process and its own
  conversation (below).
* **Inside the terminal** — type **`/voice`** at the ASTRA prompt to start
  continuous listening *in the same session you already have open* (see
  [Using voice from the terminal](#using-voice-from-the-terminal)).
* **In the web app** — the composer's **🎙 mic button** enters hands-free voice
  mode. The *browser* owns the microphone and speaker; the server reuses this
  speech layer for speech-to-text (whisper.cpp) and text-to-speech (piper) via
  `web/backend/voice_api.py`. The Firefox extension popup's **Voice mode**
  button opens that page. No audio device or extra Python packages are needed on
  the server — just the same models `--setup` installs.

All three use the same local models and configuration; pick whichever fits how
you are working.

## Start

```bash
./voice/astra-voice --setup          # one-time: fetch models + build whisper.cpp
./voice/astra-voice                  # continuous listening (default)
./voice/astra-voice --push-to-talk   # press Enter to talk, Enter again to send
./voice/astra-voice --file clip.wav  # process one audio file, then exit
./voice/astra-voice --text "hello"   # send text (no microphone)
./voice/astra-voice --say "hello"    # speak text only (no agent)
./voice/astra-voice --status         # show readiness / what is missing
```

The launcher reuses `core/.venv`, installing the core dependencies if missing and
the **optional** audio extras on a best-effort basis.

The default mode **listens continuously**: the microphone stays open and the
moment you stop talking the utterance is transcribed, answered and spoken. Just
start talking — there is nothing to press. You can also press **Enter** to send
what you have said so far without waiting for the pause (turn this off with
`--no-enter` or `ASTRA_VOICE_ENTER_SEND=0`). `--push-to-talk` switches back to
press-Enter-to-talk, which is useful in noisy rooms or when you also want to type
at the `voice>` prompt (`q` quits).

## Using voice from the terminal

You do not need the standalone launcher to talk to ASTRA. The terminal app has a
built-in **`/voice`** command that runs the same speech layer *in-process* and
drives the terminal's own agent, so a spoken turn continues the same session and
history already open at the prompt:

```
You: /voice
ASTRA voice  ·  local_setup/llama3
Listening continuously — just speak, then pause — or press Enter to send.
🎤 listening…
You: what's on my calendar?
ASTRA: …
```

| Command | Effect |
|---------|--------|
| `/voice` | Continuous listening (default). Speak, then pause; **Ctrl-C** returns to the prompt. |
| `/voice once` | Record a single utterance, answer, then return to the prompt. |
| `/voice push` | A push-to-talk sub-REPL: Enter records, typing sends text, `q` quits back to the terminal. |
| `/voice status` | Show which speech components are installed (same report as `--status`). |
| `/voice help` | List these options. |

`/voice` is optional and degrades gracefully: if the speech layer is not
installed, it prints exactly what is missing and points at
`./voice/astra-voice --setup`. Nothing about the normal text terminal changes
when you never use it.

Because the terminal, `/voice` and the standalone wrapper all share one SQLite
history file (`core/memory/chat_history.db`), prefer **one** live frontend at a
time for a single coherent session (see the note under
[Notes & limitations](#notes--limitations)).

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
  backend and is used automatically when present.
* **command-line tools** — `arecord`/`aplay` (ALSA) or `ffmpeg`/`ffplay`. Nothing
  to install in Python. Continuous listening works here too: raw PCM is streamed
  from the recorder and gated in pure Python (no numpy needed).

Either backend supports continuous listening; `--status` reports which one was
selected.

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
| `ASTRA_VOICE_VAD_THRESHOLD` | `0` (auto) | energy gate for endpoint detection |
| `ASTRA_VOICE_SILENCE` | `0.8` | seconds of silence that ends an utterance |
| `ASTRA_VOICE_MAX_UTTERANCE` | `15` | max seconds captured for one utterance |
| `ASTRA_VOICE_ENTER_SEND` | on | press Enter to send instead of waiting for a pause |
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
| `--seconds N` | With `--push-to-talk`, record a fixed `N` seconds per turn. |
| `--listen` | Continuous listening (the default; kept for compatibility). |
| `--push-to-talk` | Press Enter to record and Enter again to send. |
| `--no-enter` | In continuous mode, ignore Enter and only send on a pause. |
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
* **Continuous listening is endpoint-gated.** The mic opens per utterance, so
  nothing is captured while a reply is generated or spoken. It detects the *pause*
  after speech, not who is speaking: press **Enter** to send early, use
  `--push-to-talk`, or tune `ASTRA_VOICE_VAD_THRESHOLD` in a noisy room.
* **First whisper call is slowest.** The model is loaded per invocation; larger
  models add noticeable latency.
* **Piper is a subprocess.** Each reply is a fresh process; this keeps the code
  dependency-free and the models swappable.

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for the full design.
