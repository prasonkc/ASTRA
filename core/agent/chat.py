import sys
import threading
import time
import traceback
import browser_bridge
from ai.model import AgentModel
from browser_server import browser_bridge_endpoint, start_browser_context_server
from controller.provider_controller import ProviderController
from controller.session_controller import SessionController
from utils.colors import (
    Colors, error, success, warning, info, title, dim, user_msg, important, secondary, bold
)


class Chat:
    def __init__(self):
        try:
            # Provider and model are resolved from settings/environment, so
            # nothing about the model is hard-coded here.
            self.model = AgentModel()
            self.session_controller = SessionController(self.model)
            self.provider_controller = ProviderController(self.model)
        except Exception as e:
            print(error(f"Failed to initialize chat: {e}"))
            traceback.print_exc()
            sys.exit(1)

        # Serializes turns between the terminal REPL and the browser bridge, which
        # share the same model/history but run on different threads.
        self._turn_lock = threading.Lock()

    def start(self):
        print(title("Welcome to ASTRA. Type 'exit' to quit."))
        try:
            snap = self.model.describe()
            print(info(f"Model: {snap['provider_label']} · {snap['model']}"))
        except Exception:
            pass
        print(dim("Session commands: /s new | /s list | /s <num> | /s resume | /s del <num> | /s clear"))
        print(dim("Provider: /provider (local_setup · openai · anthropic · gemini) | /model <name> | /thinking on|off"))
        self._register_browser_message_handler()
        self._start_browser_bridge()
        self._safe_show_current_session()

        while True:
            try:
                content = ""
                thoughts = ""
                thinking = True

                user_input = self._safe_input("You: ")

                if user_input is None:  # EOF or interrupt
                    print("\nGoodbye!")
                    break

                if user_input.lower().strip() == "exit":
                    print("Goodbye!")
                    break

                if user_input.strip() == "":
                    continue

                # Handle provider/model/thinking setup commands
                if user_input.startswith("/provider") or user_input.startswith("/model") or user_input.startswith("/thinking"):
                    self.provider_controller.handle(user_input)
                    continue

                # Handle session commands
                if user_input.startswith("/session") or user_input.startswith("/s "):
                    self.session_controller.handle(user_input)
                    continue

                # Generate response with error handling. The model is shared
                # with the browser bridge, so hold the turn lock for the whole
                # turn to keep the two paths from interleaving (the browser
                # popup blocks on the same lock when it sends a message).
                with self._turn_lock:
                    try:
                        response_stream = self.model.generate(user_input)
                    except Exception as e:
                        print(error(f"Error generating response: {e}"))
                        continue

                    print("ASTRA: ", end="", flush=True)

                    # Thinking indicator
                    dots = 0
                    for chunk in response_stream:
                        try:
                            if chunk.message.thinking:
                                if not thinking:
                                    thinking = True
                                thoughts += chunk.message.thinking
                                dots = (dots + 1) % 4
                                print("\rASTRA: " + "." * (dots) + " ", end="", flush=True)
                                time.sleep(0.2)

                            if chunk.message.content:
                                if thinking:
                                    thinking = False
                                    print("\rASTRA: " + " " * 10 + "\r", end="", flush=True)
                                    print("ASTRA: ", end="", flush=True)

                                content += chunk.message.content
                                print(chunk.message.content, end="", flush=True)
                        except Exception as e:
                            print(f"\n" + error(f"Error processing response chunk: {e}"))
                            break

                print()  # New line after response

                if thoughts:
                    print(dim(thoughts))

                # Assistant responses are persisted by the core (OllamaModel.generate)
                # so the terminal and web wrapper share a single source of truth.

            except EOFError:
                print("\nGoodbye!")
                break
            except KeyboardInterrupt:
                print("\nInterrupted. Type 'exit' to quit.")
                continue
            except Exception as e:
                print(error(f"Unexpected error: {e}"))
                traceback.print_exc()
                continue

        # Cleanup
        self._cleanup()

    def _start_browser_bridge(self):
        """Start the localhost listener for the ASTRA browser extension.

        Idempotent; silently stays off when disabled via ASTRA_BROWSER_BRIDGE=0
        or when the port is already taken (astra-web is running instead).
        """
        try:
            server = start_browser_context_server()
            if server is not None:
                print(info(f"Browser integration: {browser_bridge_endpoint()}"))
            else:
                print(dim("Browser integration: off (disabled or port in use)"))
        except Exception as e:
            print(dim(f"Browser integration: not started ({e})"))

    def _register_browser_message_handler(self):
        """Let the extension popup send chat messages to this agent.

        The handler runs on the bridge's HTTP thread, so it serializes with the
        REPL via ``_turn_lock`` and reuses the same model, session and history —
        a message sent from the browser continues the conversation the user
        already has open in the terminal.
        """
        try:
            browser_bridge.set_message_handler(self._handle_browser_message)
        except Exception:
            pass

    def _handle_browser_message(self, message: str) -> dict:
        """Run one chat turn for the browser extension popup.

        Returns ``{"reply", "session_id", "error"}``; ``reply`` is the assistant's
        final text (tool calls are executed as usual by the agent loop but not
        surfaced here).
        """
        text = (message or "").strip()
        if not text:
            return {"reply": "", "session_id": getattr(self.model, "session_id", None), "error": "Message cannot be empty"}

        parts = []
        error_text = None
        with self._turn_lock:
            try:
                for chunk in self.model.generate(text):
                    try:
                        piece = chunk.message.content
                    except AttributeError:
                        piece = None
                    if piece:
                        parts.append(piece)
            except Exception as e:
                error_text = str(e)

        return {
            "reply": "".join(parts).strip(),
            "session_id": getattr(self.model, "session_id", None),
            "error": error_text,
        }

    def _safe_input(self, prompt: str) -> str | None:
        """Safely get user input, handling EOF and KeyboardInterrupt."""
        try:
            return input(prompt)
        except EOFError:
            return None
        except KeyboardInterrupt:
            raise

    def _safe_show_current_session(self):
        """Safely show current session, never crashes."""
        try:
            self.session_controller._show_current_session()
        except Exception:
            pass

    def _cleanup(self):
        """Clean up resources on exit."""
        try:
            if hasattr(self, 'model') and self.model:
                self.model.close()
        except Exception:
            pass


if __name__ == "__main__":
    chat = Chat()
    chat.start()