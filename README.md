# Oracle Query Optimizer (Optimus Oracle)

Приложение для поиска тяжёлых SQL-запросов в Oracle (через ASH/AWR) 
и получения рекомендаций по оптимизации от LLM-моделей.

## Возможности

- **Поиск тяжёлых запросов** — топ-20 из `V$ACTIVE_SESSION_HISTORY` 
  за последние 12 часов, отфильтрованные по количеству samples (>=10)
  или из DBA_HIST_ACTIVE_SESS_HISTORY
  за за последние сутки, в AWR сэмплов меньше, чем в ASH, поэтому порог 1
- **План выполнения** — загрузка из AWR через `dbms_xplan.display_awr` или `dbms_xplan.display_cursor`
- **Информация об объектах** — таблицы, столбцы, существующие индексы, 
  статистика, размер сегментов, полученные из словарей БД
- **Анализ LLM** — отправка SQL, плана, метаданных объектов и схемы 
  в LLM модель для получения рекомендаций
  Есть возможность подключение следующих провайдеров LLM моделей:
  - openai
  - dashscope
  - ollama
  - litellm
  - TODO: добавить поддержку Google GenAI, Anthropic
- **Экспорт отчёта** — сохранение всех данных и рекомендаций в текстовый файл

## Безопасность

Программа выполняет только `SELECT`-запросы к системным представлениям 
и словарям Oracle. Никакие DML или DDL команды не выполняются.

## Установка

### 1. Установите Python-зависимости

```bash
pip install -r requirements.txt
```

### 2. Установите Ollama (если требуется)

```bash
# macOS
brew install ollama

# Linux
curl -fsSL https://ollama.com/install.sh | sh

# Windows — скачайте с https://ollama.com
```

### 3. Запустите Ollama и скачайте модель

```bash
ollama serve
ollama pull llama3   # или qwen2.5, codellama, mistral
```

### 4. Запустите приложение

```bash
python oracle_query_optimizer.py
```

## Настройки
ORACLE_QUEUE_OPTIMIZER_ORACLE_PATH - путь к драйверам Oracle (пример: C:/oracle/product/12.1.0/client)
ORACLE_QUEUE_OPTIMIZER_ORACLE_DNS - адрес подключения к Oracle (пример: ip_address/database_sid)
ORACLE_QUEUE_OPTIMIZER_ORACLE_USER = имя пользователя по умолчанию
![Подключение к БД Oracle](images/OptimusOracle_connect.png)
ORACLE_QUEUE_OPTIMIZER_LLM_MODELS = JSON массив списка используемых моделей
Пример:
[
    {"provider": "llm_ollama.OllamaLLM", "server_name": "http://localhost:11434", "model_name": "qwen3:14b"},
    {"provider": "llm_lite.LiteLLM", "server_name": "http://localhost:11434", "model_name": "ollama/gemma4:26b"},
    {"provider": "llm_alibaba.AlibabaLLM", "api_key":"API_KEY", "base_url": "https://{workspace_id}.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1", "model_name":"qwen3.7-plus", "is_remote": true},
    {"provider": "llm_alibaba.AlibabaDashscope", "api_key":"API_KEY", "base_url": "https://{workspace_id}.ap-southeast-1.maas.aliyuncs.com/api/v1", "model_name":"qwen3.7-plus-2026-05-26", "workspace": "{workspace_id}", "is_remote": true}
]

provider - провайдер(модуль.имя_класса), который обрабатывает запрос к LLM. На текущий момент добавлено три провайдере
  llm_ollama.OllamaLLM - подключение к ollama
  llm_alibaba.AlibabaLLM - подключение в alibaba qwen через openai
  llm_lite.LiteLLM - универсальный провайдер litellm

Важно правильно описать модели, доступные Вам. Именно те модели, которые вы подключите, будут анализировать SQL, план, метаданные объектов и предоставлять рекомендации, которые позволят улучшить быстродействия Вашего сервера.
Локальные модели qwen3:14b/gemma4:26b не справляются с тяжелыми запросами, содержащими множественные join
Облачная модель qwen3.7-plus очень хорошо анализирует сложные SQL запросы и генерирует полезные советы.

ORACLE_QUEUE_OPTIMIZER_LLM_TEMPERATURE - температура 

## Использование

1. Нажмите **«Подключиться к Oracle»** и введите параметры подключения
![Подключение к БД Oracle](images/OptimusOracle_connect.png)
2. Нажмите **«Обновить ASH»** — загрузится топ-20 тяжёлых запросов из ASH
3. Нажмите **«Обновить AWR»** — загрузится топ-20 тяжёлых запросов из AWR
4. Выберите запрос в таблице — автоматически загрузятся план выполнения 
   и информация об объектах
![SQL/План запроса](images/OptimusOracle_SqlPlan.png)
![Информация об объектах](images/OptimusOracle_ObjectInfo.png)
5. Нажмите **«Оптимизировать через LLM»** — модель проанализирует 
   запрос и предложит оптимизации
![Рекомендации LLM](images/OptimusOracle_llm.png)
6. Экспортируйте результат через меню **Файл → Экспорт отчёта**
![Отчет об оптимизации SQL запроса](images/OptimusOracle_report.png)
## Системные представления Oracle

Приложение обращается к следующим представлениям:

| Представление | Назначение |
|---|---|
| `V$ACTIVE_SESSION_HISTORY` | Поиск тяжёлых запросов |
| `V$SQLAREA` | Текст SQL-запросов |
| `DBMS_XPLAN.DISPLAY_AWR` | План выполнения из AWR |
| `DBA_HIST_SQL_PLAN` | Объекты из плана запроса |
| `DBA_OBJECTS` | Информация об объектах |
| `DBA_SEGMENTS` | Размер сегментов |
| `DBA_INDEXES` / `DBA_IND_COLUMNS` | Существующие индексы |
| `DBA_TAB_COLUMNS` | Столбцы таблиц |
| `DBA_TABLES` | Статистика по таблицам |

## Требования к правам

Пользователь Oracle должен иметь права на чтение системных представлений:

```sql
-- Минимальные гранты (роли)
GRANT SELECT_CATALOG_ROLE TO <user>;

-- Или индивидуальные гранты
GRANT SELECT ON V$ACTIVE_SESSION_HISTORY TO <user>;
GRANT SELECT ON V$SQLAREA TO <user>;
GRANT SELECT ON DBA_HIST_SQLTEXT TO <user>;
GRANT SELECT ON DBA_HIST_SQL_PLAN TO <user>;
GRANT SELECT ON DBA_OBJECTS TO <user>;
GRANT SELECT ON DBA_SEGMENTS TO <user>;
GRANT SELECT ON DBA_INDEXES TO <user>;
GRANT SELECT ON DBA_IND_COLUMNS TO <user>;
GRANT SELECT ON DBA_TAB_COLUMNS TO <user>;
GRANT SELECT ON DBA_TABLES TO <user>;
GRANT EXECUTE ON DBMS_XPLAN TO <user>;
```
