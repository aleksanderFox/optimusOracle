from openai import OpenAI
from llm_providers import (BaseLLM, temperature)

class AlibabaLLM(BaseLLM):
    def __init__(self, model_info: dict, sql_info: dict):
        super().__init__(model_info, sql_info)
        base_url =self.model_info['base_url'] 
        api_key = self.model_info['api_key']
        self.client = OpenAI(
            api_key = api_key,
            base_url = base_url,
            timeout = 3000.0,
            max_retries = 1
        )

    def _ask_llm(self, message: list, sql_id: str, thread) -> str:
        if temperature:
            stream = self.client.chat.completions.create(
                model = self.model_info['model_name'],
                messages = message,
                temperature = float(temperature),
                stream = True
            )
        else:
            stream = self.client.chat.completions.create(
                model = self.model_info['model_name'],
                messages = message,
                stream = True
            )

        result = ''
        i = 0
        for chunk in stream:
            if chunk.choices and len(chunk.choices) > 0:
                delta = chunk.choices[0].delta
                if delta.content:
                    result += delta.content
                    thread.progress.emit(sql_id, i, delta.content)
                    i += 1

        return result

def main():
    raise SystemError("This file cannot be operable")
 
if __name__ == "__main__":
    main()
