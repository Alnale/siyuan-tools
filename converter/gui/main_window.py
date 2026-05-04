import os
import logging
import shutil
from datetime import datetime

logger = logging.getLogger(__name__)

from PySide6.QtWidgets import (
    QMainWindow, QToolBar, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFileDialog, QMessageBox, QProgressBar,
    QListWidget, QListWidgetItem, QAbstractItemView, QApplication,
    QRadioButton, QButtonGroup, QSplitter,
)
from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QAction, QColor, QPalette, QShortcut, QKeySequence

from core.converter import PandocConverter
from core.pdf_converter import PdfConverter
from core.doc_to_pdf import DocToPdfConverter
from core.worker import ConversionWorker, BatchWorker, PdfBatchWorker
from core.siyuan_client import SiYuanClient
from core.siyuan_config import load_siyuan_config
from core.siyuan_worker import SiYuanImportWorker, SiYuanBatchImportWorker
from core.temp_manager import temp_manager
from gui.drop_zone import DropZone
from gui.import_dialog import SiYuanImportDialog
from gui.preview_panel import PreviewPanel
from gui.styles import STYLESHEET

_STATUS_PENDING = "待转换"
_STATUS_RUNNING = "转换中..."
_STATUS_DONE = "✓ 完成"
_STATUS_ERROR = "✗ 失败"

# 固定输出目录：siyuan-tools/output/
_OUTPUT_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "output")
)


class MainWindow(QMainWindow):
    def __init__(self, converter: PandocConverter, parent=None):
        super().__init__(parent)
        self._converter = converter
        self._pdf_converter = PdfConverter()
        self._doc_to_pdf = DocToPdfConverter()
        self._worker: BatchWorker | PdfBatchWorker | None = None
        self._current_markdown: str = ""
        self._output_dir: str = ""
        self._output_mode: str = "markdown"  # "markdown" | "pdf"

        # path -> {"markdown": str, "error": str, "media_dir": str, ...}
        self._results: dict[str, dict] = {}

        # 思源笔记集成
        self._siyuan_client: SiYuanClient | None = None
        self._siyuan_import_worker = None
        self._siyuan_batch_worker = None
        self._init_siyuan_client()

        self.setWindowTitle("DOC / DOCX / PDF → Markdown 转换器")
        self.setMinimumSize(960, 620)
        self.resize(1100, 700)
        self.setAcceptDrops(True)
        self._apply_dark_palette()
        self.setStyleSheet(STYLESHEET)

        self._build_toolbar()
        self._build_ui()
        self._build_statusbar()
        self._update_actions(False)

    # ── 全局拖放 ──────────────────────────────────────────────

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.toLocalFile().lower().endswith((".doc", ".docx", ".pdf")):
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event):
        paths = [
            url.toLocalFile()
            for url in event.mimeData().urls()
            if url.toLocalFile().lower().endswith((".doc", ".docx", ".pdf"))
        ]
        if paths:
            self._add_files(paths)

    # ── 暗色调色板 ────────────────────────────────────────────

    def _apply_dark_palette(self):
        palette = QPalette()
        surface = QColor("#161920")
        text = QColor("#c4c7d4")
        accent = QColor("#e2a84b")

        palette.setColor(QPalette.ColorRole.Window, surface)
        palette.setColor(QPalette.ColorRole.WindowText, text)
        palette.setColor(QPalette.ColorRole.Base, QColor("#13151c"))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#1a1e28"))
        palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#1e2230"))
        palette.setColor(QPalette.ColorRole.ToolTipText, text)
        palette.setColor(QPalette.ColorRole.Text, text)
        palette.setColor(QPalette.ColorRole.Button, surface)
        palette.setColor(QPalette.ColorRole.ButtonText, text)
        palette.setColor(QPalette.ColorRole.BrightText, QColor("#ffffff"))
        palette.setColor(QPalette.ColorRole.Link, QColor("#6b8cce"))
        palette.setColor(QPalette.ColorRole.Highlight, accent)
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#0f1117"))
        palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#6b6f80"))
        palette.setColor(QPalette.ColorRole.Light, QColor("#2a2e3a"))
        palette.setColor(QPalette.ColorRole.Midlight, QColor("#232733"))
        palette.setColor(QPalette.ColorRole.Dark, QColor("#0c0e14"))
        palette.setColor(QPalette.ColorRole.Shadow, QColor("#000000"))

        self.setPalette(palette)
        QApplication.instance().setPalette(palette)

    # ── 工具栏 ────────────────────────────────────────────────

    def _build_toolbar(self):
        toolbar = QToolBar("工具栏")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        # 文件管理
        self._open_action = QAction("添加文件", self)
        self._open_action.setShortcut("Ctrl+O")
        self._open_action.triggered.connect(self._on_open_files)
        toolbar.addAction(self._open_action)

        self._clear_action = QAction("清空", self)
        self._clear_action.setShortcut("Ctrl+L")
        self._clear_action.triggered.connect(self._on_clear)
        toolbar.addAction(self._clear_action)

        toolbar.addSeparator()

        # 输出操作
        self._save_action = QAction("保存当前", self)
        self._save_action.setShortcut("Ctrl+S")
        self._save_action.triggered.connect(self._on_save)
        toolbar.addAction(self._save_action)

        self._save_all_action = QAction("全部保存", self)
        self._save_all_action.setShortcut("Ctrl+Shift+S")
        self._save_all_action.triggered.connect(self._on_save_all)
        toolbar.addAction(self._save_all_action)

        self._copy_action = QAction("复制全部", self)
        self._copy_action.setShortcut("Ctrl+Shift+C")
        self._copy_action.setToolTip("复制当前 Markdown 全文到剪贴板")
        self._copy_action.triggered.connect(self._on_copy)
        toolbar.addAction(self._copy_action)

        toolbar.addSeparator()

        # 思源笔记
        self._import_siyuan_action = QAction("导入思源", self)
        self._import_siyuan_action.setShortcut("Ctrl+I")
        self._import_siyuan_action.setToolTip("将当前 Markdown 导入到思源笔记")
        self._import_siyuan_action.triggered.connect(self._on_import_siyuan)
        toolbar.addAction(self._import_siyuan_action)

        self._import_all_siyuan_action = QAction("全部导入思源", self)
        self._import_all_siyuan_action.setShortcut("Ctrl+Shift+I")
        self._import_all_siyuan_action.setToolTip("将所有已转换的 Markdown 批量导入到思源笔记")
        self._import_all_siyuan_action.triggered.connect(self._on_import_all_siyuan)
        toolbar.addAction(self._import_all_siyuan_action)

        self._import_folder_action = QAction("从文件导入思源", self)
        self._import_folder_action.setShortcut("Ctrl+F")
        self._import_folder_action.setToolTip("从历史导出的时间戳文件夹中选择 Markdown 文件导入到思源笔记")
        self._import_folder_action.triggered.connect(self._on_import_from_folder)
        toolbar.addAction(self._import_folder_action)

    # ── 主界面布局 ────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(12)

        # ── 左面板 ──
        left_panel = QWidget()
        left_panel.setMinimumWidth(240)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)

        # 格式切换（始终在顶部）
        format_section = QWidget()
        format_layout = QHBoxLayout(format_section)
        format_layout.setContentsMargins(0, 0, 0, 0)
        format_layout.setSpacing(12)

        format_label = QLabel("输出格式")
        format_label.setObjectName("formatSectionLabel")
        format_layout.addWidget(format_label)

        self._radio_markdown = QRadioButton("Markdown")
        self._radio_pdf = QRadioButton("PDF")
        self._radio_markdown.setChecked(True)
        self._format_group = QButtonGroup(self)
        self._format_group.addButton(self._radio_markdown)
        self._format_group.addButton(self._radio_pdf)
        self._radio_markdown.toggled.connect(self._on_format_changed)
        format_layout.addWidget(self._radio_markdown)
        format_layout.addWidget(self._radio_pdf)
        format_layout.addStretch()

        left_layout.addWidget(format_section)

        # Drop Zone（无文件时显示）
        self._drop_zone = DropZone()
        self._drop_zone.files_dropped.connect(self._on_files_dropped)
        left_layout.addWidget(self._drop_zone)

        # 文件列表区域（有文件时显示）
        self._file_list_widget = QWidget()
        file_list_layout = QVBoxLayout(self._file_list_widget)
        file_list_layout.setContentsMargins(0, 0, 0, 0)
        file_list_layout.setSpacing(6)

        self._file_list_label = QLabel("文件列表")
        self._file_list_label.setObjectName("fileNameLabel")
        file_list_layout.addWidget(self._file_list_label)

        self._file_list = QListWidget()
        self._file_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._file_list.currentItemChanged.connect(self._on_item_changed)
        self._file_list.itemDoubleClicked.connect(self._on_item_double_clicked)
        file_list_layout.addWidget(self._file_list)

        self._file_count_label = QLabel()
        self._file_count_label.setObjectName("fileInfoLabel")
        file_list_layout.addWidget(self._file_count_label)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._add_btn = QPushButton("添加文件")
        self._add_btn.setObjectName("clearButton")
        self._add_btn.clicked.connect(self._on_open_files)
        btn_row.addWidget(self._add_btn)

        self._remove_btn = QPushButton("移除")
        self._remove_btn.setObjectName("clearButton")
        self._remove_btn.clicked.connect(self._on_remove_selected)
        btn_row.addWidget(self._remove_btn)

        file_list_layout.addLayout(btn_row)

        self._convert_btn = QPushButton("全部转换")
        self._convert_btn.setObjectName("convertButton")
        self._convert_btn.setEnabled(False)
        self._convert_btn.clicked.connect(self._start_batch_conversion)
        file_list_layout.addWidget(self._convert_btn)

        self._file_list_widget.setVisible(False)
        left_layout.addWidget(self._file_list_widget)

        left_layout.addStretch()

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 0)
        self._progress_bar.setVisible(False)
        left_layout.addWidget(self._progress_bar)

        # ── 右面板（预览） ──
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self._preview_panel = PreviewPanel()
        right_layout.addWidget(self._preview_panel)

        # ── 可拖拽分割器 ──
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([280, 700])
        main_layout.addWidget(splitter)

        # ── 快捷键 ──
        delete_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Delete), self._file_list)
        delete_shortcut.activated.connect(self._on_remove_selected)

    def _build_statusbar(self):
        self._status_label = QLabel("就绪")
        self.statusBar().addWidget(self._status_label, 1)

    # ── 格式切换 ──────────────────────────────────────────────

    def _on_format_changed(self):
        self._output_mode = "pdf" if self._radio_pdf.isChecked() else "markdown"
        is_pdf = self._output_mode == "pdf"

        if is_pdf:
            current = self._file_list.currentItem()
            if current:
                path = current.data(Qt.ItemDataRole.UserRole)
                r = self._results.get(path)
                if r and r.get("pdf_bytes"):
                    self._preview_panel.set_pdf_bytes(r["pdf_bytes"])
                    # 如果同时有markdown结果，显示所有标签页
                    if r.get("markdown"):
                        self._current_markdown = r["markdown"]
                        media_dir = r.get("media_dir", "")
                        if media_dir:
                            self._preview_panel.set_media_dir(media_dir)
                        self._preview_panel._raw_editor.setPlainText(r["markdown"])
                        html = self._preview_panel._render_html(r["markdown"])
                        self._preview_panel._preview_browser.setHtml(html)
                        self._preview_panel._show_all_tabs(default_pdf=True)
                else:
                    self._preview_panel.set_markdown(
                        "## PDF 输出模式\n\n"
                        "转换完成后单击文件可预览 PDF，\n"
                        "或点击「保存当前」/「全部保存」导出。"
                    )
            else:
                self._preview_panel.set_markdown(
                    "## PDF 输出模式\n\n"
                    "转换完成后单击文件可预览 PDF，\n"
                    "或点击「保存当前」/「全部保存」导出。"
                )
        elif self._current_markdown:
            self._preview_panel.set_markdown(self._current_markdown)
        else:
            self._preview_panel.clear()

        self._copy_action.setEnabled(not is_pdf and bool(self._current_markdown))
        self._import_siyuan_action.setEnabled(
            not is_pdf and bool(self._current_markdown) and self._siyuan_client is not None
        )
        has_batch = any(r.get("markdown") for r in self._results.values())
        self._import_all_siyuan_action.setEnabled(
            not is_pdf and has_batch and self._siyuan_client is not None
        )
        self._update_convert_button_text()

    def _update_actions(self, has_content: bool):
        is_pdf = self._output_mode == "pdf"
        self._save_action.setEnabled(has_content)
        self._save_all_action.setEnabled(has_content)
        self._copy_action.setEnabled(has_content and not is_pdf)
        self._import_siyuan_action.setEnabled(
            has_content and not is_pdf and self._siyuan_client is not None
        )
        has_batch = any(r.get("markdown") for r in self._results.values())
        self._import_all_siyuan_action.setEnabled(
            has_batch and not is_pdf and self._siyuan_client is not None
        )
        self._import_folder_action.setEnabled(self._siyuan_client is not None)

    # ── 工具方法 ──────────────────────────────────────────────

    def _path_to_name(self, path: str) -> str:
        return os.path.basename(path)

    def _format_size(self, size: int) -> str:
        if size < 1024:
            return f"{size} B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        else:
            return f"{size / (1024 * 1024):.1f} MB"

    def _make_timestamp_dir(self) -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        folder_name = f"output_{timestamp}"
        folder_path = os.path.join(_OUTPUT_DIR, folder_name)
        os.makedirs(folder_path, exist_ok=True)
        return folder_path

    def _update_convert_button_text(self):
        count = self._file_list.count()
        if self._output_mode == "pdf":
            self._convert_btn.setText(f"全部转为 PDF ({count})")
        else:
            self._convert_btn.setText(f"全部转换 ({count})")

    def _update_format_options(self):
        """根据文件列表中的文件类型，动态控制PDF选项的显示。"""
        has_doc = False
        has_pdf = False
        for i in range(self._file_list.count()):
            path = self._file_list.item(i).data(Qt.ItemDataRole.UserRole)
            if path.lower().endswith((".doc", ".docx")):
                has_doc = True
            elif path.lower().endswith(".pdf"):
                has_pdf = True

        # 全部是PDF文件时，隐藏PDF选项
        only_pdf = has_pdf and not has_doc
        self._radio_pdf.setVisible(not only_pdf)

        # 如果当前选中PDF模式但被隐藏，自动切换到Markdown
        if only_pdf and self._radio_pdf.isChecked():
            self._radio_markdown.setChecked(True)

    def _copy_media_files(self, src_dir: str, dst_dir: str):
        """复制图片资源目录中的文件到目标目录。"""
        if not os.path.isdir(src_dir):
            return
        for item in os.listdir(src_dir):
            src_path = os.path.join(src_dir, item)
            if os.path.isfile(src_path):
                dst_path = os.path.join(dst_dir, item)
                if not os.path.exists(dst_path):
                    shutil.copy2(src_path, dst_path)

    # ── 文件管理 ──────────────────────────────────────────────

    def _add_files(self, paths: list[str]):
        existing = {self._file_list.item(i).data(Qt.ItemDataRole.UserRole)
                     for i in range(self._file_list.count())}
        added = 0
        for path in paths:
            if not path.lower().endswith((".doc", ".docx", ".pdf")):
                continue
            if path in existing:
                continue
            if not os.path.isfile(path):
                continue

            name = self._path_to_name(path)
            size = self._format_size(os.path.getsize(path))
            item = QListWidgetItem(f"{name}  [{size}]  {_STATUS_PENDING}")
            item.setData(Qt.ItemDataRole.UserRole, path)
            item.setForeground(QColor("#6b6f80"))
            self._file_list.addItem(item)
            self._results[path] = {"markdown": "", "error": ""}
            added += 1

        if added > 0:
            self._file_list_widget.setVisible(True)
            self._drop_zone.setVisible(False)
            self._convert_btn.setEnabled(True)
            self._update_file_count()
            self._update_convert_button_text()
            self._update_format_options()

    def _update_file_count(self):
        total = self._file_list.count()
        done = sum(1 for i in range(total)
                   if _STATUS_DONE in self._file_list.item(i).text())
        err = sum(1 for i in range(total)
                  if _STATUS_ERROR in self._file_list.item(i).text())
        parts = [f"共 {total} 个文件"]
        if done:
            parts.append(f"{done} 个已完成")
        if err:
            parts.append(f"{err} 个失败")
        self._file_count_label.setText(" | ".join(parts))

    def _update_item_status(self, path: str, status: str):
        for i in range(self._file_list.count()):
            item = self._file_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == path:
                name = self._path_to_name(path)
                size = self._format_size(os.path.getsize(path))
                item.setText(f"{name}  [{size}]  {status}")
                if status == _STATUS_DONE:
                    item.setForeground(QColor("#5aad6b"))
                elif status == _STATUS_ERROR:
                    item.setForeground(QColor("#d45858"))
                elif status == _STATUS_RUNNING:
                    item.setForeground(QColor("#e2a84b"))
                else:
                    item.setForeground(QColor("#6b6f80"))
                break

    # ── 文件操作 ──────────────────────────────────────────────

    @Slot(list)
    def _on_files_dropped(self, paths: list[str]):
        self._add_files(paths)

    @Slot()
    def _on_open_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择文件", "",
            "支持的文件 (*.doc *.docx *.pdf);;Word 文档 (*.doc *.docx);;PDF 文档 (*.pdf);;所有文件 (*)"
        )
        if paths:
            self._add_files(paths)

    @Slot()
    def _on_remove_selected(self):
        row = self._file_list.currentRow()
        if row < 0:
            return
        item = self._file_list.item(row)
        path = item.data(Qt.ItemDataRole.UserRole)
        self._results.pop(path, None)
        self._file_list.takeItem(row)
        self._update_file_count()
        self._update_convert_button_text()
        self._update_format_options()

        if self._file_list.count() == 0:
            self._on_clear()

    @Slot(QListWidgetItem, QListWidgetItem)
    def _on_item_changed(self, current: QListWidgetItem, previous: QListWidgetItem):
        if current is None:
            return
        path = current.data(Qt.ItemDataRole.UserRole)
        result = self._results.get(path)
        if result and (result.get("markdown") or result.get("pdf_bytes")):
            self._show_preview(path, result)

    @Slot(QListWidgetItem)
    def _on_item_double_clicked(self, item: QListWidgetItem):
        path = item.data(Qt.ItemDataRole.UserRole)
        result = self._results.get(path)
        if not result:
            return
        if result["error"]:
            QMessageBox.warning(self, "转换错误", result["error"])
            return
        self._show_preview(path, result)

    def _show_preview(self, path: str, result: dict):
        has_pdf = bool(result.get("pdf_bytes"))
        has_md = bool(result.get("markdown"))

        # PDF模式 → 优先显示PDF
        if has_pdf and self._output_mode == "pdf":
            pdf_bytes = result["pdf_bytes"]
            name = self._path_to_name(path)
            size = self._format_size(len(pdf_bytes))
            self._preview_panel.set_pdf_bytes(pdf_bytes)

            # 如果同时有markdown结果，显示所有标签页
            if result.get("markdown"):
                self._current_markdown = result["markdown"]
                media_dir = result.get("media_dir", "")
                if media_dir:
                    self._preview_panel.set_media_dir(media_dir)
                self._preview_panel._raw_editor.setPlainText(result["markdown"])
                html = self._preview_panel._render_html(result["markdown"])
                self._preview_panel._preview_browser.setHtml(html)
                self._preview_panel._show_all_tabs(default_pdf=True)

            self._update_actions(True)
            self._status_label.setText(f"已转换：{name} — {size}")
        elif result.get("markdown"):
            self._current_markdown = result["markdown"]
            media_dir = result.get("media_dir", "")
            if media_dir:
                self._preview_panel.set_media_dir(media_dir)
            self._preview_panel.set_markdown(result["markdown"])
            self._update_actions(True)

            name = self._path_to_name(path)
            char_count = len(result["markdown"])
            line_count = result["markdown"].count("\n") + 1
            self._status_label.setText(f"预览：{name} — {char_count} 字符，{line_count} 行")

    # ── 批量转换 ──────────────────────────────────────────────

    @Slot()
    def _start_batch_conversion(self):
        if self._worker and self._worker.isRunning():
            return

        files = [
            self._file_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self._file_list.count())
        ]
        if not files:
            return

        self._convert_btn.setEnabled(False)
        self._progress_bar.setRange(0, len(files))
        self._progress_bar.setValue(0)
        self._progress_bar.setVisible(True)

        # 清除之前的输出目录（保存时才创建）
        self._output_dir = ""

        if self._output_mode == "pdf":
            self._worker = PdfBatchWorker(
                files, self._doc_to_pdf,
                pdf_converter=self._pdf_converter,
            )
            self._worker.progress.connect(self._on_batch_progress)
            self._worker.file_finished.connect(self._on_pdf_batch_file_finished)
            self._worker.all_done.connect(self._on_batch_all_done)
        else:
            # MD 模式：创建临时目录存放媒体文件
            temp_media_dir = temp_manager.create_temp_dir(prefix="media_")
            self._worker = BatchWorker(
                files, self._converter, self._pdf_converter,
                media_dir=temp_media_dir,
            )
            self._worker.progress.connect(self._on_batch_progress)
            self._worker.file_finished.connect(self._on_batch_file_finished)
            self._worker.all_done.connect(self._on_batch_all_done)

        self._worker.start()

    @Slot(int, int, str)
    def _on_batch_progress(self, current: int, total: int, file_path: str):
        self._progress_bar.setValue(current - 1)
        name = self._path_to_name(file_path)
        self._status_label.setText(f"正在转换 ({current}/{total})：{name}")
        self._update_item_status(file_path, _STATUS_RUNNING)

    @Slot(str, bytes, str, str, str)
    def _on_batch_file_finished(self, path: str, pdf_bytes: bytes, markdown: str, media_dir: str, error: str):
        self._results[path] = {"markdown": markdown, "pdf_bytes": pdf_bytes, "media_dir": media_dir, "error": error}
        if markdown or pdf_bytes:
            self._update_item_status(path, _STATUS_DONE)
        else:
            self._update_item_status(path, _STATUS_ERROR)
        self._update_file_count()

    @Slot(str, bytes, str, str, str)
    def _on_pdf_batch_file_finished(self, path: str, pdf_bytes: bytes, markdown: str, media_dir: str, error: str):
        self._results[path] = {"markdown": markdown, "pdf_bytes": pdf_bytes, "media_dir": media_dir, "error": error}
        if pdf_bytes or markdown:
            self._update_item_status(path, _STATUS_DONE)
        else:
            self._update_item_status(path, _STATUS_ERROR)
        self._update_file_count()

    @Slot()
    def _on_batch_all_done(self):
        self._progress_bar.setVisible(False)
        self._convert_btn.setEnabled(True)
        self._update_convert_button_text()

        if self._output_mode == "pdf":
            done = sum(1 for r in self._results.values() if r.get("pdf_bytes") or r.get("markdown"))
        else:
            done = sum(1 for r in self._results.values() if r.get("markdown") or r.get("pdf_bytes"))
        err = sum(1 for r in self._results.values() if r["error"])
        self._status_label.setText(f"全部转换完成 — {done} 个成功，{err} 个失败")

        if done > 0:
            for i in range(self._file_list.count()):
                item = self._file_list.item(i)
                path = item.data(Qt.ItemDataRole.UserRole)
                r = self._results.get(path)
                if self._output_mode == "pdf":
                    if r and (r.get("pdf_bytes") or r.get("markdown")):
                        self._file_list.setCurrentItem(item)
                        break
                else:
                    if r and (r.get("markdown") or r.get("pdf_bytes")):
                        self._file_list.setCurrentItem(item)
                        break

    # ── 保存 ──────────────────────────────────────────────────

    @Slot()
    def _on_save(self):
        current = self._file_list.currentItem()
        if not current:
            return
        path = current.data(Qt.ItemDataRole.UserRole)
        result = self._results.get(path)
        if not result:
            return

        # 确保时间戳目录已创建
        if not self._output_dir:
            self._output_dir = self._make_timestamp_dir()

        if self._output_mode == "pdf" and result.get("pdf_bytes"):
            # 保存PDF文件
            base = os.path.splitext(self._path_to_name(path))[0]
            pdf_path = os.path.join(self._output_dir, base + ".pdf")
            try:
                with open(pdf_path, "wb") as f:
                    f.write(result["pdf_bytes"])
                saved_files = [pdf_path]
                name = self._path_to_name(path)
                size = self._format_size(len(result["pdf_bytes"]))
                # 标记为已保存
                for saved_file in saved_files:
                    temp_manager.mark_saved(saved_file)
                QMessageBox.information(
                    self, "已保存",
                    f"文件：{name}\n大小：{size}\n路径：\n{pdf_path}"
                )
                self._status_label.setText(f"已保存：{pdf_path}")
            except Exception as e:
                QMessageBox.critical(self, "保存失败", f"无法保存文件：\n\n{e}")
        elif self._current_markdown:
            base = os.path.splitext(self._path_to_name(path))[0]
            try:
                ts_dir = self._output_dir or self._make_timestamp_dir()
                if not self._output_dir:
                    self._output_dir = ts_dir
                save_path = os.path.join(ts_dir, base + ".md")
                with open(save_path, "w", encoding="utf-8") as f:
                    f.write(self._current_markdown)
                # 复制图片资源
                media_dir = result.get("media_dir", "")
                if media_dir and os.path.isdir(media_dir):
                    self._copy_media_files(media_dir, ts_dir)
                saved_files = [save_path]
                # 标记为已保存
                for saved_file in saved_files:
                    temp_manager.mark_saved(saved_file)
                self._status_label.setText(f"已保存：{', '.join(saved_files)}")
            except Exception as e:
                QMessageBox.critical(self, "保存失败", f"无法保存文件：\n\n{e}")

    @Slot()
    def _on_save_all(self):
        if self._output_mode == "pdf":
            self._save_all_pdf()
        else:
            self._save_all_markdown()

    def _save_all_markdown(self):
        done_results = {p: r for p, r in self._results.items() if r["markdown"]}
        if not done_results:
            QMessageBox.information(self, "无可保存内容", "没有已成功转换的文件。")
            return

        ts_dir = self._output_dir or self._make_timestamp_dir()
        if not self._output_dir:
            self._output_dir = ts_dir

        saved = 0
        saved_files = []
        errors = []
        for path, result in done_results.items():
            base = os.path.splitext(self._path_to_name(path))[0]
            out_path = os.path.join(ts_dir, base + ".md")
            try:
                with open(out_path, "w", encoding="utf-8") as f:
                    f.write(result["markdown"])
                # 复制图片资源
                media_dir = result.get("media_dir", "")
                if media_dir and os.path.isdir(media_dir):
                    self._copy_media_files(media_dir, ts_dir)
                saved_files.append(out_path)
                saved += 1
            except Exception as e:
                errors.append(f"{base}: {e}")

        # 标记所有保存的文件
        for saved_file in saved_files:
            temp_manager.mark_saved(saved_file)

        msg = f"已保存 {saved} 个文件到：\n{ts_dir}"
        if errors:
            msg += f"\n\n失败 {len(errors)} 个：\n" + "\n".join(errors)
            QMessageBox.warning(self, "批量保存完成", msg)
        else:
            QMessageBox.information(self, "批量保存完成", msg)

        self._status_label.setText(f"已保存 {saved} 个文件")

    def _save_all_pdf(self):
        done_results = {p: r for p, r in self._results.items() if r.get("pdf_bytes")}
        if not done_results:
            QMessageBox.information(self, "无可保存内容", "没有已成功转换的文件。")
            return

        # 确保时间戳目录已创建
        if not self._output_dir:
            self._output_dir = self._make_timestamp_dir()

        saved = 0
        saved_files = []
        errors = []
        for path, result in done_results.items():
            base = os.path.splitext(self._path_to_name(path))[0]
            out_path = os.path.join(self._output_dir, base + ".pdf")
            try:
                with open(out_path, "wb") as f:
                    f.write(result["pdf_bytes"])
                saved_files.append(out_path)
                saved += 1
            except Exception as e:
                errors.append(f"{base}: {e}")

        # 标记所有保存的文件
        for saved_file in saved_files:
            temp_manager.mark_saved(saved_file)

        msg = f"已保存 {saved} 个 PDF 到：\n{self._output_dir}"
        if errors:
            msg += f"\n\n失败 {len(errors)} 个：\n" + "\n".join(errors)
            QMessageBox.warning(self, "批量保存完成", msg)
        else:
            QMessageBox.information(self, "批量保存完成", msg)

        self._status_label.setText(f"已保存 {saved} 个文件")

    @Slot()
    def _on_copy(self):
        if self._current_markdown:
            QApplication.clipboard().setText(self._current_markdown)
            self._status_label.setText("已复制到剪贴板")

    @Slot()
    def _on_clear(self):
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait()

        self._current_markdown = ""
        self._results.clear()
        self._output_dir = ""

        self._file_list.clear()
        self._file_list_widget.setVisible(False)
        self._drop_zone.setVisible(True)
        self._preview_panel.clear()
        self._update_actions(False)
        self._convert_btn.setEnabled(False)
        self._update_convert_button_text()
        self._progress_bar.setVisible(False)
        self._status_label.setText("就绪")

    # ── 思源笔记导入 ──────────────────────────────────────────

    def _init_siyuan_client(self):
        try:
            config = load_siyuan_config()
            if config.token:
                self._siyuan_client = SiYuanClient(config)
        except Exception as e:
            logger.warning("初始化思源客户端失败: %s", e)
            self._siyuan_client = None

    @Slot()
    def _on_import_siyuan(self):
        if not self._current_markdown or not self._siyuan_client:
            return

        current = self._file_list.currentItem()
        media_dir = ""
        if current:
            path = current.data(Qt.ItemDataRole.UserRole)
            doc_name = os.path.splitext(self._path_to_name(path))[0]
            result = self._results.get(path, {})
            media_dir = result.get("media_dir", "")
        else:
            doc_name = "未命名文档"

        config = load_siyuan_config()
        doc_path = f"{config.default_path}/{doc_name}" if config.default_path else f"/{doc_name}"

        self._import_siyuan_action.setEnabled(False)
        self._status_label.setText(f"正在导入到思源笔记：{doc_name}...")

        self._siyuan_import_worker = SiYuanImportWorker(
            self._siyuan_client,
            config.default_notebook,
            doc_path,
            self._current_markdown,
            media_dir=media_dir,
        )
        self._siyuan_import_worker.finished.connect(self._on_siyuan_import_done)
        self._siyuan_import_worker.status.connect(
            lambda msg: self._status_label.setText(msg)
        )
        self._siyuan_import_worker.start()

    def _on_siyuan_import_done(self, doc_id: str, error: str):
        self._import_siyuan_action.setEnabled(
            self._siyuan_client is not None and bool(self._current_markdown)
        )

        if error:
            self._status_label.setText(f"导入失败：{error}")
            QMessageBox.critical(
                self, "导入失败",
                f"无法导入到思源笔记：\n\n{error}\n\n"
                f"请确保思源笔记已启动，且 API 地址和令牌正确。"
            )
        else:
            self._status_label.setText(f"已导入到思源笔记（文档 ID: {doc_id}）")

    @Slot()
    def _on_import_all_siyuan(self):
        done_results = [
            (self._path_to_name(p), r["markdown"], r.get("media_dir", ""))
            for p, r in self._results.items() if r["markdown"]
        ]
        if not done_results or not self._siyuan_client:
            return

        clean_results = [
            (os.path.splitext(name)[0], md) for name, md, _ in done_results
        ]
        media_dirs = {
            os.path.splitext(name)[0]: mdir
            for name, _, mdir in done_results if mdir
        }

        config = load_siyuan_config()

        reply = QMessageBox.question(
            self, "批量导入确认",
            f"即将导入 {len(clean_results)} 个文档到思源笔记。\n"
            f"目标路径：{config.default_path}\n\n"
            f"是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._import_all_siyuan_action.setEnabled(False)
        self._import_siyuan_action.setEnabled(False)
        self._progress_bar.setRange(0, len(clean_results))
        self._progress_bar.setValue(0)
        self._progress_bar.setVisible(True)

        self._siyuan_batch_worker = SiYuanBatchImportWorker(
            self._siyuan_client,
            config.default_notebook,
            config.default_path,
            clean_results,
            media_dirs=media_dirs,
        )
        self._siyuan_batch_worker.progress.connect(self._on_siyuan_batch_progress)
        self._siyuan_batch_worker.file_finished.connect(self._on_siyuan_batch_file_done)
        self._siyuan_batch_worker.all_done.connect(self._on_siyuan_batch_all_done)
        self._siyuan_batch_worker.start()

    def _on_siyuan_batch_progress(self, current: int, total: int, name: str):
        self._progress_bar.setValue(current - 1)
        self._status_label.setText(f"正在导入到思源 ({current}/{total})：{name}")

    def _on_siyuan_batch_file_done(self, name: str, doc_id: str, error: str):
        if error:
            self._status_label.setText(f"导入失败：{name} — {error}")

    def _on_siyuan_batch_all_done(self, success: int, fail: int):
        self._progress_bar.setVisible(False)
        self._import_all_siyuan_action.setEnabled(True)
        self._import_siyuan_action.setEnabled(bool(self._current_markdown))

        self._status_label.setText(f"思源导入完成 — {success} 个成功，{fail} 个失败")

        if fail > 0:
            QMessageBox.warning(
                self, "批量导入完成",
                f"成功导入 {success} 个文档，{fail} 个失败。\n\n"
                f"请检查思源笔记是否已启动。"
            )
        else:
            QMessageBox.information(
                self, "批量导入完成",
                f"已成功导入 {success} 个文档到思源笔记。"
            )

    # ── 从时间戳文件夹导入 ────────────────────────────────────

    @Slot()
    def _on_import_from_folder(self):
        if not self._siyuan_client:
            QMessageBox.warning(
                self, "思源笔记未连接",
                "无法连接到思源笔记，请检查配置和 API 令牌。"
            )
            return

        if not os.path.isdir(_OUTPUT_DIR):
            QMessageBox.information(
                self, "暂无导出记录",
                "尚未导出任何文件。\n"
                f"导出目录：{_OUTPUT_DIR}"
            )
            return

        config = load_siyuan_config()

        dialog = SiYuanImportDialog(
            base_dir=_OUTPUT_DIR,
            client=self._siyuan_client,
            default_notebook=config.default_notebook,
            parent=self,
        )
        if dialog.exec() != SiYuanImportDialog.DialogCode.Accepted:
            return

        selected_files = dialog.get_selected_files()
        notebook_id = dialog.get_notebook_id()

        if not selected_files or not notebook_id:
            return

        documents = [(name, content) for name, content, _ in selected_files]
        media_dirs = {name: file_dir for name, _, file_dir in selected_files}

        self._import_folder_action.setEnabled(False)
        self._progress_bar.setRange(0, len(documents))
        self._progress_bar.setValue(0)
        self._progress_bar.setVisible(True)

        self._siyuan_batch_worker = SiYuanBatchImportWorker(
            self._siyuan_client,
            notebook_id,
            config.default_path,
            documents,
            media_dirs=media_dirs,
        )
        self._siyuan_batch_worker.progress.connect(self._on_siyuan_batch_progress)
        self._siyuan_batch_worker.file_finished.connect(self._on_siyuan_batch_file_done)
        self._siyuan_batch_worker.all_done.connect(self._on_folder_import_all_done)
        self._siyuan_batch_worker.start()

    def _on_folder_import_all_done(self, success: int, fail: int):
        self._progress_bar.setVisible(False)
        self._import_folder_action.setEnabled(True)

        self._status_label.setText(f"文件夹导入完成 — {success} 个成功，{fail} 个失败")

        if fail > 0:
            QMessageBox.warning(
                self, "导入完成",
                f"成功导入 {success} 个文档，{fail} 个失败。"
            )
        else:
            QMessageBox.information(
                self, "导入完成",
                f"已成功导入 {success} 个文档到思源笔记。"
            )
