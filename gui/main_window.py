from __future__ import annotations

import os
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core import Glossary, GlossaryEntry, GlossaryError
from models import (
    BookAnalysisConfig,
    ProviderConfig,
    TranslationConfig,
    DEFAULT_ANALYSIS_CHUNK_TOKENS,
    DEFAULT_ANALYSIS_MAX_TERMS,
    DEFAULT_ANALYSIS_MAX_TOKENS,
    DEFAULT_ANALYSIS_MIN_CONFIDENCE,
    DEFAULT_ANALYSIS_TEMPERATURE,
    DEFAULT_CHUNK_TOKENS,
    DEFAULT_MAX_RETRIES,
    DEFAULT_MAX_TOKENS,
    DEFAULT_TARGET_LANGUAGE,
    DEFAULT_TEMPERATURE,
    DEFAULT_TIMEOUT,
)
from providers import PROVIDERS, create_provider
from services import JobCancelled, run_book_analysis_job, run_translation_job


class JobWorker(QObject):
    log = Signal(str)
    progress = Signal(int, int, str)
    analysis_progress = Signal(int, int, int)
    glossary_ready = Signal(object, str)
    completed = Signal(object)
    failed = Signal(str)
    cancelled = Signal(str)
    finished = Signal()

    def __init__(self, config: TranslationConfig, glossary: Glossary | None, mode: str) -> None:
        super().__init__()
        self.config = config
        self.glossary = glossary
        self.mode = mode
        self.cancel_event = threading.Event()

    @Slot()
    def run(self) -> None:
        try:
            if self.mode == "analysis":
                result = run_book_analysis_job(
                    self.config,
                    existing_glossary=self.glossary,
                    log_callback=self.log.emit,
                    progress_callback=self.analysis_progress.emit,
                    cancel_event=self.cancel_event,
                )
            else:
                result = run_translation_job(
                    self.config,
                    glossary_override=self.glossary,
                    log_callback=self.log.emit,
                    progress_callback=self.progress.emit,
                    analysis_progress_callback=self.analysis_progress.emit,
                    cancel_event=self.cancel_event,
                )
            if result.glossary is not None:
                self.glossary_ready.emit(result.glossary, str(result.glossary_path or ""))
            self.completed.emit(result)
        except JobCancelled as exc:
            self.cancelled.emit(str(exc))
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()

    def cancel(self) -> None:
        self.cancel_event.set()


class ModelListWorker(QObject):
    models_ready = Signal(list)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, provider_config: ProviderConfig) -> None:
        super().__init__()
        self.provider_config = provider_config

    @Slot()
    def run(self) -> None:
        try:
            provider = create_provider(
                self.provider_config.name,
                model=self.provider_config.model,
                api_key=self.provider_config.api_key,
                api_key_env=self.provider_config.api_key_env,
                base_url=self.provider_config.base_url,
                timeout=self.provider_config.timeout,
            )
            self.models_ready.emit(provider.list_models())
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Translate EPUB")
        self.resize(1180, 820)
        self._job_thread: QThread | None = None
        self._job_worker: JobWorker | None = None
        self._model_thread: QThread | None = None
        self._glossary_path: Path | None = None
        self._close_after_cancel = False
        self._build_ui()
        self._populate_providers()
        self._provider_changed()

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)

        file_row = QHBoxLayout()
        self.epub_edit = QLineEdit()
        self.epub_edit.setPlaceholderText("Select an EPUB file...")
        browse = QPushButton("Browse...")
        browse.clicked.connect(self._browse_epub)
        file_row.addWidget(QLabel("EPUB"))
        file_row.addWidget(self.epub_edit, 1)
        file_row.addWidget(browse)
        outer.addLayout(file_row)

        splitter = QSplitter()
        outer.addWidget(splitter, 1)

        settings_panel = QWidget()
        settings_layout = QVBoxLayout(settings_panel)
        tabs = QTabWidget()
        tabs.addTab(self._build_provider_tab(), "Provider")
        tabs.addTab(self._build_translation_tab(), "Translation")
        tabs.addTab(self._build_analysis_tab(), "Book Analysis")
        settings_layout.addWidget(tabs)
        settings_layout.addStretch(1)
        splitter.addWidget(settings_panel)

        glossary_panel = QWidget()
        glossary_layout = QVBoxLayout(glossary_panel)
        glossary_layout.addWidget(self._build_glossary_group())
        splitter.addWidget(glossary_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        action_row = QHBoxLayout()
        self.analyze_button = QPushButton("Analyze Book")
        self.analyze_button.clicked.connect(self._start_analysis)
        self.start_button = QPushButton("Start Translation")
        self.start_button.clicked.connect(self._start_translation)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._cancel_job)
        action_row.addWidget(self.analyze_button)
        action_row.addStretch(1)
        action_row.addWidget(self.start_button)
        action_row.addWidget(self.cancel_button)
        outer.addLayout(action_row)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        outer.addWidget(self.progress)
        self.status_label = QLabel("Ready")
        outer.addWidget(self.status_label)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(3000)
        self.log.setPlaceholderText("Job log...")
        outer.addWidget(self.log, 1)

    def _build_provider_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.provider_combo = QComboBox()
        self.provider_combo.currentIndexChanged.connect(self._provider_changed)
        form.addRow("AI provider", self.provider_combo)

        model_row = QWidget()
        model_layout = QHBoxLayout(model_row)
        model_layout.setContentsMargins(0, 0, 0, 0)
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.refresh_models_button = QPushButton("Refresh models")
        self.refresh_models_button.clicked.connect(self._refresh_models)
        model_layout.addWidget(self.model_combo, 1)
        model_layout.addWidget(self.refresh_models_button)
        form.addRow("Model", model_row)

        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setPlaceholderText("Optional when environment variable is already set")
        form.addRow("API key", self.api_key_edit)

        self.api_env_edit = QLineEdit()
        form.addRow("API key env", self.api_env_edit)
        self.base_url_edit = QLineEdit()
        form.addRow("Base URL", self.base_url_edit)
        self.timeout_spin = QDoubleSpinBox()
        self.timeout_spin.setRange(1, 3600)
        self.timeout_spin.setValue(DEFAULT_TIMEOUT)
        self.timeout_spin.setSuffix(" s")
        form.addRow("Timeout", self.timeout_spin)
        return page

    def _build_translation_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.target_edit = QLineEdit(DEFAULT_TARGET_LANGUAGE)
        form.addRow("Target language", self.target_edit)
        self.workers_spin = QSpinBox()
        self.workers_spin.setRange(1, 64)
        self.workers_spin.setValue(4)
        form.addRow("Parallel files", self.workers_spin)
        self.chunk_tokens_spin = QSpinBox()
        self.chunk_tokens_spin.setRange(256, 128000)
        self.chunk_tokens_spin.setValue(DEFAULT_CHUNK_TOKENS)
        self.chunk_tokens_spin.setSingleStep(500)
        form.addRow("Chunk tokens (~)", self.chunk_tokens_spin)
        self.max_tokens_spin = QSpinBox()
        self.max_tokens_spin.setRange(256, 128000)
        self.max_tokens_spin.setValue(DEFAULT_MAX_TOKENS)
        self.max_tokens_spin.setSingleStep(1000)
        form.addRow("Max output tokens", self.max_tokens_spin)
        self.temperature_spin = QDoubleSpinBox()
        self.temperature_spin.setRange(0, 2)
        self.temperature_spin.setDecimals(2)
        self.temperature_spin.setSingleStep(0.05)
        self.temperature_spin.setValue(DEFAULT_TEMPERATURE)
        form.addRow("Temperature", self.temperature_spin)
        self.retries_spin = QSpinBox()
        self.retries_spin.setRange(1, 10)
        self.retries_spin.setValue(DEFAULT_MAX_RETRIES)
        form.addRow("Retries", self.retries_spin)
        return page

    def _build_analysis_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.auto_glossary_check = QCheckBox("Generate/merge glossary before translation")
        form.addRow(self.auto_glossary_check)
        self.analysis_chunk_spin = QSpinBox()
        self.analysis_chunk_spin.setRange(256, 128000)
        self.analysis_chunk_spin.setValue(DEFAULT_ANALYSIS_CHUNK_TOKENS)
        form.addRow("Analysis chunk tokens", self.analysis_chunk_spin)
        self.analysis_max_tokens_spin = QSpinBox()
        self.analysis_max_tokens_spin.setRange(256, 128000)
        self.analysis_max_tokens_spin.setValue(DEFAULT_ANALYSIS_MAX_TOKENS)
        form.addRow("Analysis max output", self.analysis_max_tokens_spin)
        self.analysis_max_terms_spin = QSpinBox()
        self.analysis_max_terms_spin.setRange(1, 5000)
        self.analysis_max_terms_spin.setValue(DEFAULT_ANALYSIS_MAX_TERMS)
        form.addRow("Max glossary terms", self.analysis_max_terms_spin)
        self.analysis_confidence_spin = QDoubleSpinBox()
        self.analysis_confidence_spin.setRange(0, 1)
        self.analysis_confidence_spin.setDecimals(2)
        self.analysis_confidence_spin.setSingleStep(0.05)
        self.analysis_confidence_spin.setValue(DEFAULT_ANALYSIS_MIN_CONFIDENCE)
        form.addRow("Min confidence", self.analysis_confidence_spin)
        self.analysis_temperature_spin = QDoubleSpinBox()
        self.analysis_temperature_spin.setRange(0, 2)
        self.analysis_temperature_spin.setDecimals(2)
        self.analysis_temperature_spin.setValue(DEFAULT_ANALYSIS_TEMPERATURE)
        form.addRow("Analysis temperature", self.analysis_temperature_spin)
        return page

    def _build_glossary_group(self) -> QGroupBox:
        group = QGroupBox("Glossary")
        layout = QVBoxLayout(group)
        self.enforce_glossary_check = QCheckBox("Enforce glossary terminology")
        self.enforce_glossary_check.setChecked(True)
        layout.addWidget(self.enforce_glossary_check)

        self.glossary_table = QTableWidget(0, 7)
        self.glossary_table.setHorizontalHeaderLabels(
            ["Source", "Target", "Category", "Note", "Confidence", "Case", "Whole word"]
        )
        self.glossary_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.glossary_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        header = self.glossary_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.glossary_table, 1)

        row = QHBoxLayout()
        add = QPushButton("Add")
        add.clicked.connect(self._add_glossary_row)
        remove = QPushButton("Remove")
        remove.clicked.connect(self._remove_glossary_rows)
        load = QPushButton("Import JSON")
        load.clicked.connect(self._import_glossary)
        save = QPushButton("Export JSON")
        save.clicked.connect(self._export_glossary)
        row.addWidget(add)
        row.addWidget(remove)
        row.addStretch(1)
        row.addWidget(load)
        row.addWidget(save)
        layout.addLayout(row)
        return group

    def _populate_providers(self) -> None:
        self.provider_combo.clear()
        for name, info in PROVIDERS.items():
            self.provider_combo.addItem(info.display_name, name)
        idx = self.provider_combo.findData("ollama")
        if idx >= 0:
            self.provider_combo.setCurrentIndex(idx)

    @Slot()
    def _provider_changed(self) -> None:
        name = self.provider_combo.currentData()
        if not name:
            return
        info = PROVIDERS[name]
        self.model_combo.clear()
        self.model_combo.addItem(info.default_model)
        self.api_env_edit.setText(info.default_api_key_env or "")
        self.base_url_edit.setText(info.default_base_url or "")
        self.api_key_edit.setEnabled(info.requires_api_key)
        if not info.requires_api_key:
            self.api_key_edit.clear()
        self.workers_spin.setValue(1 if name == "ollama" else 4)

    def _browse_epub(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select EPUB", "", "EPUB files (*.epub)")
        if path:
            self.epub_edit.setText(path)
            if self._glossary_path is None:
                self._glossary_path = Path(path).with_name(f"{Path(path).stem}-glossary.json")

    def _provider_config(self) -> ProviderConfig:
        api_key = self.api_key_edit.text().strip() or None
        return ProviderConfig(
            name=str(self.provider_combo.currentData()),
            model=self.model_combo.currentText().strip() or None,
            api_key=api_key,
            api_key_env=self.api_env_edit.text().strip() or None,
            base_url=self.base_url_edit.text().strip() or None,
            timeout=float(self.timeout_spin.value()),
        )

    def _build_config(self, *, analysis_enabled: bool, analysis_only: bool) -> TranslationConfig:
        epub_text = self.epub_edit.text().strip()
        if not epub_text:
            raise ValueError("Select an EPUB file first.")
        epub_path = Path(epub_text)
        analysis_output = self._glossary_path or epub_path.with_name(f"{epub_path.stem}-glossary.json")
        return TranslationConfig(
            input_epub=epub_path,
            target_language=self.target_edit.text().strip(),
            workers=int(self.workers_spin.value()),
            chunk_tokens=int(self.chunk_tokens_spin.value()),
            max_tokens=int(self.max_tokens_spin.value()),
            temperature=float(self.temperature_spin.value()),
            retries=int(self.retries_spin.value()),
            glossary_path=None,
            enforce_glossary=self.enforce_glossary_check.isChecked(),
            provider=self._provider_config(),
            analysis=BookAnalysisConfig(
                enabled=analysis_enabled,
                analysis_only=analysis_only,
                output_path=analysis_output,
                chunk_tokens=int(self.analysis_chunk_spin.value()),
                max_tokens=int(self.analysis_max_tokens_spin.value()),
                max_terms=int(self.analysis_max_terms_spin.value()),
                min_confidence=float(self.analysis_confidence_spin.value()),
                temperature=float(self.analysis_temperature_spin.value()),
            ),
        )

    def _glossary_from_table(self) -> Glossary | None:
        entries: list[GlossaryEntry] = []
        for row in range(self.glossary_table.rowCount()):
            source = self._cell_text(row, 0).strip()
            target = self._cell_text(row, 1).strip()
            if not source and not target:
                continue
            confidence_text = self._cell_text(row, 4).strip()
            entries.append(
                GlossaryEntry(
                    source=source,
                    target=target,
                    category=self._cell_text(row, 2).strip() or None,
                    note=self._cell_text(row, 3).strip() or None,
                    confidence=float(confidence_text) if confidence_text else None,
                    case_sensitive=self._cell_checked(row, 5),
                    whole_word=self._cell_checked(row, 6, default=True),
                )
            )
        return Glossary(entries) if entries else None

    def _cell_text(self, row: int, col: int) -> str:
        item = self.glossary_table.item(row, col)
        return item.text() if item is not None else ""

    def _cell_checked(self, row: int, col: int, default: bool = False) -> bool:
        item = self.glossary_table.item(row, col)
        return (item.checkState() == Qt.CheckState.Checked) if item is not None else default

    def _set_glossary(self, glossary: Glossary, path: str | None = None) -> None:
        self.glossary_table.setRowCount(0)
        for entry in glossary.entries:
            self._append_glossary_entry(entry)
        if path:
            self._glossary_path = Path(path)
        self.status_label.setText(f"Glossary: {len(glossary)} entries")

    def _append_glossary_entry(self, entry: GlossaryEntry | None = None) -> None:
        entry = entry or GlossaryEntry(source="New term", target="Translation")
        row = self.glossary_table.rowCount()
        self.glossary_table.insertRow(row)
        values = [entry.source, entry.target, entry.category or "", entry.note or "", "" if entry.confidence is None else f"{entry.confidence:.2f}"]
        for col, value in enumerate(values):
            self.glossary_table.setItem(row, col, QTableWidgetItem(value))
        for col, checked in ((5, entry.case_sensitive), (6, entry.whole_word)):
            item = QTableWidgetItem()
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
            self.glossary_table.setItem(row, col, item)

    def _add_glossary_row(self) -> None:
        self._append_glossary_entry()

    def _remove_glossary_rows(self) -> None:
        rows = sorted({index.row() for index in self.glossary_table.selectedIndexes()}, reverse=True)
        for row in rows:
            self.glossary_table.removeRow(row)

    def _import_glossary(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import glossary", "", "JSON files (*.json)")
        if not path:
            return
        try:
            glossary = Glossary.load_json(path)
            self._set_glossary(glossary, path)
        except Exception as exc:
            QMessageBox.critical(self, "Glossary error", str(exc))

    def _export_glossary(self) -> None:
        try:
            glossary = self._glossary_from_table()
            if glossary is None:
                raise GlossaryError("Glossary is empty.")
            default = str(self._glossary_path or Path.cwd() / "glossary.json")
            path, _ = QFileDialog.getSaveFileName(self, "Export glossary", default, "JSON files (*.json)")
            if not path:
                return
            saved = glossary.save_json(path)
            self._glossary_path = saved
            self.status_label.setText(f"Glossary saved: {saved.name}")
        except Exception as exc:
            QMessageBox.critical(self, "Glossary error", str(exc))

    def _start_analysis(self) -> None:
        try:
            config = self._build_config(analysis_enabled=True, analysis_only=True)
            glossary = self._glossary_from_table()
            self._start_job(config, glossary, "analysis")
        except Exception as exc:
            QMessageBox.critical(self, "Cannot start analysis", str(exc))

    def _start_translation(self) -> None:
        try:
            auto = self.auto_glossary_check.isChecked()
            config = self._build_config(analysis_enabled=auto, analysis_only=False)
            glossary = self._glossary_from_table()
            self._start_job(config, glossary, "translation")
        except Exception as exc:
            QMessageBox.critical(self, "Cannot start translation", str(exc))

    def _start_job(self, config: TranslationConfig, glossary: Glossary | None, mode: str) -> None:
        if self._job_thread is not None:
            return
        self.log.clear()
        self.progress.setValue(0)
        self._set_busy(True)
        self.status_label.setText("Running...")

        thread = QThread(self)
        worker = JobWorker(config, glossary, mode)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.log.connect(self._append_log)
        worker.progress.connect(self._on_progress)
        worker.analysis_progress.connect(self._on_analysis_progress)
        worker.glossary_ready.connect(self._set_glossary)
        worker.completed.connect(self._job_completed)
        worker.failed.connect(self._job_failed)
        worker.cancelled.connect(self._job_cancelled)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._job_thread_finished)
        self._job_thread = thread
        self._job_worker = worker
        thread.start()

    @Slot(str)
    def _append_log(self, message: str) -> None:
        self.log.appendPlainText(message)

    @Slot(int, int, str)
    def _on_progress(self, current: int, total: int, path: str) -> None:
        percent = int(current * 100 / total) if total else 0
        self.progress.setValue(percent)
        self.status_label.setText(f"Translation {current}/{total}: {Path(path).name}")

    @Slot(int, int, int)
    def _on_analysis_progress(self, current: int, total: int, candidates: int) -> None:
        percent = int(current * 100 / total) if total else 0
        self.progress.setValue(percent)
        self.status_label.setText(f"Book analysis {current}/{total} - {candidates} candidates")

    @Slot(object)
    def _job_completed(self, result) -> None:
        if result.output_path:
            self.status_label.setText(f"Completed: {result.output_path.name}")
            self.progress.setValue(100)
        elif result.glossary_path:
            self.status_label.setText(f"Glossary ready: {result.glossary_path.name}")
            self.progress.setValue(100)
        if result.failed_files:
            QMessageBox.warning(self, "Completed with failures", "Some files failed. See the log and rerun to retry them.")

    @Slot(str)
    def _job_failed(self, message: str) -> None:
        self.status_label.setText("Failed")
        self._append_log(f"ERROR: {message}")
        QMessageBox.critical(self, "Job failed", message)

    @Slot(str)
    def _job_cancelled(self, message: str) -> None:
        self.status_label.setText("Cancelled")
        self._append_log(message)

    @Slot()
    def _job_thread_finished(self) -> None:
        self._job_thread = None
        self._job_worker = None
        self._set_busy(False)
        if self._close_after_cancel:
            self._close_after_cancel = False
            self.close()

    def _set_busy(self, busy: bool) -> None:
        self.start_button.setEnabled(not busy)
        self.analyze_button.setEnabled(not busy)
        self.refresh_models_button.setEnabled(not busy and self._model_thread is None)
        self.cancel_button.setEnabled(busy)

    def _cancel_job(self) -> None:
        if self._job_worker is not None:
            self.status_label.setText("Cancelling after current API request...")
            self._job_worker.cancel()
            self.cancel_button.setEnabled(False)

    def _refresh_models(self) -> None:
        if self._model_thread is not None:
            return
        try:
            config = self._provider_config()
        except Exception as exc:
            QMessageBox.critical(self, "Provider error", str(exc))
            return
        self.refresh_models_button.setEnabled(False)
        self.status_label.setText("Loading models...")
        thread = QThread(self)
        worker = ModelListWorker(config)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.models_ready.connect(self._models_ready)
        worker.failed.connect(lambda msg: QMessageBox.critical(self, "Model list error", msg))
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._model_thread_finished)
        self._model_thread = thread
        self._model_worker = worker
        thread.start()

    @Slot(list)
    def _models_ready(self, models: list[str]) -> None:
        current = self.model_combo.currentText()
        self.model_combo.clear()
        self.model_combo.addItems(models)
        if current and current not in models:
            self.model_combo.insertItem(0, current)
        if current:
            self.model_combo.setCurrentText(current)
        self.status_label.setText(f"Loaded {len(models)} model(s)")

    @Slot()
    def _model_thread_finished(self) -> None:
        self._model_thread = None
        self._model_worker = None
        self.refresh_models_button.setEnabled(self._job_thread is None)

    def closeEvent(self, event) -> None:
        if self._job_worker is not None:
            answer = QMessageBox.question(self, "Job is running", "Cancel the running job and close?")
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self._close_after_cancel = True
            self._job_worker.cancel()
            self.status_label.setText("Cancelling before close...")
            event.ignore()
            return
        event.accept()
