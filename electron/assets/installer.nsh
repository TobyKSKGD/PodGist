!include FileFunc.nsh

!macro customPageAfterChangeDir
  Page custom EnsurePodGistInstallDirectory
!macroend

Function EnsurePodGistInstallDirectory
  # electron-updater 触发的是静默安装，必须继续使用已登记的安装目录，不能迁移位置。
  IfSilent ensure_done

  # 安装向导让用户选择的是父目录；最终程序始终放入独立的 PodGist 子目录。
  # 仅比较最后一级目录名，避免 D:\PodGistDownloads 这类路径被误认为专用目录。
  ${GetFileName} "$INSTDIR" $0
  StrCmp $0 "${APP_FILENAME}" ensure_done
  StrCpy $INSTDIR "$INSTDIR\${APP_FILENAME}"

  # 这是一个无 UI 的过渡页面：修改路径后立即进入安装进度页。
ensure_done:
  Abort
FunctionEnd
