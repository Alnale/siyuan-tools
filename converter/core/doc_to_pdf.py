"""DOC/DOCX → PDF 无损转换引擎

使用 Microsoft Word COM 自动化进行高质量 PDF 转换。
需要本机安装 Microsoft Word 和 pywin32。
"""

import os
from core.temp_manager import temp_manager


class DocToPdfConverter:
    """将 DOC/DOCX 文件无损转换为 PDF（通过 Microsoft Word）。"""

    def __init__(self):
        self._engine: str | None = None  # "word" | None
        self._checked = False

    def _detect(self):
        """检测 Word COM 是否可用。"""
        if self._checked:
            return
        self._checked = True

        try:
            import win32com.client  # noqa: F401
            self._engine = "word"
        except ImportError:
            self._engine = None

    def is_available(self) -> tuple[bool, str]:
        """检查 Word COM 是否可用。返回 (可用, 引擎描述)。"""
        self._detect()
        if self._engine == "word":
            return True, "Microsoft Word"
        return False, "未找到 pywin32，请运行 pip install pywin32"

    def convert(
        self,
        input_path: str,
        output_dir: str | None = None,
    ) -> str:
        """将 DOC/DOCX 转换为 PDF，返回 PDF 文件路径。

        Args:
            input_path: 输入的 .doc 或 .docx 文件路径
            output_dir: 输出目录。为 None 时使用统一临时目录。

        Returns:
            生成的 PDF 文件路径。

        Raises:
            FileNotFoundError: 输入文件不存在。
            RuntimeError: 无可用引擎或转换失败。
        """
        if not os.path.isfile(input_path):
            raise FileNotFoundError(f"输入文件不存在：{input_path}")

        self._detect()

        if self._engine is None:
            raise RuntimeError(
                "未安装 pywin32，无法使用 Word 转换 DOC/DOCX 文件。\n"
                "请运行：pip install pywin32"
            )

        if output_dir is None:
            # 使用统一的临时目录管理器
            output_dir = temp_manager.create_temp_dir(prefix="doc2pdf_")
        else:
            os.makedirs(output_dir, exist_ok=True)

        return self._convert_word(input_path, output_dir)

    def _convert_word(self, input_path: str, output_dir: str) -> str:
        """使用 Microsoft Word COM 高质量转换。"""
        import win32com.client

        word = None
        doc = None
        try:
            word = win32com.client.Dispatch("Word.Application")
            word.Visible = False

            abs_input = os.path.abspath(input_path)
            abs_output = os.path.join(
                output_dir,
                os.path.splitext(os.path.basename(input_path))[0] + ".pdf",
            )

            doc = word.Documents.Open(abs_input)

            # ExportAsFixedFormat 支持更多质量参数（优于 SaveAs）
            # wdExportFormatPDF = 17
            # wdExportOptimizeForPrint = 1
            doc.ExportAsFixedFormat(
                OutputFileName=abs_output,
                ExportFormat=17,        # wdExportFormatPDF
                OpenAfterExport=False,
                OptimizeFor=1,          # wdExportOptimizeForPrint (高质量)
                Range=0,                # wdExportAllDocument
                Item=0,                 # wdExportDocumentContent
                IncludeDocProps=True,   # 保留文档属性
                KeepIRM=True,           # 保留权限管理
                CreateBookmarks=1,      # wdExportCreateWordBookmarks
                DocStructureTags=True,  # 保留文档结构（辅助功能）
                BitmapMissingFonts=True,# 嵌入缺失字体的位图
                UseISO19005_1=False,    # 不强制 PDF/A（保留更多格式）
            )

            if not os.path.isfile(abs_output):
                raise RuntimeError(f"Word 转换完成但未找到输出文件：{abs_output}")

            return abs_output

        except Exception as e:
            raise RuntimeError(f"Word COM 转换失败：{e}")
        finally:
            if doc:
                try:
                    doc.Close(SaveChanges=0)
                except Exception:
                    pass
            if word:
                try:
                    word.Quit()
                except Exception:
                    pass
