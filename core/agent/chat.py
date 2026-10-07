import sys
import time
import traceback
from ai.ollama import OllamaModel
from controller.session_controller import SessionController
from utils.colors import (
    Colors, error, success, warning, info, title, dim, user_msg, important, secondary, bold
)


class Chat:
    def __init__(self):
        try:
            self.model = OllamaModel("qwen3:14b")
            self.session_controller = SessionController(self.model)
        except Exception as e:
            print(error(f"Failed to initialize chat: {e}"))
            traceback.print_exc()
            sys.exit(1)

    def start(self):
        print(title("Welcome to ASTRA. Type 'exit' to quit."))
        print(dim("Session commands: /s new | /s list | /s <num> | /s resume | /s del <num> | /s clear"))
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

                # Handle session commands
                if user_input.startswith("/session") or user_input.startswith("/s "):
                    self.session_controller.handle(user_input)
                    continue

                # Generate response with error handling
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

                # Add response to history
                if content:
                    try:
                        self.model.add_response(content)
                    except Exception as e:
                        print(warning(f"Warning: Failed to save response to history: {e}"))

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