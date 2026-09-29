import ollama

class OllamaModel:
    def __init__(self, model_name):
        self.model_name = model_name
        # Temporary cached chat history 
        with open("./config/identity.txt") as f:
            system_prompt = f.read().strip()
        
        self.history = [{"role": "system", "content": system_prompt}]
            
    def generate(self, prompt):
        self.history.append({
            "role": "user",
            "content": prompt
        })

        return ollama.chat(
            model=self.model_name,
            messages=self.history,
            think=True,
            stream=True
        )
        
    def add_response(self, content):
        self.history.append({
            "role": "assistant",
            "content": content
        })
