; Astrarium（原名：已知行星可视化）—— Inno Setup 安装脚本
; 编译：ISCC.exe installer.iss
; 特性：安装路径用户自选、桌面快捷方式可选（安装包保留，不自动删除）
; v1.2.0：onedir 目录化安装（exe + _internal），免除 onefile 每次启动的
;        解包等待，配合启动画面/数据缓存显著加快启动
; v1.3.0：软件显示名与 exe 更名为 Astrarium；显式保留安装目录选择页
; v1.4.0：太阳系物理演化与天文事件大功能（亿年时间轴/吞噬/洛希极限/
;        教学场景）+ 系外宿主恒星演化吞噬 + 地表视角城市切换崩溃修复
; v1.4.1：修复日历弹出报错（QCalendarWidget 无 aboutToHide 信号）
; v1.5.0：Blender 风格 XYZ 视角导航轴（View Gizmo）：视口右上角导航球，
;        点击轴向端点平滑切视角（300~500ms 缓动/可打断/极点保持方位）；
;        Numpad 1/3/7 与 Gizmo 统一动画；设置新增导航轴显隐开关（五语言）

#define MyAppName "Astrarium"
#define MyAppVersion "1.5.0"
#define MyAppPublisher "已知行星可视化项目组"
#define MyAppExeName "Astrarium.exe"
#define MyAppDirName "Astrarium"

[Setup]
AppId={{AAB4A786-FA11-4590-8929-1A69885E1CD6}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} 安装程序
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
DisableDirPage=no
DisableWelcomePage=no
AllowNoIcons=yes
OutputDir=D:\比赛文件\Astrarium_Release
OutputBaseFilename={#MyAppName}_安装程序_v{#MyAppVersion}
SetupIconFile=assets\app.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "cn"; MessagesFile: "assets\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务："; Flags: checkedonce

[Files]
Source: "dist\{#MyAppDirName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "立即运行 {#MyAppName}"; Flags: nowait postinstall skipifsilent