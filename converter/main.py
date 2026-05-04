import sys
import atexit
from PySide6.QtWidgets import QApplication, QMessageBox
from core.converter import PandocConverter
from core.doc_to_pdf import DocToPdfConverter
from core.temp_manager import temp_manager
from gui.main_window import MainWindow


def cleanup_on_exit():
    """程序退出时清理未保存的临时文件。"""
    temp_manager.cleanup_unsaved()


def main():
    # 注册退出清理
    atexit.register(cleanup_on_exit)

    app = QApplication(sys.argv)
    app.setApplicationName("DOCX / PDF to Markdown 转换器")
    app.setStyle("Fusion")

    converter = PandocConverter()
    pandoc_ok, _ = converter.check_pandoc_available()

    doc_converter = DocToPdfConverter()
    doc_ok, doc_engine = doc_converter.is_available()

    warnings = []
    if not doc_ok:
        if pandoc_ok:
            warnings.append(
                "Word COM 不可用（需要安装 Microsoft Word 和 pywin32）。\n"
                "DOCX 文件将通过 Pandoc 转换，DOC 文件暂不可用。\n"
                "运行 pip install pywin32 并确保已安装 Microsoft Word。"
            )
        else:
            warnings.append(
                "Word COM 不可用且 Pandoc 也未安装。\n"
                "DOC/DOCX → PDF 文件无法转换。\n"
                "请运行 pip install pywin32，确保已安装 Microsoft Word，\n"
                "并从 https://pandoc.org/installing.html 安装 Pandoc。"
            )
    elif not pandoc_ok:
        warnings.append(
            "Pandoc 未找到，DOCX 直接转换不可用（不影响 PDF 流程）。\n"
            f"DOC/DOCX → PDF 引擎：{doc_engine}\n"
            "如需 Pandoc 支持，请从 https://pandoc.org/installing.html 安装。"
        )

    if warnings:
        QMessageBox.warning(None, "转换引擎检测", "\n\n".join(warnings))

    window = MainWindow(converter=converter)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
