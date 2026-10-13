"""Best-effort setup for the voice layer's local models.

``./voice/astra-voice --setup`` walks through, in order:

1. Build **whisper.cpp** (git clone + cmake) if it is not already present.
2. Download a whisper ``ggml-*.bin`` speech-to-text model.
3. Download the **piper** binary for this platform (if not on ``PATH``).
4. Download a piper ``.onnx`` voice (+ its ``.json`` config).

Every step is idempotent and skippable: an existing file is left alone, and a
missing prerequisite (no git/cmake) prints manual instructions instead of
failing the whole run. Nothing here is imported by the runtime path.
"""
from __future__ import annotations

import platform
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Optional

WHISPER_MODEL_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-{name}.bin"
WHISPER_REPO_URL = "https://github.com/ggerganov/whisper.cpp.git"
PIPER_RELEASE_URL = "https://github.com/rhasspy/piper/releases/latest/download/{asset}"
PIPER_VOICE_URL = (
    "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
    "{lang}/{family}/{name}/{quality}/{voice}.onnx{ext}"
)

DEFAULT_STT_MODEL = "base.en"
DEFAULT_TTS_VOICE = "en_US-lessac-medium"


def _log(message: str) -> None:
    print(f"[astra-voice setup] {message}")


def _download(url: str, dest: Path, label: str) -> bool:
    """Stream ``url`` to ``dest`` with a simple progress line. Returns success."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310
            total = int(response.headers.get("Content-Length") or 0)
            seen = 0
            with open(tmp, "wb") as handle:
                while True:
                    chunk = response.read(1024 * 256)
                    if not chunk:
                        break
                    handle.write(chunk)
                    seen += len(chunk)
                    if total:
                        pct = seen * 100 // total
                        print(f"\r  {label}: {pct:3d}% ({seen // 1048576} MiB)", end="", flush=True)
        if total:
            print()
        tmp.replace(dest)
        _log(f"downloaded {label} → {dest}")
        return True
    except Exception as exc:  # noqa: BLE001
        print()
        _log(f"could not download {label}: {exc}")
        tmp.unlink(missing_ok=True)
        return False


def _whisper_model_path(models_dir: Path, name: str) -> Path:
    return models_dir / f"ggml-{name}.bin"


def ensure_whisper_model(models_dir: Path, name: str = DEFAULT_STT_MODEL) -> Optional[Path]:
    dest = _whisper_model_path(models_dir, name)
    if dest.exists():
        _log(f"whisper model already present: {dest}")
        return dest
    url = WHISPER_MODEL_URL.format(name=name)
    if _download(url, dest, f"whisper model ggml-{name}.bin"):
        return dest
    return None


def build_whisper_cpp(models_dir: Path) -> Optional[Path]:
    """Clone and build whisper.cpp. Returns the CLI path if it exists."""
    target = models_dir / "whisper.cpp"
    for candidate in ("build/bin/whisper-cli", "build/bin/main", "whisper-cli"):
        existing = target / candidate
        if existing.exists():
            _log(f"whisper.cpp already built: {existing}")
            return existing

    missing = [tool for tool in ("git", "cmake") if shutil.which(tool) is None]
    if missing:
        _log("whisper.cpp is not built and these tools are missing: " + ", ".join(missing))
        _manual_whisper_instructions(target)
        return None

    try:
        if not target.exists():
            _log("cloning whisper.cpp…")
            subprocess.run(["git", "clone", "--depth", "1", WHISPER_REPO_URL, str(target)],
                           check=True)
        _log("building whisper.cpp (this can take a minute)…")
        subprocess.run(["cmake", "-B", "build", "-DCMAKE_BUILD_TYPE=Release"],
                       cwd=target, check=True)
        subprocess.run(["cmake", "--build", "build", "--config", "Release", "-j"],
                       cwd=target, check=True)
    except subprocess.CalledProcessError as exc:
        _log(f"whisper.cpp build failed ({exc}).")
        _manual_whisper_instructions(target)
        return None

    for candidate in ("build/bin/whisper-cli", "build/bin/main"):
        built = target / candidate
        if built.exists():
            _log(f"built whisper.cpp: {built}")
            return built
    _manual_whisper_instructions(target)
    return None


def _manual_whisper_instructions(target: Path) -> None:
    _log("build it manually, then re-run --setup or set ASTRA_VOICE_WHISPER_BIN:")
    print(f"    git clone {WHISPER_REPO_URL} {target}")
    print(f"    cmake -B {target}/build -DCMAKE_BUILD_TYPE=Release")
    print(f"    cmake --build {target}/build --config Release -j")


def _piper_asset() -> Optional[str]:
    system = platform.system().lower()
    machine = platform.machine().lower()
    arm = machine in ("aarch64", "arm64")
    if system == "linux":
        return "piper_linux_aarch64.tar.gz" if arm else "piper_linux_x86_64.tar.gz"
    if system == "darwin":
        return "piper_macos_aarch64.tar.gz" if arm else "piper_macos_x64.tar.gz"
    if system == "windows":
        return "piper_windows_amd64.zip"
    return None


def install_piper(models_dir: Path) -> Optional[Path]:
    """Download the piper release binary into ``models_dir/piper`` if needed."""
    binary = models_dir / "piper" / ("piper.exe" if platform.system().lower() == "windows" else "piper")
    if binary.exists():
        _log(f"piper already present: {binary}")
        return binary

    found = shutil.which("piper")
    if found:
        _log(f"piper found on PATH: {found}")
        return Path(found)

    asset = _piper_asset()
    if asset is None:
        _log("no prebuilt piper binary for this platform — install piper manually.")
        return None

    with tempfile.TemporaryDirectory(prefix="astra-piper-") as tmp:
        archive = Path(tmp) / asset
        if not _download(PIPER_RELEASE_URL.format(asset=asset), archive, asset):
            return None
        _log("extracting piper…")
        models_dir.mkdir(parents=True, exist_ok=True)
        if asset.endswith(".zip"):
            with zipfile.ZipFile(archive) as zf:
                zf.extractall(models_dir)
        else:
            with tarfile.open(archive) as tf:
                tf.extractall(models_dir)
        if binary.exists():
            binary.chmod(0o755)
            _log(f"installed piper: {binary}")
            return binary

    _log("piper archive did not contain the expected binary.")
    return None


def _voice_urls(voice: str):
    """Map ``en_US-lessac-medium`` to its HF onnx + json URLs."""
    parts = voice.split("-")
    if len(parts) != 3:
        return None
    lang_family, name, quality = parts
    lang = lang_family.split("_")[0]
    base = PIPER_VOICE_URL.format(lang=lang, family=lang_family, name=name,
                                  quality=quality, voice=voice, ext="")
    return base, base + ".json"


def ensure_piper_voice(models_dir: Path, voice: str = DEFAULT_TTS_VOICE) -> Optional[Path]:
    dest = models_dir / f"{voice}.onnx"
    config = models_dir / f"{voice}.onnx.json"
    if dest.exists() and config.exists():
        _log(f"piper voice already present: {dest}")
        return dest

    urls = _voice_urls(voice)
    if urls is None:
        _log(f"unrecognised voice name '{voice}' (expected e.g. en_US-lessac-medium).")
        return None

    onnx_url, json_url = urls
    ok_onnx = dest.exists() or _download(onnx_url, dest, f"{voice}.onnx")
    ok_json = config.exists() or _download(json_url, config, f"{voice}.onnx.json")
    return dest if (ok_onnx and ok_json) else None


def main(stt_model: Optional[str] = None, tts_voice: Optional[str] = None,
         models_dir: Optional[Path] = None) -> int:
    models_dir = Path(models_dir) if models_dir else Path(__file__).resolve().parents[1] / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    _log(f"models directory: {models_dir}")

    build_whisper_cpp(models_dir)
    ensure_whisper_model(models_dir, stt_model or DEFAULT_STT_MODEL)
    install_piper(models_dir)
    ensure_piper_voice(models_dir, tts_voice or DEFAULT_TTS_VOICE)

    print()
    _log("done. Check readiness with './voice/astra-voice --status'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
