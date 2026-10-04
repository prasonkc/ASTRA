import sys
import time
from ai.ollama import OllamaModel
from agent.session_controller import SessionController


class Chat:
    def __init__(self):
        self.model = OllamaModel("qwen3:8b")
        self.session_controller = SessionController(self.model)

    def start(self):
        print("Welcome to ASTRA. Type 'exit' to quit.")
        print("Session commands: /s new | /s list | /s <num> | /s resume | /s del <num> | /s clear")
        self.session_controller._show_current_session()

        while True:
            content = ""
            thoughts = ""
            thinking = True

            user_input = input("You: ")

            if user_input.lower() == "exit":
                break

            if user_input.strip() == "":
                continue

            # Handle session commands
            if user_input.startswith("/session") or user_input.startswith("/s "):
                self.session_controller.handle(user_input)
                continue

            response_stream = self.model.generate(user_input)
            print("ASTRA: ", end="", flush=True)

            # Thinking indicator
            dots = 0
            for chunk in response_stream:
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
            print()
            print(thoughts)

            self.model.add_response(content)


if __name__ == "__main__":
    chat = Chat()
    chat.start()