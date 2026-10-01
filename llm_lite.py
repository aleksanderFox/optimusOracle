import os
from litellm import completion
from llm_providers import BaseLLM

class LiteLLM(BaseLLM):

    def __init__(self, model_info: dict, sql_info: dict):
        super().__init__(model_info, sql_info)
        model_name = self.model_info['model_name']
        if "/" in model_name:
            self.model_class = model_name.split("/")[0]
            if self.model_class == "ollama":
                os.environ["OLLAMA_API_BASE"] = self.model_info['server_name']
            if self.model_class == "openai":
                os.environ["OPENAI_API_KEY"] = self.model_info['api_key']
            # TODO добавить поддержку других провайдеров
        else:
            self.model_class = None

    def _ask_llm(self, message: list, sql_id: str, thread) -> str:
        api_base = self.model_info['server_name'] if self.model_class == "ollama" else None            
        response = completion(
            model = self.model_info['model_name'],
            messages = message,
            api_base = api_base,
            stream = True,
            timeout = 1800
        )
        result = ''
        i = 0
        for chunk in response: # type: ignore
            content = chunk.choices[0].delta.content
            if content:
                result += content
                thread.progress.emit(sql_id, i, content)
                i += 1
        return result
