"""
Provider command handler.

Implements the interactive ``/provider`` setup command for the terminal app:
choose between local Ollama and cloud providers (OpenAI, Anthropic, Gemini),
paste an API key, and run the ``local_setup`` flow that installs Ollama and
downloads a model. The same operations are exposed to the web UI through
``astra_service`` / the ``/api/providers`` endpoints.
"""
from __future__ import annotations

import getpass
from typing import List, Optional

from ai import local_setup
from ai import settings as settings_module
from ai.model import AgentModel
from utils.colors import (
    Colors, error, success, warning, info, title, dim, user_msg, important, secondary, bold
)


class ProviderController:
    def __init__(self, model: AgentModel):
        self.model = model
        self.settings = settings_module.get_settings()

    # ---- dispatch -----------------------------------------------------------
    def handle(self, user_input: str) -> bool:
        """Handle ``/provider`` / ``/model`` commands. Returns True if handled."""
        try:
            parts = user_input.strip().split()
            if not parts:
                return False
            cmd = parts[0].lower()

            if cmd in ("/model", "/models"):
                self._model_command(parts[1:])
                return True
            if cmd in ("/thinking", "/think"):
                self._thinking_command(parts[1:])
                return True
            if cmd not in ("/provider", "/providers"):
                return False

            args = parts[1:]
            if not args or args[0].lower() in ("menu", "setup"):
                self._menu()
                return True

            sub = args[0].lower()
            if sub in ("status", "show", "current"):
                self._show_status()
            elif sub in ("help", "?", "h"):
                self._print_help()
            elif sub in ("local_setup", "local-setup", "localsetup", "setup-local", "install"):
                self._local_setup()
            elif sub in ("local", "ollama"):
                self._configure_local()
            elif sub in ("openai", "gpt"):
                self._configure_cloud("openai", args[1:])
            elif sub in ("anthropic", "claude"):
                self._configure_cloud("anthropic", args[1:])
            elif sub in ("gemini", "google"):
                self._configure_cloud("gemini", args[1:])
            elif sub in settings_module.PROVIDERS:
                self._configure_cloud(sub, args[1:])
            elif sub == "set":
                # /provider set <name> [model]
                if len(args) < 2:
                    print(error("Usage: /provider set <provider> [model]"))
                else:
                    self._apply(args[1], model=args[2] if len(args) > 2 else None)
            else:
                print(error(f"Unknown provider option: {args[0]}"))
                self._print_help()
            return True
        except (EOFError, KeyboardInterrupt):
            print("\n" + error("Provider setup cancelled"))
            return True
        except Exception as e:
            print(error(f"Error configuring provider: {e}"))
            return True

    # ---- menu ---------------------------------------------------------------
    def _menu(self):
        while True:
            current = self.model.describe()
            print()
            print(title("Provider setup"))
            print(dim("─" * 62))
            print(f"  Current: {bold(current['provider_label'])} · {bold(current['model'])}")
            print(dim("─" * 62))
            print("  1) Local (Ollama)       pick a model already on this machine")
            print("  2) local_setup          install Ollama + download a model")
            print("  3) OpenAI               use an API key")
            print("  4) Anthropic (Claude)   use an API key")
            print("  5) Google (Gemini)      use an API key")
            print("  q) Cancel")
            print(dim("─" * 62))

            choice = self._read("Select [1-5]: ")
            if choice is None:
                return
            choice = choice.strip().lower()
            if choice in ("", "q", "quit", "cancel"):
                return
            if choice == "1":
                self._configure_local()
                return
            if choice == "2":
                self._local_setup()
                return
            if choice == "3":
                self._configure_cloud("openai")
                return
            if choice == "4":
                self._configure_cloud("anthropic")
                return
            if choice == "5":
                self._configure_cloud("gemini")
                return
            print(error("Please choose 1-5 or q."))

    # ---- cloud providers ----------------------------------------------------
    def _configure_cloud(self, provider: str, extra: Optional[List[str]] = None):
        provider = settings_module.normalize_provider(provider)
        extra = extra or []
        label = settings_module.PROVIDER_LABELS.get(provider, provider)
        existing = self.settings.api_key(provider)

        print()
        print(title(f"{label} setup"))
        if existing:
            src = self.settings.api_key_source(provider)
            note = f" (from {'environment' if src == 'env' else 'config file'})"
            print(dim(f"A key is already configured{note}: {self.settings._mask(existing)}"))

        if extra:
            api_key = extra[0].strip()
        else:
            prompt = "API key (leave blank to keep current): " if existing else "Paste your API key: "
            api_key = self._read_secret(prompt)
            if api_key is None:
                return
            api_key = api_key.strip()

        if not api_key:
            if not existing:
                print(warning("No API key provided — aborting."))
                return
            api_key = None  # keep existing

        default_model = self.settings.active_model(provider) or settings_module.default_model(provider)
        if len(extra) > 1:
            model = extra[1].strip()
        else:
            model = (self._read(f"Model [{default_model}]: ") or "").strip() or default_model

        if api_key:
            self.settings.set_api_key(provider, api_key)
        self._apply(provider, model=model)

    # ---- local / ollama -----------------------------------------------------
    def _configure_local(self):
        host = self.settings.base_url("ollama")
        if not local_setup.is_ollama_installed():
            print()
            print(warning("Ollama is not installed on this machine."))
            choice = self._read("Run local_setup to install it now? (Y/n): ")
            if choice is None:
                return
            if choice.strip().lower() in ("", "y", "yes"):
                self._local_setup()
            else:
                print(info("Install Ollama from https://ollama.com/download, then try again."))
            return

        if not local_setup.is_ollama_running(host):
            print(dim("Starting the Ollama server…"))
            if not local_setup.start_ollama_server(None, host):
                print(error("Could not start Ollama. Try running 'ollama serve' manually."))
                return

        models = local_setup.list_local_models(host)
        print()
        print(title("Local models"))
        if models:
            for i, m in enumerate(models, 1):
                marker = ""
                if m["name"] == self.model.model_name and self.model.provider_name == "ollama":
                    marker = bold(" (current)")
                print(f"  {i}) {m['name']:<28} {m['size_human']}{marker}")
        else:
            print(dim("  (no models downloaded yet)"))
        print("  d) Download a new model (local_setup)")
        print("  q) Cancel")

        choice = self._read("Select: ")
        if choice is None:
            return
        choice = choice.strip().lower()
        if choice in ("", "q", "cancel"):
            return
        if choice == "d":
            self._local_setup()
            return
        try:
            index = int(choice) - 1
            if 0 <= index < len(models):
                self._apply("ollama", model=models[index]["name"])
            else:
                print(error("Invalid selection."))
        except ValueError:
            # Allow typing a model tag directly.
            self._apply("ollama", model=choice)

    def _local_setup(self):
        print()
        print(title("Local setup — install Ollama & download a model"))
        if local_setup.is_ollama_installed():
            print(success("Ollama is already installed."))
        else:
            print(info("Ollama will be installed automatically."))

        print(dim("Recommended models:"))
        for i, m in enumerate(local_setup.RECOMMENDED_MODELS, 1):
            default = " (default)" if m["name"] == self.settings.active_model("ollama") else ""
            print(f"  {i}) {m['name']:<16} {m['size']:<9} {m['description']}{default}")
        print("  Or type any Ollama model tag (e.g. llama3.2:3b), or q to cancel.")

        choice = self._read("Select model: ")
        if choice is None:
            return
        choice = choice.strip()
        if choice.lower() in ("", "q", "quit", "cancel"):
            return
        if choice.isdigit():
            index = int(choice) - 1
            if 0 <= index < len(local_setup.RECOMMENDED_MODELS):
                model = local_setup.RECOMMENDED_MODELS[index]["name"]
            else:
                print(error("Invalid selection."))
                return
        else:
            model = choice

        progress = self._progress_printer()
        ok = local_setup.install_and_pull(model, progress, self.settings.base_url("ollama"))
        progress.finish()
        if not ok:
            print(error("Local setup did not complete. See the messages above."))
            return
        self._apply("ollama", model=model)

    # ---- model command ------------------------------------------------------
    def _model_command(self, args: List[str]):
        provider = self.model.provider_name
        if not args or args[0].lower() in ("status", "show"):
            print(info(f"Model: {bold(self.model.model_name)}  ({self.model.provider_name})"))
            if provider == "ollama":
                models = local_setup.list_local_models(self.settings.base_url("ollama"))
                if models:
                    print(dim("  Available locally: " + ", ".join(m["name"] for m in models)))
            return
        if args[0].lower() in ("list", "ls"):
            self._configure_local() if provider == "ollama" else None
            return
        self._apply(provider, model=args[0])

    # ---- thinking command ---------------------------------------------------
    def _thinking_command(self, args: List[str]):
        """Toggle or set whether the active model emits reasoning tokens."""
        if args and args[0].lower() in ("status", "show", "current"):
            self._print_thinking()
            return

        enabled: Optional[bool] = None
        if args:
            word = args[0].strip().lower()
            if word not in ("toggle", "switch"):
                enabled = settings_module._parse_bool(word)
                if enabled is None:
                    print(error("Usage: /thinking [on|off|toggle|status]"))
                    return

        if enabled is None:
            enabled = not self.model.thinking_enabled()

        self.model.set_thinking(enabled)
        effective = self.model.thinking_enabled()
        state = success("on") if effective else warning("off")
        print(info(
            f"Thinking is {state} for {bold(self.model.model_name)} "
            f"({self.model.provider_name})."
        ))
        if self.settings.thinking_source() == "env":
            print(warning("ASTRA_THINKING is set in the environment and overrides this toggle."))

    def _print_thinking(self):
        enabled = self.model.thinking_enabled()
        state = success("on") if enabled else warning("off")
        source = self.settings.thinking_source()
        print(info(
            f"Thinking is {state} for {bold(self.model.model_name)} "
            f"({self.model.provider_name})  [source: {source}]"
        ))

    # ---- apply --------------------------------------------------------------
    def _apply(self, provider: str, model: Optional[str] = None):
        provider = settings_module.normalize_provider(provider)
        if provider not in settings_module.PROVIDERS:
            print(error(f"Unknown provider: {provider}"))
            return

        # Persist the active choice.
        self.settings.set_active(provider, model)
        resolved = self.settings.active_model(provider)

        # Warn (but don't block) if a keyed provider has no key.
        if provider != "ollama" and not self.settings.api_key(provider):
            print(warning(
                f"Note: no API key stored for {provider}. "
                f"Run '/provider {provider}' to add one."
            ))

        info_snapshot = self.model.reconfigure(provider, resolved)
        print(success(
            f"Now using {info_snapshot['provider_label']} · {info_snapshot['model']}"
        ))

    # ---- helpers ------------------------------------------------------------
    def _show_status(self):
        snap = self.model.describe()
        print()
        print(title("Current model"))
        print(f"  Provider: {bold(snap['provider_label'])}  ({snap['provider']})")
        print(f"  Model:    {bold(snap['model'])}")
        if snap["provider"] == "ollama":
            host = self.settings.base_url("ollama")
            running = local_setup.is_ollama_running(host)
            state = success("running") if running else warning("not running")
            print(f"  Ollama:   {state}  ({host})")
        else:
            key = self.settings.api_key(snap["provider"])
            src = self.settings.api_key_source(snap["provider"])
            state = f"{self.settings._mask(key)} ({src})" if key else warning("not set")
            print(f"  API key:  {state}")

    def _read(self, prompt: str) -> Optional[str]:
        try:
            return input(prompt)
        except EOFError:
            return None
        except KeyboardInterrupt:
            print()
            return None

    def _read_secret(self, prompt: str) -> Optional[str]:
        try:
            return getpass.getpass(prompt)
        except (EOFError, KeyboardInterrupt):
            print()
            return None
        except Exception:
            return self._read(prompt)

    def _progress_printer(self):
        state = {"last": 0}

        def progress(text: str):
            line = str(text)
            if "%" in line and "(" in line:
                pad = max(0, state["last"] - len(line))
                print("\r  " + line + " " * pad, end="", flush=True)
                state["last"] = len(line)
            else:
                if state["last"]:
                    print("\r" + " " * (state["last"] + 2) + "\r", end="")
                    state["last"] = 0
                print(dim(f"  {line}"))

        def finish():
            if state["last"]:
                print()
                state["last"] = 0

        progress.finish = finish  # type: ignore[attr-defined]
        return progress

    def _print_help(self, parts=None):
        print(f"""
{title("Provider & model commands")}

  /provider                 Open the provider setup menu
  /provider status          Show the current provider and model
  /provider local           Pick an Ollama model already on this machine
  /provider local_setup     Install Ollama (if needed) and download a model
  /provider openai          Add an OpenAI API key (also: /provider gpt)
  /provider anthropic       Add an Anthropic (Claude) API key
  /provider gemini          Add a Google (Gemini) API key
  /provider set <p> [model] Set the active provider (and model) directly
  /model [name]             Show or switch the model for the current provider
  /thinking [on|off|toggle] Toggle thinking/reasoning for the active model
  /provider help            Show this help

Environment variables always win over saved settings:
  ASTRA_PROVIDER, ASTRA_MODEL, ASTRA_THINKING,
  ASTRA_OPENAI_API_KEY, ASTRA_ANTHROPIC_API_KEY, ASTRA_GEMINI_API_KEY
        """.strip())
