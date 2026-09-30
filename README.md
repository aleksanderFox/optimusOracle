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

## Использование

1. Нажмите **«Подключиться к Oracle»** и введите параметры подключения
2. Нажмите **«Обновить ASH»** — загрузится топ-20 тяжёлых запросов из ASH
3. Нажмите **«Обновить AWR»** — загрузится топ-20 тяжёлых запросов из AWR
4. Выберите запрос в таблице — автоматически загрузятся план выполнения 
   и информация об объектах
5. Нажмите **«Оптимизировать через LLM»** — модель проанализирует 
   запрос и предложит оптимизации
6. Экспортируйте результат через меню **Файл → Экспорт отчёта**

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
