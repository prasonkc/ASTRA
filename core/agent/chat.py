import sys
from ai.ollama import OllamaModel

class Chat:
    def __init__(self):
        # Replace with your model name
        self.model = OllamaModel("qwen3:8b")

    def start(self):
        print("Welcome to the chat agent. Type 'exit' to quit.")
        while True:
            user_input = input("You: ")
            if user_input.lower() == 'exit':
                break
            response = self.model.generate(user_input)
            print("ASTRA:", response.response)