import os
import shutil

from PySide6.QtCore import QThread, Signal

from core.converter import PandocConverter
from core.pdf_converter import PdfConverter
from core.doc_to_pdf import DocToPdfConverter


class ConversionWorker(QThread):
    finished = Signal(str, str)
    error = Signal(str)
    progress = Signal(str)

    def __init__(
        self,
        converter,
        input_path: str,
        media_dir: str | None = None,
    ):
        super().__init__()
        self.converter = converter
        self.input_path = input_path
        self.media_dir = media_dir

    def run(self):
        tmp_pdf = None
        try:
            path = self.input_path
            media_dir = self.media_dir

            # DOC/DOCX → PDF → Markdown（需要 LibreOffice 或 Word）
            if path.lower().endswith((".doc", ".docx")):
                doc_converter = DocToPdfConverter()
                ok, engine = doc_converter.is_available()
                if ok:
                    self.progress.emit(f"正在通过 {engine} 将 Word 文档转换为 PDF...")
                    tmp_pdf = doc_converter.convert(path)
                    path = tmp_pdf
                    # 图片目录放在原文件旁边（非临时目录），避免被清理
                    if not media_dir:
                        stem = os.path.splitext(os.path.basename(self.input_path))[0]
                        media_dir = os.path.join(os.path.dirname(self.input_path), f"{stem}_media")
                elif path.lower().endswith(".docx") and isinstance(self.converter, PandocConverter):
                    # DOCX 可通过 Pandoc 直接转换，DOC 不行
                    self.progress.emit("正在通过 Pandoc 转换文档...")
                    if not media_dir:
                        stem = os.path.splitext(os.path.basename(path))[0]
                        media_dir = os.path.join(os.path.dirname(path), f"{stem}_media")
                    markdown = self.converter.convert(path, extract_media_dir=media_dir)
                    self.progress.emit("转换完成")
                    self.finished.emit(markdown, media_dir or "")
                    return
                else:
                    raise RuntimeError(engine)

            self.progress.emit("正在转换文档...")
            markdown, used_media_dir = self.converter.convert(
                path,
                extract_media_dir=media_dir,
            )
            self.progress.emit("转换完成")
            self.finished.emit(markdown, used_media_dir or "")
        except Exception as e:
            self.error.emit(str(e))
        finally:
            if tmp_pdf:
                tmp_dir = os.path.dirname(tmp_pdf)
                shutil.rmtree(tmp_dir, ignore_errors=True)


class BatchWorker(QThread):
    file_finished = Signal(str, bytes, str, str, str)  # (path, pdf_bytes, markdown, media_dir, error)
    progress = Signal(int, int, str)       # (current, total, filename)
    all_done = Signal()

    def __init__(
        self,
        files: list[str],
        pandoc_converter: PandocConverter,
        pdf_converter: PdfConverter,
        doc_to_pdf_converter: DocToPdfConverter | None = None,
        media_dir: str | None = None,
    ):
        super().__init__()
        self.files = files
        self.pandoc_converter = pandoc_converter
        self.pdf_converter = pdf_converter
        self.doc_to_pdf_converter = doc_to_pdf_converter or DocToPdfConverter()
        self.media_dir = media_dir
        self._cancel = False
        self._temp_dirs: list[str] = []  # 待清理的临时目录

    def cancel(self):
        self._cancel = True

    def run(self):
        doc_ok, _ = self.doc_to_pdf_converter.is_available()

        total = len(self.files)
        for idx, path in enumerate(self.files):
            if self._cancel:
                break

            self.progress.emit(idx + 1, total, path)

            tmp_pdf = None
            try:
                pdf_bytes = b""
                if path.lower().endswith((".doc", ".docx")):
                    if doc_ok:
                        # 先创建媒体目录（放在原文件旁边，不在临时目录中）
                        if self.media_dir:
                            media_dir = self.media_dir
                        else:
                            stem = os.path.splitext(os.path.basename(path))[0]
                            media_dir = os.path.join(
                                os.path.dirname(path),
                                f"{stem}_media"
                            )
                        
                        # 转换为临时PDF
                        tmp_pdf = self.doc_to_pdf_converter.convert(path)
                        
                        # 从临时PDF提取Markdown（图片存放到持久化媒体目录）
                        md, used_media_dir = self.pdf_converter.convert(
                            tmp_pdf, extract_media_dir=media_dir,
                        )
                        
                        # 读取临时PDF为字节
                        with open(tmp_pdf, "rb") as f:
                            pdf_bytes = f.read()
                        
                        # 确保media_dir被正确设置
                        media_dir = used_media_dir
                    elif path.lower().endswith(".docx"):
                        # DOCX 可通过 Pandoc 直接转换，DOC 不行
                        md = self.pandoc_converter.convert(
                            path, extract_media_dir=self.media_dir,
                        )
                        media_dir = self.media_dir or ""
                    else:
                        raise RuntimeError(
                            "DOC 文件转换需要 Microsoft Word 和 pywin32"
                        )
                elif path.lower().endswith(".pdf"):
                    # PDF文件只需生成MD
                    md, media_dir = self.pdf_converter.convert(
                        path, extract_media_dir=self.media_dir,
                    )
                else:
                    md = self.pandoc_converter.convert(
                        path, extract_media_dir=self.media_dir,
                    )
                    media_dir = self.media_dir or ""
                self.file_finished.emit(path, pdf_bytes, md, media_dir or "", "")
            except Exception as e:
                self.file_finished.emit(path, b"", "", "", str(e))
            finally:
                if tmp_pdf:
                    tmp_dir = os.path.dirname(tmp_pdf)
                    self._temp_dirs.append(tmp_dir)

        # 清理临时目录
        for d in self._temp_dirs:
            shutil.rmtree(d, ignore_errors=True)
        self._temp_dirs.clear()

        self.all_done.emit()


class PdfBatchWorker(QThread):
    """批量将文件转换/复制为 PDF，同时生成 Markdown。结果存储在内存中。"""

    file_finished = Signal(str, bytes, str, str, str)  # (原路径, pdf_bytes, markdown, media_dir, 错误)
    progress = Signal(int, int, str)       # (当前, 总数, 文件名)
    all_done = Signal()

    def __init__(
        self,
        files: list[str],
        doc_to_pdf_converter: DocToPdfConverter | None = None,
        pdf_converter: PdfConverter | None = None,
    ):
        super().__init__()
        self.files = files
        self.doc_to_pdf_converter = doc_to_pdf_converter or DocToPdfConverter()
        self.pdf_converter = pdf_converter
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        doc_ok, _ = self.doc_to_pdf_converter.is_available()
        total = len(self.files)

        for idx, path in enumerate(self.files):
            if self._cancel:
                break

            self.progress.emit(idx + 1, total, path)

            tmp_pdf = None
            try:
                pdf_bytes = b""

                if path.lower().endswith((".doc", ".docx")):
                    if not doc_ok:
                        raise RuntimeError(
                            "DOC/DOCX → PDF 转换需要 Microsoft Word 和 pywin32"
                        )
                    # 转换为PDF
                    tmp_pdf = self.doc_to_pdf_converter.convert(path)
                    with open(tmp_pdf, "rb") as f:
                        pdf_bytes = f.read()

                elif path.lower().endswith(".pdf"):
                    with open(path, "rb") as f:
                        pdf_bytes = f.read()
                else:
                    raise RuntimeError(f"不支持的文件格式：{os.path.basename(path)}")

                self.file_finished.emit(path, pdf_bytes, "", "", "")
            except Exception as e:
                self.file_finished.emit(path, b"", "", "", str(e))
            finally:
                if tmp_pdf:
                    shutil.rmtree(os.path.dirname(tmp_pdf), ignore_errors=True)

        self.all_done.emit()
