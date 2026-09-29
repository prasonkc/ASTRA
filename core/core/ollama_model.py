import os

class OllamaModel:
    def __init__(self):
        # Read system prompt from config file
        with open("config/identity.txt", "r") as f:
            system_prompt = f.read().strip()
        
        self.history = [{"role": "system", "content": system_prompt}]
        
    def add_user_message(self, prompt):
        self.history.append({"role": "user", "content": prompt})

    def add_assistant_response(self, response):
        self.history.append({"role": "assistant", "content": response})

    def generate_response(self):
        # Simulated response for demonstration
        return "Hello! I am ASTRA, your local AI assistant. How can I help you today?"

    def chat(self):
        while True:
            user_input = input("You: ")
            if user_input.lower() in ["exit", "quit"]:
                break
            
            self.add_user_message(user_input)
            response = self.generate_response()
            self.add_assistant_response(response)
            print(f"ASTRA: {response}")

if __name__ == "__main__":
    model = OllamaModel()
    model.chat()