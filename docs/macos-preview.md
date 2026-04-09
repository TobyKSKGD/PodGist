# macOS 预览版说明

## 当前状态

PodGist macOS 版本目前处于 **UNSIGNED PREVIEW** 状态。

## 为什么是预览版

PodGist macOS 应用**未使用 Apple Developer ID 签名**，也**未经 Apple 公证 (notarization)**。

在 macOS 14 (Sonoma) 及以上版本，未经公证的应用会被 Gatekeeper 拦截，显示"已损坏"错误。

## 首次运行放行步骤

### 方式一：移除 quarantine 属性（推荐）

```bash
sudo xattr -rd com.apple.quarantine /Applications/PodGist.app
open /Applications/PodGist.app
```

### 方式二：手动签名后打开

```bash
# 先移除隔离属性
sudo xattr -rd com.apple.quarantine /Applications/PodGist.app

# 强制签名（临时方案，非 App Store 签名）
sudo codesign --force --deep --sign - /Applications/PodGist.app

# 打开应用
open /Applications/PodGist.app
```

### 方式三：右键打开（无终端）

1. 在 Finder 中找到 `PodGist.app`
2. 按住 **Control** 键，点击应用图标
3. 选择 **"打开"**
4. 在弹出对话框中再次点击 **"打开"**

> 如果没有看到"打开"选项，先执行方式一中的 xattr 命令。

## 常见问题

### Q: 为什么签名后 spctl --assess 仍然 rejected？

这是**预期行为**。Ad-hoc 签名（`codesign --sign -`）不是 Apple Developer ID 签名，无法通过 Gatekeeper 的远程验证。

但只要你执行了上述放行步骤，**应用可以正常使用**。

### Q: 以后会有正式签名版本吗？

是的。未来在获取 Apple Developer Program 会员资格后，会提供正式签名+公证的版本。

### Q: Windows 版本也需要这样处理吗？

不需要。Windows 版本使用代码签名（不是 Apple 的），不受影响。

## 下载地址

正式 macOS 下载入口：**GitHub Release 的 .dmg 文件**。

不要从 Actions Artifacts 下载（仅供内部调试，行为可能不一致）。
