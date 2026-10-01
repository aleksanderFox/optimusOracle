import ollama
from llm_providers import (BaseLLM, temperature)

class OllamaLLM(BaseLLM):
    def __init__(self, model_info: dict, sql_info: dict):
        super().__init__(model_info, sql_info)
        if (model_info['server_name']):
            self.client = ollama.Client(host = model_info['server_name'])
        else:
            self.client = ollama.Client()

    def _ask_llm(self, message: list, sql_id: str, thread) -> str:
        options = {'temperature': temperature} if temperature else {}
        response = self.client.chat(
            model = self.model_info['model_name'],
            messages = message,
            stream = True,
            options = options
        )
        result = ''
        i = 0
        for chunk in response:
            content  = chunk['message']['content']
            if content:
                result += content
                thread.progress.emit(sql_id, i, content)
                i += 1
        return result

def main():
    raise SystemError("This file cannot be operable")
 
if __name__ == "__main__":
    main()
 