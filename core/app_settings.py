"""
app_settings.py —— 用户偏好持久化（语言 / 主题）

保存为程序目录下的 JSON（与错误日志同目录），键值：
    {"language": "zh", "theme": "night"}

设计：本模块只负责读写与「应用」偏好，不持有 UI 状态；
应用语言/主题时惰性导入 ui.style，避免 core → ui 的模块级循环依赖。
"""
import json
import os
import sys

_FILE_NAME = "已知行星可视化_设置.json"

DEFAULTS = {"language": "zh", "theme": "night"}


def _config_path() -> str:
    if getattr(sys, "frozen", False):
        base = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, _FILE_NAME)


def load() -> dict:
    data = dict(DEFAULTS)
    try:
        with open(_config_path(), "r", encoding="utf-8") as f:
            saved = json.load(f)
        if isinstance(saved, dict):
            for k in DEFAULTS:
                if k in saved and isinstance(saved[k], str):
                    data[k] = saved[k]
    except Exception:
        pass
    return data


def save(data: dict):
    try:
        with open(_config_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def get_language() -> str:
    return load().get("language", "zh")


def get_theme() -> str:
    return load().get("theme", "night")


def set_language(code: str):
    from core import i18n
    i18n.set_language(code)
    d = load()
    d["language"] = code
    save(d)


def set_theme(name: str):
    from ui import style
    style.apply_theme(name)
    d = load()
    d["theme"] = name
    save(d)


def apply_saved():
    """启动时应用已保存的语言与主题。"""
    d = load()
    from core import i18n
    i18n.set_language(d["language"])
    from ui import style
    style.apply_theme(d["theme"])
    return d
