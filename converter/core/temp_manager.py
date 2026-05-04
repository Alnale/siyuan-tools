"""临时文件管理模块

管理转换流程产生的临时文件，支持：
- 创建统一的临时目录
- 追踪已保存的文件
- 退出时自动清理未保存的临时文件
"""

import os
import shutil
import logging
from typing import Set

logger = logging.getLogger(__name__)

# 临时文件根目录
TEMP_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "temp")
)


class TempFileManager:
    """管理临时文件的创建和清理。"""

    def __init__(self, temp_root: str = TEMP_ROOT):
        self._temp_root = temp_root
        self._saved_files: Set[str] = set()  # 已保存的文件路径
        self._initialized = False

    def initialize(self):
        """初始化临时目录。"""
        if not self._initialized:
            os.makedirs(self._temp_root, exist_ok=True)
            self._initialized = True
            logger.info(f"临时目录已初始化：{self._temp_root}")

    def cleanup_unsaved(self):
        """清理未保存的临时文件。
        
        如果用户没有点击保存就退出程序，则删除 temp 文件夹下缓存的内容。
        """
        if not os.path.exists(self._temp_root):
            return

        try:
            for item in os.listdir(self._temp_root):
                item_path = os.path.join(self._temp_root, item)
                if item_path in self._saved_files:
                    continue
                if os.path.isfile(item_path):
                    os.remove(item_path)
                    logger.debug(f"已清理临时文件：{item_path}")
                elif os.path.isdir(item_path):
                    shutil.rmtree(item_path, ignore_errors=True)
                    logger.debug(f"已清理临时目录：{item_path}")
            logger.info(f"已清理未保存的临时文件：{self._temp_root}")
        except Exception as e:
            logger.error(f"清理临时文件失败：{e}")

    def cleanup_all(self):
        """清理所有临时文件（包括已保存的）。"""
        if not os.path.exists(self._temp_root):
            return
        try:
            shutil.rmtree(self._temp_root, ignore_errors=True)
            logger.info(f"已清理所有临时文件：{self._temp_root}")
        except Exception as e:
            logger.error(f"清理所有临时文件失败：{e}")

    def mark_saved(self, file_path: str):
        """标记文件为已保存。"""
        self._saved_files.add(file_path)
        logger.debug(f"已标记保存：{file_path}")

    def create_temp_dir(self, prefix: str = "temp_") -> str:
        """创建临时子目录。
        
        Returns:
            临时目录路径
        """
        self.initialize()
        import tempfile
        temp_dir = tempfile.mkdtemp(prefix=prefix, dir=self._temp_root)
        logger.debug(f"创建临时目录：{temp_dir}")
        return temp_dir

    @property
    def temp_root(self) -> str:
        return self._temp_root


# 全局临时文件管理器实例
temp_manager = TempFileManager()
