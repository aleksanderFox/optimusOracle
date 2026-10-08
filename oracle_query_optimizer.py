#!/usr/bin/env python3
"""
Oracle Query Optimizer (Optimus Oracle)
======================
Приложение для поиска тяжёлых запросов в Oracle ASH/AWR,
анализа планов выполнения и получения рекомендаций
по оптимизации от LLM-моделей.

Зависимости:
    pip install oracledb PyQt6 ollama OpenAI litellm
"""

import sys
import os
from pathlib import Path
from datetime import datetime
import json
import oracledb
from PyQt6.QtCore import Qt, QTranslator, QLocale, QLibraryInfo, QEvent
from PyQt6.QtGui import QFont, QAction
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QCheckBox,
    QGridLayout, QLabel, QLineEdit, QPushButton, QTextEdit, QTableWidget,
    QTableWidgetItem, QTabWidget, QSplitter, QFileDialog, QGroupBox,
    QMessageBox, QProgressBar, QComboBox, QHeaderView, QPlainTextEdit,
    QDialog, QDialogButtonBox, QMenuBar
)
from workers import ( LongQueryWorker, FullSQLWorker, PlanWorker, 
    ObjectDDLWorker, ObjectInfoWorker, LongQuerySource )
import llm_providers

I18N_DIR = Path(__file__).parent / "i18n"
BASE_LOCALE = "ru_RU"   # язык исходников — .qm для него не нужен

# ─────────────────────────────────────────────────────────────────────────────
# Диалог подключения к Oracle
# ─────────────────────────────────────────────────────────────────────────────

class ConnectionDialog(QDialog):
    """Диалог для ввода параметров подключения к Oracle."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Подключение к Oracle"))
        self.setModal(True)
        self._build_ui()

    def _build_ui(self):
        layout = QGridLayout(self)

        # Метки и поля ввода
        layout.addWidget(QLabel("dns:"), 0, 0)
        dsn = os.getenv('ORACLE_QUEUE_OPTIMIZER_ORACLE_DNS')
        self.dsn_edit = QLineEdit(dsn)
        layout.addWidget(self.dsn_edit, 0, 1)

        layout.addWidget(QLabel(self.tr("Путь к клиенту Oracle:")), 1, 0)
        path = os.getenv('ORACLE_QUEUE_OPTIMIZER_ORACLE_PATH')
        self.path_edit = QLineEdit(path)
        layout.addWidget(self.path_edit, 1, 1)

        layout.addWidget(QLabel(self.tr("Пользователь:")), 2, 0)
        user = os.getenv('ORACLE_QUEUE_OPTIMIZER_ORACLE_USER')
        self.user_edit = QLineEdit(user)
        layout.addWidget(self.user_edit, 2, 1)

        layout.addWidget(QLabel(self.tr("Пароль:")), 3, 0)
        self.pwd_edit = QLineEdit()
        self.pwd_edit.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.pwd_edit, 3, 1)

        # Кнопки
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons, 7, 0, 1, 2)

    def get_params(self):
        dsn = self.dsn_edit.text().strip()
        path = self.path_edit.text().strip()
        user = self.user_edit.text().strip()
        pwd = self.pwd_edit.text()

        return {
            "user": user,
            "password": pwd,
            "dsn": dsn,
            "path": path
        }

# ─────────────────────────────────────────────────────────────────────────────
# Главное окно
# ─────────────────────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):

    def __init__(self, translator: QTranslator, translator_path: str):
        super().__init__()
        self.translator = translator
        self.translator_path = translator_path
        self.setWindowTitle("Oracle Query Optimizer (Optimus Oracle)")
        self.resize(1400, 900)

        self.connection_params: dict = {}
        self.long_query_results = []
        self.schema_cache = {}     # sql_id -> schema for tables in query 
        self.sql_cache  = {}       # sql_id -> full sql
        self.plan_cache = {}       # sql_id + '_' + plan_hash -> plan_text
        self.tables_cache = {}     # sql_id -> table list 
        self.object_cache = {}     # sql_id -> object_info
        self.llm_cache = {}        # sql_id -> response
        self.models_loaded = False
        try:
            llm_models = os.getenv('ORACLE_QUEUE_OPTIMIZER_LLM_MODELS', '[]')
            self.models = json.loads(llm_models)
            self.models_loaded = self.tr
        except Exception as e:
            self.models = []

        self._build_ui()
        self._build_menu()

    # ── UI ───────────────────────────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        # --- Панель подключения и настроек ---
        self.ctrl_group = QGroupBox(self.tr("Управление"))
        ctrl_layout = QHBoxLayout(self.ctrl_group)

        self.connect_btn = QPushButton(self.tr("Подключиться к Oracle"))
        self.connect_btn.clicked.connect(self.on_connect)
        ctrl_layout.addWidget(self.connect_btn)

        self.conn_status = QLabel(self.tr("Статус: не подключено"))
        ctrl_layout.addWidget(self.conn_status)

        ctrl_layout.addStretch()

        self.llm_models_info = QLabel(self.tr("Доступно N моделей LLM "))
        ctrl_layout.addWidget(self.llm_models_info)
        self.llm_name = QLabel(self.tr("Модель:"))
        ctrl_layout.addWidget(self.llm_name)
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        for model in self.models:
            self.model_combo.addItem(model['model_name'], model)
        self.model_combo.currentTextChanged.connect(self.on_model_changed)
        ctrl_layout.addWidget(self.model_combo)
        if self.models_loaded:
            self.llm_models_info.setText(self.tr("Доступно {length} моделей LLM ").format(length=len(self.models)))
        else:
            self.llm_models_info.setText(self.tr("Ошибка загрузки списка моделей"))

        main_layout.addWidget(self.ctrl_group)

        # --- Основной сплиттер ---
        splitter = QSplitter(Qt.Orientation.Vertical)

        # Верх: таблица ASH/AWR
        self.long_query_group = QGroupBox(self.tr("Топ-20 тяжёлых запросов"))
        ash_layout = QVBoxLayout(self.long_query_group)

        long_query_btn_row = QHBoxLayout()
        self.ash_btn = QPushButton(self.tr("Обновить ASH"))
        self.ash_btn.clicked.connect(self.on_refresh_ash)
        self.ash_btn.setEnabled(False)
        long_query_btn_row.addWidget(self.ash_btn)

        self.awr_btn = QPushButton(self.tr("Обновить AWR"))
        self.awr_btn.clicked.connect(self.on_refresh_awr)
        self.awr_btn.setEnabled(False)
        long_query_btn_row.addWidget(self.awr_btn)

        self.long_query_progress = QProgressBar()
        self.long_query_progress.setVisible(False)
        long_query_btn_row.addWidget(self.long_query_progress)

        self.elapsed_label = QLabel("")
        long_query_btn_row.addWidget(self.elapsed_label)
        long_query_btn_row.addStretch()
        ash_layout.addLayout(long_query_btn_row)

        self.ash_table = QTableWidget()
        self.ash_table.setColumnCount(9)
        self.ash_table.setHorizontalHeaderLabels([
            "SQL_ID", "Plan Hash", "Exec Start", "SQL Text",
            "Samples", "Est. Elapsed (s)", "Program", "First Sample", "Wait Class"
        ])
        self.ash_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.ash_table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection
        )
        self.ash_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.ash_table.itemSelectionChanged.connect(self.on_ash_row_selected)
        header = self.ash_table.horizontalHeader()
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        ash_layout.addWidget(self.ash_table)

        splitter.addWidget(self.long_query_group)

        # Низ: вкладки с деталями
        self.detail_tabs = QTabWidget()

        # Вкладка: SQL + план
        sql_plan_widget = QWidget()
        sql_splitter = QSplitter(Qt.Orientation.Horizontal)

        self.sql_text_view = QPlainTextEdit()
        self.sql_text_view.setReadOnly(True)
        self.sql_text_view.setPlaceholderText(self.tr("Текст SQL-запроса появится здесь..."))
        sql_font = QFont("Consolas", 10)
        self.sql_text_view.setFont(sql_font)

        self.plan_text_view = QPlainTextEdit()
        self.plan_text_view.setReadOnly(True)
        self.plan_text_view.setPlaceholderText(self.tr("План выполнения появится здесь..."))
        self.plan_text_view.setFont(sql_font)

        sql_splitter.addWidget(self.sql_text_view)
        sql_splitter.addWidget(self.plan_text_view)
        sql_splitter.setSizes([1, 1])
        sql_splitter.setStretchFactor(0, 1)
        sql_splitter.setStretchFactor(1, 1)

        sql_plan_layout = QVBoxLayout(sql_plan_widget)
        sql_plan_layout.setContentsMargins(0, 0, 0, 0)
        sql_plan_layout.addWidget(sql_splitter)

        self.detail_tabs.addTab(sql_plan_widget, self.tr("SQL / План"))

        ##################################################
        # Вкладка: Информация об объектах
        object_info_widget = QWidget()
        object_info_layout = QVBoxLayout(object_info_widget)

        self.object_info_view = QPlainTextEdit()
        self.object_info_view.setReadOnly(True)
        self.object_info_view.setPlaceholderText(
            self.tr("Информация об объектах (таблицы, индексы, статистика)...")
        )
        self.object_info_view.setFont(sql_font)
        object_info_layout.addWidget(self.object_info_view)
        
        self.detail_tabs.addTab(object_info_widget, self.tr("Информация об объектах"))

        ##################################################
        # Вкладка: Информация DDL объектов
        object_ddl_widget = QWidget()
        object_ddl_layout = QVBoxLayout(object_ddl_widget)

        self.object_ddl_view = QPlainTextEdit()
        self.object_ddl_view.setReadOnly(True)
        self.object_ddl_view.setPlaceholderText(
            self.tr("DDL объектов запроса (таблицы, индексы)...")
        )
        self.object_ddl_view.setFont(sql_font)
        object_ddl_layout.addWidget(self.object_ddl_view)
        
        self.detail_tabs.addTab(object_ddl_widget, self.tr("DDL объектов запроса"))

        ################################################
        # Вкладка: рекомендации LLM
        llm_widget = QWidget()
        llm_layout = QVBoxLayout(llm_widget)

        llm_btn_row = QHBoxLayout()
        self.analyze_btn = QPushButton(self.tr("Оптимизировать используя LLM"))
        self.analyze_btn.clicked.connect(self.on_analyze)
        self.analyze_btn.setEnabled(False)
        llm_btn_row.addWidget(self.analyze_btn)

        self.copy_analyze_btn = QPushButton(self.tr("Копировать"))
        self.copy_analyze_btn.clicked.connect(self.on_copy_analyze)
        self.copy_analyze_btn.setEnabled(False)
        llm_btn_row.addWidget(self.copy_analyze_btn)

        self.can_change_query_checkbox = QCheckBox(self.tr("Предлагать переписывание запроса"))
        self.can_change_query_checkbox.setChecked(True)
        llm_btn_row.addWidget(self.can_change_query_checkbox)

        self.llm_progress = QProgressBar()
        self.llm_progress.setVisible(False)
        llm_btn_row.addWidget(self.llm_progress)
        llm_btn_row.addStretch()
        llm_layout.addLayout(llm_btn_row)

        self.llm_output = QTextEdit()
        self.llm_output.setReadOnly(True)
        self.llm_output.setPlaceholderText(
            self.tr("Рекомендации по оптимизации от LLM появятся здесь...")
        )
        self.llm_output.setFont(QFont("Consolas", 10))
        llm_layout.addWidget(self.llm_output)

        self.detail_tabs.addTab(llm_widget, self.tr("Рекомендации LLM"))

        splitter.addWidget(self.detail_tabs)
        splitter.setSizes([350, 550])

        main_layout.addWidget(splitter)

    def _build_language_menu(self, menubar: QMenuBar | None):
        files = [
            f for f in I18N_DIR.rglob('*')
            if f.is_file() and f.suffix == '.qm'
        ]
        self.language_menu = None
        if len(files) > 1:
            self.language_menu = menubar.addMenu(self.tr("Язык"))
            for file in files:
                locale = file.name.replace('translation_', '').replace('.qm', '')
                language_action = self.language_menu.addAction(locale)
                language_action.setData(language_action)
                language_action.setCheckable(True)
                if self.translator_path == str(file):
                    language_action.setChecked(True)
                else:
                    language_action.setChecked(False)
                language_action.triggered.connect(self.on_language_change)

    def _build_menu(self):
        menubar = self.menuBar()

        self.file_menu = menubar.addMenu(self.tr("Файл"))

        self.export_all_data_action = QAction(self.tr("Экспорт отчёта для всех данных..."), self)
        self.export_all_data_action.triggered.connect(self.on_export_all_data_report)
        self.file_menu.addAction(self.export_all_data_action)

        self.export_selected_data_action = QAction(self.tr("Экспорт отчёта текущей записи..."), self)
        self.export_selected_data_action.triggered.connect(self.on_export_selected_data_report)
        self.file_menu.addAction(self.export_selected_data_action)

        self.file_menu.addSeparator()
        self.exit_action = QAction(self.tr("Выход"), self)
        self.exit_action.triggered.connect(self.close)
        self.file_menu.addAction(self.exit_action)

        self._build_language_menu(menubar)

        self.help_menu = menubar.addMenu(self.tr("Справка"))
        self.about_action = QAction(self.tr("О программе"), self)
        self.about_action.triggered.connect(self.on_about)
        self.help_menu.addAction(self.about_action)

    # ── Слоты ─────────────────────────────────────────────────────────────────

    def on_connect(self):
        dlg = ConnectionDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.connection_params = dlg.get_params()
            try:
                if self.connection_params['path']:
                    oracledb.init_oracle_client(lib_dir=self.connection_params['path'])
                conn = oracledb.connect(
                    user=self.connection_params['user'],
                    password=self.connection_params['password'],
                    dsn=self.connection_params['dsn']
                )
                conn.close()
                self.conn_status.setText(
                    f"Статус: подключено ({self.connection_params['user']})"
                )
                self.ash_btn.setEnabled(True)
                self.awr_btn.setEnabled(True)
                #QMessageBox.information(
                #    self, "Подключение",
                #    "Успешное подключение к Oracle!"
                #)
                self.ash_btn.click()
            except Exception as e:
                QMessageBox.critical(
                    self, self.tr("Ошибка подключения"), str(e)
                )

    def on_model_changed(self, text):
        pass

    def on_refresh_query(self, source_name: str, source: LongQuerySource):
        if not self.connection_params:
            QMessageBox.warning(self, self.tr("Внимание"), self.tr("Сначала подключитесь к Oracle"))
            return


        self.ash_table.clearSelection()
        self.sql_text_view.setPlainText('')
        self.plan_text_view.setPlainText('')
        self.object_info_view.setPlainText('')
        self.object_ddl_view.setPlainText('')
        self.llm_output.setPlainText('')

        if source == LongQuerySource.ASH:
            self.ash_btn.setEnabled(False)
        elif source == LongQuerySource.AWR:
            self.awr_btn.setEnabled(False)
        self.long_query_progress.setVisible(True)
        self.long_query_progress.setValue(0)

        self.long_query_group.setTitle(self.tr("Топ-20 тяжёлых запросов {source_name}").format(source_name=source_name))
        self.long_query_worker = LongQueryWorker(self.connection_params, source)
        self.long_query_worker.progress.connect(self._long_query_progress)
        self.long_query_worker.finished.connect(self._long_query_loaded)
        self.long_query_worker.error.connect(self._long_query_error)
        self.long_query_worker.start()

    def on_refresh_ash(self):
        self.on_refresh_query("ASH", LongQuerySource.ASH)

    def on_refresh_awr(self):
        self.on_refresh_query("AWR", LongQuerySource.AWR)

    def _long_query_progress(self, val, msg):
        self.long_query_progress.setValue(val)
        self.elapsed_label.setText(msg)

    def _long_query_loaded(self, results, source):
        self.long_query_results = results
        self.long_query_progress.setVisible(False)
        if source == LongQuerySource.ASH:
            self.ash_btn.setEnabled(True)
            self.elapsed_label.setText(
                self.tr("Загружено: {length} запросов из ASH в {dt}").format(length=len(results), dt=datetime.now().strftime('%H:%M:%S'))
            )
        elif source == LongQuerySource.AWR:
            self.awr_btn.setEnabled(True)
            self.elapsed_label.setText(
                self.tr("Загружено: {length} запросов из AWR в {dt}").format(length=len(results), dt=datetime.now().strftime('%H:%M:%S'))
            )
        self._populate_long_query_table(results)

    def _long_query_error(self, msg, source):
        self.long_query_progress.setVisible(False)
        if source == LongQuerySource.ASH:
            self.ash_btn.setEnabled(True)
            QMessageBox.critical(self, self.tr("Ошибка ASH"), msg)
        elif source == LongQuerySource.AWR:
            self.awr_btn.setEnabled(True)
            QMessageBox.critical(self, self.tr("Ошибка AWR"), msg)

    def _populate_long_query_table(self, results):
        self.ash_table.setRowCount(len(results))
        for i, r in enumerate(results):
            self.ash_table.setItem(i, 0, QTableWidgetItem(r.get("SQL_ID", "")))
            self.ash_table.setItem(
                i, 1, QTableWidgetItem(str(r.get("SQL_PLAN_HASH_VALUE", "")))
            )
            self.ash_table.setItem(i, 2, QTableWidgetItem(r.get("SQL_START", "")))
            sql_text = r.get("SQL_TEXT", "")
            # Обрезаем длинный текст для таблицы
            display = sql_text[:120].replace("\n", " ")
            self.ash_table.setItem(i, 3, QTableWidgetItem(display))
            self.ash_table.setItem(
                i, 4, QTableWidgetItem(str(r.get("TOTAL_SAMPLES", "")))
            )
            self.ash_table.setItem(
                i, 5, QTableWidgetItem(str(r.get("ESTIMATED_ELAPSED_SECONDS", "")))
            )
            self.ash_table.setItem(i, 6, QTableWidgetItem(r.get("PROGRAM", "")))
            first_sample = r.get("FIRST_SAMPLE_TIME", "")
            self.ash_table.setItem(i, 7, QTableWidgetItem(str(first_sample)))
            self.ash_table.setItem(
                i, 8, QTableWidgetItem(str(r.get("DOMINANT_WAIT_CLASS", "")))
            )
        self.ash_table.resizeRowsToContents()

    def on_ash_row_selected(self):
        rows = self.ash_table.selectionModel().selectedRows()
        if not rows:
            return
        row = rows[0].row()
        sql_id = self.ash_table.item(row, 0).text()
        plan_hash = self.ash_table.item(row, 1).text()
        sql_text_full = self.long_query_results[row].get("SQL_TEXT", "")

        self.sql_text_view.setPlainText(sql_text_full)
        self.plan_text_view.setPlaceholderText(self.tr("Загрузка плана..."))
        self.object_info_view.setPlaceholderText(self.tr("Загрузка объектов..."))
        self.object_ddl_view.setPlaceholderText(self.tr("Загрузка DDL..."))
        self.llm_output.clear()

        # Загружаем информацию о SQL 
        if sql_id in self.sql_cache:
            self.sql_text_view.setPlainText(self.sql_cache[sql_id])
        else:
            self.sql_text_view.clear()
            self._load_full_sql(sql_id)
            
        # Загружаем план и инфо об объектах
        if sql_id in self.plan_cache:
            self.plan_text_view.setPlainText(self.plan_cache[sql_id + '_' + plan_hash])
        else:
            self.plan_text_view.clear()
            self._load_plan(sql_id, plan_hash)

        if sql_id in self.object_cache:
            self.object_info_view.setPlainText(self.object_cache[sql_id])
        else:
            self.object_info_view.clear()
            self._load_object_info(sql_id)

        if sql_id in self.schema_cache:
            self.object_ddl_view.setPlainText(self.schema_cache[sql_id])
        else:
            self.object_ddl_view.clear()

        # Если есть кэш LLM — показываем
        if sql_id in self.llm_cache:
            self.llm_output.setMarkdown(self.llm_cache[sql_id])

        self.analyze_btn.setEnabled(True)
        self.copy_analyze_btn.setEnabled(True)

    def _load_full_sql(self, sql_id):
        self.sql_worker = FullSQLWorker(self.connection_params, sql_id)
        self.sql_worker.finished.connect(self._full_sql_loaded)
        self.sql_worker.error.connect(self._full_sql_error)
        self.sql_worker.start()

    def _full_sql_loaded(self, sql_id, sql_full_text):
        self.sql_cache[sql_id] = sql_full_text
        if self._current_sql_id() == sql_id:
            self.sql_text_view.setPlainText(sql_full_text)

    def _full_sql_error(self, msg):
        self.sql_text_view.setPlainText(self.tr("Ошибка получения полного текста SQL: {msg}").format(msg=msg))
        
    def _load_plan(self, sql_id, plan_hash):
        self.plan_worker = PlanWorker(self.connection_params, sql_id, plan_hash)
        self.plan_worker.finished.connect(self._plan_loaded)
        self.plan_worker.error.connect(self._plan_error)
        self.plan_worker.start()

    def _plan_loaded(self, sql_id, plan_hash, plan_text):
        self.plan_cache[sql_id + '_' + plan_hash] = plan_text
        if self._current_sql_id_hash() == sql_id + '_' + plan_hash:
            self.plan_text_view.setPlainText(plan_text)

    def _plan_error(self, msg):
        self.plan_text_view.setPlainText(self.tr("Ошибка загрузки плана: {msg}").format(msg=msg))

    def _load_object_info(self, sql_id):
        self.obj_worker = ObjectInfoWorker(self.connection_params, sql_id)
        self.obj_worker.finished.connect(self._obj_loaded)
        self.obj_worker.error.connect(self._obj_error)
        self.obj_worker.start()

    def _obj_loaded(self, sql_id, info_text, table_list):
        self.object_cache[sql_id] = info_text
        self.tables_cache[sql_id] = table_list
        if (table_list and len(table_list) > 0):
            self._load_object_ddl(sql_id, table_list)
        if self._current_sql_id() == sql_id:
            self.object_info_view.setPlainText(info_text)

    def _obj_error(self, msg):
        self.object_info_view.setPlainText(
            self.tr("Ошибка загрузки объектов: {msg}").format(msg=msg)
        )

    def _load_object_ddl(self, sql_id, table_list):
        self.ddl_worker = ObjectDDLWorker(self.connection_params, sql_id, table_list)
        self.ddl_worker.finished.connect(self._ddl_loaded)
        self.ddl_worker.error.connect(self._ddl_error)
        self.ddl_worker.start()

    def _ddl_loaded(self, sql_id, ddl_text):
        self.schema_cache[sql_id] = ddl_text
        if self._current_sql_id() == sql_id:
            self.object_ddl_view.setPlainText(ddl_text)

    def _ddl_error(self, msg):
        self.object_ddl_view.setPlainText(
            self.tr("Ошибка загрузки DDL: {msg}").format(msg=msg)
        )

    def on_analyze(self):
        sql_id = self._current_sql_id()
        if not sql_id:
            return

        sql_text = self.sql_text_view.toPlainText()
        plan_text = self.plan_text_view.toPlainText()
        object_info = self.object_info_view.toPlainText()
        model = self.model_combo.currentData()
        if 'is_remote' not in model:
            object_ddl = self.object_ddl_view.toPlainText() if self.tables_cache and len(self.tables_cache[sql_id]) <= 5 else None
        else:
            object_ddl = self.object_ddl_view.toPlainText()

        self.analyze_btn.setEnabled(False)
        self.copy_analyze_btn.setEnabled(False)
        self.llm_progress.setVisible(True)
        self.llm_progress.setValue(10)
        self.llm_output.clear()

        self.llm_output.setPlainText(
            self.tr("Отправка данных в LLM ({model_name})...\n").format(model_name= model['model_name'])
        )
        model = self.model_combo.currentData()
        self.llm_worker = llm_providers.LLMProvider(provider_name = model['provider'],
            model_info = model,
            sql_id = sql_id,
            sql_info = {'sql_text': sql_text, 'plan_text': plan_text, 'object_info': object_info, 'schema_text': object_ddl, 'can_change_query': self.can_change_query_checkbox.isChecked()}
        )
        self.llm_worker.finished.connect(self._llm_finished)
        self.llm_worker.error.connect(self._llm_error)
        self.llm_worker.progress.connect(self._llm_progress)
        self.llm_worker.start()

    def on_copy_analyze(self):
        clipboard = QApplication.clipboard()
        clipboard.setText(self.llm_output.toPlainText())

    def _llm_finished(self, sql_id, response):
        self.llm_cache[sql_id] = response
        self.llm_progress.setVisible(False)
        self.analyze_btn.setEnabled(True)
        self.copy_analyze_btn.setEnabled(True)
        if self._current_sql_id() == sql_id:
            self.llm_output.setMarkdown(response)

    def _llm_error(self, sql_id, msg):
        self.llm_progress.setVisible(False)
        self.analyze_btn.setEnabled(True)
        self.copy_analyze_btn.setEnabled(True)
        if self._current_sql_id() == sql_id:
            self.llm_output.setPlainText(self.tr("Ошибка LLM: {msg}\n\n").format(msg=msg))

    def _llm_progress(self, sql_id, index, msg):
        if self._current_sql_id() == sql_id:
            if index == 0:
                self.llm_output.setPlainText(msg)
            else:
                cursor = self.llm_output.textCursor()
                cursor.movePosition(cursor.MoveOperation.End)
                self.llm_output.setTextCursor(cursor)
                self.llm_output.insertPlainText(msg)


    def _current_sql_id(self):
        rows = self.ash_table.selectionModel().selectedRows()
        if not rows:
            return None
        return self.ash_table.item(rows[0].row(), 0).text()

    def _current_sql_id_hash(self):
        rows = self.ash_table.selectionModel().selectedRows()
        if not rows:
            return None
        return self.ash_table.item(rows[0].row(), 0).text() + '_' + self.ash_table.item(rows[0].row(), 1).text()

    def on_export_all_data_report(self):
        if not self.long_query_results:
            QMessageBox.information(self, self.tr("Экспорт"), self.tr("Нет данных для экспорта"))
            return

        path, _ = QFileDialog.getSaveFileName(
            self, self.tr("Сохранить отчёт"),
            f"oracle_optimization_{datetime.now():%Y%m%d_%H%M%S}.txt",
            "Text files (*.txt);;All files (*)"
        )
        if not path:
            return

        lines = []
        lines.append(self.tr("Oracle Query Optimizer — Отчёт"))
        lines.append(self.tr("Дата: {dt}").format(dt=datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        model = self.model_combo.currentData()
        lines.append(self.tr("Модель LLM: {model_name}").format(model_name=model['model_name']))
        lines.append("=" * 80)

        for i, r in enumerate(self.long_query_results, 1):
            sql_id = r.get("SQL_ID", "")
            plan_hash = r.get("SQL_IDSQL_PLAN_HASH_VALUE", "")
            lines.append(self.tr("\n--- Запрос #{i} ---").format(i=i))
            lines.append(f"SQL_ID: {sql_id}")
            lines.append(f"Plan Hash: {r.get('SQL_PLAN_HASH_VALUE', '')}")
            lines.append(f"Elapsed (est): {r.get('ESTIMATED_ELAPSED_SECONDS', '')} s")
            lines.append(f"Program: {r.get('PROGRAM', '')}")
            lines.append(f"SQL:\n{r.get('SQL_TEXT', '')}")

            if sql_id + '_' + plan_hash in self.plan_cache:
                lines.append(self.tr("\nПлан:") + f"\n{self.plan_cache[sql_id + '_' + plan_hash]}")
            if sql_id in self.object_cache:
                lines.append(self.tr("\nОбъекты:") + f"\n{self.object_cache[sql_id]}")
            if sql_id in self.llm_cache:
                lines.append(self.tr("\nРекомендации LLM:") +f"\n{self.llm_cache[sql_id]}")
            lines.append("-" * 80)

        Path(path).write_text("\n".join(lines), encoding="utf-8")
        QMessageBox.information(self, self.tr("Экспорт"), self.tr("Отчёт сохранён: {path}").format(path=path))

    def on_export_selected_data_report(self):
        if not self.long_query_results:
            QMessageBox.information(self, self.tr("Экспорт"), self.tr("Нет данных для экспорта"))
            return

        rows = self.ash_table.selectionModel().selectedRows()
        if not rows:
            QMessageBox.information(self, self.tr("Экспорт"), self.tr("Нет выделенной записи для экспорта"))
            return

        path, _ = QFileDialog.getSaveFileName(
            self, self.tr("Сохранить отчёт"),
            f"oracle_optimization_{datetime.now():%Y%m%d_%H%M%S}.txt",
            "Text files (*.txt);;All files (*)"
        )
        if not path:
            return

        lines = []
        lines.append(self.tr("Oracle Query Optimizer — Отчёт"))
        lines.append(self.tr("Дата: {dt}").format(dt=datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        model = self.model_combo.currentData()
        lines.append(self.tr("Модель LLM: {model_name}").format(model_name=model['model_name']))
        lines.append("=" * 80)

        row = rows[0].row()
        sql_id = self.ash_table.item(row, 0).text()
        plan_hash = self.ash_table.item(row, 1).text()
        r = self.long_query_results[row]
        lines.append(f"SQL_ID: {sql_id}")
        lines.append(f"Plan Hash: {r.get('SQL_PLAN_HASH_VALUE', '')}")
        lines.append(f"Elapsed (est): {r.get('ESTIMATED_ELAPSED_SECONDS', '')} s")
        lines.append(f"Program: {r.get('PROGRAM', '')}")
        lines.append(f"SQL:\n{r.get('SQL_TEXT', '')}")

        if sql_id + '_' + plan_hash in self.plan_cache:
            lines.append(self.tr("\nПлан:") + f"\n{self.plan_cache[sql_id + '_' + plan_hash]}")
        if sql_id in self.object_cache:
            lines.append(self.tr("\nОбъекты:") + f"\n{self.object_cache[sql_id]}")
        if sql_id in self.llm_cache:
            lines.append(self.tr("\nРекомендации LLM:") +f"\n{self.llm_cache[sql_id]}")
        lines.append("-" * 80)

        Path(path).write_text("\n".join(lines), encoding="utf-8")
        QMessageBox.information(self, self.tr("Экспорт"), self.tr("Отчёт сохранён: {path}").format(path=path))

    def on_about(self):
        QMessageBox.about(
            self,
            self.tr("О программе"),
            self.tr(
                "<h3>Oracle Query Optimizer (Optimus Oracle)</h3>"
                "<p>Поиск тяжёлых запросов в Oracle ASH/AWR и оптимизация "
                "через LLM модели.</p>"
                "<p><b>Возможности:</b></p>"
                "<ul>"
                "<li>Топ-20 тяжёлых запросов из ASH/AWR</li>"
                "<li>Загрузка планов выполнения из AWR</li>"
                "<li>Информация об объектах, индексах, статистике</li>"
                "<li>Рекомендации по оптимизации от LLM</li>"
                "<li>Экспорт отчёта</li>"
                "</ul>"
                "<p><b>Автор: Лисичкин Александр alisichkin@mail.ru.</p>"
            )
        )

    def retranslate_ui(self):
        self.file_menu.setTitle(self.tr("Файл"))
        self.export_all_data_action.setText(self.tr("Экспорт отчёта для всех данных..."))
        self.export_selected_data_action.setText(self.tr("Экспорт отчёта текущей записи..."))
        self.exit_action.setText(self.tr("Выход"))
        if self.language_menu:
            self.language_menu.setTitle(self.tr("Язык"))
        self.help_menu.setTitle(self.tr("Справка"))
        self.about_action.setText(self.tr("О программе"))
        ########################################
        self.ctrl_group.setTitle(self.tr("Управление"))
        self.connect_btn.setText(self.tr("Подключиться к Oracle"))
        if not self.connection_params:
            self.conn_status.setText(self.tr("Статус: не подключено"))
        else:
            self.conn_status.setText(
                    f"Статус: подключено ({self.connection_params['user']})"
                )
        self.llm_models_info.setText(self.tr("Доступно N моделей LLM "))
        if self.models_loaded:
            self.llm_models_info.setText(self.tr("Доступно {length} моделей LLM ").format(length=len(self.models)))
        else:
            self.llm_models_info.setText(self.tr("Ошибка загрузки списка моделей"))
        self.llm_name.setText(self.tr("Модель:"))
        ########################################
        self.long_query_group.setTitle(self.tr("Топ-20 тяжёлых запросов"))
        self.ash_btn.setText(self.tr("Обновить ASH"))
        self.awr_btn.setText(self.tr("Обновить AWR"))
        ########################################
        self.sql_text_view.setPlaceholderText(self.tr("Текст SQL-запроса появится здесь..."))
        self.plan_text_view.setPlaceholderText(self.tr("План выполнения появится здесь..."))
        self.detail_tabs.setTabText(0, self.tr("SQL / План"))
        ########################################
        self.object_info_view.setPlaceholderText(
            self.tr("Информация об объектах (таблицы, индексы, статистика)...")
        )
        self.detail_tabs.setTabText(1, self.tr("Информация об объектах"))
        ########################################
        self.object_ddl_view.setPlaceholderText(
            self.tr("DDL объектов запроса (таблицы, индексы)...")
        )
        self.detail_tabs.setTabText(2, self.tr("DDL объектов запроса"))
        ########################################
        self.analyze_btn.setText(self.tr("Оптимизировать используя LLM"))
        self.copy_analyze_btn.setText(self.tr("Копировать"))
        self.can_change_query_checkbox.setText(self.tr("Предлагать переписывание запроса"))
        self.llm_output.setPlaceholderText(
            self.tr("Рекомендации по оптимизации от LLM появятся здесь...")
        )
        self.detail_tabs.setTabText(3, self.tr("Рекомендации LLM"))

    def changeEvent(self, a0):
        if a0.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(a0)
                            
    def on_language_change(self):
        if not self:
            return
        action: QAction = self.sender() # type: ignore
        locale = action.text()
        path = I18N_DIR / f"translation_{locale}.qm"
        if self.translator_path != str(path):
            QApplication.instance().removeTranslator(self.translator)
            self.translator = QTranslator()
            if self.translator.load(str(path)):
                QApplication.instance().installTranslator(self.translator)
                self.translator_path = str(path)
            for action in self.language_menu.actions():
                if action.text() != locale:
                    action.setChecked(False)
            

def load_translation(app: QApplication, locale: str) -> tuple[QTranslator, str]:
    translator = QTranslator()
    path = I18N_DIR / f"translation_{locale}.qm"
    if not os.path.exists(path) and locale != "ru_RU":
        path = I18N_DIR / f"translation_ru_RU.qm"
    if translator.load(str(path)):
        app.installTranslator(translator)
    return translator, str(path)

# ─────────────────────────────────────────────────────────────────────────────
# Точка входа
# ─────────────────────────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)

    # Also translate Qt's built-in dialogs (Yes/No, file dialogs, etc.)
    qt_translator = QTranslator()
    qt_path = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    if qt_translator.load(f"qtbase_{QLocale.system().name()}", qt_path):
        app.installTranslator(qt_translator)

    locale = QLocale.system().name()
    locale = os.getenv('ORACLE_QUEUE_OPTIMIZER_DEFAULT_LANGUAGE', locale)
    translator, path = load_translation(app, locale)

    app.setApplicationName("Oracle Query Optimizer")
    window = MainWindow(translator, path)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
