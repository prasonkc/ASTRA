import sys
import time
from ai.ollama import OllamaModel


class Chat:
    def __init__(self):
        self.model = OllamaModel("qwen3:8b")

    def start(self):
        print("Welcome to ASTRA. Type 'exit' to quit.")

        while True:
            content = ""
            thoughts = ""
            thinking = True

            user_input = input("You: ")

            if user_input.lower() == "exit":
                break
            
            if user_input.strip() == "":
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
            self.model.add_response(content)