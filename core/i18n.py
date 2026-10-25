"""
i18n.py —— 轻量国际化框架（联合国六种官方语言）

设计要点：
    * 以「中文原文」作为翻译键（source-string key），调用处只需 `tr("设置")`，
      无需先建 key 表，便于在既有中文硬编码工程上渐进式接入；
    * 未收录的字符串自动回退为原文（中文），因此可分批逐步补齐翻译，
      不会因为漏翻而出现空白或报错；
    * 语言切换即时生效：`set_language()` 会通知所有注册的监听者重建界面文字。

联合国六种官方语言：阿拉伯语 / 中文 / 英语 / 法语 / 俄语 / 西班牙语。
"""
from PyQt5.QtCore import Qt

# (代码, 本族语名称, 英文名称)
LANGUAGES = [
    ("zh", "中文", "Chinese"),
    ("en", "English", "English"),
    ("fr", "Français", "French"),
    ("ru", "Русский", "Russian"),
    ("es", "Español", "Spanish"),
    ("ar", "العربية", "Arabic"),
]

LANGUAGE_CODES = [c for c, _, _ in LANGUAGES]
_RTL_LANGS = {"ar"}

_current = "zh"
_listeners = []


# ---------------------------------------------------------------- 语言注册表
def available_languages():
    """返回 [(代码, 本族语名称, 英文名称), ...]"""
    return list(LANGUAGES)


def language_native_name(code: str) -> str:
    for c, native, _ in LANGUAGES:
        if c == code:
            return native
    return code


def is_rtl(code: str = None) -> bool:
    return (code or _current) in _RTL_LANGS


def get_language() -> str:
    return _current


def set_language(code: str):
    """切换当前语言；若发生变化则通知监听者（即时生效）。"""
    global _current
    if code not in LANGUAGE_CODES or code == _current:
        return
    _current = code
    for cb in list(_listeners):
        try:
            cb()
        except Exception:
            pass


def add_listener(cb):
    """注册语言变化回调（组件在此重建自身文字）。"""
    if cb not in _listeners:
        _listeners.append(cb)


def remove_listener(cb):
    if cb in _listeners:
        _listeners.remove(cb)


def layout_direction(code: str = None):
    """阿拉伯语等 RTL 语言返回 Qt.RightToLeft，其余 LeftToRight。"""
    return Qt.RightToLeft if is_rtl(code) else Qt.LeftToRight


def tr(text: str) -> str:
    """翻译：返回当前语言下 text 的译文；未收录则原样返回。"""
    if not text or _current == "zh":
        return text
    table = _T.get(_current)
    if not table:
        return text
    return table.get(text, text)


# ---------------------------------------------------------------- 翻译表
# 仅收录需翻译的条目；键为中文原文，值为各语言译文。
# 分模块维护，便于后续分批扩充。
_T = {
    # ============================== 英语 ==============================
    "en": {
        # —— 通用 / 窗口 ——
        "Astrarium": "Astrarium",
        "Astrarium —— 太阳系 + 系外行星": "Astrarium — Solar System + Exoplanets",
        "Astrarium —— 选择视图模式": "Astrarium — Select View Mode",
        "设置": "Settings", "确定": "OK", "取消": "Cancel", "关闭": "Close",
        "显示": "Display", "交互": "Interaction", "外观": "Appearance",
        "引导": "Guide", "关于": "About",
        "语言": "Language", "主题": "Theme", "夜间": "Night", "日间": "Day",
        "跟随系统": "Follow system",
        # —— 主工具栏 ——
        "搜索天体…": "Search bodies…", "搜索": "Search", "搜索:": "Search:",
        "轨道线": "Orbits", "标签": "Labels", "网格": "Grid",
        "背景星": "Background stars", "星云": "Nebula", "按需渲染": "On-demand",
        "尾迹 · 自动清除": "Trails · Auto-clear",
        "尾迹 · 一直显示": "Trails · Persist",
        "尾迹 · 关闭": "Trails · Off",
        "真实比例": "True scale", "实体球": "Solid spheres",
        "锁定跟随": "Lock follow", "卫星": "Moons", "行星环": "Planetary rings",
        "人造卫星": "Artificial satellites", "自转轴": "Rotation axis",
        "太阳系轨道": "Solar orbits", "系外行星轨道": "Exoplanet orbits",
        "小天体": "Small bodies",
        "少": "Few", "中": "Medium", "多": "Many",
        "灵敏度:": "Sensitivity:", "很慢": "Very slow", "慢": "Slow",
        "标准": "Standard", "快": "Fast", "很快": "Very fast",
        "帮助 (F1)": "Help (F1)", "教学场景": "Teaching scenes",
        "新手引导": "Getting started", "切换模式": "Switch mode",
        # —— 右侧标签页 ——
        "详情": "Details", "对比分析": "Comparison", "测距": "Distance",
        "天象推演": "Phenomena", "观测特征": "Observation",
        "地面视角": "Ground view", "地表视角": "Surface view",
        # —— 启动器 ——
        "太阳系 + 系外行星 · 请选择视图模式": "Solar System + Exoplanets · Choose a view mode",
        "3D 立体视图": "3D View",
        "2D 平面视图": "2D View", "引力系统": "Gravity System",
        "打开三维立体视图（快捷键 3）": "Open the 3D view (key 3)",
        "打开二维平面视图（快捷键 2）": "Open the 2D view (key 2)",
        "打开引力系统视图（快捷键 G）": "Open the gravity view (key G)",
        "三个视图共用同一套数据与时间系统；可用主窗口工具栏的「切换模式」随时返回本窗口。":
            "All three views share the same data and time system; use “Switch mode” in the toolbar to return here.",
        # —— 天体树 ——
        "搜索天体 / 恒星系名称…": "Search bodies / star systems…",
        "恒星系（系群）": "Star systems",
        "太阳系": "Solar System", "黑洞": "Black holes",
        "近邻恒星": "Nearby stars", "星际天体": "Interstellar objects",
        "极端海外天体": "Extreme TNOs",
        "个": "", "个天体": "bodies", "颗行星": "planets", "颗卫星": "moons",
        "光年": "ly", "匹配": "matched",
        "共": "Total", "恒星系": "systems",
        # —— 时间轴 ——
        "播放 / 暂停（空格键）": "Play / Pause (Space)",
        "暂停（空格键）": "Pause (Space)", "播放（空格键）": "Play (Space)",
        "倒放 / 正放切换": "Reverse / forward",
        "时间倍速": "Time speed", "跳转:": "Jump:", "跳转": "Jump",
        "日历": "Calendar", "今天": "Today", "年": "Year",
        "星历范围: {lo}–{hi}": "Ephemeris range: {lo}–{hi}",
        "⚠ 超出星历范围 ({lo}–{hi})": "⚠ Outside ephemeris range ({lo}–{hi})",
        # —— 设置面板 ——
        "显示模式": "Display mode", "选择窗口/全屏模式": "Window / fullscreen mode",
        "窗口模式": "Windowed", "无边框窗口": "Borderless windowed",
        "无边框全屏": "Borderless fullscreen", "独占全屏": "Exclusive fullscreen",
        "最大化窗口": "Maximized",
        "分辨率": "Resolution", "独占全屏模式下可单独设置渲染分辨率":
            "Render resolution, configurable in exclusive fullscreen",
        "自动（推荐）": "Auto (recommended)",
        "显示器": "Monitor", "多显示器环境下选择全屏显示的屏幕":
            "Choose which screen to use in fullscreen",
        "帧率限制": "Frame limit", "上限帧率，避免占用过高显卡资源（默认 90 FPS）":
            "Cap the frame rate to reduce GPU load (default 90 FPS)",
        "无限制": "Unlimited", "当前帧率": "Current FPS", "实时 FPS 读数": "Live FPS reading",
        "垂直同步": "V-Sync", "与显示器刷新率同步，防止画面撕裂":
            "Sync with the display refresh rate to prevent tearing",
        "启用 V-Sync": "Enable V-Sync",
        "DPI 缩放": "DPI scaling", "跟随系统 DPI 或强制 100%": "Follow system DPI or force 100%",
        "自动（跟随系统）": "Auto (follow system)", "100%（强制）": "100% (forced)",
        "按需渲染": "On-demand rendering", "空闲时降到低帧率重绘，省算力":
            "Redraw at a low frame rate when idle to save power",
        "启用按需渲染": "Enable on-demand rendering",
        "鼠标灵敏度": "Mouse sensitivity", "拖拽旋转/平移速度":
            "Drag rotate / pan speed",
        "新手引导": "Getting started", "可随时重新开启引导教程":
            "You can reopen the tutorial at any time",
        "重新打开引导": "Reopen tutorial",
        "界面语言": "Interface language", "选择界面显示语言（联合国六种官方语言）":
            "Choose the interface language (six UN official languages)",
        "界面主题": "Interface theme", "在夜间与日间配色之间切换":
            "Switch between night and day color schemes",
        "数据来源：JPL / NASA Exoplanet Archive / IAU / MPC":
            "Data sources: JPL / NASA Exoplanet Archive / IAU / MPC",
        # —— 详情面板 / 时间轴 / 启动器补充 ——
        "未选中天体": "No body selected", "未知": "Unknown", "—": "—",
        "聚焦": "Focus", "加入对比": "Add to comparison", "尺寸对比": "Size comparison",
        "打开「观测特征」标签页：凌星光变曲线 / 视向速度曲线 / 宜居带\n（太阳系天体仅有宜居带与光通量）":
            "Open the “Observation” tab: transit light curve / radial-velocity curve / habitable zone\n(solar-system bodies show only the habitable zone and flux)",
        "打开「地面视角」标签页：站在选定地点抬头看天的星空图\n（行星/太阳/亮星的地平坐标 + 当日日轨线与升落时刻）\n当前选中天体若在地平线上方会高亮标注":
            "Open the “Ground view” tab: a sky chart from a chosen location\n(horizontal coordinates of planets/Sun/bright stars + daily path and rise/set times)\nThe selected body is highlighted if it is above the horizon",
        "打开「地表视角」标签页：站到该行星/卫星表面，第一人称环视天空\n（天空底色随太阳高度变化，亮星为柔和光晕，地平线为静态地形剪影）\n仅对具备自转轴数据的天体可用":
            "Open the “Surface view” tab: stand on that planet/moon and look around in first person\n(sky color varies with solar altitude, stars are soft glows, the horizon is a static silhouette)\nAvailable only for bodies with rotation-axis data",
        "点击弹出日历面板，选择目标日期": "Open a calendar to pick a target date",
        '视角导航轴：点击 X/Y/Z 切换轴向视角': 'View gizmo: click X/Y/Z to switch axis views',
        '侧视图（+X 轴）': 'Side view (+X)',
        '侧视图（-X 轴）': 'Side view (−X)',
        '侧视图（+Y 轴）': 'Side view (+Y)',
        '侧视图（-Y 轴）': 'Side view (−Y)',
        '俯视图（+Z 轴）': 'Top view (+Z)',
        '仰视图（-Z 轴）': 'Bottom view (−Z)',
        '显示导航轴': 'Show navigation gizmo',
        '3D 视角导航轴': '3D view gizmo',
        '视口右上角 Blender 风格 XYZ 导航球；关闭后快捷键 1/3/7 仍可用': 'Blender-style XYZ navigation ball at the top-right of the 3D viewport; keyboard 1/3/7 still works when hidden',
        "跳转到当前真实日期": "Jump to today's real date",
        "系": "system", "宿主恒星": "Host star", "系外行星": "Exoplanets",
        "3D 立体视图\n\n三维轨道空间 · 可旋转缩放\n实体球 + 程序化表面贴图\n系外行星与背景亮星":
            "3D View\n\nThree-dimensional orbital space · rotate & zoom\nSolid spheres + procedural surface textures\nExoplanets and bright background stars",
        "2D 平面视图\n\n俯视黄道面的轨道图\n行星轨道椭圆 · 自适应刻度\n轻量平面 · 便于看轨道关系":
            "2D View\n\nTop-down orbital map of the ecliptic\nElliptical orbits · adaptive scale\nLightweight plane · easy to read orbits",
        "引力系统\n\n时空弯曲网格\n天体按 M/r 引力势把网格压出凹陷\n质量越大 · 距离越近 · 凹陷越深":
            "Gravity System\n\nCurved spacetime grid\nBodies dent the grid by their M/r potential\nThe heavier and closer, the deeper the well",
        # —— 图形 / 显卡 ——
        "图形 / 显卡": "Graphics / GPU",
        "当前显卡": "Current GPU",
        "图形接口": "Graphics API",
        "加速状态": "Acceleration",
        "显卡要求": "GPU requirement",
        "硬件加速（GPU）": "Hardware accelerated (GPU)",
        "软件渲染（CPU）": "Software rendering (CPU)",
        "检测失败": "Detection failed",
        "支持桌面 OpenGL 3.3 Core 的显卡；建议使用独立显卡并保持驱动为最新":
            "A GPU supporting desktop OpenGL 3.3 Core; a dedicated GPU with up-to-date drivers is recommended",
        "软件渲染时三维画面由 CPU 计算，帧率会明显偏低，请更新显卡驱动或在独立显卡上运行":
            "In software rendering the 3D view is computed on the CPU and the frame rate is much lower; please update your graphics driver or run on a dedicated GPU",
        "检测到的显卡": "Detected GPUs",
        "本机安装的全部显示适配器": "All display adapters installed on this PC",
        "检测到独立显卡但当前未使用：": "A dedicated GPU is present but not in use: ",
        "如需改用独立显卡：NVIDIA 控制面板 → 管理 3D 设置 → 程序设置，将本程序设为「高性能 NVIDIA 处理器」；或 Windows 设置 → 显示 → 图形，将本程序设为「高性能」。":
            "To use the dedicated GPU: in NVIDIA Control Panel → Manage 3D settings → Program Settings, set this app to \"High-performance NVIDIA processor\"; or in Windows Settings → Display → Graphics, set this app to \"High performance\".",
        "改用独立显卡（重启生效）": "Use dedicated GPU (restart to apply)",
        "已启用独立显卡（点击撤销）": "Dedicated GPU enabled (click to undo)",
        "设置对象：": "Applies to: ",
        "图形首选项": "Graphics preference",
        "设置失败": "Setup failed",
        "写入设置失败：": "Failed to write the setting: ",
        "已设为优先使用独立显卡，请关闭并重新启动程序后生效。":
            "This app is now set to prefer the dedicated GPU. Please close and restart the program for it to take effect.",
        "已恢复由系统自动选择显卡，请重新启动程序后生效。":
            "Reverted to automatic GPU selection by the system. Please restart the program for it to take effect.",
        "已切换显卡首选项，请关闭并重新启动程序后生效。":
            "GPU preference changed. Please close and restart the program for it to take effect.",
        # —— P2/P3 新增：字体 / 性能 / 大模型 ——
        "保存": "Save", "已保存": "Saved", "测试连接": "Test connection",
        "天文助手": "Astronomy Assistant", "助手": "Assistant",
        "发送": "Send", "清空对话": "Clear chat", "就绪": "Ready",
        "我": "Me", "系统": "System", "已回复": "Replied",
        "自动适配": "Auto adapt",
        "基于大模型 API（在「设置 → 大模型」中配置）":
            "Powered by an LLM API (configure in Settings → LLM)",
        "输入天文问题…（Ctrl+Enter 发送）":
            "Ask an astronomy question… (Ctrl+Enter to send)",
        "思考中…（正在调用大模型 API）": "Thinking… (calling the LLM API)",
        "测试中…（正在请求大模型 API）": "Testing… (requesting the LLM API)",
        "调用失败：": "Request failed: ",
        "连接失败：": "Connection failed: ", "连接成功：": "Connected: ",
        "请先填写 API Key": "Enter the API key first",
        "未配置 API Key，请在「设置 → 大模型」中填写。":
            "No API key configured. Enter it in Settings → LLM.",
        "选择大模型服务商（OpenAI 兼容接口）":
            "Choose an LLM provider (OpenAI-compatible API)",
        "OpenAI 兼容的接口根地址（如 https://api.deepseek.com/v1）":
            "OpenAI-compatible API base URL (e.g. https://api.deepseek.com/v1)",
        "如 deepseek-chat / gpt-4o-mini": "e.g. deepseek-chat / gpt-4o-mini",
        "仅保存在本机设置文件，不会上传":
            "Stored only in the local settings file; never uploaded",
        "图形 API 与着色器语言版本": "Graphics API and shader language version",
        "当前实际用于渲染的图形设备": "Graphics device actually used for rendering",
        "是否由 GPU 硬件加速渲染": "Whether rendering is GPU hardware-accelerated",
        "手动选择本程序使用的显卡（Windows 图形设置，重启程序后生效）":
            "Choose the GPU used by this app (Windows graphics settings; takes effect after restart)",
        "拖动滑块调节界面文字大小（0.8～1.6 倍），即时生效":
            "Drag the slider to adjust UI text size (0.8–1.6×), applied instantly",
        "在显卡可承受范围内尽量多显示（目标 30 FPS 以上，上限 100 万）":
            "Show as many bodies as the GPU can handle (target 30+ FPS, up to 1,000,000)",
        "当前帧率与正在渲染的天体数量":
            "Current frame rate and number of bodies being rendered",
        "高性能：上限 100 万颗；均衡：50 万；省电：12 万":
            "High: up to 1M; Balanced: 500K; Power-saving: 120K",
    },
    # ============================== 法语 ==============================
    "fr": {
        "Astrarium": "Astrarium",
        "Astrarium —— 太阳系 + 系外行星": "Astrarium — Système solaire + exoplanètes",
        "Astrarium —— 选择视图模式": "Astrarium — Choisir le mode d'affichage",
        "设置": "Paramètres", "确定": "OK", "取消": "Annuler", "关闭": "Fermer",
        "显示": "Affichage", "交互": "Interaction", "外观": "Apparence",
        "引导": "Guide", "关于": "À propos",
        "语言": "Langue", "主题": "Thème", "夜间": "Nuit", "日间": "Jour",
        "跟随系统": "Suivre le système",
        "搜索天体…": "Rechercher des corps…", "搜索": "Rechercher", "搜索:": "Rechercher :",
        "轨道线": "Orbites", "标签": "Étiquettes", "网格": "Grille",
        "背景星": "Étoiles de fond", "星云": "Nébuleuse", "按需渲染": "À la demande",
        "尾迹 · 自动清除": "Traînées · Effacement auto",
        "尾迹 · 一直显示": "Traînées · Persistantes",
        "尾迹 · 关闭": "Traînées · Désactivées",
        "真实比例": "Échelle réelle", "实体球": "Sphères pleines",
        "锁定跟随": "Verrouiller le suivi", "卫星": "Lunes",
        "行星环": "Anneaux planétaires", "人造卫星": "Satellites artificiels",
        "自转轴": "Axe de rotation", "太阳系轨道": "Orbites du système solaire",
        "系外行星轨道": "Orbites des exoplanètes", "小天体": "Petits corps",
        "少": "Peu", "中": "Moyen", "多": "Beaucoup",
        "灵敏度:": "Sensibilité :", "很慢": "Très lent", "慢": "Lent",
        "标准": "Standard", "快": "Rapide", "很快": "Très rapide",
        "帮助 (F1)": "Aide (F1)", "教学场景": "Scènes pédagogiques",
        "新手引导": "Prise en main", "切换模式": "Changer de mode",
        "详情": "Détails", "对比分析": "Comparaison", "测距": "Distance",
        "天象推演": "Phénomènes", "观测特征": "Observation",
        "地面视角": "Vue du sol", "地表视角": "Vue de surface",
        "太阳系 + 系外行星 · 请选择视图模式": "Système solaire + exoplanètes · Choisissez un mode",
        "3D 立体视图": "Vue 3D", "2D 平面视图": "Vue 2D", "引力系统": "Système gravitationnel",
        "打开三维立体视图（快捷键 3）": "Ouvrir la vue 3D (touche 3)",
        "打开二维平面视图（快捷键 2）": "Ouvrir la vue 2D (touche 2)",
        "打开引力系统视图（快捷键 G）": "Ouvrir la vue gravitationnelle (touche G)",
        "三个视图共用同一套数据与时间系统；可用主窗口工具栏的「切换模式」随时返回本窗口。":
            "Les trois vues partagent les mêmes données et le même temps ; utilisez « Changer de mode » pour revenir ici.",
        "搜索天体 / 恒星系名称…": "Rechercher des corps / systèmes…",
        "恒星系（系群）": "Systèmes stellaires",
        "太阳系": "Système solaire", "黑洞": "Trous noirs",
        "近邻恒星": "Étoiles proches", "星际天体": "Objets interstellaires",
        "极端海外天体": "Objets transneptuniens extrêmes",
        "个天体": "corps", "颗行星": "planètes", "颗卫星": "lunes",
        "光年": "al", "匹配": "correspondances",
        "共": "Total", "恒星系": "systèmes",
        "播放 / 暂停（空格键）": "Lecture / Pause (Espace)",
        "暂停（空格键）": "Pause (Espace)", "播放（空格键）": "Lecture (Espace)",
        "倒放 / 正放切换": "Inverser / avant",
        "时间倍速": "Vitesse du temps", "跳转:": "Aller à :", "跳转": "Aller",
        "日历": "Calendrier", "今天": "Aujourd'hui", "年": "Année",
        "星历范围: {lo}–{hi}": "Plage d'éphéméride : {lo}–{hi}",
        "⚠ 超出星历范围 ({lo}–{hi})": "⚠ Hors plage d'éphéméride ({lo}–{hi})",
        "显示模式": "Mode d'affichage", "选择窗口/全屏模式": "Mode fenêtre / plein écran",
        "窗口模式": "Fenêtré", "无边框窗口": "Fenêtré sans bordure",
        "无边框全屏": "Plein écran sans bordure", "独占全屏": "Plein écran exclusif",
        "最大化窗口": "Maximisé",
        "分辨率": "Résolution", "独占全屏模式下可单独设置渲染分辨率":
            "Résolution de rendu, réglable en plein écran exclusif",
        "自动（推荐）": "Auto (recommandé)",
        "显示器": "Écran", "多显示器环境下选择全屏显示的屏幕":
            "Choisir l'écran utilisé en plein écran",
        "帧率限制": "Limite de fréquence", "上限帧率，避免占用过高显卡资源（默认 90 FPS）":
            "Limiter la fréquence pour réduire la charge GPU (90 FPS par défaut)",
        "无限制": "Illimité", "当前帧率": "FPS actuel", "实时 FPS 读数": "FPS en direct",
        "垂直同步": "V-Sync", "与显示器刷新率同步，防止画面撕裂":
            "Synchroniser avec l'écran pour éviter le déchirement",
        "启用 V-Sync": "Activer V-Sync",
        "DPI 缩放": "Mise à l'échelle DPI", "跟随系统 DPI 或强制 100%":
            "Suivre le DPI système ou forcer 100 %",
        "自动（跟随系统）": "Auto (suivre le système)", "100%（强制）": "100 % (forcé)",
        "按需渲染": "Rendu à la demande", "空闲时降到低帧率重绘，省算力":
            "Redessiner à basse fréquence au repos pour économiser",
        "启用按需渲染": "Activer le rendu à la demande",
        "鼠标灵敏度": "Sensibilité souris", "拖拽旋转/平移速度":
            "Vitesse rotation / déplacement",
        "新手引导": "Prise en main", "可随时重新开启引导教程":
            "Vous pouvez rouvrir le tutoriel à tout moment",
        "重新打开引导": "Rouvrir le tutoriel",
        "界面语言": "Langue de l'interface",
        "选择界面显示语言（联合国六种官方语言）":
            "Choisir la langue de l'interface (six langues officielles de l'ONU)",
        "界面主题": "Thème de l'interface",
        "在夜间与日间配色之间切换": "Basculer entre les thèmes nuit et jour",
        "数据来源：JPL / NASA Exoplanet Archive / IAU / MPC":
            "Sources : JPL / NASA Exoplanet Archive / IAU / MPC",
        # —— 详情面板 / 时间轴 / 启动器补充 ——
        "未选中天体": "Aucun corps sélectionné", "未知": "Inconnu", "—": "—",
        "聚焦": "Centrer", "加入对比": "Ajouter à la comparaison",
        "尺寸对比": "Comparaison de taille",
        "打开「观测特征」标签页：凌星光变曲线 / 视向速度曲线 / 宜居带\n（太阳系天体仅有宜居带与光通量）":
            "Ouvrir l'onglet « Observation » : courbe de transit / courbe de vitesse radiale / zone habitable\n(les corps du système solaire n'ont que la zone habitable et le flux)",
        "打开「地面视角」标签页：站在选定地点抬头看天的星空图\n（行星/太阳/亮星的地平坐标 + 当日日轨线与升落时刻）\n当前选中天体若在地平线上方会高亮标注":
            "Ouvrir l'onglet « Vue du sol » : carte du ciel depuis un lieu choisi\n(coordonnées horizontales des planètes/Soleil/étoiles brillantes + trajectoire du jour et heures de lever/coucher)\nLe corps sélectionné est surligné s'il est au-dessus de l'horizon",
        "打开「地表视角」标签页：站到该行星/卫星表面，第一人称环视天空\n（天空底色随太阳高度变化，亮星为柔和光晕，地平线为静态地形剪影）\n仅对具备自转轴数据的天体可用":
            "Ouvrir l'onglet « Vue de surface » : se tenir sur cette planète/lune et regarder autour en vue subjective\n(la couleur du ciel varie avec la hauteur du Soleil, les étoiles sont des halos doux, l'horizon est une silhouette statique)\nDisponible uniquement pour les corps avec données d'axe de rotation",
        "点击弹出日历面板，选择目标日期": "Ouvrir un calendrier pour choisir une date cible",
        '视角导航轴：点击 X/Y/Z 切换轴向视角': 'Gizmo de vue : cliquez X/Y/Z pour changer de vue axiale',
        '侧视图（+X 轴）': 'Vue latérale (+X)',
        '侧视图（-X 轴）': 'Vue latérale (−X)',
        '侧视图（+Y 轴）': 'Vue latérale (+Y)',
        '侧视图（-Y 轴）': 'Vue latérale (−Y)',
        '俯视图（+Z 轴）': 'Vue de dessus (+Z)',
        '仰视图（-Z 轴）': 'Vue de dessous (−Z)',
        '显示导航轴': 'Afficher le gizmo de navigation',
        '3D 视角导航轴': 'Gizmo de vue 3D',
        '视口右上角 Blender 风格 XYZ 导航球；关闭后快捷键 1/3/7 仍可用': 'Sphère de navigation XYZ style Blender en haut à droite de la vue 3D ; les touches 1/3/7 restent actives si masquée',
        "跳转到当前真实日期": "Aller à la date réelle d'aujourd'hui",
        "系": "système", "宿主恒星": "Étoile hôte", "系外行星": "Exoplanètes",
        "3D 立体视图\n\n三维轨道空间 · 可旋转缩放\n实体球 + 程序化表面贴图\n系外行星与背景亮星":
            "Vue 3D\n\nEspace orbital tridimensionnel · rotation et zoom\nSphères pleines + textures de surface procédurales\nExoplanètes et étoiles brillantes de fond",
        "2D 平面视图\n\n俯视黄道面的轨道图\n行星轨道椭圆 · 自适应刻度\n轻量平面 · 便于看轨道关系":
            "Vue 2D\n\nCarte orbitale vue de dessus de l'écliptique\nOrbites elliptiques · échelle adaptative\nPlan léger · lecture facile des orbites",
        "引力系统\n\n时空弯曲网格\n天体按 M/r 引力势把网格压出凹陷\n质量越大 · 距离越近 · 凹陷越深":
            "Système gravitationnel\n\nGrille d'espace-temps courbée\nLes corps creusent la grille selon leur potentiel M/r\nPlus la masse est grande et proche, plus le puits est profond",
        # —— 图形 / 显卡 ——
        "图形 / 显卡": "Graphismes / GPU",
        "当前显卡": "GPU actuel",
        "图形接口": "API graphique",
        "加速状态": "Accélération",
        "显卡要求": "Configuration GPU requise",
        "硬件加速（GPU）": "Accélération matérielle (GPU)",
        "软件渲染（CPU）": "Rendu logiciel (CPU)",
        "检测失败": "Détection échouée",
        "支持桌面 OpenGL 3.3 Core 的显卡；建议使用独立显卡并保持驱动为最新":
            "Un GPU compatible OpenGL 3.3 Core de bureau ; un GPU dédié avec des pilotes à jour est recommandé",
        "软件渲染时三维画面由 CPU 计算，帧率会明显偏低，请更新显卡驱动或在独立显卡上运行":
            "En rendu logiciel, la vue 3D est calculée par le CPU et le taux de rafraîchissement est nettement plus faible ; mettez à jour le pilote graphique ou utilisez un GPU dédié",
        "检测到的显卡": "GPU détectés",
        "本机安装的全部显示适配器": "Tous les adaptateurs d'affichage installés sur ce PC",
        "检测到独立显卡但当前未使用：": "Un GPU dédié est présent mais non utilisé : ",
        "如需改用独立显卡：NVIDIA 控制面板 → 管理 3D 设置 → 程序设置，将本程序设为「高性能 NVIDIA 处理器」；或 Windows 设置 → 显示 → 图形，将本程序设为「高性能」。":
            "Pour utiliser le GPU dédié : dans le Panneau de configuration NVIDIA → Gérer les paramètres 3D → Paramètres du programme, réglez cette application sur « Processeur NVIDIA hautes performances » ; ou dans Paramètres Windows → Affichage → Graphiques, réglez cette application sur « Hautes performances ».",
        "改用独立显卡（重启生效）": "Utiliser le GPU dédié (redémarrage requis)",
        "已启用独立显卡（点击撤销）": "GPU dédié activé (cliquer pour annuler)",
        "设置对象：": "S'applique à : ",
        "图形首选项": "Préférence graphique",
        "设置失败": "Échec de la configuration",
        "写入设置失败：": "Échec de l'écriture du paramètre : ",
        "已设为优先使用独立显卡，请关闭并重新启动程序后生效。":
            "Cette application est désormais réglée pour privilégier le GPU dédié. Veuillez fermer puis redémarrer le programme pour que cela prenne effet.",
        "已恢复由系统自动选择显卡，请重新启动程序后生效。":
            "Sélection automatique du GPU par le système rétablie. Veuillez redémarrer le programme pour que cela prenne effet.",
        "已切换显卡首选项，请关闭并重新启动程序后生效。":
            "Préférence GPU modifiée. Veuillez fermer puis redémarrer le programme pour que cela prenne effet.",
        # —— P2/P3 新增：字体 / 性能 / 大模型 ——
        "保存": "Enregistrer", "已保存": "Enregistré", "测试连接": "Tester la connexion",
        "天文助手": "Assistant d'astronomie", "助手": "Assistant",
        "发送": "Envoyer", "清空对话": "Effacer la conversation", "就绪": "Prêt",
        "我": "Moi", "系统": "Système", "已回复": "Répondu",
        "自动适配": "Adaptation automatique",
        "基于大模型 API（在「设置 → 大模型」中配置）":
            "Basé sur une API de LLM (à configurer dans Paramètres → LLM)",
        "输入天文问题…（Ctrl+Enter 发送）":
            "Posez une question d'astronomie… (Ctrl+Entrée pour envoyer)",
        "思考中…（正在调用大模型 API）": "Réflexion… (appel de l'API du LLM)",
        "测试中…（正在请求大模型 API）": "Test en cours… (requête à l'API du LLM)",
        "调用失败：": "Échec de l'appel : ",
        "连接失败：": "Échec de connexion : ", "连接成功：": "Connexion réussie : ",
        "请先填写 API Key": "Saisissez d'abord la clé API",
        "未配置 API Key，请在「设置 → 大模型」中填写。":
            "Aucune clé API configurée. Saisissez-la dans Paramètres → LLM.",
        "选择大模型服务商（OpenAI 兼容接口）":
            "Choisir un fournisseur de LLM (API compatible OpenAI)",
        "OpenAI 兼容的接口根地址（如 https://api.deepseek.com/v1）":
            "URL racine compatible OpenAI (ex. https://api.deepseek.com/v1)",
        "如 deepseek-chat / gpt-4o-mini": "ex. deepseek-chat / gpt-4o-mini",
        "仅保存在本机设置文件，不会上传":
            "Stockée uniquement dans le fichier de paramètres local ; jamais envoyée",
        "图形 API 与着色器语言版本": "API graphique et version du langage de shader",
        "当前实际用于渲染的图形设备": "Périphérique graphique réellement utilisé pour le rendu",
        "是否由 GPU 硬件加速渲染": "Si le rendu est accéléré par le matériel GPU",
        "手动选择本程序使用的显卡（Windows 图形设置，重启程序后生效）":
            "Choisir le GPU utilisé par cette application (paramètres graphiques Windows ; effet après redémarrage)",
        "拖动滑块调节界面文字大小（0.8～1.6 倍），即时生效":
            "Faites glisser le curseur pour ajuster la taille du texte de l'interface (0,8–1,6×), effet immédiat",
        "在显卡可承受范围内尽量多显示（目标 30 FPS 以上，上限 100 万）":
            "Afficher autant de corps que le GPU le permet (objectif 30 FPS ou plus, jusqu'à 1 000 000)",
        "当前帧率与正在渲染的天体数量":
            "Fréquence d'images actuelle et nombre de corps affichés",
        "高性能：上限 100 万颗；均衡：50 万；省电：12 万":
            "Élevé : jusqu'à 1 M ; Équilibré : 500 K ; Économe : 120 K",
    },
    # ============================== 俄语 ==============================
    "ru": {
        "Astrarium": "Astrarium",
        "Astrarium —— 太阳系 + 系外行星": "Astrarium — Солнечная система + экзопланеты",
        "Astrarium —— 选择视图模式": "Astrarium — Выбор режима",
        "设置": "Настройки", "确定": "ОК", "取消": "Отмена", "关闭": "Закрыть",
        "显示": "Отображение", "交互": "Управление", "外观": "Внешний вид",
        "引导": "Обучение", "关于": "О программе",
        "语言": "Язык", "主题": "Тема", "夜间": "Ночь", "日间": "День",
        "跟随系统": "Как в системе",
        "搜索天体…": "Поиск тел…", "搜索": "Поиск", "搜索:": "Поиск:",
        "轨道线": "Орбиты", "标签": "Подписи", "网格": "Сетка",
        "背景星": "Фоновые звёзды", "星云": "Туманность", "按需渲染": "По требованию",
        "尾迹 · 自动清除": "Следы · Автоочистка",
        "尾迹 · 一直显示": "Следы · Постоянно",
        "尾迹 · 关闭": "Следы · Выкл.",
        "真实比例": "Реальный масштаб", "实体球": "Сплошные сферы",
        "锁定跟随": "Закрепить слежение", "卫星": "Спутники",
        "行星环": "Кольца планет", "人造卫星": "Искусственные спутники",
        "自转轴": "Ось вращения", "太阳系轨道": "Орбиты Солнечной системы",
        "系外行星轨道": "Орбиты экзопланет", "小天体": "Малые тела",
        "少": "Мало", "中": "Средне", "多": "Много",
        "灵敏度:": "Чувствительность:", "很慢": "Очень медленно", "慢": "Медленно",
        "标准": "Стандарт", "快": "Быстро", "很快": "Очень быстро",
        "帮助 (F1)": "Справка (F1)", "教学场景": "Учебные сцены",
        "新手引导": "Первые шаги", "切换模式": "Сменить режим",
        "详情": "Подробности", "对比分析": "Сравнение", "测距": "Расстояние",
        "天象推演": "Явления", "观测特征": "Наблюдения",
        "地面视角": "Вид с Земли", "地表视角": "Вид с поверхности",
        "太阳系 + 系外行星 · 请选择视图模式": "Солнечная система + экзопланеты · Выберите режим",
        "3D 立体视图": "3D-вид", "2D 平面视图": "2D-вид", "引力系统": "Гравитация",
        "打开三维立体视图（快捷键 3）": "Открыть 3D-вид (клавиша 3)",
        "打开二维平面视图（快捷键 2）": "Открыть 2D-вид (клавиша 2)",
        "打开引力系统视图（快捷键 G）": "Открыть гравитационный вид (клавиша G)",
        "三个视图共用同一套数据与时间系统；可用主窗口工具栏的「切换模式」随时返回本窗口。":
            "Все три вида используют одни данные и время; вернитесь сюда кнопкой «Сменить режим».",
        "搜索天体 / 恒星系名称…": "Поиск тел / звёздных систем…",
        "恒星系（系群）": "Звёздные системы",
        "太阳系": "Солнечная система", "黑洞": "Чёрные дыры",
        "近邻恒星": "Ближайшие звёзды", "星际天体": "Межзвёздные объекты",
        "极端海外天体": "Экстремальные объекты",
        "个天体": "тел", "颗行星": "планет", "颗卫星": "спутников",
        "光年": "св. лет", "匹配": "совпадений",
        "共": "Всего", "恒星系": "систем",
        "播放 / 暂停（空格键）": "Воспроизведение / Пауза (Пробел)",
        "暂停（空格键）": "Пауза (Пробел)", "播放（空格键）": "Воспроизведение (Пробел)",
        "倒放 / 正放切换": "Реверс / вперёд",
        "时间倍速": "Скорость времени", "跳转:": "Перейти:", "跳转": "Перейти",
        "日历": "Календарь", "今天": "Сегодня", "年": "Год",
        "星历范围: {lo}–{hi}": "Диапазон эфемерид: {lo}–{hi}",
        "⚠ 超出星历范围 ({lo}–{hi})": "⚠ Вне диапазона эфемерид ({lo}–{hi})",
        "显示模式": "Режим отображения", "选择窗口/全屏模式": "Оконный / полноэкранный режим",
        "窗口模式": "Оконный", "无边框窗口": "Оконный без рамки",
        "无边框全屏": "Полный экран без рамки", "独占全屏": "Эксклюзивный полный экран",
        "最大化窗口": "Развёрнутый",
        "分辨率": "Разрешение", "独占全屏模式下可单独设置渲染分辨率":
            "Разрешение рендеринга, настраивается в эксклюзивном полном экране",
        "自动（推荐）": "Авто (рекомендуется)",
        "显示器": "Монитор", "多显示器环境下选择全屏显示的屏幕":
            "Выбор экрана для полного экрана",
        "帧率限制": "Ограничение FPS", "上限帧率，避免占用过高显卡资源（默认 90 FPS）":
            "Ограничение частоты кадров для снижения нагрузки на GPU (90 FPS по умолчанию)",
        "无限制": "Без ограничений", "当前帧率": "Текущий FPS", "实时 FPS 读数": "FPS в реальном времени",
        "垂直同步": "V-Sync", "与显示器刷新率同步，防止画面撕裂":
            "Синхронизация с частотой экрана против разрывов",
        "启用 V-Sync": "Включить V-Sync",
        "DPI 缩放": "Масштаб DPI", "跟随系统 DPI 或强制 100%":
            "Как в системе или принудительно 100 %",
        "自动（跟随系统）": "Авто (как в системе)", "100%（强制）": "100 % (принудительно)",
        "按需渲染": "Рендеринг по требованию", "空闲时降到低帧率重绘，省算力":
            "Низкая частота кадров в простое для экономии ресурсов",
        "启用按需渲染": "Включить рендеринг по требованию",
        "鼠标灵敏度": "Чувствительность мыши", "拖拽旋转/平移速度":
            "Скорость вращения / перемещения",
        "新手引导": "Первые шаги", "可随时重新开启引导教程":
            "Обучение можно открыть заново в любой момент",
        "重新打开引导": "Открыть обучение заново",
        "界面语言": "Язык интерфейса",
        "选择界面显示语言（联合国六种官方语言）":
            "Выбор языка интерфейса (шесть официальных языков ООН)",
        "界面主题": "Тема интерфейса",
        "在夜间与日间配色之间切换": "Переключение между ночной и дневной темами",
        "数据来源：JPL / NASA Exoplanet Archive / IAU / MPC":
            "Источники: JPL / NASA Exoplanet Archive / IAU / MPC",
        # —— 详情面板 / 时间轴 / 启动器补充 ——
        "未选中天体": "Тело не выбрано", "未知": "Неизвестно", "—": "—",
        "聚焦": "Навести", "加入对比": "Добавить к сравнению",
        "尺寸对比": "Сравнение размеров",
        "打开「观测特征」标签页：凌星光变曲线 / 视向速度曲线 / 宜居带\n（太阳系天体仅有宜居带与光通量）":
            "Открыть вкладку «Наблюдения»: кривая транзита / кривая лучевых скоростей / обитаемая зона\n(у тел Солнечной системы — только обитаемая зона и поток)",
        "打开「地面视角」标签页：站在选定地点抬头看天的星空图\n（行星/太阳/亮星的地平坐标 + 当日日轨线与升落时刻）\n当前选中天体若在地平线上方会高亮标注":
            "Открыть вкладку «Вид с Земли»: карта неба из выбранного места\n(горизонтальные координаты планет/Солнца/ярких звёзд + суточный путь и времена восхода/захода)\nВыбранное тело подсвечивается, если оно над горизонтом",
        "打开「地表视角」标签页：站到该行星/卫星表面，第一人称环视天空\n（天空底色随太阳高度变化，亮星为柔和光晕，地平线为静态地形剪影）\n仅对具备自转轴数据的天体可用":
            "Открыть вкладку «Вид с поверхности»: встать на эту планету/спутник и осмотреться от первого лица\n(цвет неба зависит от высоты Солнца, звёзды — мягкие ореолы, горизонт — статичный силуэт)\nДоступно только для тел с данными об оси вращения",
        "点击弹出日历面板，选择目标日期": "Открыть календарь для выбора даты",
        '视角导航轴：点击 X/Y/Z 切换轴向视角': 'Гизмо вида: нажмите X/Y/Z для переключения осевых видов',
        '侧视图（+X 轴）': 'Вид сбоку (+X)',
        '侧视图（-X 轴）': 'Вид сбоку (−X)',
        '侧视图（+Y 轴）': 'Вид сбоку (+Y)',
        '侧视图（-Y 轴）': 'Вид сбоку (−Y)',
        '俯视图（+Z 轴）': 'Вид сверху (+Z)',
        '仰视图（-Z 轴）': 'Вид снизу (−Z)',
        '显示导航轴': 'Показывать гизмо навигации',
        '3D 视角导航轴': 'Гизмо 3D-вида',
        '视口右上角 Blender 风格 XYZ 导航球；关闭后快捷键 1/3/7 仍可用': 'XYZ-навигационная сфера в стиле Blender в правом верхнем углу 3D-окна; горячие клавиши 1/3/7 работают и при скрытии',
        "跳转到当前真实日期": "Перейти к сегодняшней реальной дате",
        "系": "система", "宿主恒星": "Родительская звезда", "系外行星": "Экзопланеты",
        "3D 立体视图\n\n三维轨道空间 · 可旋转缩放\n实体球 + 程序化表面贴图\n系外行星与背景亮星":
            "3D-вид\n\nТрёхмерное орбитальное пространство · вращение и масштаб\nСплошные сферы + процедурные текстуры поверхности\nЭкзопланеты и яркие фоновые звёзды",
        "2D 平面视图\n\n俯视黄道面的轨道图\n行星轨道椭圆 · 自适应刻度\n轻量平面 · 便于看轨道关系":
            "2D-вид\n\nОрбитальная карта эклиптики сверху\nЭллиптические орбиты · адаптивный масштаб\nЛёгкая плоскость · удобно читать орбиты",
        "引力系统\n\n时空弯曲网格\n天体按 M/r 引力势把网格压出凹陷\n质量越大 · 距离越近 · 凹陷越深":
            "Гравитация\n\nИскривлённая сетка пространства-времени\nТела прогибают сетку по потенциалу M/r\nЧем больше масса и ближе расстояние, тем глубже яма",
        # —— 图形 / 显卡 ——
        "图形 / 显卡": "Графика / Видеокарта",
        "当前显卡": "Текущая видеокарта",
        "图形接口": "Графический API",
        "加速状态": "Аппаратное ускорение",
        "显卡要求": "Требования к видеокарте",
        "硬件加速（GPU）": "Аппаратное ускорение (GPU)",
        "软件渲染（CPU）": "Программный рендеринг (CPU)",
        "检测失败": "Не удалось определить",
        "支持桌面 OpenGL 3.3 Core 的显卡；建议使用独立显卡并保持驱动为最新":
            "Видеокарта с поддержкой настольного OpenGL 3.3 Core; рекомендуется дискретная видеокарта с актуальными драйверами",
        "软件渲染时三维画面由 CPU 计算，帧率会明显偏低，请更新显卡驱动或在独立显卡上运行":
            "При программном рендеринге 3D-сцена считается на CPU, и частота кадров заметно ниже; обновите драйвер видеокарты или запустите на дискретной видеокарте",
        "检测到的显卡": "Обнаруженные видеокарты",
        "本机安装的全部显示适配器": "Все видеоадаптеры, установленные на этом ПК",
        "检测到独立显卡但当前未使用：": "Обнаружена дискретная видеокарта, но она не используется: ",
        "如需改用独立显卡：NVIDIA 控制面板 → 管理 3D 设置 → 程序设置，将本程序设为「高性能 NVIDIA 处理器」；或 Windows 设置 → 显示 → 图形，将本程序设为「高性能」。":
            "Чтобы использовать дискретную видеокарту: в Панели управления NVIDIA → Управление параметрами 3D → Параметры программы выберите для этого приложения «Высокопроизводительный процессор NVIDIA»; или в Параметрах Windows → Дисплей → Графика выберите «Высокая производительность».",
        "改用独立显卡（重启生效）": "Использовать дискретную видеокарту (нужен перезапуск)",
        "已启用独立显卡（点击撤销）": "Дискретная видеокарта включена (нажмите для отмены)",
        "设置对象：": "Применяется к: ",
        "图形首选项": "Графический параметр",
        "设置失败": "Не удалось настроить",
        "写入设置失败：": "Не удалось записать параметр: ",
        "已设为优先使用独立显卡，请关闭并重新启动程序后生效。":
            "Для этого приложения выбрана дискретная видеокарта. Закройте и снова запустите программу, чтобы изменения вступили в силу.",
        "已恢复由系统自动选择显卡，请重新启动程序后生效。":
            "Возвращён автоматический выбор видеокарты системой. Перезапустите программу, чтобы изменения вступили в силу.",
        "已切换显卡首选项，请关闭并重新启动程序后生效。":
            "Настройка видеокарты изменена. Закройте и снова запустите программу, чтобы изменения вступили в силу.",
        # —— P2/P3 新增：字体 / 性能 / 大模型 ——
        "保存": "Сохранить", "已保存": "Сохранено", "测试连接": "Проверить соединение",
        "天文助手": "Астрономический помощник", "助手": "Помощник",
        "发送": "Отправить", "清空对话": "Очистить чат", "就绪": "Готово",
        "我": "Я", "系统": "Система", "已回复": "Ответ получен",
        "自动适配": "Автоподбор",
        "基于大模型 API（在「设置 → 大模型」中配置）":
            "На базе API языковой модели (настраивается в разделе Настройки → LLM)",
        "输入天文问题…（Ctrl+Enter 发送）":
            "Задайте астрономический вопрос… (Ctrl+Enter — отправить)",
        "思考中…（正在调用大模型 API）": "Размышление… (вызов API языковой модели)",
        "测试中…（正在请求大模型 API）": "Тестирование… (запрос к API языковой модели)",
        "调用失败：": "Ошибка запроса: ",
        "连接失败：": "Не удалось подключиться: ", "连接成功：": "Подключено: ",
        "请先填写 API Key": "Сначала введите ключ API",
        "未配置 API Key，请在「设置 → 大模型」中填写。":
            "Ключ API не настроен. Введите его в разделе Настройки → LLM.",
        "选择大模型服务商（OpenAI 兼容接口）":
            "Выберите провайдера языковой модели (API, совместимый с OpenAI)",
        "OpenAI 兼容的接口根地址（如 https://api.deepseek.com/v1）":
            "Базовый URL, совместимый с OpenAI (напр. https://api.deepseek.com/v1)",
        "如 deepseek-chat / gpt-4o-mini": "напр. deepseek-chat / gpt-4o-mini",
        "仅保存在本机设置文件，不会上传":
            "Хранится только в локальном файле настроек и никуда не отправляется",
        "图形 API 与着色器语言版本": "Версия графического API и языка шейдеров",
        "当前实际用于渲染的图形设备": "Графическое устройство, фактически используемое для рендеринга",
        "是否由 GPU 硬件加速渲染": "Используется ли аппаратное ускорение GPU при рендеринге",
        "手动选择本程序使用的显卡（Windows 图形设置，重启程序后生效）":
            "Выбор видеокарты для этого приложения (графические настройки Windows; действует после перезапуска)",
        "拖动滑块调节界面文字大小（0.8～1.6 倍），即时生效":
            "Перетащите ползунок, чтобы изменить размер текста интерфейса (0,8–1,6×), применяется сразу",
        "在显卡可承受范围内尽量多显示（目标 30 FPS 以上，上限 100 万）":
            "Показывать столько тел, сколько выдержит видеокарта (цель — от 30 FPS, до 1 000 000)",
        "当前帧率与正在渲染的天体数量":
            "Текущая частота кадров и число отображаемых небесных тел",
        "高性能：上限 100 万颗；均衡：50 万；省电：12 万":
            "Высокая: до 1 млн; Баланс: 500 тыс; Экономия: 120 тыс",
    },
    # ============================== 西班牙语 ==============================
    "es": {
        "Astrarium": "Astrarium",
        "Astrarium —— 太阳系 + 系外行星": "Astrarium — Sistema solar + exoplanetas",
        "Astrarium —— 选择视图模式": "Astrarium — Elegir modo de vista",
        "设置": "Ajustes", "确定": "Aceptar", "取消": "Cancelar", "关闭": "Cerrar",
        "显示": "Pantalla", "交互": "Interacción", "外观": "Apariencia",
        "引导": "Guía", "关于": "Acerca de",
        "语言": "Idioma", "主题": "Tema", "夜间": "Noche", "日间": "Día",
        "跟随系统": "Seguir el sistema",
        "搜索天体…": "Buscar cuerpos…", "搜索": "Buscar", "搜索:": "Buscar:",
        "轨道线": "Órbitas", "标签": "Etiquetas", "网格": "Rejilla",
        "背景星": "Estrellas de fondo", "星云": "Nebulosa", "按需渲染": "Bajo demanda",
        "尾迹 · 自动清除": "Estelas · Borrado auto",
        "尾迹 · 一直显示": "Estelas · Persistentes",
        "尾迹 · 关闭": "Estelas · Desactivadas",
        "真实比例": "Escala real", "实体球": "Esferas sólidas",
        "锁定跟随": "Bloquear seguimiento", "卫星": "Lunas",
        "行星环": "Anillos planetarios", "人造卫星": "Satélites artificiales",
        "自转轴": "Eje de rotación", "太阳系轨道": "Órbitas del sistema solar",
        "系外行星轨道": "Órbitas de exoplanetas", "小天体": "Cuerpos menores",
        "少": "Pocos", "中": "Medio", "多": "Muchos",
        "灵敏度:": "Sensibilidad:", "很慢": "Muy lento", "慢": "Lento",
        "标准": "Estándar", "快": "Rápido", "很快": "Muy rápido",
        "帮助 (F1)": "Ayuda (F1)", "教学场景": "Escenas didácticas",
        "新手引导": "Primeros pasos", "切换模式": "Cambiar modo",
        "详情": "Detalles", "对比分析": "Comparación", "测距": "Distancia",
        "天象推演": "Fenómenos", "观测特征": "Observación",
        "地面视角": "Vista desde el suelo", "地表视角": "Vista de superficie",
        "太阳系 + 系外行星 · 请选择视图模式": "Sistema solar + exoplanetas · Elige un modo",
        "3D 立体视图": "Vista 3D", "2D 平面视图": "Vista 2D", "引力系统": "Gravedad",
        "打开三维立体视图（快捷键 3）": "Abrir la vista 3D (tecla 3)",
        "打开二维平面视图（快捷键 2）": "Abrir la vista 2D (tecla 2)",
        "打开引力系统视图（快捷键 G）": "Abrir la vista de gravedad (tecla G)",
        "三个视图共用同一套数据与时间系统；可用主窗口工具栏的「切换模式」随时返回本窗口。":
            "Las tres vistas comparten datos y tiempo; usa «Cambiar modo» para volver aquí.",
        "搜索天体 / 恒星系名称…": "Buscar cuerpos / sistemas…",
        "恒星系（系群）": "Sistemas estelares",
        "太阳系": "Sistema solar", "黑洞": "Agujeros negros",
        "近邻恒星": "Estrellas cercanas", "星际天体": "Objetos interestelares",
        "极端海外天体": "Objetos transneptunianos extremos",
        "个天体": "cuerpos", "颗行星": "planetas", "颗卫星": "lunas",
        "光年": "años luz", "匹配": "coincidencias",
        "共": "Total", "恒星系": "sistemas",
        "播放 / 暂停（空格键）": "Reproducir / Pausar (Espacio)",
        "暂停（空格键）": "Pausar (Espacio)", "播放（空格键）": "Reproducir (Espacio)",
        "倒放 / 正放切换": "Retroceso / avance",
        "时间倍速": "Velocidad del tiempo", "跳转:": "Ir a:", "跳转": "Ir",
        "日历": "Calendario", "今天": "Hoy", "年": "Año",
        "星历范围: {lo}–{hi}": "Rango de efemérides: {lo}–{hi}",
        "⚠ 超出星历范围 ({lo}–{hi})": "⚠ Fuera del rango de efemérides ({lo}–{hi})",
        "显示模式": "Modo de pantalla", "选择窗口/全屏模式": "Modo ventana / pantalla completa",
        "窗口模式": "Ventana", "无边框窗口": "Ventana sin bordes",
        "无边框全屏": "Pantalla completa sin bordes", "独占全屏": "Pantalla completa exclusiva",
        "最大化窗口": "Maximizada",
        "分辨率": "Resolución", "独占全屏模式下可单独设置渲染分辨率":
            "Resolución de renderizado, ajustable en pantalla completa exclusiva",
        "自动（推荐）": "Auto (recomendado)",
        "显示器": "Monitor", "多显示器环境下选择全屏显示的屏幕":
            "Elige la pantalla para el modo de pantalla completa",
        "帧率限制": "Límite de FPS", "上限帧率，避免占用过高显卡资源（默认 90 FPS）":
            "Limita los FPS para reducir la carga de GPU (90 FPS por defecto)",
        "无限制": "Sin límite", "当前帧率": "FPS actual", "实时 FPS 读数": "Lectura de FPS en vivo",
        "垂直同步": "V-Sync", "与显示器刷新率同步，防止画面撕裂":
            "Sincroniza con la pantalla para evitar el desgarro",
        "启用 V-Sync": "Activar V-Sync",
        "DPI 缩放": "Escalado DPI", "跟随系统 DPI 或强制 100%":
            "Seguir el DPI del sistema o forzar 100 %",
        "自动（跟随系统）": "Auto (seguir el sistema)", "100%（强制）": "100 % (forzado)",
        "按需渲染": "Renderizado bajo demanda", "空闲时降到低帧率重绘，省算力":
            "Redibuja a baja frecuencia en reposo para ahorrar",
        "启用按需渲染": "Activar renderizado bajo demanda",
        "鼠标灵敏度": "Sensibilidad del ratón", "拖拽旋转/平移速度":
            "Velocidad de rotación / desplazamiento",
        "新手引导": "Primeros pasos", "可随时重新开启引导教程":
            "Puedes reabrir el tutorial en cualquier momento",
        "重新打开引导": "Reabrir el tutorial",
        "界面语言": "Idioma de la interfaz",
        "选择界面显示语言（联合国六种官方语言）":
            "Elige el idioma de la interfaz (seis idiomas oficiales de la ONU)",
        "界面主题": "Tema de la interfaz",
        "在夜间与日间配色之间切换": "Cambia entre los temas de noche y día",
        "数据来源：JPL / NASA Exoplanet Archive / IAU / MPC":
            "Fuentes: JPL / NASA Exoplanet Archive / IAU / MPC",
        # —— 详情面板 / 时间轴 / 启动器补充 ——
        "未选中天体": "Ningún cuerpo seleccionado", "未知": "Desconocido", "—": "—",
        "聚焦": "Centrar", "加入对比": "Añadir a comparación",
        "尺寸对比": "Comparación de tamaño",
        "打开「观测特征」标签页：凌星光变曲线 / 视向速度曲线 / 宜居带\n（太阳系天体仅有宜居带与光通量）":
            "Abrir la pestaña «Observación»: curva de tránsito / curva de velocidad radial / zona habitable\n(los cuerpos del sistema solar solo tienen zona habitable y flujo)",
        "打开「地面视角」标签页：站在选定地点抬头看天的星空图\n（行星/太阳/亮星的地平坐标 + 当日日轨线与升落时刻）\n当前选中天体若在地平线上方会高亮标注":
            "Abrir la pestaña «Vista desde el suelo»: carta del cielo desde un lugar elegido\n(coordenadas horizontales de planetas/Sol/estrellas brillantes + trayectoria diaria y horas de salida/puesta)\nEl cuerpo seleccionado se resalta si está sobre el horizonte",
        "打开「地表视角」标签页：站到该行星/卫星表面，第一人称环视天空\n（天空底色随太阳高度变化，亮星为柔和光晕，地平线为静态地形剪影）\n仅对具备自转轴数据的天体可用":
            "Abrir la pestaña «Vista de superficie»: situarse en ese planeta/luna y mirar alrededor en primera persona\n(el color del cielo varía con la altura solar, las estrellas son halos suaves, el horizonte es una silueta estática)\nDisponible solo para cuerpos con datos de eje de rotación",
        "点击弹出日历面板，选择目标日期": "Abrir un calendario para elegir una fecha",
        '视角导航轴：点击 X/Y/Z 切换轴向视角': 'Gizmo de vista: pulsa X/Y/Z para cambiar de vista axial',
        '侧视图（+X 轴）': 'Vista lateral (+X)',
        '侧视图（-X 轴）': 'Vista lateral (−X)',
        '侧视图（+Y 轴）': 'Vista lateral (+Y)',
        '侧视图（-Y 轴）': 'Vista lateral (−Y)',
        '俯视图（+Z 轴）': 'Vista superior (+Z)',
        '仰视图（-Z 轴）': 'Vista inferior (−Z)',
        '显示导航轴': 'Mostrar gizmo de navegación',
        '3D 视角导航轴': 'Gizmo de vista 3D',
        '视口右上角 Blender 风格 XYZ 导航球；关闭后快捷键 1/3/7 仍可用': 'Esfera de navegación XYZ estilo Blender en la esquina superior derecha de la vista 3D; los atajos 1/3/7 siguen funcionando al ocultarla',
        "跳转到当前真实日期": "Ir a la fecha real de hoy",
        "系": "sistema", "宿主恒星": "Estrella anfitriona", "系外行星": "Exoplanetas",
        "3D 立体视图\n\n三维轨道空间 · 可旋转缩放\n实体球 + 程序化表面贴图\n系外行星与背景亮星":
            "Vista 3D\n\nEspacio orbital tridimensional · rotar y ampliar\nEsferas sólidas + texturas de superficie procedurales\nExoplanetas y estrellas brillantes de fondo",
        "2D 平面视图\n\n俯视黄道面的轨道图\n行星轨道椭圆 · 自适应刻度\n轻量平面 · 便于看轨道关系":
            "Vista 2D\n\nMapa orbital cenital de la eclíptica\nÓrbitas elípticas · escala adaptativa\nPlano ligero · fácil de leer las órbitas",
        "引力系统\n\n时空弯曲网格\n天体按 M/r 引力势把网格压出凹陷\n质量越大 · 距离越近 · 凹陷越深":
            "Gravedad\n\nRejilla de espacio-tiempo curvada\nLos cuerpos hunden la rejilla según su potencial M/r\nA mayor masa y menor distancia, más profundo el pozo",
        # —— 图形 / 显卡 ——
        "图形 / 显卡": "Gráficos / GPU",
        "当前显卡": "GPU actual",
        "图形接口": "API gráfica",
        "加速状态": "Aceleración",
        "显卡要求": "Requisitos de GPU",
        "硬件加速（GPU）": "Aceleración por hardware (GPU)",
        "软件渲染（CPU）": "Renderizado por software (CPU)",
        "检测失败": "Detección fallida",
        "支持桌面 OpenGL 3.3 Core 的显卡；建议使用独立显卡并保持驱动为最新":
            "Una GPU compatible con OpenGL 3.3 Core de escritorio; se recomienda una GPU dedicada con controladores actualizados",
        "软件渲染时三维画面由 CPU 计算，帧率会明显偏低，请更新显卡驱动或在独立显卡上运行":
            "Con renderizado por software, la vista 3D se calcula en la CPU y la tasa de fotogramas es mucho menor; actualice el controlador gráfico o ejecute en una GPU dedicada",
        "检测到的显卡": "GPU detectadas",
        "本机安装的全部显示适配器": "Todos los adaptadores de pantalla instalados en este equipo",
        "检测到独立显卡但当前未使用：": "Hay una GPU dedicada presente pero sin usar: ",
        "如需改用独立显卡：NVIDIA 控制面板 → 管理 3D 设置 → 程序设置，将本程序设为「高性能 NVIDIA 处理器」；或 Windows 设置 → 显示 → 图形，将本程序设为「高性能」。":
            "Para usar la GPU dedicada: en el Panel de control de NVIDIA → Administrar configuración 3D → Configuración de programas, establece esta aplicación en «Procesador NVIDIA de alto rendimiento»; o en Configuración de Windows → Pantalla → Gráficos, establece esta aplicación en «Alto rendimiento».",
        "改用独立显卡（重启生效）": "Usar GPU dedicada (requiere reinicio)",
        "已启用独立显卡（点击撤销）": "GPU dedicada activada (clic para deshacer)",
        "设置对象：": "Se aplica a: ",
        "图形首选项": "Preferencia gráfica",
        "设置失败": "Error de configuración",
        "写入设置失败：": "No se pudo escribir la configuración: ",
        "已设为优先使用独立显卡，请关闭并重新启动程序后生效。":
            "Esta aplicación ahora prefiere la GPU dedicada. Cierre y reinicie el programa para que surta efecto.",
        "已恢复由系统自动选择显卡，请重新启动程序后生效。":
            "Se ha restaurado la selección automática de GPU del sistema. Reinicie el programa para que surta efecto.",
        "已切换显卡首选项，请关闭并重新启动程序后生效。":
            "Preferencia de GPU cambiada. Cierre y reinicie el programa para que surta efecto.",
        # —— P2/P3 新增：字体 / 性能 / 大模型 ——
        "保存": "Guardar", "已保存": "Guardado", "测试连接": "Probar conexión",
        "天文助手": "Asistente de astronomía", "助手": "Asistente",
        "发送": "Enviar", "清空对话": "Borrar conversación", "就绪": "Listo",
        "我": "Yo", "系统": "Sistema", "已回复": "Respondido",
        "自动适配": "Adaptación automática",
        "基于大模型 API（在「设置 → 大模型」中配置）":
            "Basado en una API de LLM (se configura en Ajustes → LLM)",
        "输入天文问题…（Ctrl+Enter 发送）":
            "Haga una pregunta de astronomía… (Ctrl+Enter para enviar)",
        "思考中…（正在调用大模型 API）": "Pensando… (llamando a la API del LLM)",
        "测试中…（正在请求大模型 API）": "Probando… (solicitando la API del LLM)",
        "调用失败：": "Fallo de la solicitud: ",
        "连接失败：": "Conexión fallida: ", "连接成功：": "Conexión correcta: ",
        "请先填写 API Key": "Introduzca primero la clave API",
        "未配置 API Key，请在「设置 → 大模型」中填写。":
            "No hay clave API configurada. Introdúzcala en Ajustes → LLM.",
        "选择大模型服务商（OpenAI 兼容接口）":
            "Elegir un proveedor de LLM (API compatible con OpenAI)",
        "OpenAI 兼容的接口根地址（如 https://api.deepseek.com/v1）":
            "URL raíz compatible con OpenAI (p. ej. https://api.deepseek.com/v1)",
        "如 deepseek-chat / gpt-4o-mini": "p. ej. deepseek-chat / gpt-4o-mini",
        "仅保存在本机设置文件，不会上传":
            "Se guarda solo en el archivo local de ajustes; nunca se sube",
        "图形 API 与着色器语言版本": "API de gráficos y versión del lenguaje de sombreado",
        "当前实际用于渲染的图形设备": "Dispositivo gráfico realmente usado para el renderizado",
        "是否由 GPU 硬件加速渲染": "Si el renderizado está acelerado por el hardware de la GPU",
        "手动选择本程序使用的显卡（Windows 图形设置，重启程序后生效）":
            "Elegir la GPU que usa esta aplicación (ajustes de gráficos de Windows; surte efecto tras reiniciar)",
        "拖动滑块调节界面文字大小（0.8～1.6 倍），即时生效":
            "Arrastre el control para ajustar el tamaño del texto de la interfaz (0,8–1,6×), efecto inmediato",
        "在显卡可承受范围内尽量多显示（目标 30 FPS 以上，上限 100 万）":
            "Mostrar tantos cuerpos como soporte la GPU (objetivo de 30 FPS o más, hasta 1 000 000)",
        "当前帧率与正在渲染的天体数量":
            "Frecuencia de imagen actual y número de cuerpos en renderizado",
        "高性能：上限 100 万颗；均衡：50 万；省电：12 万":
            "Alto: hasta 1 M; Equilibrado: 500 K; Ahorro: 120 K",
    },
    # ============================== 阿拉伯语 ==============================
    "ar": {
        "Astrarium": "Astrarium",
        "Astrarium —— 太阳系 + 系外行星": "Astrarium — النظام الشمسي + الكواكب الخارجية",
        "Astrarium —— 选择视图模式": "Astrarium — اختر وضع العرض",
        "设置": "الإعدادات", "确定": "موافق", "取消": "إلغاء", "关闭": "إغلاق",
        "显示": "العرض", "交互": "التفاعل", "外观": "المظهر",
        "引导": "الإرشاد", "关于": "حول",
        "语言": "اللغة", "主题": "السمة", "夜间": "ليلي", "日间": "نهاري",
        "跟随系统": "حسب النظام",
        "搜索天体…": "ابحث عن الأجرام…", "搜索": "بحث", "搜索:": "بحث:",
        "轨道线": "المدارات", "标签": "التسميات", "网格": "الشبكة",
        "背景星": "النجوم الخلفية", "星云": "السديم", "按需渲染": "عند الطلب",
        "尾迹 · 自动清除": "الآثار · مسح تلقائي",
        "尾迹 · 一直显示": "الآثار · دائمة",
        "尾迹 · 关闭": "الآثار · إيقاف",
        "真实比例": "المقياس الحقيقي", "实体球": "كرات صلبة",
        "锁定跟随": "تثبيت المتابعة", "卫星": "الأقمار",
        "行星环": "حلقات الكواكب", "人造卫星": "الأقمار الصناعية",
        "自转轴": "محور الدوران", "太阳系轨道": "مدارات النظام الشمسي",
        "系外行星轨道": "مدارات الكواكب الخارجية", "小天体": "الأجرام الصغيرة",
        "少": "قليل", "中": "متوسط", "多": "كثير",
        "灵敏度:": "الحساسية:", "很慢": "بطيء جدًا", "慢": "بطيء",
        "标准": "قياسي", "快": "سريع", "很快": "سريع جدًا",
        "帮助 (F1)": "مساعدة (F1)", "教学场景": "مشاهد تعليمية",
        "新手引导": "البدء السريع", "切换模式": "تبديل الوضع",
        "详情": "التفاصيل", "对比分析": "المقارنة", "测距": "المسافة",
        "天象推演": "الظواهر", "观测特征": "الرصد",
        "地面视角": "منظور أرضي", "地表视角": "منظور سطحي",
        "太阳系 + 系外行星 · 请选择视图模式": "النظام الشمسي + الكواكب الخارجية · اختر وضع العرض",
        "3D 立体视图": "عرض ثلاثي الأبعاد", "2D 平面视图": "عرض ثنائي الأبعاد",
        "引力系统": "نظام الجاذبية",
        "打开三维立体视图（快捷键 3）": "افتح العرض ثلاثي الأبعاد (المفتاح 3)",
        "打开二维平面视图（快捷键 2）": "افتح العرض ثنائي الأبعاد (المفتاح 2)",
        "打开引力系统视图（快捷键 G）": "افتح عرض الجاذبية (المفتاح G)",
        "三个视图共用同一套数据与时间系统；可用主窗口工具栏的「切换模式」随时返回本窗口。":
            "تتشارك العروض الثلاثة البيانات والزمن؛ استخدم «تبديل الوضع» للعودة إلى هنا.",
        "搜索天体 / 恒星系名称…": "ابحث عن الأجرام / الأنظمة النجمية…",
        "恒星系（系群）": "الأنظمة النجمية",
        "太阳系": "النظام الشمسي", "黑洞": "الثقوب السوداء",
        "近邻恒星": "النجوم القريبة", "星际天体": "الأجرام بين النجمية",
        "极端海外天体": "الأجرام البعيدة للغاية",
        "个天体": "جرمًا", "颗行星": "كوكبًا", "颗卫星": "قمرًا",
        "光年": "سنة ضوئية", "匹配": "نتيجة",
        "共": "الإجمالي", "恒星系": "أنظمة",
        "播放 / 暂停（空格键）": "تشغيل / إيقاف (مسافة)",
        "暂停（空格键）": "إيقاف (مسافة)", "播放（空格键）": "تشغيل (مسافة)",
        "倒放 / 正放切换": "عكس / تقدّم",
        "时间倍速": "سرعة الزمن", "跳转:": "انتقال:", "跳转": "انتقال",
        "日历": "التقويم", "今天": "اليوم", "年": "سنة",
        "星历范围: {lo}–{hi}": "نطاق التقويم الفلكي: {lo}–{hi}",
        "⚠ 超出星历范围 ({lo}–{hi})": "⚠ خارج نطاق التقويم الفلكي ({lo}–{hi})",
        "显示模式": "وضع العرض", "选择窗口/全屏模式": "وضع النافذة / ملء الشاشة",
        "窗口模式": "نافذة", "无边框窗口": "نافذة بلا إطار",
        "无边框全屏": "ملء الشاشة بلا إطار", "独占全屏": "ملء الشاشة الحصري",
        "最大化窗口": "مكبّرة",
        "分辨率": "الدقة", "独占全屏模式下可单独设置渲染分辨率":
            "دقة العرض، قابلة للضبط في ملء الشاشة الحصري",
        "自动（推荐）": "تلقائي (موصى به)",
        "显示器": "الشاشة", "多显示器环境下选择全屏显示的屏幕":
            "اختر الشاشة المستخدمة في ملء الشاشة",
        "帧率限制": "حد معدل الإطارات", "上限帧率，避免占用过高显卡资源（默认 90 FPS）":
            "حدّد معدل الإطارات لتقليل الحمل على كرت الرسوميات (90 افتراضيًا)",
        "无限制": "بلا حد", "当前帧率": "معدل الإطارات الحالي", "实时 FPS 读数": "قراءة مباشرة",
        "垂直同步": "المزامنة العمودية", "与显示器刷新率同步，防止画面撕裂":
            "المزامنة مع معدل تحديث الشاشة لمنع التمزق",
        "启用 V-Sync": "تفعيل المزامنة العمودية",
        "DPI 缩放": "مقياس DPI", "跟随系统 DPI 或强制 100%":
            "حسب النظام أو فرض 100%",
        "自动（跟随系统）": "تلقائي (حسب النظام)", "100%（强制）": "100% (مفروض)",
        "按需渲染": "العرض عند الطلب", "空闲时降到低帧率重绘，省算力":
            "خفض معدل الإطارات عند الخمول لتوفير الموارد",
        "启用按需渲染": "تفعيل العرض عند الطلب",
        "鼠标灵敏度": "حساسية الفأرة", "拖拽旋转/平移速度":
            "سرعة التدوير / الإزاحة",
        "新手引导": "البدء السريع", "可随时重新开启引导教程":
            "يمكنك إعادة فتح الشرح في أي وقت",
        "重新打开引导": "إعادة فتح الشرح",
        "界面语言": "لغة الواجهة",
        "选择界面显示语言（联合国六种官方语言）":
            "اختر لغة الواجهة (اللغات الرسمية الست للأمم المتحدة)",
        "界面主题": "سمة الواجهة",
        "在夜间与日间配色之间切换": "التبديل بين سمتَي الليل والنهار",
        "数据来源：JPL / NASA Exoplanet Archive / IAU / MPC":
            "المصادر: JPL / NASA Exoplanet Archive / IAU / MPC",
        # —— 详情面板 / 时间轴 / 启动器补充 ——
        "未选中天体": "لا يوجد جرم محدد", "未知": "غير معروف", "—": "—",
        "聚焦": "تركيز", "加入对比": "إضافة إلى المقارنة",
        "尺寸对比": "مقارنة الأحجام",
        "打开「观测特征」标签页：凌星光变曲线 / 视向速度曲线 / 宜居带\n（太阳系天体仅有宜居带与光通量）":
            "افتح تبويب «الرصد»: منحنى العبور / منحنى السرعة الشعاعية / المنطقة القابلة للسكنى\n(أجرام النظام الشمسي لها المنطقة القابلة للسكنى والتدفق فقط)",
        "打开「地面视角」标签页：站在选定地点抬头看天的星空图\n（行星/太阳/亮星的地平坐标 + 当日日轨线与升落时刻）\n当前选中天体若在地平线上方会高亮标注":
            "افتح تبويب «منظور أرضي»: خريطة السماء من موقع مختار\n(الإحداثيات الأفقية للكواكب/الشمس/النجوم الساطعة + المسار اليومي وأوقات الشروق والغروب)\nيُبرز الجرم المحدد إذا كان فوق الأفق",
        "打开「地表视角」标签页：站到该行星/卫星表面，第一人称环视天空\n（天空底色随太阳高度变化，亮星为柔和光晕，地平线为静态地形剪影）\n仅对具备自转轴数据的天体可用":
            "افتح تبويب «منظور سطحي»: قف على سطح هذا الكوكب/القمر وانظر حولك بمنظور الشخص الأول\n(يتغير لون السماء حسب ارتفاع الشمس، والنجوم هالات ناعمة، والأفق ظل ثابت)\nمتاح فقط للأجرام التي تملك بيانات محور دوران",
        "点击弹出日历面板，选择目标日期": "افتح تقويمًا لاختيار التاريخ المطلوب",
        '视角导航轴：点击 X/Y/Z 切换轴向视角': 'أداة العرض: انقر X/Y/Z لتبديل المنظر المحوري',
        '侧视图（+X 轴）': 'منظر جانبي (+X)',
        '侧视图（-X 轴）': 'منظر جانبي (−X)',
        '侧视图（+Y 轴）': 'منظر جانبي (+Y)',
        '侧视图（-Y 轴）': 'منظر جانبي (−Y)',
        '俯视图（+Z 轴）': 'منظر علوي (+Z)',
        '仰视图（-Z 轴）': 'منظر سفلي (−Z)',
        '显示导航轴': 'إظهار أداة الملاحة',
        '3D 视角导航轴': 'أداة عرض ثلاثية الأبعاد',
        '视口右上角 Blender 风格 XYZ 导航球；关闭后快捷键 1/3/7 仍可用': 'كرة ملاحة XYZ بنمط Blender في أعلى يمين نافذة العرض ثلاثية الأبعاد؛ تعمل مفاتيح 1/3/7 حتى عند إخفائها',
        "跳转到当前真实日期": "الانتقال إلى تاريخ اليوم الحقيقي",
        "系": "نظام", "宿主恒星": "النجم المضيف", "系外行星": "الكواكب الخارجية",
        "3D 立体视图\n\n三维轨道空间 · 可旋转缩放\n实体球 + 程序化表面贴图\n系外行星与背景亮星":
            "عرض ثلاثي الأبعاد\n\nفضاء مداري ثلاثي الأبعاد · تدوير وتكبير\nكرات صلبة + خرائط سطح إجرائية\nكواكب خارجية ونجوم خلفية ساطعة",
        "2D 平面视图\n\n俯视黄道面的轨道图\n行星轨道椭圆 · 自适应刻度\n轻量平面 · 便于看轨道关系":
            "عرض ثنائي الأبعاد\n\nخريطة مدارية لمسيرة الشمس من الأعلى\nمدارات بيضاوية · مقياس متكيف\nمستوٍ خفيف · لقراءة المدارات بسهولة",
        "引力系统\n\n时空弯曲网格\n天体按 M/r 引力势把网格压出凹陷\n质量越大 · 距离越近 · 凹陷越深":
            "نظام الجاذبية\n\nشبكة زمكان منحنية\nتُحدث الأجرام انخفاضات في الشبكة حسب الجهد M/r\nكلما زادت الكتلة وقصرت المسافة، زاد عمق البئر",
        # —— 图形 / 显卡 ——
        "图形 / 显卡": "الرسوميات / بطاقة الرسوميات",
        "当前显卡": "بطاقة الرسوميات الحالية",
        "图形接口": "واجهة الرسوميات",
        "加速状态": "التسريع",
        "显卡要求": "متطلبات بطاقة الرسوميات",
        "硬件加速（GPU）": "تسريع عتادي (GPU)",
        "软件渲染（CPU）": "عرض برمجي (CPU)",
        "检测失败": "فشل الكشف",
        "支持桌面 OpenGL 3.3 Core 的显卡；建议使用独立显卡并保持驱动为最新":
            "بطاقة رسوميات تدعم OpenGL 3.3 Core لسطح المكتب؛ يُوصى ببطاقة منفصلة مع تعريفات محدّثة",
        "软件渲染时三维画面由 CPU 计算，帧率会明显偏低，请更新显卡驱动或在独立显卡上运行":
            "في العرض البرمجي يُحسب المشهد ثلاثي الأبعاد على المعالج وتنخفض معدل الإطارات بوضوح؛ يرجى تحديث تعريف الرسوميات أو التشغيل على بطاقة منفصلة",
        "检测到的显卡": "بطاقات الرسوميات المكتشفة",
        "本机安装的全部显示适配器": "جميع محوّلات العرض المثبّتة على هذا الجهاز",
        "检测到独立显卡但当前未使用：": "توجد بطاقة رسوميات منفصلة لكنها غير مستخدمة: ",
        "如需改用独立显卡：NVIDIA 控制面板 → 管理 3D 设置 → 程序设置，将本程序设为「高性能 NVIDIA 处理器」；或 Windows 设置 → 显示 → 图形，将本程序设为「高性能」。":
            "لاستخدام بطاقة الرسوميات المنفصلة: في لوحة تحكم NVIDIA → إدارة إعدادات 3D → إعدادات البرنامج، اضبط هذا التطبيق على «معالج NVIDIA عالي الأداء»؛ أو في إعدادات Windows → العرض → الرسوميات، اضبط هذا التطبيق على «الأداء العالي».",
        "改用独立显卡（重启生效）": "استخدام بطاقة الرسوميات المنفصلة (يلزم إعادة التشغيل)",
        "已启用独立显卡（点击撤销）": "تم تمكين البطاقة المنفصلة (انقر للتراجع)",
        "设置对象：": "ينطبق على: ",
        "图形首选项": "تفضيل الرسوميات",
        "设置失败": "فشل الإعداد",
        "写入设置失败：": "فشل كتابة الإعداد: ",
        "已设为优先使用独立显卡，请关闭并重新启动程序后生效。":
            "تم ضبط هذا التطبيق لتفضيل بطاقة الرسوميات المنفصلة. يُرجى إغلاق البرنامج وإعادة تشغيله ليصبح الإعداد سارياً.",
        "已恢复由系统自动选择显卡，请重新启动程序后生效。":
            "تمت استعادة الاختيار التلقائي لبطاقة الرسوميات من النظام. يُرجى إعادة تشغيل البرنامج ليصبح الإعداد سارياً.",
        "已切换显卡首选项，请关闭并重新启动程序后生效。":
            "تم تغيير تفضيل بطاقة الرسوميات. يُرجى إغلاق البرنامج وإعادة تشغيله ليصبح الإعداد سارياً.",
        # —— P2/P3 新增：字体 / 性能 / 大模型 ——
        "保存": "حفظ", "已保存": "تم الحفظ", "测试连接": "اختبار الاتصال",
        "天文助手": "مساعد الفلك", "助手": "مساعد",
        "发送": "إرسال", "清空对话": "مسح المحادثة", "就绪": "جاهز",
        "我": "أنا", "系统": "النظام", "已回复": "تم الرد",
        "自动适配": "تكيّف تلقائي",
        "基于大模型 API（在「设置 → 大模型」中配置）":
            "مدعوم بواجهة نموذج لغوي كبير (يُضبط في الإعدادات ← النموذج اللغوي)",
        "输入天文问题…（Ctrl+Enter 发送）":
            "اطرح سؤالاً فلكياً… (Ctrl+Enter للإرسال)",
        "思考中…（正在调用大模型 API）": "جارٍ التفكير… (استدعاء واجهة النموذج اللغوي)",
        "测试中…（正在请求大模型 API）": "جارٍ الاختبار… (طلب واجهة النموذج اللغوي)",
        "调用失败：": "فشل الاستدعاء: ",
        "连接失败：": "فشل الاتصال: ", "连接成功：": "نجح الاتصال: ",
        "请先填写 API Key": "أدخل مفتاح API أولاً",
        "未配置 API Key，请在「设置 → 大模型」中填写。":
            "لم يتم تكوين مفتاح API. أدخله في الإعدادات ← النموذج اللغوي.",
        "选择大模型服务商（OpenAI 兼容接口）":
            "اختر مزوّد النموذج اللغوي (واجهة متوافقة مع OpenAI)",
        "OpenAI 兼容的接口根地址（如 https://api.deepseek.com/v1）":
            "العنوان الأساسي المتوافق مع OpenAI (مثل https://api.deepseek.com/v1)",
        "如 deepseek-chat / gpt-4o-mini": "مثل deepseek-chat / gpt-4o-mini",
        "仅保存在本机设置文件，不会上传":
            "يُحفظ في ملف الإعدادات المحلي فقط ولا يُرسل إلى أي جهة",
        "图形 API 与着色器语言版本": "واجهة الرسوميات وإصدار لغة التظليل",
        "当前实际用于渲染的图形设备": "جهاز الرسوميات المستخدم فعلياً للعرض",
        "是否由 GPU 硬件加速渲染": "ما إذا كان العرض مسرّعاً بعتاد بطاقة الرسوميات",
        "手动选择本程序使用的显卡（Windows 图形设置，重启程序后生效）":
            "اختيار بطاقة الرسوميات لهذا التطبيق (إعدادات الرسوميات في ويندوز؛ يسري بعد إعادة التشغيل)",
        "拖动滑块调节界面文字大小（0.8～1.6 倍），即时生效":
            "اسحب المنزلق لضبط حجم نص الواجهة (0.8–1.6×)، يسري فوراً",
        "在显卡可承受范围内尽量多显示（目标 30 FPS 以上，上限 100 万）":
            "عرض أكبر عدد تتحمله بطاقة الرسوميات (الهدف 30 إطاراً في الثانية أو أكثر، حتى 1 000 000)",
        "当前帧率与正在渲染的天体数量":
            "معدل الإطارات الحالي وعدد الأجرام السماوية المعروضة",
        "高性能：上限 100 万颗；均衡：50 万；省电：12 万":
            "عالي: حتى مليون؛ متوازن: 500 ألف؛ موفّر: 120 ألف",
    },
}
