from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget
from PySide6.QtCore import Signal, Qt, QMimeData, QTimer
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDropEvent


class DropZone(QWidget):
    files_dropped = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._label = QLabel("将 DOC / DOCX / PDF 文件拖放到此处\n支持同时拖入多个文件")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setWordWrap(True)
        self._label.setObjectName("dropZoneLabel")
        layout.addWidget(self._label)

        self._hover_style = """
            QLabel#dropZoneLabel {
                font-size: 14px;
                color: #e2a84b;
                padding: 48px 20px;
                border: 2px dashed #e2a84b;
                border-radius: 12px;
                background-color: rgba(226, 168, 75, 0.06);
                font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
            }
        """
        self._rejected_style = """
            QLabel#dropZoneLabel {
                font-size: 14px;
                color: #d45858;
                padding: 48px 20px;
                border: 2px dashed #d45858;
                border-radius: 12px;
                background-color: rgba(212, 88, 88, 0.06);
                font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
            }
        """

    def _reset_style(self):
        self._label.setStyleSheet("")  # fall back to global stylesheet

    def dragEnterEvent(self, event: QDragEnterEvent):
        mime: QMimeData = event.mimeData()
        if mime.hasUrls():
            has_valid = any(
                url.toLocalFile().lower().endswith((".doc", ".docx", ".pdf"))
                for url in mime.urls()
            )
            if has_valid:
                event.acceptProposedAction()
                self._label.setStyleSheet(self._hover_style)
            else:
                event.ignore()
                self._label.setStyleSheet(self._rejected_style)
                QTimer.singleShot(1500, self._reset_style)
        else:
            event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent):
        self._reset_style()
        event.accept()

    def dropEvent(self, event: QDropEvent):
        self._reset_style()
        paths = []
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith((".doc", ".docx", ".pdf")):
                paths.append(path)
        if paths:
            self.files_dropped.emit(paths)
