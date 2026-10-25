"""
app_settings.py —— 用户偏好持久化（语言 / 主题 / 字体 / 渲染 / 显卡 / 大模型）

保存为程序目录下的 JSON（与错误日志同目录）。设计：本模块只负责读写与「应用」
偏好，不持有 UI 状态；应用语言 / 主题 / 字体时惰性导入 ui.style，
避免 core → ui 的模块级循环依赖。

键值：
    language          界面语言（zh/en/fr/ru/es/ar）
    theme             界面主题（night/day）
    font_scale        界面字体缩放倍率（0.8 ~ 1.6）
    perf_tier         渲染性能档位（high/balanced/power）
    planet_count_mode 天体数量模式（auto 自动适配 / manual 手动）
    planet_count      手动模式下的天体数量
    gpu_pref          显卡首选项（auto 自动 / high 高性能独显 / power 省电）
    display_mode      窗口显示模式（windowed / borderless_windowed /
                      borderless_fullscreen / exclusive_fullscreen / maximized），
                      默认 maximized（占满屏幕且保留标题栏窗口控制按钮）
    llm_provider      大模型服务商键
    llm_base_url      大模型 API 地址（OpenAI 兼容）
    llm_model         模型名

API Key 不写入本 JSON：改由 core.env_store 读写程序目录下的 .env 文件，
避免密钥随设置文件被提交到仓库。
"""
import json
import os
import sys

from core import env_store

_FILE_NAME = "已知行星可视化_设置.json"
ENV_API_KEY = "LLM_API_KEY"

# 默认值：值类型决定 load() 的类型校验方式
DEFAULTS = {
    "language": "zh",
    "theme": "night",
    "font_scale": 1.0,
    "perf_tier": "high",
    "planet_count_mode": "auto",
    "planet_count": 400000,
    "gpu_pref": "auto",
    "display_mode": "maximized",
    "show_view_gizmo": True,
    "llm_provider": "deepseek",
    "llm_base_url": "https://api.deepseek.com/v1",
    "llm_model": "deepseek-chat",
}

# 字符串型键（其余按默认值类型做数值 / 布尔校验）
_STR_KEYS = {"language", "theme", "perf_tier", "planet_count_mode",
             "gpu_pref", "display_mode", "llm_provider", "llm_base_url",
             "llm_model"}


def _config_path() -> str:
    if getattr(sys, "frozen", False):
        base = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, _FILE_NAME)


def _coerce(key, value):
    """按默认值类型校验并转换；不合法时返回 None（表示用默认值）。"""
    default = DEFAULTS.get(key)
    if key in _STR_KEYS:
        return value if isinstance(value, str) else None
    if isinstance(default, bool):
        return bool(value) if isinstance(value, (bool, int, float)) else None
    if isinstance(default, float):
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None
    if isinstance(default, int):
        return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None
    return value


def load() -> dict:
    data = dict(DEFAULTS)
    try:
        with open(_config_path(), "r", encoding="utf-8") as f:
            saved = json.load(f)
        if isinstance(saved, dict):
            for k in DEFAULTS:
                if k in saved:
                    v = _coerce(k, saved[k])
                    if v is not None:
                        data[k] = v
    except Exception:
        pass
    return data


def save(data: dict):
    # 双保险：即使调用方传入 llm_api_key，也不落盘到设置 JSON
    safe = {k: v for k, v in data.items() if k != "llm_api_key"}
    try:
        with open(_config_path(), "w", encoding="utf-8") as f:
            json.dump(safe, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def get(key: str):
    return load().get(key, DEFAULTS.get(key))


def configured() -> bool:
    """配置文件是否已存在（用于首次启动的初始化判断）。"""
    return os.path.exists(_config_path())


def set_value(key: str, value):
    d = load()
    d[key] = value
    save(d)
    return d


# ---------------------------------------------------------------- 语言 / 主题
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


# ---------------------------------------------------------------- 字体缩放
def get_font_scale() -> float:
    try:
        return float(load().get("font_scale", 1.0))
    except Exception:
        return 1.0


def set_font_scale(scale: float):
    from ui import style
    style.apply_font_scale(scale)
    d = load()
    d["font_scale"] = float(scale)
    save(d)


# ---------------------------------------------------------------- 渲染 / 显卡
def get_perf_tier() -> str:
    return load().get("perf_tier", "high")


def set_perf_tier(tier: str):
    d = load()
    d["perf_tier"] = tier
    save(d)


def get_planet_count_mode() -> str:
    return load().get("planet_count_mode", "auto")


def get_planet_count() -> int:
    try:
        return int(load().get("planet_count", DEFAULTS["planet_count"]))
    except Exception:
        return DEFAULTS["planet_count"]


def set_planet_count(count: int, mode: str = None):
    d = load()
    d["planet_count"] = int(count)
    if mode is not None:
        d["planet_count_mode"] = mode
    save(d)


def get_gpu_pref() -> str:
    return load().get("gpu_pref", "auto")


def set_gpu_pref(pref: str):
    d = load()
    d["gpu_pref"] = pref
    save(d)


# ---------------------------------------------------------------- 显示模式
def get_display_mode() -> str:
    """窗口显示模式（默认 maximized：占满屏幕且保留窗口控制按钮）。"""
    mode = load().get("display_mode", "maximized")
    return mode if mode in ("windowed", "borderless_windowed",
                            "borderless_fullscreen", "exclusive_fullscreen",
                            "maximized") else "maximized"


def set_display_mode(mode: str):
    d = load()
    d["display_mode"] = mode
    save(d)


# ---------------------------------------------------------------- 视角导航轴
def get_show_view_gizmo() -> bool:
    """3D 视口右上角 Blender 风格视角导航轴（View Gizmo）显隐，默认开启。"""
    return bool(load().get("show_view_gizmo", True))


def set_show_view_gizmo(shown: bool):
    d = load()
    d["show_view_gizmo"] = bool(shown)
    save(d)


# ---------------------------------------------------------------- 大模型
def _legacy_api_key() -> str:
    """读取旧版本遗留在设置 JSON 里的 API Key（仅用于迁移与兜底）。"""
    try:
        with open(_config_path(), "r", encoding="utf-8") as f:
            saved = json.load(f)
        value = saved.get("llm_api_key") if isinstance(saved, dict) else None
        return value if isinstance(value, str) else ""
    except Exception:
        return ""


def migrate_api_key():
    """把旧设置 JSON 里的 API Key 搬到 .env，并从 JSON 中移除。"""
    legacy = _legacy_api_key()
    if not legacy:
        return
    if not env_store.get(ENV_API_KEY):
        env_store.set_value(ENV_API_KEY, legacy)
    save(load())


def get_llm_config() -> dict:
    d = load()
    return {
        "provider": d.get("llm_provider", "deepseek"),
        "base_url": d.get("llm_base_url", ""),
        "model": d.get("llm_model", ""),
        "api_key": env_store.get(ENV_API_KEY) or _legacy_api_key(),
    }


def set_llm_config(provider: str = None, base_url: str = None,
                   model: str = None, api_key: str = None):
    d = load()
    if provider is not None:
        d["llm_provider"] = provider
    if base_url is not None:
        d["llm_base_url"] = base_url
    if model is not None:
        d["llm_model"] = model
    save(d)
    if api_key is not None:
        env_store.set_value(ENV_API_KEY, api_key)


def apply_saved():
    """启动时应用已保存的语言、主题与字体缩放。"""
    migrate_api_key()
    d = load()
    from core import i18n
    i18n.set_language(d["language"])
    from ui import style
    style.apply_theme(d["theme"])
    style.apply_font_scale(d["font_scale"])
    return d
