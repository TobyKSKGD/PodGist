# PodGist 发布流程

## 后端源码真源

**唯一后端源码位置**：
- `api.py` — FastAPI 主程序入口
- `backend/` — 所有后端模块（`worker.py`, `transcriber.py`, `llm_agent.py`, `downloader.py` 等）

**重要**：`electron/scripts/backend/` 和 `electron/scripts/api.py` 已废弃，不应再作为源码维护。所有构建均从根目录 `backend/` 和 `api.py` 出发。

---

## 本地开发启动

```bash
# 在项目根目录（PodGist/）运行：
npm run dev

# 或分别启动：
npm run dev:backend   # 仅后端（uvicorn on :8000）
npm run dev:frontend  # 仅前端（vite on :5173）
```

**前端开发**：`frontend/package.json` 的 `dev` 仅运行 `vite`，不再耦合后端启动。

**后端开发**：`scripts/dev/run-backend.mjs` 自动寻找 Python 解释器并启动 uvicorn，不需要 `source env/bin/activate`。

---

## 本地 mac 打包

```bash
# 1. 安装前端依赖并构建
cd frontend && npm install && npm run build && cd ..

# 2. 创建 python_venv（如果还没有）
python3 -m venv env

# 3. 安装 Python 依赖
pip install -r requirements.txt

# 4. Bootstrap runtime（安装 yt-dlp 和 ffmpeg）
bash scripts/release/bootstrap-runtime-mac.sh

# 5. 预构建（复制根目录源码到 electron/ 目录）
cd electron && npm install && npm run prebuild && cd ..

# 6. 打包
cd electron && npm run build:mac
# 产物：release/${version}/PodGist-${version}-mac-arm64.dmg
```

---

## Windows 构建（通过 CI）

Windows 不在本地构建。通过 GitHub Actions 统一 workflow：

### 触发发布

```bash
# 推送一个 v* tag 即可同时触发 mac + win 构建
git tag v0.1.1
git push origin v0.1.1
```

### 或手动触发

在 GitHub Actions 页面手动运行 `Build Desktop App` workflow，可选择只构建特定平台。

### CI 流程概述

1. **create-release** job — 为 tag 创建 draft release
2. **build** job (matrix) — 并行构建 mac + win
   - macOS：bootstrap-runtime → electron-builder dmg
   - Windows：PyInstaller backend → ffmpeg → electron-builder nsis
3. 自动上传安装包到同一个 release 页面

---

## 统一 workflow 文件

`.github/workflows/build-desktop.yml` — 唯一的正式发布 workflow

- **触发条件**：`push tag v*` 或 `workflow_dispatch`
- **构建平台**：macOS (arm64 dmg) + Windows (x64 nsis)
- **产物位置**：`release/${version}/`

已删除的旧 workflow：
- `.github/workflows/build-windows.yml` — 废弃（已合并到 build-desktop.yml）
- `.github/workflows/release.yml` — 废弃（功能已合并到 build-desktop.yml）

---

## 平台运行时差异（保留）

| 差异点 | macOS | Windows |
|--------|-------|---------|
| 后端入口 | `python_venv/bin/python3 start_electron.py` | `api-engine.exe` (PyInstaller) |
| Python 环境 | `electron/resources/python_venv/` | 打包进 `api-engine.exe` |
| FFmpeg | `electron/resources/ffmpeg/` | `electron/resources/ffmpeg/` |
| 进程管理 | `backendStarter.js` spawn + SIGKILL | `backendStarter.js` spawn + taskkill |

**共同点**：均使用根目录 `backend/` 和 `api.py` 作为源码，无第二份源码。

---

## 版本规则

- **版本格式**：严格使用 Semantic Versioning 的三段式 `主版本.次版本.修订版本`，例如 `0.2.7`
- **主版本**：发生不兼容的重大变化时递增
- **次版本**：以向后兼容方式增加功能时递增
- **修订版本**：以向后兼容方式修复问题或进行小幅改进时递增；补丁发布也递增此位，不使用第四段数字
- **测试阶段**：当前主版本为 `0`，表示产品仍处于持续迭代阶段
- **发布标签**：在版本号前加 `v`，例如 `v0.2.7`
- **不再使用**：`v*-windows` 这种 tag 格式
- 同一个 tag 产生同一个 release 页面，包含 mac + win 两个安装包

## 内置自动更新发布要求

PodGist 客户端通过 GitHub Releases 检查更新。免费分发阶段仅 Windows 使用程序内自动安装：

- Windows：NSIS 安装包、`latest.yml` 与对应 blockmap；
- macOS：DMG；客户端仅检查最新 Release 并引导用户手动替换 Applications 中的应用。

Windows 更新文件由 `electron-builder --publish always` 自动生成并上传。不要手动混用不同构建产生的 `latest.yml`、安装包或 blockmap，否则客户端的 SHA-512 校验会拒绝更新。

更新客户端无法读取 Draft Release；workflow 会在所有构建、验包和资源上传成功后才发布 Release。未来若 macOS 配置 Developer ID 签名与 notarization，可恢复 macOS ZIP 自动更新载荷。

---

## 后续不要再引入第二套后端源码

### 如果需要在 `backend/` 之外修改后端代码，直接修改根目录 `backend/` 和 `api.py`。所有 CI 和本地构建均读取根目录，不再同步自 `electron/scripts/`。
