import os

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTabWidget, QTextBrowser, QPlainTextEdit,
    QScrollArea, QLabel, QSizePolicy, QPushButton, QApplication,
)
from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QFont, QColor, QPalette, QPixmap, QImage, QWheelEvent

import pymupdf
import markdown

from gui.markdown_highlighter import MarkdownHighlighter


class ShiftWheelHorizontalScrollMixin:
    """按住SHIFT键时，滚轮事件转换为水平滚动。"""

    def wheelEvent(self, event: QWheelEvent):
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            # 创建水平滚动事件
            horizontal_event = QWheelEvent(
                event.position(),
                event.globalPosition(),
                event.pixelDelta(),
                event.angleDelta() if hasattr(event, 'angleDelta') else event.delta(),
                event.buttons(),
                event.modifiers() & ~Qt.KeyboardModifier.ShiftModifier,
                event.phase(),
                event.inverted(),
                event.source(),
            )
            # 发送给水平滚动条
            if hasattr(self, 'horizontalScrollBar'):
                scrollbar = self.horizontalScrollBar()
                if scrollbar:
                    delta = event.angleDelta().y() if hasattr(event, 'angleDelta') else event.delta()
                    scrollbar.setValue(scrollbar.value() - delta)
                    event.accept()
                    return
        super().wheelEvent(event)


class ScrollableTextBrowser(ShiftWheelHorizontalScrollMixin, QTextBrowser):
    pass


class ScrollablePlainTextEdit(ShiftWheelHorizontalScrollMixin, QPlainTextEdit):
    pass


class ScrollableScrollArea(ShiftWheelHorizontalScrollMixin, QScrollArea):
    pass

_TAB_PREVIEW = 0
_TAB_RAW = 1
_TAB_PDF = 2

_PREVIEW_CSS = """
body {
    font-family: "Microsoft YaHei", "PingFang SC", "Segoe UI", sans-serif;
    font-size: 14px;
    line-height: 1.75;
    color: #c4c7d4;
    padding: 16px 20px;
    background-color: #13151c;
}
h1, h2, h3, h4, h5, h6 {
    color: #e8eaf0;
    margin-top: 1.4em;
    margin-bottom: 0.5em;
    font-weight: 600;
}
h1 {
    font-size: 1.8em;
    border-bottom: 2px solid #232733;
    padding-bottom: 0.35em;
}
h2 {
    font-size: 1.5em;
    border-bottom: 1px solid #232733;
    padding-bottom: 0.25em;
}
h3 { font-size: 1.25em; }
code {
    font-family: "Cascadia Code", "Consolas", "Courier New", monospace;
    background-color: #1a1e28;
    padding: 2px 6px;
    border-radius: 4px;
    font-size: 0.88em;
    color: #e2a84b;
}
pre {
    background-color: #1a1e28;
    border: 1px solid #232733;
    border-radius: 8px;
    padding: 14px 16px;
    overflow-x: auto;
}
pre code {
    background: none;
    padding: 0;
    color: #c4c7d4;
}
blockquote {
    border-left: 4px solid #e2a84b;
    margin: 1em 0;
    padding: 0.6em 1.2em;
    color: #8b8fa3;
    background-color: rgba(226, 168, 75, 0.04);
    border-radius: 0 6px 6px 0;
}
table {
    border-collapse: collapse;
    width: 100%;
    margin: 1em 0;
}
th, td {
    border: 1px solid #2a2e3a;
    padding: 9px 14px;
    text-align: left;
}
th {
    background-color: #1a1e28;
    font-weight: bold;
    color: #e8eaf0;
}
tr:nth-child(even) {
    background-color: rgba(255, 255, 255, 0.015);
}
a {
    color: #6b8cce;
    text-decoration: none;
}
a:hover {
    color: #8baae6;
    text-decoration: underline;
}
img {
    max-width: 100%;
    height: auto;
    border-radius: 6px;
}
hr {
    border: none;
    border-top: 1px solid #2a2e3a;
    margin: 1.8em 0;
}
ul, ol {
    padding-left: 2em;
}
li {
    margin-bottom: 0.35em;
}
strong {
    color: #e8eaf0;
}
em {
    color: #9b9fb0;
}
"""


class PreviewPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._media_dir: str = ""
        self._pdf_doc = None
        self._pdf_rendered_count = 0
        self._pdf_total_pages = 0
        self._PDF_BATCH = 10

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._tabs = QTabWidget()
        layout.addWidget(self._tabs)

        # Preview browser
        self._preview_browser = ScrollableTextBrowser()
        self._preview_browser.setOpenExternalLinks(True)
        palette = self._preview_browser.palette()
        palette.setColor(QPalette.ColorRole.Base, QColor("#13151c"))
        palette.setColor(QPalette.ColorRole.Text, QColor("#c4c7d4"))
        self._preview_browser.setPalette(palette)
        self._tabs.addTab(self._preview_browser, "预览")

        # Raw markdown editor
        self._raw_editor = ScrollablePlainTextEdit()
        self._raw_editor.setReadOnly(True)
        font = QFont("Cascadia Code", 12)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self._raw_editor.setFont(font)
        self._raw_editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        editor_palette = self._raw_editor.palette()
        editor_palette.setColor(QPalette.ColorRole.Base, QColor("#0f1117"))
        editor_palette.setColor(QPalette.ColorRole.Text, QColor("#c4c7d4"))
        self._raw_editor.setPalette(editor_palette)
        self._highlighter = MarkdownHighlighter(self._raw_editor.document())
        self._tabs.addTab(self._raw_editor, "原始 Markdown")

        # PDF preview tab
        self._pdf_scroll = ScrollableScrollArea()
        self._pdf_scroll.setWidgetResizable(True)
        self._pdf_scroll.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        pdf_palette = self._pdf_scroll.palette()
        pdf_palette.setColor(QPalette.ColorRole.Base, QColor("#13151c"))
        self._pdf_scroll.setPalette(pdf_palette)

        self._pdf_container = QWidget()
        self._pdf_layout = QVBoxLayout(self._pdf_container)
        self._pdf_layout.setContentsMargins(16, 12, 16, 12)
        self._pdf_layout.setSpacing(8)
        self._pdf_scroll.setWidget(self._pdf_container)

        self._tabs.addTab(self._pdf_scroll, "PDF 预览")

        # Hide PDF tab by default
        self._pdf_scroll.setVisible(False)
        self._tabs.setTabVisible(_TAB_PDF, False)

    def set_media_dir(self, media_dir: str):
        self._media_dir = media_dir

    def set_markdown(self, content: str):
        self._raw_editor.setPlainText(content)
        if self._media_dir and os.path.isdir(self._media_dir):
            paths = [self._media_dir]
            media_sub = os.path.join(self._media_dir, "media")
            if os.path.isdir(media_sub):
                paths.append(media_sub)
            self._preview_browser.setSearchPaths(paths)
        html = self._render_html(content)
        self._preview_browser.setHtml(html)
        self._show_markdown_tabs()

    def set_pdf(self, pdf_path: str):
        self._clear_pdf_pages()
        try:
            self._pdf_doc = pymupdf.open(pdf_path)
            self._pdf_total_pages = len(self._pdf_doc)
            self._pdf_rendered_count = 0
            self._render_pdf_batch()
            self._show_pdf_tab()
        except Exception as e:
            err_label = QLabel(f"PDF 预览加载失败：{e}")
            err_label.setStyleSheet("color: #e25555; font-size: 13px; padding: 20px;")
            err_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._pdf_layout.addWidget(err_label)
            self._show_pdf_tab()

    def set_pdf_bytes(self, pdf_bytes: bytes):
        """从内存中的bytes加载PDF进行预览。"""
        self._clear_pdf_pages()
        try:
            self._pdf_doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
            self._pdf_total_pages = len(self._pdf_doc)
            self._pdf_rendered_count = 0
            self._render_pdf_batch()
            self._show_pdf_tab()
        except Exception as e:
            err_label = QLabel(f"PDF 预览加载失败：{e}")
            err_label.setStyleSheet("color: #e25555; font-size: 13px; padding: 20px;")
            err_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._pdf_layout.addWidget(err_label)
            self._show_pdf_tab()

    def _render_pdf_batch(self):
        start = self._pdf_rendered_count
        end = min(start + self._PDF_BATCH, self._pdf_total_pages)

        # Remove "load more" button if present
        if hasattr(self, '_load_more_btn') and self._load_more_btn:
            self._pdf_layout.removeWidget(self._load_more_btn)
            self._load_more_btn.deleteLater()
            self._load_more_btn = None

        # 高 DPI 适配：根据设备像素比提升渲染精度
        dpr = QApplication.primaryScreen().devicePixelRatio() if QApplication.primaryScreen() else 1.0
        render_dpi = int(200 * dpr)

        for i in range(start, end):
            page = self._pdf_doc[i]
            pix = page.get_pixmap(dpi=render_dpi)
            img = QImage(
                pix.samples, pix.width, pix.height,
                pix.stride, QImage.Format.Format_RGB888,
            )
            pixmap = QPixmap.fromImage(img)
            pixmap.setDevicePixelRatio(dpr)

            label = QLabel()
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setPixmap(pixmap)
            label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self._pdf_layout.addWidget(label)

            if i < self._pdf_total_pages - 1:
                sep = QLabel(f"── 第 {i + 1} 页 ──")
                sep.setObjectName("pdfPageSeparator")
                sep.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self._pdf_layout.addWidget(sep)

        self._pdf_rendered_count = end

        if self._pdf_rendered_count < self._pdf_total_pages:
            self._load_more_btn = QPushButton(
                f"加载更多页面 ({self._pdf_rendered_count}/{self._pdf_total_pages})"
            )
            self._load_more_btn.setObjectName("clearButton")
            self._load_more_btn.clicked.connect(self._on_load_more_pages)
            self._pdf_layout.addWidget(self._load_more_btn)
        else:
            self._close_pdf_doc()

    def _on_load_more_pages(self):
        self._render_pdf_batch()

    def _close_pdf_doc(self):
        if self._pdf_doc:
            self._pdf_doc.close()
            self._pdf_doc = None

    def _clear_pdf_pages(self):
        while self._pdf_layout.count():
            item = self._pdf_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self._close_pdf_doc()
        self._pdf_rendered_count = 0
        self._pdf_total_pages = 0
        if hasattr(self, '_load_more_btn'):
            self._load_more_btn = None

    def _show_markdown_tabs(self):
        self._tabs.setTabVisible(_TAB_PREVIEW, True)
        self._tabs.setTabVisible(_TAB_RAW, True)
        self._tabs.setTabVisible(_TAB_PDF, False)
        self._tabs.setCurrentIndex(_TAB_PREVIEW)

    def _show_pdf_tab(self):
        self._tabs.setTabVisible(_TAB_PREVIEW, False)
        self._tabs.setTabVisible(_TAB_RAW, False)
        self._tabs.setTabVisible(_TAB_PDF, True)
        self._tabs.setCurrentIndex(_TAB_PDF)

    def _show_all_tabs(self, default_pdf: bool = True):
        """同时显示PDF和Markdown标签页。"""
        self._tabs.setTabVisible(_TAB_PREVIEW, True)
        self._tabs.setTabVisible(_TAB_RAW, True)
        self._tabs.setTabVisible(_TAB_PDF, True)
        if default_pdf:
            self._tabs.setCurrentIndex(_TAB_PDF)
        else:
            self._tabs.setCurrentIndex(_TAB_PREVIEW)

    def get_markdown(self) -> str:
        return self._raw_editor.toPlainText()

    def _render_html(self, md_text: str) -> str:
        extensions = ["tables", "fenced_code", "codehilite", "toc", "attr_list", "md_in_html"]
        html_body = markdown.markdown(md_text, extensions=extensions)
        return f"<style>{_PREVIEW_CSS}</style><body>{html_body}</body>"

    def clear(self):
        self._preview_browser.clear()
        self._raw_editor.clear()
        self._clear_pdf_pages()
        self._show_markdown_tabs()
        self._media_dir = ""
