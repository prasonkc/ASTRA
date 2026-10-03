import ollama

from tools.memory_tool import MemoryTool


class OllamaModel:
    def __init__(self, model_name):
        self.model_name = model_name
        self.memory_tool = MemoryTool()

        with open("./config/identity.txt") as f:
            system_prompt = f.read().strip()

        self.history = [
            {
                "role": "system",
                "content": system_prompt
            }
        ]

    def generate(self, prompt):
        self.history.append({
            "role": "user",
            "content": prompt
        })

        while True:
            response = ollama.chat(
                model=self.model_name,
                messages=self.history,
                tools=self.memory_tool.get_tools(),
                think=True,
                stream=True
            )

            chunks = []
            tool_calls = []
            content = ""

            for chunk in response:
                chunks.append(chunk)

                if chunk.message.content:
                    content += chunk.message.content

                if chunk.message.tool_calls:
                    tool_calls.extend(chunk.message.tool_calls)

            if not tool_calls:
                return iter(chunks)

            # Store the assistant's tool call in conversation history
            self.history.append({
                "role": "assistant",
                "content": content,
                "tool_calls": tool_calls
            })

            # Execute requested tools
            for tool_call in tool_calls:
                tool_name = tool_call.function.name
                arguments = tool_call.function.arguments

                function = self.memory_tool.functions.get(tool_name)

                if function is None:
                    result = f"Unknown tool: {tool_name}"
                else:
                    result = function(**arguments)

                self.history.append({
                    "role": "tool",
                    "content": str(result)
                })

    def add_response(self, content):
        self.history.append({
            "role": "assistant",
            "content": content
        })