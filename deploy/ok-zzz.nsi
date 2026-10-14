; ok-zzz NSIS 安装脚本（生成 dist/ok-zzz-v<ver>-setup.exe）
;
; 构建（先打包 PyInstaller 产物 dist/ok-zzz）：
;   makensis.exe /DAPP_VERSION=0.1.1 /DBUILD_TAG=v0.1.1-20261014 deploy/ok-zzz.nsi
;
; 说明：
; - 安装到 %ProgramFiles%\ok-zzz，需要管理员权限（游戏以管理员运行，程序需同级权限）。
; - 卸载默认保留 config/（配置与运行记录），删除程序文件与 logs/debug/cache。
; - 可选把安装目录加入 Windows Defender 排除项（对应 pyappify.yml 的 show_add_defender）；
;   静默安装不写系统安全设置。

Unicode true

!include "MUI2.nsh"
!include "FileFunc.nsh"
!include "LogicLib.nsh"
!include "x64.nsh"

!define APP_NAME "ok-zzz"
!define APP_PUBLISHER "R0smontis"
!define APP_URL "https://github.com/R0smontis/ok-zzz"
!define APP_EXE "ok-zzz.exe"
!define UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\ok-zzz"

!ifndef APP_VERSION
  !define APP_VERSION "0.1.1"
!endif
!ifndef BUILD_TAG
  !define BUILD_TAG "v0.1.1-20261014"
!endif
!ifndef ROOT
  !define ROOT "${__FILEDIR__}\.."
!endif
!ifndef DIST_DIR
  !define DIST_DIR "${ROOT}\dist\ok-zzz"
!endif
!ifndef OUT_FILE
  !define OUT_FILE "${ROOT}\dist\${APP_NAME}-${BUILD_TAG}-setup.exe"
!endif

!if /FileExists "${DIST_DIR}\${APP_EXE}"
!else
  !error "缺少打包产物 ${DIST_DIR}\${APP_EXE}，请先运行 PyInstaller（deploy/ok-zzz.spec）"
!endif

!ifndef INSTALL_DIR
  !define INSTALL_DIR "$PROGRAMFILES64\${APP_NAME}"
!endif
!ifndef REQUEST_LEVEL
  !define REQUEST_LEVEL admin
!endif

Name "${APP_NAME} ${APP_VERSION}"
OutFile "${OUT_FILE}"
InstallDir "${INSTALL_DIR}"
InstallDirRegKey HKLM "Software\${APP_NAME}" "InstallDir"
RequestExecutionLevel ${REQUEST_LEVEL}
SetCompressor lzma
CRCCheck on

VIProductVersion "${APP_VERSION}.0"
VIAddVersionKey /LANG=2052 "ProductName" "${APP_NAME}"
VIAddVersionKey /LANG=2052 "FileDescription" "${APP_NAME} 安装程序"
VIAddVersionKey /LANG=2052 "FileVersion" "${APP_VERSION}"
VIAddVersionKey /LANG=2052 "ProductVersion" "${APP_VERSION}"
VIAddVersionKey /LANG=2052 "LegalCopyright" "GPL-3.0"
VIAddVersionKey /LANG=2052 "CompanyName" "${APP_PUBLISHER}"

!define MUI_ABORTWARNING
!define MUI_FINISHPAGE_NOAUTOCLOSE
!define MUI_FINISHPAGE_SHOWREADME "$INSTDIR\README.md"
!define MUI_FINISHPAGE_SHOWREADME_TEXT "查看自述文件（安装、权限与后台驱动说明）"
!if /FileExists "${ROOT}\icons\icon.ico"
  !define MUI_ICON "${ROOT}\icons\icon.ico"
  !define MUI_UNICON "${ROOT}\icons\icon.ico"
!endif

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "${ROOT}\LICENSE"
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_UNPAGE_FINISH

!insertmacro MUI_LANGUAGE "SimpChinese"
!insertmacro MUI_LANGUAGE "English"

LangString DESC_SecMain ${LANG_SIMPCHINESE} "ok-zzz 主程序与运行库（必需）。"
LangString DESC_SecMain ${LANG_ENGLISH} "ok-zzz application and runtime (required)."
LangString DESC_SecStartMenu ${LANG_SIMPCHINESE} "在开始菜单创建快捷方式。"
LangString DESC_SecStartMenu ${LANG_ENGLISH} "Create a Start Menu shortcut."
LangString DESC_SecDesktop ${LANG_SIMPCHINESE} "在桌面创建快捷方式。"
LangString DESC_SecDesktop ${LANG_ENGLISH} "Create a desktop shortcut."
LangString DESC_SecDefender ${LANG_SIMPCHINESE} "把安装目录加入 Windows Defender 排除项，避免打包目录被实时扫描拖慢。"
LangString DESC_SecDefender ${LANG_ENGLISH} "Add the install directory to Windows Defender exclusions."

Function .onInit
  SetRegView 64
  ${IfNot} ${RunningX64}
    MessageBox MB_ICONSTOP|MB_OK "ok-zzz 仅支持 64 位 Windows。"
    Abort
  ${EndIf}
FunctionEnd

Function un.onInit
  SetRegView 64
FunctionEnd

Section "!${APP_NAME} 主程序" SecMain
  SectionIn RO
  SetShellVarContext all
  SetOutPath "$INSTDIR"
  SetOverwrite on

  File /r "${DIST_DIR}\*.*"
  WriteUninstaller "$INSTDIR\uninstall.exe"

  WriteRegStr HKLM "Software\${APP_NAME}" "InstallDir" "$INSTDIR"
  WriteRegStr HKLM "Software\${APP_NAME}" "Version" "${APP_VERSION}"
  WriteRegStr HKLM "Software\${APP_NAME}" "BuildTag" "${BUILD_TAG}"

  WriteRegStr HKLM "${UNINST_KEY}" "DisplayName" "${APP_NAME}"
  WriteRegStr HKLM "${UNINST_KEY}" "DisplayVersion" "${APP_VERSION}"
  WriteRegStr HKLM "${UNINST_KEY}" "DisplayIcon" "$INSTDIR\${APP_EXE}"
  WriteRegStr HKLM "${UNINST_KEY}" "Publisher" "${APP_PUBLISHER}"
  WriteRegStr HKLM "${UNINST_KEY}" "URLInfoAbout" "${APP_URL}"
  WriteRegStr HKLM "${UNINST_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKLM "${UNINST_KEY}" "UninstallString" '"$INSTDIR\uninstall.exe"'
  WriteRegStr HKLM "${UNINST_KEY}" "QuietUninstallString" '"$INSTDIR\uninstall.exe" /S'
  WriteRegDWORD HKLM "${UNINST_KEY}" "NoModify" 1
  WriteRegDWORD HKLM "${UNINST_KEY}" "NoRepair" 1

  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  IntFmt $0 "0x%08X" $0
  WriteRegDWORD HKLM "${UNINST_KEY}" "EstimatedSize" "$0"
SectionEnd

Section "开始菜单快捷方式" SecStartMenu
  SectionIn RO
  SetShellVarContext all
  CreateDirectory "$SMPROGRAMS\${APP_NAME}"
  CreateShortCut "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}" "" "$INSTDIR\${APP_EXE}" 0 SW_SHOWNORMAL "" "绝区零自动化助手（请以管理员身份运行）"
  CreateShortCut "$SMPROGRAMS\${APP_NAME}\卸载 ${APP_NAME}.lnk" "$INSTDIR\uninstall.exe"
  CreateShortCut "$SMPROGRAMS\${APP_NAME}\README.lnk" "$INSTDIR\README.md"
SectionEnd

Section "桌面快捷方式" SecDesktop
  SetShellVarContext all
  CreateShortCut "$DESKTOP\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}" "" "$INSTDIR\${APP_EXE}" 0 SW_SHOWNORMAL "" "绝区零自动化助手（请以管理员身份运行）"
SectionEnd

Section /o "添加 Windows Defender 排除项" SecDefender
  ; 静默安装没有组件页、拿不到用户同意，不改变系统安全设置。
  IfSilent defender_skip
  DetailPrint "添加 Windows Defender 排除项：$INSTDIR"
  nsExec::ExecToLog "powershell -NoProfile -NonInteractive -Command $\"Add-MpPreference -ExclusionPath '$INSTDIR'$\""
  Pop $0
  ${If} $0 == 0
    WriteRegDWORD HKLM "Software\${APP_NAME}" "DefenderExclusion" 1
  ${Else}
    DetailPrint "Defender 排除项添加失败，退出码 $0"
    MessageBox MB_ICONEXCLAMATION|MB_OK "未能添加 Windows Defender 排除项（退出码 $0）。$\n$\n可稍后在「Windows 安全中心 → 病毒和威胁防护 → 排除项」手动添加：$\n$INSTDIR"
  ${EndIf}
  defender_skip:
SectionEnd

!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${SecMain} $(DESC_SecMain)
  !insertmacro MUI_DESCRIPTION_TEXT ${SecStartMenu} $(DESC_SecStartMenu)
  !insertmacro MUI_DESCRIPTION_TEXT ${SecDesktop} $(DESC_SecDesktop)
  !insertmacro MUI_DESCRIPTION_TEXT ${SecDefender} $(DESC_SecDefender)
!insertmacro MUI_FUNCTION_DESCRIPTION_END

Section "Uninstall"
  SetShellVarContext all
  SetRegView 64

  StrCpy $R0 0 ; 0 = 删除配置，1 = 保留配置
  IfFileExists "$INSTDIR\config\*.*" 0 config_done
  IfSilent keep_config
  MessageBox MB_YESNO|MB_ICONQUESTION|MB_DEFBUTTON1 \
    "是否保留配置与运行记录（$INSTDIR\config）？$\n$\n选择「否」将连同程序一起删除。" \
    IDYES keep_config
  Goto config_done
  keep_config:
    StrCpy $R0 1
  config_done:

  ; 程序文件
  Delete "$INSTDIR\${APP_EXE}"
  Delete "$INSTDIR\pyappify.yml"
  Delete "$INSTDIR\LICENSE"
  Delete "$INSTDIR\THIRD_PARTY_NOTICES.md"
  Delete "$INSTDIR\README.md"
  RMDir /r "$INSTDIR\_internal"
  RMDir /r "$INSTDIR\assets"
  RMDir /r "$INSTDIR\i18n"
  RMDir /r "$INSTDIR\icons"
  RMDir /r "$INSTDIR\docs"

  ; 运行时目录
  RMDir /r "$INSTDIR\logs"
  RMDir /r "$INSTDIR\debug"
  RMDir /r "$INSTDIR\.log"
  RMDir /r "$INSTDIR\configs"
  RMDir /r "$INSTDIR\cache"
  RMDir /r "$INSTDIR\.install"

  ${If} $R0 == 0
    RMDir /r "$INSTDIR\config"
  ${EndIf}

  Delete "$INSTDIR\uninstall.exe"

  ; Defender 排除项（仅移除安装时由本程序添加的）
  ReadRegDWORD $0 HKLM "Software\${APP_NAME}" "DefenderExclusion"
  ${If} $0 == 1
    DetailPrint "移除 Windows Defender 排除项：$INSTDIR"
    nsExec::ExecToLog "powershell -NoProfile -NonInteractive -Command $\"Remove-MpPreference -ExclusionPath '$INSTDIR'$\""
    Pop $1
  ${EndIf}

  DeleteRegKey HKLM "${UNINST_KEY}"
  DeleteRegKey HKLM "Software\${APP_NAME}"

  ; 快捷方式
  Delete "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk"
  Delete "$SMPROGRAMS\${APP_NAME}\卸载 ${APP_NAME}.lnk"
  Delete "$SMPROGRAMS\${APP_NAME}\README.lnk"
  RMDir "$SMPROGRAMS\${APP_NAME}"
  Delete "$DESKTOP\${APP_NAME}.lnk"

  RMDir "$INSTDIR"

  ${If} $R0 == 1
    MessageBox MB_ICONINFORMATION|MB_OK "程序已卸载，配置与运行记录保留在：$\n$INSTDIR\config"
  ${EndIf}
SectionEnd
