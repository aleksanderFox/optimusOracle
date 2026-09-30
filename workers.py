import os
from pathlib import Path
from abc import abstractmethod
from enum import Enum
import oracledb
from oracledb.connection import Connection 
from oracledb.cursor import Cursor
from PyQt6.QtCore import QThread, pyqtSignal

# ─────────────────────────────────────────────────────────────────────────────
# Worker потоки (фоновые задачи)
# ─────────────────────────────────────────────────────────────────────────────

def get_query(query_file_name: str, file_ext: str = '.sql') -> str:
    """ Функция возвращающая текст SQL запроса из файла """
    script_dir = Path(__file__).parent.resolve()
    file_name = os.path.join(script_dir, 'sql', query_file_name + file_ext)
    with open(file_name, 'r', encoding='utf-8') as file:
        sql = file.read()
    return sql

class BaseWorker(QThread):
    """Базовый поток для работы с БД"""
    error = pyqtSignal(str)

    def __init__(self, connection_params: dict):
        super().__init__()
        self.connection_params = connection_params

    def connect(self) -> Connection:
        return oracledb.connect(
            user=self.connection_params['user'],
            password=self.connection_params['password'],
            dsn=self.connection_params['dsn']
        );

    @abstractmethod
    def work(self, cur: Cursor):
        pass

    def process(self):
        with self.connect() as conn:
            with conn.cursor() as cur:
                self.work(cur)

    def run(self):
        try:
            self.process()
        except Exception as e:
            self.error.emit(str(e))

class LongQuerySource(Enum):
  ASH = 1
  AWR = 2

class LongQueryWorker(BaseWorker):
    """Поток для загрузки топ-тяжёлых запросов из ASH/AWR"""
    finished = pyqtSignal(list, LongQuerySource)
    error = pyqtSignal(str, LongQuerySource)
    progress = pyqtSignal(int, str)

    def work(self, cur: Cursor):
        if self.source == LongQuerySource.ASH:
            cur.execute(get_query('ASH_TOP_SQL'))
        elif self.source == LongQuerySource.AWR:
            cur.execute(get_query('GET_HIST_SNAPSHOT'))
            snapshot = cur.fetchall()
            snapshot_cols = [d[0] for d in cur.description]
            dbid = snapshot[0][snapshot_cols.index('DBID')]
            instance_number = snapshot[0][snapshot_cols.index('INSTANCE_NUMBER')]
            snap_id = []
            for r in snapshot:
                snap_id.append(r[snapshot_cols.index('SNAP_ID')])
            snap_ids = ', '.join(str(x) for x in snap_id)
            sql = get_query('AWR_TOP_SQL').replace(":snap_id", snap_ids)
            sql = sql.replace(":dbid", str(dbid))
            sql = sql.replace(":instance_number", str(instance_number))
            cur.execute(sql)

        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        self.progress.emit(80, "Обработка результатов...")
        results = []
        for r in rows:
            results.append(dict(zip(cols, r)))
        self.progress.emit(100, f"Готово: найдено {len(results)} запросов")
        self.finished.emit(results, self.source)

    def __init__(self, connection_params: dict, source: LongQuerySource):
        super().__init__(connection_params)
        self.source = source

    def run(self):
        try:
            self.progress.emit(10, "Подключение к Oracle...")
            self.process()
        except Exception as e:
            self.error.emit(str(e), self.source)

class FullSQLWorker(BaseWorker):
    """Поток для загрузки полного текста SQL запроса """
    finished = pyqtSignal(str, str)  # sql_id, plan_text

    def __init__(self, connection_params: dict, sql_id: str):
        super().__init__(connection_params)
        self.sql_id = sql_id

    def work(self, cur: Cursor):
        cur.execute(get_query('SQL_FULL_TEXT'), {"sql_id": self.sql_id})
        row = cur.fetchone()
        if row and len(row) == 1:
            sql_full_text = row[0]
            self.finished.emit(self.sql_id, sql_full_text)
        else:
            # Получение текста SQL из AWR (если в v$sqlarea уже нет)
            cur.execute(get_query('SQL_FULL_TEXT_HIST'), {"sql_id": self.sql_id})
            row = cur.fetchone()
            sql_full_text = row[0]
            self.finished.emit(self.sql_id, sql_full_text)

    def run(self):
        try:
            oracledb.defaults.fetch_lobs = False
            self.process()
        except Exception as e:
            self.error.emit(str(e))

class PlanWorker(BaseWorker):
    """Поток для загрузки плана выполнения конкретного SQL."""
    finished = pyqtSignal(str, str, str)  # sql_id, plan_hash, plan_text

    def __init__(self, connection_params: dict, sql_id: str, plan_hash: str):
        super().__init__(connection_params)
        self.sql_id = sql_id
        self.plan_hash = plan_hash

    def work(self, cur: Cursor):
        # Получение плана выполнения из AWR
        cur.execute(get_query('PLAN_AWR_SQL'), {"sql_id": self.sql_id, "plan_hash": self.plan_hash})
        rows = cur.fetchall()
        if len(rows) == 0:
            cur.execute(get_query('PLAN_SQL'), {"sql_id": self.sql_id})
            rows = cur.fetchall()
        plan_lines = []
        for r in rows:
            if r[0] is not None:
                plan_lines.append(r[0])
        plan_text = "\n".join(plan_lines) if plan_lines else "План не найден в AWR"
        self.finished.emit(self.sql_id, self.plan_hash, plan_text)

class ObjectInfoWorker(BaseWorker):
    """Поток для загрузки информации об объектах, затронутых запросом."""
    finished = pyqtSignal(str, str, list)  # sql_id, info_text

    def __init__(self, connection_params: dict, sql_id: str):
        super().__init__(connection_params)
        self.sql_id = sql_id

    def work(self, cur: Cursor):
        # Получаем объекты из плана
        # Получение информации об объектах из AWR для конкретного sql_id
        cur.execute(get_query('SQL_OBJECTS_AWR'), {"sql_id": self.sql_id})
        obj_rows = cur.fetchall()
        obj_cols = [d[0] for d in cur.description]
        objects = [dict(zip(obj_cols, r)) for r in obj_rows]
        add_objects = {}
        tables = []

        info_parts = []

        for obj in objects:
            owner = obj.get("OWNER")
            obj_name = obj.get("OBJECT_NAME")
            obj_type = obj.get("OBJECT_TYPE")

            if not owner or not obj_name:
                continue

            if owner + '.' + obj_name in add_objects:
                continue

            add_objects[owner + '.' + obj_name] = 1
            info_parts.append(f"\n{'='*60}")
            info_parts.append(f"Объект: {owner}.{obj_name} ({obj_type})")
            info_parts.append(f"{'='*60}")

            # Размер сегмента
            cur.execute(get_query('SEGMENT_INFO'), {"obj_name": obj_name, "owner": owner})
            seg_rows = cur.fetchall()
            for sr in seg_rows:
                info_parts.append(f"  Размер: {sr[2]} MB, TS: {sr[3]}")

            if obj_type == "TABLE" or obj_type == "TABLE PARTITION":
                tables.append({"owner": owner, "table_name": obj_name})
                # Столбцы
                cur.execute(get_query('TABLE_COLUMNS'), {"owner": owner, "table_name": obj_name})
                col_rows = cur.fetchall()
                info_parts.append("\n  Столбцы:")
                for cr in col_rows:
                    nullable = "NULL" if cr[5] == "Y" else "NOT NULL"
                    n_distinct = f"NDV={cr[6]}" if cr[6] else ""
                    info_parts.append(
                        f"    {cr[0]:30s} {cr[1]:15s} {nullable:8s} {n_distinct}"
                    )

                # Статистика
                cur.execute(get_query('TABLE_STATS'), {"owner": owner, "table_name": obj_name})
                stat_rows = cur.fetchall()
                if stat_rows and stat_rows[0][0]:
                    s = stat_rows[0]
                    info_parts.append(
                        f"\n  Статистика: rows={s[0]}, blocks={s[1]}, "
                        f"avg_row_len={s[5]}, last_analyzed={s[6]}"
                    )

                # Существующие индексы
                cur.execute(
                    get_query('EXISTING_INDEXES'),
                    {"owner": owner, "table_name": obj_name},
                )
                idx_rows = cur.fetchall()
                if idx_rows:
                    info_parts.append("\n  Индексы:")
                    current_idx = None
                    for ir in idx_rows:
                        if ir[0] != current_idx:
                            current_idx = ir[0]
                            info_parts.append(
                                f"    {ir[0]:35s} {ir[1]:15s} "
                                f"{ir[2]:10s} status={ir[5]}"
                            )
                        info_parts.append(f"      -> {ir[3]} (pos {ir[4]})")
                else:
                    info_parts.append("\n  Индексы: нет (возможно, нужен)")
            elif obj_type == "INDEX":
                info_parts.append("  (это индекс — см. таблицу для деталей)")

        if not info_parts:
            info_parts.append("Информация об объектах не найдена в AWR")

        self.finished.emit(self.sql_id, "\n".join(info_parts), tables)

class ObjectDDLWorker(BaseWorker):
    """Поток для загрузки DDL таблиц SQL."""
    finished = pyqtSignal(str, str)  # sql_id, plan_text

    def __init__(self, connection_params: dict, sql_id: str, table_list: list):
        super().__init__(connection_params)
        self.sql_id = sql_id
        self.table_list = table_list

    def work(self, cur: Cursor):
            cur.callproc("dbms_output.enable")
            cur.execute("begin DBMS_OUTPUT.ENABLE(1000000); end;")
            result_string = ""

            for table in self.table_list:
                # Получение DDL
                cur.execute(get_query('GET_METADATA'), {'owner': table['owner'], 'table_name': table['table_name']})

                chunk_size = 100  # Размер пакета для чтения
                lines_var = cur.arrayvar(str, chunk_size)
                num_lines_var = cur.var(int)
                num_lines_var.setvalue(0, chunk_size)

                # 5. Собираем строки в список
                all_lines = []
                while True:
                    # Вызываем get_lines, который забирает строки из буфера
                    cur.callproc("dbms_output.get_lines", (lines_var, num_lines_var))
                    
                    num_lines = num_lines_var.getvalue()
                    lines = lines_var.getvalue()[:num_lines]
                    
                    # Фильтруем возможные None (пустые строки)
                    for line in lines:
                        if line is not None:
                            all_lines.append(line)
                    
                    # Если прочитали меньше, чем размер буфера — значит, достигли конца
                    if num_lines < chunk_size:
                        break
                # 6. Соединяем в одну строку
                result_string = result_string + "\n".join(all_lines) + "\n"

            self.finished.emit(self.sql_id, result_string)

def main():
    raise SystemError("This file cannot be operable")
 
if __name__ == "__main__":
    main()
 