"""
env_store.py —— .env 文件读写（仅标准库实现，保持本项目零第三方依赖）

用途：把大模型 API Key 等敏感配置从可提交的设置 JSON 中分离出来，单独存放
在程序目录下的 .env 文件里；.env 已在 .gitignore 中排除，不会被推送到仓库。

语法兼容常见 dotenv 写法：
    KEY=VALUE
    KEY="VALUE WITH SPACE"
    KEY='VALUE'
    export KEY=VALUE
    # 以 # 开头的行为注释

设计：与 core.llm_client 一样只依赖 Python 标准库（os/sys），
避免为打包 exe 引入 python-dotenv 等额外依赖。
"""
import os
import sys

_FILE_NAME = ".env"


def _env_path() -> str:
    """定位 .env：打包后取 exe 同级目录，源码运行时取项目根目录。"""
    if getattr(sys, "frozen", False):
        base = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, _FILE_NAME)


def _parse_line(line: str):
    """解析一行，返回 (key, value)；非键值行返回 None。"""
    text = line.strip()
    if not text or text.startswith("#"):
        return None
    if text.startswith("export "):
        text = text[len("export "):].lstrip()
    key, sep, value = text.partition("=")
    if not sep:
        return None
    key = key.strip()
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1]
    if not key:
        return None
    return key, value


def _quote(value: str) -> str:
    """按需给值加双引号，保证空格 / # / 引号不会破坏解析。"""
    v = (value or "").strip()
    if v == "":
        return '""'
    if any(ch in v for ch in ' \t"#\''):
        return '"' + v.replace('\\', '\\\\').replace('"', '\\"') + '"'
    return v


def read_all() -> dict:
    data = {}
    try:
        with open(_env_path(), "r", encoding="utf-8") as f:
            for line in f:
                parsed = _parse_line(line)
                if parsed:
                    data[parsed[0]] = parsed[1]
    except Exception:
        pass
    return data


def get(key: str, default: str = "") -> str:
    return read_all().get(key, default)


def set_value(key: str, value: str):
    """写入或更新一个键，保留文件中其余行与注释。"""
    try:
        with open(_env_path(), "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
    except Exception:
        lines = ["# 本地敏感配置，请勿提交到仓库（已在 .gitignore 中排除）"]
    entry = f"{key}={_quote(value)}"
    for i, line in enumerate(lines):
        parsed = _parse_line(line)
        if parsed and parsed[0] == key:
            lines[i] = entry
            break
    else:
        lines.append(entry)
    try:
        with open(_env_path(), "w", encoding="utf-8") as f:
            f.write("\n".join(lines).rstrip("\n") + "\n")
    except Exception:
        pass


def exists() -> bool:
    return os.path.exists(_env_path())
