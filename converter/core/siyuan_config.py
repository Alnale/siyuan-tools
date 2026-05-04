"""从项目根目录 config.json 加载思源笔记连接配置"""

import json
import os
from core.siyuan_client import SiYuanConfig

# 从 converter/core/ 上溯到 siyuan-tools/
_SIYUAN_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    ".."
)


def load_siyuan_config(config_dir: str | None = None) -> SiYuanConfig:
    """加载思源笔记配置。

    Args:
        config_dir: config.json 所在目录，默认为项目根目录。

    Returns:
        SiYuanConfig 实例
    """
    base = config_dir or os.path.normpath(_SIYUAN_DIR)
    config_path = os.path.join(base, "config.json")

    if not os.path.isfile(config_path):
        raise FileNotFoundError(
            f"找不到配置文件: {config_path}\n"
            f"请确保 config.json 在项目根目录下。"
        )

    with open(config_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    default_user_name = raw.get("defaultUser", "local")
    users = raw.get("users", {})
    user = users.get(default_user_name, {})
    import_cfg = raw.get("import", {})

    return SiYuanConfig(
        endpoint=user.get("endpoint", "http://127.0.0.1:6806"),
        token=user.get("token", ""),
        default_notebook=user.get("defaultNotebook", ""),
        default_path=import_cfg.get("defaultPath", "/Claude Code"),
    )
