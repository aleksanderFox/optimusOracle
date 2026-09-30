import traceback
import os
from abc import abstractmethod
from PyQt6.QtCore import QThread, pyqtSignal
import ollama
from openai import OpenAI

# ─────────────────────────────────────────────────────────────────────────────
# Поставщики LLM (Поставщики ИИ моделей)
# ─────────────────────────────────────────────────────────────────────────────

temperature = os.getenv('ORACLE_QUEUE_OPTIMIZER_LLM_TEMPERATURE', '0.3')
temperature = float(temperature) if temperature.isdigit() else None

# TODO перенести в файл
SYSTEM_PROMPT = """Ты — эксперт по оптимизации Oracle Database.
Твоя задача — проанализировать SQL-запрос, его план выполнения, 
схему данных и существующие индексы, затем предложить конкретные шаги 
по оптимизации.

Правила:
1. Предлагай только оптимизации, которые не требуют изменения логики запроса.
2. Для каждого предложения укажи:
   - Тип оптимизации (индекс, переписывание запроса, если это разрешено, изменение структуры таблицы, статистика, подсказки оптимизатору)
   - Конкретный DDL или изменённый SQL (только как рекомендацию, не для выполнения)
   - Ожидаемый эффект
   - Риски и побочные эффекты
3. Если запрос уже оптимизирован хорошо — так и скажи.
4. Учитывай версию Oracle и особенности оптимизатора.
5. Отвечай на русском языке.

Формат ответа:
## Анализ текущего состояния
...

## Рекомендации

### Рекомендация 1: [Тип]
**Действие**: ...
**Код**: 
```sql
...
```
**Ожидаемый эффект**: ...
**Риски**: ...

### Рекомендация 2: [Тип]
...

## Приоритет оптимизаций
1. ...
2. ...
"""

class BaseLLM:
    _registry: dict[str, type["BaseLLM"]] = {}

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        BaseLLM._registry[cls.__name__] = cls

    def __init__(self, model_info: dict, sql_info: dict):
        self.model_info = model_info
        self.sql_info = sql_info

    @abstractmethod
    def _ask_llm(self, message: list, sql_id: str, thread) -> str:
        pass

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

class LLMProvider(QThread):
    finished = pyqtSignal(str, str)  # sql_id, response
    error = pyqtSignal(str, str) # sql_id, error message
    progress = pyqtSignal(str, int, str) # sql_id, step, message

    def __init__(self, provider_name: str, model_info: dict, sql_id: str, sql_info: dict):
        super().__init__()
        self.model_info = model_info
        self.sql_id = sql_id
        self.sql_info = sql_info
        try:
            llm_cls = BaseLLM._registry[provider_name]
        except KeyError:
            raise ValueError(f"Неизвестный провайдер LLM: {provider_name!r}") from None

        self.llm = llm_cls(model_info, sql_info)

    def _build_prompt(self) -> str:
        prompt_parts = [
            "Проанализируй следующий SQL-запрос из Oracle и предложи оптимизации.\n",
            f"SQL_ID: {self.sql_id}\n",
            "\n## SQL-запрос\n```sql\n",
            self.sql_info['sql_text'],
            "\n```\n",
        ]
        if self.sql_info['plan_text'] and self.sql_info['plan_text'] != "План не найден в AWR":
            prompt_parts.append("\n## План выполнения (из AWR)\n```\n")
            prompt_parts.append(self.sql_info['plan_text'])
            prompt_parts.append("\n```\n")

        if self.sql_info['object_info']:
            prompt_parts.append("\n## Информация об объектах схемы\n```\n")
            prompt_parts.append(self.sql_info['object_info'])
            prompt_parts.append("\n```\n")

        if self.sql_info['schema_text']:
            prompt_parts.append("\n## Схема данных\n```\n")
            prompt_parts.append(self.sql_info['schema_text'])
            prompt_parts.append("\n```\n")

        if self.sql_info['can_change_query']:
            prompt_parts.append(
                "\n## Задача\n"
                "1. Найди узкие места в плане выполнения (full table scan, "
                "Cartesian joins, плохие порядки соединения, неэффективные фильтры).\n"
                "2. Предложи создание индексов с конкретными DDL.\n"
                "3. Предложи переписывание запроса, если это улучшит план.\n"
                "4. Отметь, если нужна актуализация статистики.\n"
                "5. Укажи приоритет каждой оптимизации.\n"
            )
        else:
            prompt_parts.append(
                "\n## Задача\n"
                "1. Найди узкие места в плане выполнения (full table scan, "
                "Cartesian joins, плохие порядки соединения, неэффективные фильтры).\n"
                "2. Предложи создание индексов с конкретными DDL.\n"
                "3. НЕ предлагай изменение запроса, добавление хинтов к запросу, по скольку это не возможно.\n"
                "4. Отметь, если нужна актуализация статистики.\n"
                "5. Укажи приоритет каждой оптимизации.\n"
            )        
        return "".join(prompt_parts)

    def run(self):
        try:
            user_prompt = self._build_prompt()
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ]
            response = self.llm._ask_llm(messages, self.sql_id, self)
            self.finished.emit(self.sql_id, response)
        except Exception as e:
            stack_list = traceback.format_tb(e.__traceback__)
            stack_str = "".join(stack_list) + "\n" + str(e)
            self.error.emit(self.sql_id, str(stack_str))

def main():
    raise SystemError("This file cannot be operable")
 
if __name__ == "__main__":
    main()
 