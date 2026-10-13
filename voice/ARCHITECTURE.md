# astra-voice — architecture

> A local, optional speech frontend for the standalone ASTRA core. This document
> explains how the pieces fit together, how audio flows, how the layer degrades
> when parts are missing, and where to extend it.

---

## 1. Purpose & scope

`voice/` gives ASTRA three new senses without touching the core:

1. **Hearing** — microphone audio → text, via **whisper.cpp** (local).
2. **Speaking** — reply text → audio, via **piper** (local).
3. **A conversation loop** — record → transcribe → ask the agent → speak.

**In scope:** a runnable voice frontend, the speech layer as reusable modules,
and best-effort local model setup.

**Out of scope (by design):** modifying the core, adding a resident server,
streaming STT, speaker diarisation, wake words. The wrapper is a *client* of the
same core the terminal and web apps embed.

### Design goals

| Goal | How it is met |
|------|---------------|
| **Optional** | No dependency is mandatory; missing tools are reported, never fatal. |
| **Local** | whisper.cpp + piper run offline; nothing leaves the machine. |
| **No duplication** | Reuses `web.backend.astra_service.AstraService` for the agent. |
| **Swappable parts** | STT/TTS/audio are separate modules behind tiny interfaces. |
| **Predictable config** | Environment-first resolution with sensible defaults. |

---

## 2. Component map

```
                      ┌──────────────────────────────────────────┐
                      │                 run.py                    │
                      │  arg parsing · mode dispatch · lifecycle  │
                      └───────────────┬──────────────────────────┘
                                      │ builds
        ┌───────────────┬─────────────┼───────────────┬────────────────┐
        ▼               ▼             ▼               ▼                ▼
   ┌─────────┐    ┌──────────┐   ┌─────────┐    ┌──────────┐    ┌───────────┐
   │ audio.py│    │  stt.py  │   │ tts.py  │    │ agent.py │    │  deps.py  │
   │ record  │    │ whisper  │   │ piper   │    │ AstraSvc │    │ readiness │
   │ VAD     │    │ cpp      │   │         │    │ bridge   │    │ report    │
   │ play    │    └──────────┘   └─────────┘    └──────────┘    └───────────┘
   └────┬────┘         ▲             ▲               ▲                ▲
        │              │             │               │                │
        └──────────────┴─────────────┴───────────────┴────────────────┘
                                      │
                          ┌───────────┴───────────┐
                          │     voice_loop.py      │
                          │  record→STT→ask→TTS    │
                          └───────────────────────┘
                                      ▲
                                      │ resolved by
                              ┌───────┴────────┐
                              │   config.py    │  env-first paths/devices
                              └────────────────┘
                                      ▲
                              ┌───────┴────────┐
                              │   install.py   │  --setup downloads/builds
                              └────────────────┘
```

### File reference

| File | Responsibility |
|------|----------------|
| `backend/run.py` | CLI entrypoint: parse args, pick a mode, build components, own the lifecycle (close agent, clean temp audio). |
| `backend/config.py` | `VoiceConfig` — resolve binaries, models, language, devices and backend from env + defaults. |
| `backend/deps.py` | `build_status()` / `format_status()` — is the layer ready, and what is missing. |
| `backend/audio.py` | `AudioIO` — record (fixed / push-to-talk / VAD), play, and `ensure_wav16k` conversion. |
| `backend/stt.py` | `WhisperCppSTT` — invoke whisper.cpp, parse and clean the transcript. |
| `backend/tts.py` | `PiperTTS` — feed text to piper, return a WAV path. |
| `backend/agent.py` | `VoiceAgent` — facade over `AstraService`; streams a turn, collects the reply. |
| `backend/voice_loop.py` | `VoiceLoop` — the conversation orchestration and its interaction modes. |
| `backend/install.py` | `--setup`: build whisper.cpp, download models, fetch piper. |
| `astra-voice` | Shell launcher: venv, dependency install, exec `run.py`. |

---

## 3. The speech pipeline

A single turn flows through five stages. Every stage is independently optional.

```
  [mic]         [audio.py]        [stt.py]           [agent.py]         [tts.py]        [speaker]
 capture  ───▶  16 kHz mono  ───▶ whisper.cpp  ───▶  ASTRA turn  ───▶  piper  ───▶  playback
 (VAD/PTT)      WAV               transcript         (streamed)         WAV
```

1. **Capture** — `AudioIO.record()` produces a WAV. It is converted to 16 kHz
   mono 16-bit PCM (`ensure_wav16k`) because that is the only format whisper.cpp
   accepts. Conversion is a no-op when the recording already matches.
2. **Transcribe** — `WhisperCppSTT` runs `whisper-cli -m MODEL -f WAV -otxt -of B
   -nt -l LANG`. It prefers the `.txt` sidecar and falls back to stdout, then
   strips timestamps and non-speech markers (`[BLANK_AUDIO]`, `[Music]`, …).
3. **Ask** — `VoiceAgent.ask()` drives `AstraService.stream_chat()`; `content`
   deltas are printed live, tool calls are noted, and the concatenated text is
   the reply.
4. **Speak** — `PiperTTS.synthesize()` pipes the reply to `piper -m VOICE -f OUT`.
5. **Play** — `AudioIO.play()` renders the WAV through the active audio backend.

---

## 4. Data flows

### 4a. Push-to-talk (default)

```
voice> ⏎                     ┌───────────────┐
  │                          │ record thread │  AudioIO.record(stop_event)
  ▼                          └───────┬───────┘
"recording… press Enter" ────────────┘
  │ ⏎ (stop_event.set())
  ▼
STT → agent (streamed) → TTS → play
  │
  └─▶ back to the prompt
```

Recording runs on a **daemon thread** that blocks on `stop_event`; the main
thread waits for the user's Enter and then sets it. This works for both audio
backends (the sounddevice stream stops cleanly; a spawned `arecord`/`ffmpeg`
receives `SIGINT` to finalise its file).

### 4b. Hands-free listening (`--listen`)

`AudioIO.record_utterance()` calibrates ambient noise, then energy-gates: it
waits for an above-noise burst, records until a short silence, and returns one
WAV per utterance. The loop calls it repeatedly until Ctrl-C.

```
calibrate noise ─▶ wait for speech ─▶ record until silence ─▶ WAV ─▶ turn ─▶ repeat
```

This mode requires the **sounddevice** backend; the command-line backend has no
reliable silence detection, and `--listen` fails fast with a clear message.

### 4c. File / text modes

`--file`, `--text`, `--say` and `--stt-only` run one action and exit. They are
the scriptable surface and the easiest way to test a single stage in isolation.

---

## 5. Agent integration

The voice layer is a **frontend**, like `web/`. It embeds the core rather than
spawning the terminal, and it does **not** reimplement any agent logic:

```python
from web.backend.astra_service import AstraService   # thread-affine core handling
service = AstraService()                              # one worker thread, one model
for event in service.stream_chat(prompt): ...         # session/content/tool/error
```

Why reuse `AstraService`:

* The core is single-threaded and several components are **thread-affine**
  (SQLite connections, the Playwright event loop). `AstraService` already
  serialises every operation onto one persistent worker thread — exactly what
  the terminal does.
* Provider/model selection is therefore **shared** with the terminal and web
  apps through `ai.settings`; a voice session uses the same brain.

Importing `astra_service` makes the core directory the process working directory
and puts it on `sys.path` (a documented side effect of that module). The voice
layer is unaffected because it uses absolute paths for all of its own files.

### Session behaviour

`AstraService` is a singleton in the web app; here we construct our own instance
per voice session. If the terminal or web app is running **at the same time**,
the processes hold separate in-memory sessions but share the SQLite history file
(`core/memory/chat_history.db`). This mirrors the existing terminal-vs-web
caveat; run one frontend at a time for one coherent live session.

---

## 6. Configuration resolution

`VoiceConfig.from_env()` resolves each value in this order:

```
explicit env var  →  project-local default (under voice/models)  →  PATH  →  auto-discovery
```

* **Binaries** — `ASTRA_VOICE_WHISPER_BIN`, then `voice/models/whisper.cpp/build/bin/whisper-cli`
  (or `main`), then `whisper-cli` on `PATH`.
* **Models** — explicit env, else `rglob("ggml-*.bin")` (preferring `.en`) and
  `rglob("*.onnx")` under the models directory.
* **Audio backend** — `auto` prefers sounddevice, then CLI tools.

`run.py --models-dir` sets `ASTRA_VOICE_MODELS_DIR` before resolution, so the
whole config is recomputed consistently.

---

## 7. Graceful degradation

| Installed | Behaviour |
|-----------|-----------|
| whisper + piper + audio | Full spoken conversation. |
| whisper + audio, **no piper** | Talk and read replies (printed); TTS is skipped with a note. |
| **no whisper** | Conversation unavailable; `--status` explains what to install. |
| **no audio backend** | Only `--text` works; `--status` suggests extras or CLI tools. |
| `--text` / `--say` | Work without a microphone. |

`deps.build_status()` is the single source of truth for this; `--status` prints
it and exits non-zero when the conversation is not ready, so scripts can gate on
it.

---

## 8. Security & privacy

* **Fully local** — whisper.cpp and piper run on-device; audio and transcripts
  are never sent anywhere. The only network traffic is the same model-provider
  traffic the terminal app already makes (or none, for local Ollama).
* **Temp files** — recordings and synthesised audio live in a per-run
  `mkdtemp()` directory, removed on exit. `ASTRA_VOICE_KEEP_AUDIO=1` retains them
  for debugging.
* **No new listeners** — the voice layer opens no sockets and starts no server.
* **Secrets** — untouched; provider keys remain in `core/config/settings.json`
  managed by the core, never read by this layer.

---

## 9. Limitations

* One turn at a time; no barge-in while the agent or piper is speaking.
* whisper.cpp is invoked per utterance, so there is model-load latency each turn.
* `--listen` is limited to the sounddevice backend.
* Energy-gate VAD is simple: noisy environments or quiet speakers may need
  `ASTRA_VOICE_INPUT_DEVICE` tuning.
* Piper voices are discovered by filename; multiple voices require
  `ASTRA_VOICE_TTS_MODEL` to disambiguate.

---

## 10. Extension points / roadmap

* **Streaming STT** — whisper.cpp server mode to avoid per-utterance model loads.
* **HTTP surface** — expose `stt.py`/`tts.py` behind small endpoints so the web
  UI and the Firefox extension can add a mic button.
* **Wake word** — a lightweight keyword spotter in front of `--listen`.
* **Voice selection** — a `--voice` flag mapping friendly names to pyproject
  `speaker` ids for multi-speaker piper models.
* **Interrupt** — allow the user to start speaking while a reply plays.
