# macOS 预览版说明

## 当前状态

**PodGist macOS 版本处于 AD-HOC SIGNED PREVIEW 状态。**

本版本使用 ad-hoc 签名（不是 Apple 正式签名/公证）。

## 为什么是预览版

Apple 要求 macOS 14+ 上的应用必须经过**签名 + 公证**才能被系统完全信任。
签名需要 Apple Developer Program 会员资格（年费约 688 元），
公证需要 Xcode 或 `xcrun notarytool` 提交审核。

在正式签名版本发布前，提供 ad-hoc 签名预览版构建。

## 首次打开（推荐方式）

双击 `.dmg` → 拖动 `PodGist.app` 到应用程序文件夹 → 双击打开。

如果 macOS 弹出安全提示：

1. **优先选择**：点击弹框中的 **"仍要打开"（Open Anyway）**
   - 这是在系统界面放行，不需要任何终端命令
   - 放行后应用会正常启动

2. **如果弹框没有"仍要打开"选项**：在 **系统设置 → 隐私与安全性** 中滚动到底部，找到 "仍要打开" 按钮

3. **极少数情况**：如果系统直接显示"已损坏"（而非"不受信任"），才需要执行以下终端命令放行：
   ```bash
   sudo xattr -rd com.apple.quarantine /Applications/PodGist.app
   ```
   如果仍报"已损坏"，再执行：
   ```bash
   sudo codesign --force --deep --sign - /Applications/PodGist.app
   ```

## 已知行为

- ad-hoc 签名不会显示"已损坏"
- 系统会拦截并提示"不受信任"，但通常有"仍要打开"按钮
- 这是 macOS 的正常安全机制，预览版无法绕过

## 下载说明

**下载入口：GitHub Release 页面的 .dmg 文件**

不要从 GitHub Actions Artifacts 下载（仅供内部调试）。

## 正式版计划

获取 Apple Developer Program 会员资格后，将发布正式签名 + 公证版本，届时下载后直接双击即可运行，无需任何放行步骤。
