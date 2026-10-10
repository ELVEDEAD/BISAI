"""
main.py —— 行星可视化桌面软件入口

启动流程：加载数据（太阳系 + 系外行星 + 亮星）→ 弹出启动器选择视图模式
    * 3D 立体视图（ui/main_window.py）
    * 2D 平面视图（ui/main_window_2d.py）
    * 引力系统（ui/main_window_gravity.py）

可用命令行参数直接进入某个模式而跳过启动器：
    python main.py 3d
    python main.py 2d
    python main.py gravity

图形环境适配：
    * 显式要求桌面 OpenGL，避免 Qt 在部分机器上静默回退到 ANGLE(GLES)，
      导致 3D 视口的 3.3 Core 着色器全部编译失败、画面全黑；
    * 若本机拿不到 OpenGL 3.3 上下文，自动以软件渲染（打包内含 opengl32sw.dll）
      重启一次，保证 3D 视图仍可显示；
    * 安装全局异常钩子：未捕获异常写入程序同目录日志并弹窗提示，
      避免 --windowed 打包后错误被静默吞掉（表现为"点了没反应"）。
"""
import os
import sys
import traceback

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QMessageBox

from data.loader import load_all_bodies, _equatorial_to_ecliptic
from data.stars_builtin import BRIGHT_STARS
from ui import style
from core import i18n, app_settings, gpu_info
from ui.launcher import LauncherWindow

# 软件渲染重试标记：探测到硬件不满足 OpenGL 3.3 时，带此变量重启一次
_SOFT_RETRY_ENV = "KNOWN_PLANETS_GL_SOFT_RETRY"


def _app_dir():
    """程序所在目录（打包后为 exe 目录，源码运行时为脚本目录）"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def _install_excepthook():
    """未捕获异常 → 写日志 + 弹窗。

    PyQt5 对槽函数中的未捕获异常默认会直接 abort（进程静默退出）；
    替换 sys.excepthook 后既能看到错误，也不会整个程序被杀掉。
    """
    def hook(etype, value, tb):
        text = "".join(traceback.format_exception(etype, value, tb))
        try:
            log_path = os.path.join(_app_dir(), "已知行星可视化_错误日志.txt")
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(text + "\n" + "-" * 60 + "\n")
        except Exception:
            pass
        try:
            if QApplication.instance() is not None:
                QMessageBox.critical(None, "程序发生错误",
                                     text[-1800:] +
                                     "\n\n（完整信息已写入程序目录下的"
                                     "「已知行星可视化_错误日志.txt」）")
        except Exception:
            pass

    sys.excepthook = hook


def _probe_gl33() -> bool:
    """探测当前环境能否提供桌面 OpenGL 3.3 Core 上下文（并缓存显卡信息）。"""
    return gpu_info.meets_requirement()


def _star_color(spectral: str):
    s = (spectral or "G")[0].upper()
    table = {
        "O": (0.70, 0.80, 1.00), "B": (0.75, 0.84, 1.00),
        "A": (0.90, 0.93, 1.00), "F": (1.00, 0.98, 0.90),
        "G": (1.00, 0.95, 0.78), "K": (1.00, 0.85, 0.62),
        "M": (1.00, 0.74, 0.52),
    }
    return table.get(s, (0.9, 0.9, 0.95))


def build_star_list():
    stars = []
    for name, ra, dec, mag, dist, spec in BRIGHT_STARS:
        unit = _equatorial_to_ecliptic(ra, dec)
        size = max(1.6, 5.0 - mag * 1.15)
        stars.append((name, unit, size, _star_color(spec)))
    return stars


def main():
    _install_excepthook()

    soft_retry = os.environ.get(_SOFT_RETRY_ENV) == "1"
    if soft_retry:
        # 软件渲染（Mesa，打包内含 opengl32sw.dll）
        os.environ["QT_OPENGL"] = "software"
    else:
        # 强制桌面 OpenGL，禁止静默回退到 ANGLE（仅支持 GLES，无法满足 3.3 Core）
        QApplication.setAttribute(Qt.AA_UseDesktopOpenGL, True)

    app = QApplication(sys.argv)
    app.setApplicationName("已知行星可视化")
    app.setStyle("Fusion")

    # 应用已保存的语言 / 主题偏好（首次启动为默认：中文 + 夜间）
    app_settings.apply_saved()
    app.setStyleSheet(style.MAIN_QSS)
    app.setLayoutDirection(i18n.layout_direction())

    # 探测图形设备（缓存显卡名 / OpenGL 版本，供设置面板「图形 / 显卡」展示）
    _gi = gpu_info.detect()
    print(f"图形设备: {_gi['renderer'] or '未知'}"
          f"（{_gi['vendor'] or '?'}） | OpenGL {_gi['obtained'] or '?'}"
          f"{' | 软件渲染' if _gi['software'] else ''}")

    # 硬件不满足 OpenGL 3.3 → 以软件渲染自动重启一次
    if not soft_retry and not _probe_gl33():
        os.environ[_SOFT_RETRY_ENV] = "1"
        os.environ["QT_OPENGL"] = "software"
        args = [sys.executable] + (sys.argv[1:] if getattr(sys, "frozen", False)
                                   else sys.argv)
        try:
            import subprocess
            subprocess.Popen(args, env=os.environ.copy(), close_fds=True)
            sys.exit(0)
        except Exception:
            pass  # 重启失败则继续；3D 视口会自行显示"不可用"提示

    bodies, stats = load_all_bodies()
    stars = build_star_list()
    msg = (f"数据加载: 太阳系 {stats['solar_count']} 个天体, "
           f"卫星 {stats['moon_count']} 颗, "
           f"系外行星 {stats['exo_count']} 颗（{stats['exo_source']}）, "
           f"宿主恒星 {stats['host_star_count']} 颗, "
           f"黑洞 {stats['blackhole_count']} 个, "
           f"背景亮星 {len(stars)} 颗")
    print(msg)
    if stats.get("exo_skipped_no_host"):
        print(f"（已跳过 {stats['exo_skipped_no_host']} 条缺宿主恒星位置、无法三维定位的系外行星）")

    launcher = LauncherWindow(bodies, stars)
    launcher.show()

    # 可选：命令行参数直接进入某个模式（跳过启动器）
    arg = next((a.lower() for a in sys.argv[1:]
                if a.lower() in ("3d", "2d", "gravity", "g")), None)
    if arg == "g":
        arg = "gravity"
    if arg:
        launcher.show_mode(arg)

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()