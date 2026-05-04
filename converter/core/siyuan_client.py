"""思源笔记 API 客户端 — Python 版 SiYuanClient"""

import os
import re
import logging

import requests
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class SiYuanConfig:
    endpoint: str = "http://127.0.0.1:6806"
    token: str = ""
    default_notebook: str = ""
    default_path: str = "/Claude Code"


class SiYuanError(Exception):
    def __init__(self, code: int, msg: str):
        self.code = code
        self.msg = msg
        super().__init__(f"SiYuan API error [{code}]: {msg}")


class SiYuanClient:
    """HTTP client wrapping SiYuan's REST API.

    Mirrors the Node.js SiYuanClient in SiYuan/import.js.
    """

    def __init__(self, config: SiYuanConfig):
        self.endpoint = config.endpoint.rstrip("/")
        self.token = config.token
        self.default_notebook = config.default_notebook
        self.default_path = config.default_path
        self.timeout = 60

    def _call(self, api_path: str, body: dict | None = None) -> dict:
        """POST to a SiYuan API endpoint. Raises SiYuanError on non-zero code."""
        url = f"{self.endpoint}{api_path}"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Token {self.token}",
        }
        resp = requests.post(
            url, json=body or {}, headers=headers, timeout=self.timeout
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise SiYuanError(data.get("code", -1), data.get("msg", "Unknown error"))
        return data.get("data")

    def test_connection(self) -> str:
        """测试 API 连接，返回版本号。"""
        data = self._call("/api/system/version")
        return data.get("version", "unknown") if isinstance(data, dict) else str(data)

    def list_notebooks(self) -> list[dict]:
        """列出所有未关闭的笔记本。"""
        data = self._call("/api/notebook/lsNotebooks")
        notebooks = data.get("notebooks", []) if isinstance(data, dict) else []
        return [nb for nb in notebooks if not nb.get("closed")]

    def create_doc_with_md(self, notebook: str, doc_path: str, markdown: str) -> str:
        """通过 Markdown 内容创建文档。

        Args:
            notebook: 笔记本 ID
            doc_path: 文档路径（如 "/Claude Code/MyDoc"）
            markdown: Markdown 文本内容

        Returns:
            创建的文档 ID
        """
        data = self._call("/api/filetree/createDocWithMd", {
            "notebook": notebook,
            "path": doc_path,
            "markdown": markdown,
        })
        return data

    def upload_asset(self, file_path: str, assets_dir_path: str = "/assets/") -> dict:
        """上传资源文件到思源笔记。

        Args:
            file_path: 本地文件路径
            assets_dir_path: 思源资源目录路径

        Returns:
            succMap: {原始文件名: "assets/xxx.png"}
        """
        url = f"{self.endpoint}/api/asset/upload"
        headers = {"Authorization": f"Token {self.token}"}
        with open(file_path, "rb") as f:
            files = {"file[]": (os.path.basename(file_path), f)}
            data = {"assetsDirPath": assets_dir_path}
            resp = requests.post(
                url, files=files, data=data, headers=headers, timeout=self.timeout
            )
        resp.raise_for_status()
        result = resp.json()
        if result.get("code") != 0:
            raise SiYuanError(result.get("code", -1), result.get("msg", "上传失败"))
        return result.get("data", {})

    def upload_assets_from_markdown(self, markdown: str, media_dir: str) -> str:
        """扫描 Markdown 中的图片引用，上传到思源笔记，返回重写路径后的 Markdown。

        Args:
            markdown: 原始 Markdown 文本
            media_dir: 图片文件所在的本地目录

        Returns:
            图片路径已替换为思源 assets 路径的 Markdown
        """
        if not media_dir or not os.path.isdir(media_dir):
            return markdown

        # 匹配 ![alt](path) 格式的图片引用
        img_pattern = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")

        # 收集需要上传的图片：{原始引用路径: 匹配对象}
        to_upload: dict[str, str] = {}  # ref_path -> local_file_path
        for match in img_pattern.finditer(markdown):
            ref_path = match.group(2)
            # 跳过 URL 和已有 assets/ 前缀的引用
            if ref_path.startswith(("http://", "https://", "assets/")):
                continue
            local_path = os.path.join(media_dir, ref_path)
            if os.path.isfile(local_path):
                to_upload[ref_path] = local_path

        if not to_upload:
            return markdown

        # 批量上传
        path_map: dict[str, str] = {}  # 原始引用 -> 思源 assets 路径
        for ref_path, local_path in to_upload.items():
            try:
                result = self.upload_asset(local_path)
                succ_map = result.get("succMap", {})
                for orig_name, asset_path in succ_map.items():
                    path_map[ref_path] = asset_path
                    logger.info("已上传资源: %s -> %s", ref_path, asset_path)
            except Exception as e:
                logger.warning("上传资源失败 %s: %s", ref_path, e)

        if not path_map:
            return markdown

        # 替换 markdown 中的图片路径
        def replace_path(match):
            alt = match.group(1)
            ref_path = match.group(2)
            new_path = path_map.get(ref_path, ref_path)
            return f"![{alt}]({new_path})"

        return img_pattern.sub(replace_path, markdown)
