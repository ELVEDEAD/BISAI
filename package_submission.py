"""
package_submission.py —— 按 2026 华为开发者大赛·上海理工大学站 提交规范打包

生成"提交作品包/"目录（需求文档第 13.1/13.2 节）：
    {队伍名称}_{作品名称}_软件_{版本号}_{联系方式}.exe        ← 检测到 PyInstaller 时自动打包，否则留说明
    {队伍名称}_{作品名称}_说明文档_{版本号}_{联系方式}.md     ← 11 篇 md 合并为单文件
    {队伍名称}_{作品名称}_介绍PPT_{版本号}_{联系方式}.pptx    ← 真实 19 页 pptx
    {队伍名称}_{作品名称}_源码_{版本号}_{联系方式}.zip        ← 完整源码+数据+测试+构建说明
    最终提交_完整作品包.zip                                    ← 以上全部（表单一次上传用）

使用方法：
    python package_submission.py
    （改名：修改下方 TEAM / CONTACT 常量后重新运行，或直接重命名生成文件）
"""
import os
import re
import shutil
import zipfile
from datetime import datetime

# ================== 提交信息（改名改这里） ==================
TEAM = "参赛队伍"          # ← 替换为你的队伍名称
PROJECT = "已知行星可视化"  # 作品名称
VERSION = "v1.0.0"         # 版本号
CONTACT = "联系方式"       # ← 替换为你的邮箱或其他联系方式
# ==========================================================

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(ROOT, "提交作品包")


def _name(kind, ext):
    """按 13.2 命名规范生成文件名"""
    return f"{TEAM}_{PROJECT}_{kind}_{VERSION}_{CONTACT}.{ext}"


# ---------------- 说明文档合并 ----------------
DOCS = [
    "01_项目概述.md", "02_环境依赖说明.md", "03_一键安装脚本.md",
    "04_部署与运行步骤.md", "05_使用说明.md", "06_开源组件说明.md",
    "07_文件结构说明.md", "08_数据来源与精度说明.md", "09_局限性与风险声明.md",
    "10_码道使用说明.md", "11_参赛与原创声明.md",
]


def merge_docs(target_path):
    parts = [
        f"# {PROJECT} —— 作品说明文档\n",
        f"> 2026 华为开发者大赛 · 上海理工大学站　|　队伍：{TEAM}　|　"
        f"版本：{VERSION}　|　联系方式：{CONTACT}\n",
        "> 本文档由 11 篇分章文档合并生成，分章原稿见源码包 `作品说明文档/` 目录。\n",
        "\n## 目录\n",
    ]
    for i, d in enumerate(DOCS, 1):
        title = re.sub(r"^\d+_", "", d).replace(".md", "")
        parts.append(f"{i}. [{title}](#{i}.)\n")
    parts.append("\n---\n")
    for d in DOCS:
        src = os.path.join(ROOT, "作品说明文档", d)
        if os.path.exists(src):
            with open(src, encoding="utf-8") as f:
                content = f.read().strip()
        else:
            content = f"# {d}（缺失）"
        parts.append(f"\n\n---\n\n{content}\n")
    # 附：可复现性材料（验收自测记录）
    parts.append("\n\n---\n\n# 附录：可复现性验证记录\n")
    parts.append(
        "- 阶段自测脚本：`_test_stage1.py` ~ `_test_stage6.py`（各阶段功能验证）\n"
        "- 最终验收自测：`_test_final.py`（78 项检查，8 阶段全覆盖，全部通过）\n"
        "- PPT 结构验证：`_verify_pptx.py`（24 项检查，全部通过）\n"
        "- 数值验证依据：地火会合周期 780 天（真实 779.9）、火星冲日 2025-01-16（差 0.11 天）、"
        "上海夏至昼长 14.1 h、地球 10 月初日心黄经 13.87°，均与 JPL/NASA 公开数据一致\n"
        "- 数据规模：太阳系 23 个天体（含 13 颗天然卫星）+ 系外行星 6375+ 颗（4781 个恒星系）+ 62 颗亮星\n"
        f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
    with open(target_path, "w", encoding="utf-8") as f:
        f.write("".join(parts))
    return len("".join(parts))


# ---------------- 源码包 ----------------
EXCLUDE_DIRS = {"__pycache__", "build", "dist", "提交作品包",
                ".git", ".idea", ".vscode", "output"}
EXCLUDE_FILES = {".guide_completed", "package_submission.py"}
EXCLUDE_EXT = {".pyc", ".pyo", ".log"}


def iter_source_files():
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for fn in filenames:
            if fn in EXCLUDE_FILES:
                continue
            if os.path.splitext(fn)[1].lower() in EXCLUDE_EXT:
                continue
            # 跳过根目录下的成品压缩包，避免源码包把上一轮的完整作品包自我嵌套
            if dirpath == ROOT and fn.lower().endswith(".zip"):
                continue
            yield os.path.join(dirpath, fn)


def build_source_zip(zip_path):
    count = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        # 统一放到 源码/ 顶层目录，解压后不散落
        base = f"{TEAM}_{PROJECT}_源码_{VERSION}"
        for path in iter_source_files():
            rel = os.path.relpath(path, ROOT)
            z.write(path, os.path.join(base, rel))
            count += 1
        # 源码包内附打包说明
        z.writestr(os.path.join(base, "打包exe说明.txt"), BUILD_NOTE)
    return count


BUILD_NOTE = """已知行星可视化 —— 打包 exe 步骤（在本地 Windows 环境执行）
================================================================

1. 安装 Python 3.10+（勾选 Add to PATH）
2. 安装依赖：
       pip install -r requirements.txt pyinstaller
3. 打包：
       python build_exe.py
   或手动：
       pyinstaller --onefile --windowed --name "已知行星可视化" main.py
4. 得到 dist/已知行星可视化.exe
5. 按提交规范重命名：
       {TEAM}_{PROJECT}_软件_{VERSION}_{CONTACT}.exe
   并放入提交作品包目录
""".format(TEAM=TEAM, PROJECT=PROJECT, VERSION=VERSION, CONTACT=CONTACT)


# ---------------- 主流程 ----------------
def main():
    if os.path.exists(OUT_DIR):
        shutil.rmtree(OUT_DIR)
    os.makedirs(OUT_DIR)
    results = []

    # 1. 说明文档（合并 11 篇 md）
    doc_path = os.path.join(OUT_DIR, _name("说明文档", "md"))
    n_chars = merge_docs(doc_path)
    results.append((os.path.basename(doc_path), f"{n_chars / 1000:.1f} 千字符"))

    # 2. PPT
    ppt_src = os.path.join(ROOT, "作品说明文档", "已知行星可视化_答辩PPT.pptx")
    if os.path.exists(ppt_src):
        ppt_dst = os.path.join(OUT_DIR, _name("介绍PPT", "pptx"))
        shutil.copy2(ppt_src, ppt_dst)
        results.append((os.path.basename(ppt_dst), f"{os.path.getsize(ppt_dst) / 1024:.0f} KB"))
    else:
        results.append(("介绍PPT", "缺失！请先运行 _build_pptx.py"))

    # 3. 软件安装包（已有 exe 则直接复制，否则检测 PyInstaller 打包）
    exe_name = _name("软件", "exe")
    exe_cached = os.path.join(ROOT, "dist", f"{PROJECT}.exe")
    try:
        if os.path.exists(exe_cached):
            shutil.copy2(exe_cached, os.path.join(OUT_DIR, exe_name))
            results.append((exe_name, f"{os.path.getsize(exe_cached) / 1e6:.0f} MB"))
        else:
            import PyInstaller  # noqa: F401
            import subprocess, sys
            print("检测到 PyInstaller，正在打包 exe（约 3-5 分钟）…")
            subprocess.check_call([sys.executable, "_build_exe_run.py"], cwd=ROOT)
            if os.path.exists(exe_cached):
                shutil.copy2(exe_cached, os.path.join(OUT_DIR, exe_name))
                results.append((exe_name, f"{os.path.getsize(exe_cached) / 1e6:.0f} MB"))
    except ImportError:
        note_path = os.path.join(OUT_DIR, "软件安装包_待打包_请读我.txt")
        with open(note_path, "w", encoding="utf-8") as f:
            f.write(BUILD_NOTE +
                    "\n本机未安装 PyInstaller（或离线环境），无法自动生成 exe。\n"
                    "请在可联网的 Windows 环境按上述步骤打包，并按规范重命名。\n")
        results.append((exe_name, "待本地打包（已附说明 txt）"))

    # 4. 源码包
    src_zip = os.path.join(OUT_DIR, _name("源码", "zip"))
    n_files = build_source_zip(src_zip)
    results.append((os.path.basename(src_zip), f"{n_files} 个文件，"
                    f"{os.path.getsize(src_zip) / 1024:.0f} KB"))

    # 5. 完整作品包（自包含，表单一次上传）
    final_zip = os.path.join(ROOT, "最终提交_完整作品包.zip")
    if os.path.exists(final_zip):
        os.remove(final_zip)
    with zipfile.ZipFile(final_zip, "w", zipfile.ZIP_DEFLATED) as z:
        base = f"{TEAM}_{PROJECT}_完整作品包_{VERSION}"
        # 说明文件
        z.writestr(os.path.join(base, "提交清单_README.txt"), MANIFEST_NOTE)
        for fn in os.listdir(OUT_DIR):
            fp = os.path.join(OUT_DIR, fn)
            if os.path.isfile(fp):
                z.write(fp, os.path.join(base, fn))
    results.append((os.path.basename(final_zip),
                    f"{os.path.getsize(final_zip) / 1024:.0f} KB"))

    # 打印清单
    print("\n" + "=" * 62)
    print("  提交作品包生成完成 →", OUT_DIR)
    print("=" * 62)
    for name, info in results:
        print(f"  {name}")
    print(f"  {'-' * 58}")
    print(f"  {os.path.basename(final_zip)}  ← 表单一次上传用")
    print("=" * 62)
    print(f"  队伍名称 = {TEAM}　版本 = {VERSION}　联系方式 = {CONTACT}")
    print("  改名：修改 package_submission.py 顶部 TEAM/CONTACT 后重跑，")
    print("  或直接重命名生成的文件（注意 zip 内部 readme 中的名字）。\n")


MANIFEST_NOTE = """提交清单（2026 华为开发者大赛 · 上海理工大学站）
====================================================
作品名称：已知行星可视化
作品简介：基于真实天文数据的三维 / 二维行星可视化桌面软件，
          Blender 式视角操作 + 双行星相对运动分析 + 天象推演 + 地表视角。

包内文件：
  1. {TEAM}_{PROJECT}_软件_{VERSION}_{CONTACT}.exe
     —— Windows 桌面软件（离线可运行，内置天文数据）
     ※ 若包内为"待打包说明.txt"，请在本地按说明生成 exe 后一并提交
  2. {TEAM}_{PROJECT}_说明文档_{VERSION}_{CONTACT}.md
     —— 作品说明文档（11 章 + 可复现性验证附录）
  3. {TEAM}_{PROJECT}_介绍PPT_{VERSION}_{CONTACT}.pptx
     —— 答辩 PPT（19 页，Blender 深色主题）
  4. {TEAM}_{PROJECT}_源码_{VERSION}_{CONTACT}.zip
     —— 完整源码 + 内置数据 + 安装脚本 + 打包脚本 + 全部自测脚本

数据来源：JPL Horizons / NASA Exoplanet Archive / Hipparcos（公开科学数据）
精度分级：A（JPL 权威）/ B（有倾角测定）/ C（缺倾角或相位）
""".format(TEAM=TEAM, PROJECT=PROJECT, VERSION=VERSION, CONTACT=CONTACT)


if __name__ == "__main__":
    main()