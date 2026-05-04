"""QThread 工作线程：异步导入 Markdown 到思源笔记"""

from PySide6.QtCore import QThread, Signal
from core.siyuan_client import SiYuanClient


class SiYuanImportWorker(QThread):
    """单文档导入到思源笔记。"""

    finished = Signal(str, str)  # (doc_id, error)
    status = Signal(str)

    def __init__(self, client: SiYuanClient, notebook: str, doc_path: str,
                 markdown: str, media_dir: str = ""):
        super().__init__()
        self.client = client
        self.notebook = notebook
        self.doc_path = doc_path
        self.markdown = markdown
        self.media_dir = media_dir

    def run(self):
        try:
            self.status.emit("正在连接思源笔记...")
            self.client.test_connection()

            markdown = self.markdown
            if self.media_dir:
                self.status.emit("正在上传图片资源...")
                markdown = self.client.upload_assets_from_markdown(
                    markdown, self.media_dir
                )

            self.status.emit("正在导入文档...")
            doc_id = self.client.create_doc_with_md(
                self.notebook, self.doc_path, markdown
            )
            self.finished.emit(str(doc_id), "")
        except Exception as e:
            self.finished.emit("", str(e))


class SiYuanBatchImportWorker(QThread):
    """批量导入多个 Markdown 文档到思源笔记。"""

    progress = Signal(int, int, str)        # (current, total, name)
    file_finished = Signal(str, str, str)   # (name, doc_id, error)
    all_done = Signal(int, int)             # (success_count, fail_count)

    def __init__(self, client: SiYuanClient, notebook: str,
                 base_path: str, documents: list[tuple[str, str]],
                 media_dirs: dict[str, str] | None = None):
        super().__init__()
        self.client = client
        self.notebook = notebook
        self.base_path = base_path
        self.documents = documents
        self.media_dirs = media_dirs or {}
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        total = len(self.documents)
        success = 0
        fail = 0

        for idx, (name, markdown) in enumerate(self.documents):
            if self._cancel:
                break

            self.progress.emit(idx + 1, total, name)
            doc_path = f"{self.base_path}/{name}" if self.base_path else f"/{name}"

            try:
                media_dir = self.media_dirs.get(name, "")
                if media_dir:
                    markdown = self.client.upload_assets_from_markdown(
                        markdown, media_dir
                    )

                doc_id = self.client.create_doc_with_md(
                    self.notebook, doc_path, markdown
                )
                self.file_finished.emit(name, str(doc_id), "")
                success += 1
            except Exception as e:
                self.file_finished.emit(name, "", str(e))
                fail += 1

        self.all_done.emit(success, fail)
