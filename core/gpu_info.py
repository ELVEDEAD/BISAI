"""gpu_info.py —— 运行环境的图形设备信息探测

启动时创建一个离屏 OpenGL 上下文，读取显卡厂商 / 渲染器名称、OpenGL 版本与
GLSL 版本，并判断是否满足本程序所需的「桌面 OpenGL 3.3 Core」。结果缓存一次，
供设置面板的「图形 / 显卡」分组展示，也用于启动时的软件渲染回退判定。

只读探测，不改变任何渲染状态：查询完成后立即 doneCurrent()。
"""
import ctypes

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
    return _INFO


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
    try:
        import winreg
        key = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, _GPU_PREF_KEY, 0,
                                 winreg.KEY_SET_VALUE)
        try:
            if enabled:
                winreg.SetValueEx(key, exe_path(), 0, winreg.REG_SZ, _HIGH_PERF_VALUE)
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


