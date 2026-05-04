"""从时间戳文件夹选择 Markdown 文件导入思源笔记的对话框"""

import logging
import os

logger = logging.getLogger(__name__)

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QListWidget, QListWidgetItem, QAbstractItemView, QPushButton,
    QDialogButtonBox, QMessageBox, QWidget,
)
from PySide6.QtCore import Qt

from core.siyuan_client import SiYuanClient


class SiYuanImportDialog(QDialog):
    """扫描 output_* 时间戳文件夹，让用户选择 .md 文件导入思源笔记。"""

    def __init__(self, base_dir: str, client: SiYuanClient,
                 default_notebook: str = "", parent=None):
        super().__init__(parent)
        self._base_dir = base_dir
        self._client = client
        self._default_notebook = default_notebook
        self._folders: list[str] = []  # 时间戳文件夹名列表

        self.setWindowTitle("从文件夹导入到思源笔记")
        self.setMinimumSize(560, 480)
        self._build_ui()
        self._load_folders()
        self._load_notebooks()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # ── 时间戳文件夹选择 ──
        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("时间戳文件夹："))
        self._folder_combo = QComboBox()
        self._folder_combo.currentIndexChanged.connect(self._on_folder_changed)
        folder_row.addWidget(self._folder_combo, 1)
        layout.addLayout(folder_row)

        # ── 文件列表 ──
        list_header = QHBoxLayout()
        list_header.addWidget(QLabel("Markdown 文件："))
        list_header.addStretch()
        self._select_all_btn = QPushButton("全选")
        self._select_all_btn.setFixedWidth(60)
        self._select_all_btn.clicked.connect(self._select_all)
        list_header.addWidget(self._select_all_btn)
        self._deselect_all_btn = QPushButton("取消")
        self._deselect_all_btn.setFixedWidth(60)
        self._deselect_all_btn.clicked.connect(self._deselect_all)
        list_header.addWidget(self._deselect_all_btn)
        layout.addLayout(list_header)

        self._file_list = QListWidget()
        self._file_list.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection
        )
        layout.addWidget(self._file_list, 1)

        self._file_count_label = QLabel()
        layout.addWidget(self._file_count_label)

        # ── 笔记本选择 ──
        nb_row = QHBoxLayout()
        nb_row.addWidget(QLabel("目标笔记本："))
        self._notebook_combo = QComboBox()
        nb_row.addWidget(self._notebook_combo, 1)
        layout.addLayout(nb_row)

        # ── 确认/取消 ──
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _load_folders(self):
        """扫描 base_dir 下所有 output_* 子文件夹，按时间倒序排列。"""
        self._folder_combo.blockSignals(True)
        self._folder_combo.clear()
        self._folders.clear()

        if not os.path.isdir(self._base_dir):
            self._folder_combo.blockSignals(False)
            self._on_folder_changed()
            return

        dirs = []
        for name in os.listdir(self._base_dir):
            full = os.path.join(self._base_dir, name)
            if os.path.isdir(full) and name.startswith("output_"):
                dirs.append(name)

        dirs.sort(reverse=True)
        self._folders = dirs

        for d in dirs:
            # 显示更友好的名称：output_20260503_143022 → 2026-05-03 14:30:22
            display = d
            parts = d.split("_", 1)
            if len(parts) == 2 and len(parts[1]) == 15:
                ts = parts[1]
                try:
                    display = f"{ts[:4]}-{ts[4:6]}-{ts[6:8]} {ts[9:11]}:{ts[11:13]}:{ts[13:15]}"
                except (IndexError, ValueError):
                    display = d
            self._folder_combo.addItem(display, d)

        self._folder_combo.blockSignals(False)
        self._on_folder_changed()

    def _on_folder_changed(self):
        """切换时间戳文件夹时重新加载 .md 文件列表。"""
        self._file_list.clear()

        idx = self._folder_combo.currentIndex()
        if idx < 0 or idx >= len(self._folders):
            self._file_count_label.setText("未选择文件夹")
            return

        folder_name = self._folders[idx]
        folder_path = os.path.join(self._base_dir, folder_name)

        if not os.path.isdir(folder_path):
            self._file_count_label.setText("文件夹不存在")
            return

        md_files = sorted(
            f for f in os.listdir(folder_path)
            if f.lower().endswith(".md") and os.path.isfile(os.path.join(folder_path, f))
        )

        for f in md_files:
            item = QListWidgetItem(f)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, os.path.join(folder_path, f))
            self._file_list.addItem(item)

        total = len(md_files)
        self._file_count_label.setText(f"共 {total} 个文件")

    def _select_all(self):
        for i in range(self._file_list.count()):
            self._file_list.item(i).setCheckState(Qt.CheckState.Checked)

    def _deselect_all(self):
        for i in range(self._file_list.count()):
            self._file_list.item(i).setCheckState(Qt.CheckState.Unchecked)

    def _load_notebooks(self):
        """从 SiYuan API 获取笔记本列表。"""
        self._notebook_combo.clear()
        try:
            notebooks = self._client.list_notebooks()
            for nb in notebooks:
                name = nb.get("name", "未命名")
                nb_id = nb.get("id", "")
                self._notebook_combo.addItem(name, nb_id)
                if nb_id == self._default_notebook:
                    self._notebook_combo.setCurrentIndex(
                        self._notebook_combo.count() - 1
                    )
        except Exception as e:
            logger.warning("获取笔记本列表失败: %s", e)
            self._notebook_combo.addItem("（获取笔记本失败）", "")

    def _on_accept(self):
        """检查是否有选中文件，然后接受对话框。"""
        selected = self.get_selected_files()
        if not selected:
            QMessageBox.information(self, "提示", "请至少选择一个文件。")
            return
        if not self.get_notebook_id():
            QMessageBox.warning(self, "提示", "请选择目标笔记本。")
            return
        self.accept()

    def get_selected_files(self) -> list[tuple[str, str, str]]:
        """返回选中的 (文件名不含扩展名, 文件内容, 文件所在目录) 列表。"""
        result = []
        for i in range(self._file_list.count()):
            item = self._file_list.item(i)
            if item.checkState() != Qt.CheckState.Checked:
                continue
            file_path = item.data(Qt.ItemDataRole.UserRole)
            name = os.path.splitext(item.text())[0]
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
                file_dir = os.path.dirname(file_path)
                result.append((name, content, file_dir))
            except Exception as e:
                logger.warning("读取文件失败 %s: %s", file_path, e)
                continue
        return result

    def get_notebook_id(self) -> str:
        """返回选中的笔记本 ID。"""
        return self._notebook_combo.currentData() or ""
