import ollama

class OllamaModel:
    def __init__(self, model_name):
        self.model_name = model_name

    def generate(self, prompt):
        response = ollama.generate(self.model_name, prompt)
        return response