import traceback
import os
import sys
import importlib, importlib.util
import re
from pathlib import Path
from abc import abstractmethod
from PyQt6.QtCore import QThread, pyqtSignal

# ─────────────────────────────────────────────────────────────────────────────
# Поставщики LLM (Поставщики ИИ моделей)
# ─────────────────────────────────────────────────────────────────────────────

temperature = os.getenv('ORACLE_QUEUE_OPTIMIZER_LLM_TEMPERATURE', '0.3')
temperature = float(temperature) if re.match(r"^-?\d+\.\d+$", temperature) else None

script_dir = Path(__file__).parent.resolve()
file_name = os.path.join(script_dir, 'prompt', 'SYSTEM_PROMPT')
if os.path.exists(file_name):
    with open(file_name, 'r', encoding='utf-8') as file:
        SYSTEM_PROMPT = file.read()
else:
    SYSTEM_PROMPT = ""

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
class LLMProvider(QThread):
    finished = pyqtSignal(str, str)  # sql_id, response
    error = pyqtSignal(str, str) # sql_id, error message
    progress = pyqtSignal(str, int, str) # sql_id, step, message

    def __init__(self, provider_name: str, model_info: dict, sql_id: str, sql_info: dict):
        super().__init__()
        self.model_info = model_info
        self.sql_id = sql_id
        self.sql_info = sql_info

        # если имя provider_name содержит точку - найти py файл и загрузить его
        if "." in provider_name:
            provider = provider_name.split(".")
            script_dir = Path(__file__).parent.resolve()
            file_name = os.path.join(script_dir, provider[0] + '.py')
            module_name = provider[0]
            if os.path.exists(file_name):
                spec = importlib.util.spec_from_file_location(module_name, file_name)
                if spec is None:
                    raise ImportError(f"Не удалось создать спецификацию для {file_name}")
                try:
                    # Динамически импортируем модуль. 
                    # В этот момент сработает __init_subclass__ для всех классов внутри!
                    # importlib.import_module(import_path)
                    module = importlib.util.module_from_spec(spec)
                    sys.modules[module_name] = module
                    spec.loader.exec_module(module)
                    provider_name = provider[1]
                except Exception as e:
                    raise ValueError(f"Ошибка при загрузке {file_name}: {e}")

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
 