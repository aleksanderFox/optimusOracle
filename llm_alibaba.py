import dashscope
from dashscope import MultiModalConversation
from http import HTTPStatus
from llm_providers import (BaseLLM, temperature)

class DashscopeLLM(BaseLLM):
    def __init__(self, model_info: dict, sql_info: dict):
        super().__init__(model_info, sql_info)
        dashscope.base_http_api_url = self.model_info['base_url']
        dashscope.api_key = self.model_info['api_key']

    def _ask_llm(self, message: list, sql_id: str, thread) -> str:
        responses = MultiModalConversation.call(
            api_key = self.model_info['api_key'],
            model = self.model_info['model_name'],
            messages = message,
            workspace = self.model_info['workspace'],
            stream = True,               # Включает потоковую передачу данных
            incremental_output = True    # Каждый chunk содержит только новый инкрементальный текст
        )

        result = ''
        i = 0
        for response in responses: # type: ignore
            if response.status_code == HTTPStatus.OK:
                if response.output.choices and len(response.output.choices) > 0:
                    # Получаем новый фрагмент текста
                    msg = response.output.choices[0].message
                    if msg and msg.content and len(msg.content) > 0:
                        result += msg.content[0]["text"]
                        thread.progress.emit(sql_id, i, msg.content[0]["text"])
                        i += 1
            elif response.status_code == HTTPStatus.NOT_FOUND:
                raise ValueError(f"Ошибка {HTTPStatus.NOT_FOUND}: {HTTPStatus.NOT_FOUND.phrase}") 

        return result

def main():
    raise SystemError("This file cannot be operable")
 
if __name__ == "__main__":
    main()
