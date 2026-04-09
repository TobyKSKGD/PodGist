# macOS 预览版说明

## 当前状态

**PodGist macOS 版本处于 UNSIGNED PREVIEW 状态。**

本版本未使用 Apple Developer ID 签名，也未经 Apple 公证 (notarization)。

## 为什么需要预览版

Apple 要求所有 macOS 应用必须经过**签名 + 公证**才能在 macOS 14+ 上正常运行。
签名需要 Apple Developer Program 会员资格（年费约 688 元），
公证需要 Xcode 或 `xcrun notarytool` 提交审核。

在正式签名版本发布前，我们提供预览版构建，并通过以下步骤绕过 Gatekeeper 限制。

## 首次运行放行（必做，一次即可）

打开应用时，如果 macOS 弹出"无法打开，因为应用来着未知开发者"：

### 步骤 1：移除安全限制（终端执行）

```bash
sudo xattr -rd com.apple.quarantine /Applications/PodGist.app
```

### 步骤 2：启动应用

```bash
open /Applications/PodGist.app
```

之后 PodGist 会正常启动。以后再次打开不需要重复这些步骤。

> **提示**：如果步骤 1 之后仍然报"已损坏"，再执行：
> ```bash
> sudo codesign --force --deep --sign - /Applications/PodGist.app
> ```
> 这是临时 ad-hoc 签名，不是 App Store 签名，不需要 Apple ID。

## 首次后遇到其他错误怎么办

### "后端启动失败"错误页

这通常是以下三类问题之一：

**1. 端口 8000 被占用**

错误信息包含 `8000 端口被占用`。
解决：关闭其他占用 8000 端口的程序（如其他 PodGist 实例、Python 调试服务器等），然后重新打开 PodGist。

**2. FFmpeg 未找到**

错误信息包含 `ffmpeg` 或 `FFmpeg`。
解决：在终端执行 `xattr -rd com.apple.quarantine /Applications/PodGist.app`，然后重试。

**3. 其他内部错误**

请查看错误页底部的日志文件路径，或执行：
```bash
cat ~/Library/Logs/PodGist/backend-error.log | tail -50
```
将错误信息反馈给开发者。

## macOS 预览版已知限制

- 需要手动放行（执行 xattr 命令），不能直接双击打开
- macOS 可能会再次弹出安全提示（在大版本更新后）
- 部分安全软件可能报告异常（预览版未经公证，属正常警告）

## 正式版计划

在获取 Apple Developer Program 会员资格后，将发布正式签名 + 公证版本，届时：
- 下载后直接双击即可运行
- 无需终端命令
- Gatekeeper 完全通过

## 下载说明

**正式版下载入口：GitHub Release 页面的 .dmg 文件**

不要从 GitHub Actions Artifacts 下载（仅供内部调试，版本行为可能不一致）。
