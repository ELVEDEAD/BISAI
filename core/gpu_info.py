"""gpu_info.py —— 运行环境的图形设备信息探测

启动时创建一个离屏 OpenGL 上下文，读取显卡厂商 / 渲染器名称、OpenGL 版本与
GLSL 版本，并判断是否满足本程序所需的「桌面 OpenGL 3.3 Core」。结果缓存一次，
供设置面板的「图形 / 显卡」分组展示，也用于启动时的软件渲染回退判定。

只读探测，不改变任何渲染状态：查询完成后立即 doneCurrent()。

探测结果另做跨启动持久缓存（gpu_info_cache.json，7 天有效），避免每次
启动都创建离屏 GL 上下文（部分驱动上较慢或有副作用）；设置面板
「重新检测」可强制重测。
"""
import ctypes
import json
import os
import sys
import time

from PyQt5.QtGui import QOpenGLContext, QSurfaceFormat, QOffscreenSurface

REQUIRED_MAJOR = 3
REQUIRED_MINOR = 3

# glGetString 的枚举值
_GL_VENDOR = 0x1F00
_GL_RENDERER = 0x1F01
_GL_VERSION = 0x1F02
_GL_SHADING_LANGUAGE_VERSION = 0x8B8C

# 软件渲染器特征串：命中则说明未走 GPU 硬件加速
_SOFTWARE_KEYS = ("llvmpipe", "softpipe", "swrast", "software rasterizer",
                  "gdi generic", "microsoft basic render", "mesa offscreen",
                  "opengl es", "angle")

_INFO = None

# 持久缓存：格式版本号（字段变更时 +1 使旧缓存失效）
_CACHE_VERSION = 1
_CACHE_TTL_SECONDS = 7 * 86400


def _cache_path() -> str:
    """程序目录下的 gpu_info_cache.json（与设置文件同目录惯例）"""
    if getattr(sys, "frozen", False):
        base = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "gpu_info_cache.json")


def _load_disk_cache():
    try:
        with open(_cache_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        if (isinstance(data, dict)
                and data.get("version") == _CACHE_VERSION
                and time.time() - float(data.get("saved_at", 0)) < _CACHE_TTL_SECONDS
                and isinstance(data.get("info"), dict)
                and "renderer" in data["info"]):
            return data["info"]
    except Exception:
        pass
    return None


def _save_disk_cache(info: dict):
    try:
        data = {"version": _CACHE_VERSION, "saved_at": time.time(), "info": info}
        tmp = _cache_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, _cache_path())
    except Exception:
        pass


def _gl_strings(ctx):
    """在当前上下文里读取四个 glGetString 字符串。"""
    out = {"vendor": "", "renderer": "", "version": "", "glsl": ""}
    try:
        addr = ctx.getProcAddress(b"glGetString")
        if not addr:
            return out
        proto = ctypes.CFUNCTYPE(ctypes.c_char_p, ctypes.c_uint)
        gl_get_string = proto(int(addr))
        for key, enum in (("vendor", _GL_VENDOR), ("renderer", _GL_RENDERER),
                          ("version", _GL_VERSION), ("glsl", _GL_SHADING_LANGUAGE_VERSION)):
            raw = gl_get_string(enum)
            out[key] = raw.decode("utf-8", "replace") if raw else ""
    except Exception:
        pass
    return out


def detect():
    """探测并缓存图形设备信息。需在 QApplication 创建之后调用。

    返回 dict：
        ok       是否满足桌面 OpenGL 3.3 Core（程序运行的最低要求）
        vendor / renderer / version / glsl   设备信息字符串
        obtained 实际拿到的上下文版本，如 "3.3"
        software 是否判定为软件渲染（未启用 GPU 硬件加速）
    """
    global _INFO
    if _INFO is not None:
        return _INFO

    cached = _load_disk_cache()
    if cached is not None:
        _INFO = cached
        return _INFO

    info = {"ok": False, "vendor": "", "renderer": "", "version": "",
            "glsl": "", "obtained": "", "software": False}
    ctx = None
    surf = None
    try:
        fmt = QSurfaceFormat()
        fmt.setVersion(REQUIRED_MAJOR, REQUIRED_MINOR)
        fmt.setProfile(QSurfaceFormat.CoreProfile)
        surf = QOffscreenSurface()
        surf.setFormat(fmt)
        surf.create()
        if surf.isValid():
            ctx = QOpenGLContext()
            ctx.setFormat(fmt)
            if ctx.create():
                got = ctx.format()
                info["obtained"] = f"{got.majorVersion()}.{got.minorVersion()}"
                info["ok"] = (got.majorVersion() > REQUIRED_MAJOR or
                              (got.majorVersion() == REQUIRED_MAJOR and
                               got.minorVersion() >= REQUIRED_MINOR))
                if ctx.makeCurrent(surf):
                    info.update(_gl_strings(ctx))
                    ctx.doneCurrent()
    except Exception:
        pass

    blob = f"{info['vendor']} {info['renderer']}".lower()
    info["software"] = any(k in blob for k in _SOFTWARE_KEYS)
    _INFO = info
    _save_disk_cache(info)
    return _INFO


def redetect() -> dict:
    """强制重新探测：清内存与磁盘缓存后真探测（设置面板「重新检测」用）。"""
    global _INFO
    _INFO = None
    try:
        os.remove(_cache_path())
    except OSError:
        pass
    return detect()


def get():
    """返回缓存的探测结果；尚未探测时即时探测一次。"""
    return _INFO if _INFO is not None else detect()


def meets_requirement() -> bool:
    return bool(get().get("ok"))


def renderer_label() -> str:
    """人类可读的显卡名（渲染器名，必要时附厂商）。"""
    info = get()
    name = (info.get("renderer") or "").strip()
    vendor = (info.get("vendor") or "").strip()
    if not name:
        return ""
    if vendor and vendor.lower() not in name.lower():
        return f"{name}（{vendor}）"
    return name


# ---------------- 系统显卡枚举（Windows 注册表，只读、无需管理员） ----------------

_DISPLAY_CLASS_KEY = (r"SYSTEM\CurrentControlSet\Control\Class"
                      r"\{4d36e968-e325-11ce-bfc1-08002be10318}")

# 独立显卡（高性能）常见命名特征
_DISCRETE_KEYS = ("nvidia", "geforce", "rtx", "gtx", "quadro", "radeon rx",
                  "radeon pro", "arc a", "arc b", "arc pro")

_ADAPTERS = None


def list_adapters():
    """枚举本机所有显示适配器名称（顺序即系统枚举顺序）。"""
    global _ADAPTERS
    if _ADAPTERS is not None:
        return list(_ADAPTERS)
    names = []
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _DISPLAY_CLASS_KEY)
        i = 0
        while True:
            try:
                sub = winreg.EnumKey(key, i)
                i += 1
            except OSError:
                break
            if len(sub) == 4 and sub.isdigit():
                try:
                    sk = winreg.OpenKey(key, sub)
                    desc, _ = winreg.QueryValueEx(sk, "DriverDesc")
                    if desc and desc not in names:
                        names.append(desc)
                except Exception:
                    pass
    except Exception:
        pass
    _ADAPTERS = names
    return list(_ADAPTERS)


def discrete_adapters():
    """本机独立（高性能）显卡名称列表。"""
    out = []
    for name in list_adapters():
        low = name.lower()
        if any(k in low for k in _DISCRETE_KEYS):
            out.append(name)
    return out


def unused_discrete():
    """存在但当前未被 OpenGL 使用的独立显卡（用于提示用户切换）。"""
    renderer = (get().get("renderer") or "").lower()
    if not renderer:
        return []
    out = []
    for name in discrete_adapters():
        if name.lower() not in renderer:
            out.append(name)
    return out


# ---------------- 图形首选项（等效 Windows「图形设置」，用户级注册表） ----------------

_GPU_PREF_KEY = r"Software\Microsoft\DirectX\UserGpuPreferences"
_HIGH_PERF_VALUE = "GpuPreference=2;"      # 2 = 高性能（独立显卡）
_LOW_POWER_VALUE = "GpuPreference=1;"      # 1 = 省电（集成显卡）


def exe_path() -> str:
    """当前运行的解释器 / 可执行文件路径，即图形首选项的设置对象。"""
    import sys
    return sys.executable


def get_gpu_preference() -> str:
    """读取当前程序在 Windows 图形设置中的首选项（空串表示未设置）。"""
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _GPU_PREF_KEY)
        try:
            val, _ = winreg.QueryValueEx(key, exe_path())
            return str(val)
        except FileNotFoundError:
            return ""
    except Exception:
        return ""


def high_performance_enabled() -> bool:
    """当前程序是否已被设为「高性能（独立显卡）」。"""
    return "GpuPreference=2" in get_gpu_preference()


def set_high_performance(enabled: bool = True):
    """把当前程序设为「高性能（独立显卡）」；enabled=False 时移除该设置。

    只写 HKCU 用户级键，无需管理员权限，可随时撤销。返回 (ok, errmsg)。
    """
    return set_gpu_preference("high" if enabled else "auto")


# ---------------- 显卡首选项（自动 / 高性能 / 省电） ----------------

# 首选项键 → Windows 图形设置语义
GPU_PREF_KEYS = ("auto", "high", "power")

# 首选项中文名（供 i18n.tr 翻译）
GPU_PREF_LABELS = {
    "auto": "自动（由系统选择）",
    "high": "高性能（独立显卡）",
    "power": "省电（集成显卡）",
}


def current_preference() -> str:
    """读取当前程序在 Windows 图形设置中的首选项键（auto/high/power）。"""
    v = get_gpu_preference()
    if "GpuPreference=2" in v:
        return "high"
    if "GpuPreference=1" in v:
        return "power"
    return "auto"


def set_gpu_preference(pref: str):
    """按 auto / high / power 写入用户级图形首选项。返回 (ok, errmsg)。"""
    try:
        import winreg
        key = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, _GPU_PREF_KEY, 0,
                                 winreg.KEY_SET_VALUE)
        try:
            if pref == "high":
                winreg.SetValueEx(key, exe_path(), 0, winreg.REG_SZ, _HIGH_PERF_VALUE)
            elif pref == "power":
                winreg.SetValueEx(key, exe_path(), 0, winreg.REG_SZ, _LOW_POWER_VALUE)
            else:
                try:
                    winreg.DeleteValue(key, exe_path())
                except FileNotFoundError:
                    pass
        finally:
            winreg.CloseKey(key)
        return True, ""
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def best_adapter() -> str:
    """本机「性能最强」的显卡名：优先独显，其次当前渲染器，最后任一适配器。

    依据：名称命中独显特征（NVIDIA/Radeon/Arc 等）者视为最强；若无独显，
    取当前 OpenGL 实际使用的渲染器；仍无则取枚举到的第一个适配器。
    """
    disc = discrete_adapters()
    if disc:
        return disc[0]
    name = (get().get("renderer") or "").strip()
    if name:
        return name
    ads = list_adapters()
    return ads[0] if ads else ""


def recommended_tier() -> str:
    """按本机图形能力推荐渲染性能档位（首次启动据此选择初始档位）。

    * 软件渲染（CPU / 无硬件加速）→ 省电 power
    * 使用独立显卡渲染         → 高性能 high
    * 其余（集成显卡硬件加速）  → 均衡 balanced
    """
    info = get()
    if info.get("software") or not info.get("ok"):
        return "power"
    renderer = (info.get("renderer") or "").lower()
    if any(k in renderer for k in _DISCRETE_KEYS):
        return "high"
    return "balanced"


def apply_saved_preference():
    """启动时按已保存的显卡首选项写入 Windows 图形设置（幂等）。

    仅当保存的首选项与注册表当前值不一致时才写入，避免每次启动反复读写。
    返回实际生效的首选项键。
    """
    try:
        from core import app_settings
        pref = app_settings.get_gpu_pref()
    except Exception:
        return "auto"
    if pref not in GPU_PREF_KEYS:
        pref = "auto"
    if pref != current_preference():
        set_gpu_preference(pref)
    return pref


