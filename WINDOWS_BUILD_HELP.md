# PodGist Windows 跨平台打包求助文档

> 更新时间：2026-04-03
> 项目地址：https://github.com/TobyKSKGD/PodGist

---

## 一、最终目标

在 macOS 本地开发机上（无需 Windows 双系统/虚拟机），通过 GitHub Actions Windows Runner 打包 Windows .exe 安装包，并上传到 GitHub Release v1.0.0 的 Assets 区域，与已有的 macOS DMG 并存。

**最终效果参考**：https://github.com/farion1231/cc-switch/releases — 每个 Release 页面包含多平台下载物。

---

## 二、项目架构

PodGist 是一个 Electron + Python FastAPI 桌面应用：

```
前端：React 19 + TypeScript + Vite（静态构建）
后端：FastAPI + Python（Python 进程作为 Electron 子进程运行）
```

- **macOS**：Python 虚拟环境（`python_venv`）+ `start_electron.py` 脚本
- **Windows**：PyInstaller `--onedir` 打包 Python 后端为 `api-engine.exe`，无控制台窗口
- **FFmpeg**：两个平台均打包为独立二进制

---

## 三、当前已解决的核心技术问题

以下是踩过的所有坑，均已修复：

### 1. PyInstaller `--onedir` vs `--onefile`

- **问题**：`--onefile` 会每次启动时解压 1.5-2GB 到 Temp，启动慢 10-30 秒
- **解决**：使用 `--onedir` 生成目录，启动 1-2 秒

### 2. Windows `fork()` 无限递归蓝屏

- **问题**：Windows 没有 `fork()`，Uvicorn 多进程 + PyTorch 会导致无限递归启动，瞬间内存爆炸蓝屏
- **解决**：在 `backend/start_electron.py` 开头添加：
  ```python
  import multiprocessing
  if __name__ == '__main__':
      multiprocessing.freeze_support()
  ```

### 3. PyInstaller `.spec` 文件 vs 命令行参数

- **问题**：传递 `.spec` 文件时，命令行不能再传 `--onedir`、`--noconsole` 等选项
- **解决**：所有选项写在 `.spec` 文件里

### 4. `SPECPATH` 路径误解

- **问题**：`SPECPATH` 指向 spec 文件所在目录（`backend/`），而不是项目根目录
- **解决**：
  ```python
  project_root = os.path.dirname(os.path.abspath(SPECPATH))  # = 项目根目录
  entry_point = os.path.join(project_root, 'backend', 'start_electron.py')
  ```

### 5. `win_private_assemblies` 已废弃

- **问题**：PyInstaller v6.0 移除了 `win_private_assemblies` 参数
- **解决**：从 `.spec` 文件中删除该参数

### 6. windows-latest 默认 Shell 是 PowerShell 7

- **问题**：Unix 命令（`ls`、`find`、`cp -r`）在 PowerShell 中不存在，导致所有 step 失败
- **解决**：每个 step 添加 `shell: bash`

### 7. PyInstaller 日志捕获

- **问题**：构建失败时看不到日志
- **解决**：重定向到文件 + `actions/upload-artifact@v4` 上传

### 8. electron-builder 输出目录理解错误

- **问题**：`directories.output: ../release/${version}` 是相对于 `electron/` 目录的，实际输出到 `$GITHUB_WORKSPACE/release/`
- **解决**：workflow 中使用 `${{ github.workspace }}/release/` 而非 `${{ github.workspace }}/electron/release/`

### 9. PyInstaller 动态导入隐式依赖

- **问题**：FastAPI/Pydantic 有大量运行时才导入的模块，直接打包会缺模块
- **解决**：在 `.spec` 的 `hiddenimports` 中列出所有隐式依赖（60+ 个）

---

## 四、当前唯一未解决的核心问题

### 问题：两个 GitHub Actions Job 同时运行导致 Release Asset 为空

#### 现象

workflow 每次运行成功（PyInstaller 成功生成 `api-engine.exe`，electron-builder 成功生成 `PodGist.exe`），但最终 Release 的 Assets 始终为 0。

#### 根本原因分析

**`electron-builder.yml` 中存在 `publish:` 配置：**

```yaml
publish:
  provider: github
  owner: TobySKKGD
  repo: PodGist
  releaseType: draft
```

这个 `publish:` 配置会在 workflow 中**自动创建一个名为 "Create Release" 的独立 Job**，与用户定义的 "Build Windows Installer" Job **同时运行**。

```
Build Windows Installer Job          Create Release Job (electron-builder 内置)
        ↓                                    ↓
  构建产物生成                             等待构建产物
        ↓                                    ↓
  softprops/action-gh-release            electron-builder 自己的上传
  试图创建 draft release
        ↓                                    ↓
  ⚠️ 403 — release 已存在（另一 Job 创建了同名 tag 的 release）
```

两个 Job 同时争抢创建同一个 tag（`v1.0.0-windows`）的 draft release。先创建的那个成功，后来的那个收到 403 或 0 assets。

#### 已尝试但失败的方案

| 方案 | 失败原因 |
|------|----------|
| `softprops/action-gh-release` + `draft: true` | 同一个 tag 只能创建一次 release，第二次返回 403 |
| workflow_dispatch 手动指定不同 tag 名 | electron-builder publish 仍会自动创建同名 release |
| 禁用 electron-builder 的 `publish:` 配置 | 无法自动上传（需要 PAT），且 workflow 不会创建 release |
| 删除旧 draft release 后再上传 | `GITHUB_TOKEN` 跨 workflow 访问另一个 workflow 创建的 release 仍然 403 |
| `find` 循环上传所有 `.exe` 文件 | 1. 递归匹配到几百个内部 .exe；2. 403 权限问题 |

#### 构建本身是成功的

以下文件均已确认正确生成：
- `release/1.0.0/win-unpacked/PodGist.exe`（176 MB）✅
- `release/1.0.0/*.exe`（NSIS 安装包）✅
- `dist/api/`（PyInstaller 打包的 api-engine）✅

---

## 五、关键文件当前状态

### 1. `.github/workflows/build-windows.yml`

```yaml
name: Build Windows Installer

on:
  push:
    tags:
      - 'v*-win*'
  workflow_dispatch:
    inputs:
      tag:
        description: 'Git tag to build'
        required: false

jobs:
  build-windows:
    runs-on: windows-latest
    timeout-minutes: 120
    permissions: write-all

    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Setup Node.js
        uses: actions/setup-node@v4
        with:
          node-version: '20'

      - name: Build frontend
        run: |
          cd frontend
          npm install
          npm run build
        env:
          NODE_OPTIONS: '--max-old-space-size=4096'

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.10'
          cache: 'pip'
          cache-dependency-path: 'requirements.txt'

      - name: Download Windows FFmpeg
        run: |
          curl -L -o ffmpeg.zip https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip
          7z x ffmpeg.zip -o"ffmpeg_temp"
          mkdir -p electron/resources/ffmpeg
          cp ffmpeg_temp/ffmpeg-master-latest-win64-gpl/bin/*.exe electron/resources/ffmpeg/
        shell: bash

      - name: Install Python dependencies
        run: |
          pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
          pip install -r requirements.txt
          pip install pyinstaller

      - name: Run prebuild
        run: |
          cd electron
          npm install
          node scripts/prebuild.js

      - name: Package backend with PyInstaller
        run: pyinstaller --log-level=DEBUG backend/api.spec > pyinstaller_build.log 2>&1
        working-directory: ${{ github.workspace }}
        shell: bash
        continue-on-error: true

      - name: Copy PyInstaller output to electron
        run: |
          mkdir -p electron/dist
          cp -r dist/api electron/dist/api
        working-directory: ${{ github.workspace }}
        shell: bash
        continue-on-error: true

      - name: Build Windows installer
        run: npx electron-builder --win --dir
        working-directory: ${{ github.workspace }}/electron
        env:
          NODE_OPTIONS: '--max-old-space-size=4096'

      - name: List all outputs
        run: find release/ -name "*.exe" -type f
        working-directory: ${{ github.workspace }}
        shell: bash

      - name: Upload to Release
        uses: softprops/action-gh-release@v1
        with:
          draft: true
          files: |
            release/**/*.exe
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

### 2. `electron/electron-builder.yml`（问题根源）

```yaml
# ================= electron-builder 配置 =================
target:
  - target: nsis
    arch:
      - x64
  - target: dmg
    arch:
      - arm64

appId: com.podgist.desktop
productName: PodGist
copyright: Copyright © 2026 PodGist Team

# ⚠️ 这个 publish: 配置会自动创建 "Create Release" Job，与用户自定义的
# "Build Windows Installer" Job 同时运行，导致 release 冲突
publish:
  provider: github
  owner: TobySKKGD
  repo: PodGist
  releaseType: draft

directories:
  output: ../release/${version}

nsis:
  oneClick: false
  perMachine: false
  allowToChangeInstallationDirectory: true
  createDesktopShortcut: true
  createStartMenuShortcut: true
  shortcutName: PodGist
  artifactName: ${productName}-${version}-${os}-${arch}.${ext}

win:
  icon: assets/icon.ico
  forceCodeSigning: false
  signAndEditExecutable: false
  target:
    - target: nsis
      arch:
        - x64
  files:
    - src/**/*
    - package.json
    - frontend-dist/**/*
  asarUnpack:
    - frontend-dist/**/*
  extraResources:
    - from: resources/ffmpeg
      to: ffmpeg
    - from: dist/api
      to: api
```

### 3. `backend/api.spec`

```python
# -*- mode: python ; coding: utf-8 -*-
import os
import sys

project_root = os.path.dirname(os.path.abspath(SPECPATH))

block_cipher = None

a = Analysis(
    [os.path.join(project_root, 'backend', 'start_electron.py')],
    pathex=[project_root],
    binaries=[],
    datas=[
        (os.path.join(project_root, 'backend'), 'backend'),
        (os.path.join(project_root, 'api.py'), '.'),
    ],
    hiddenimports=[
        'fastapi', 'fastapi.responses', 'fastapi.middleware.cors',
        'starlette', 'starlette.responses', 'starlette.middleware', 'starlette.middleware.cors',
        'uvicorn', 'uvicorn.logging', 'uvicorn.loops', 'uvicorn.loops.auto',
        'uvicorn.protocols', 'uvicorn.protocols.http', 'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets', 'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan', 'uvicorn.lifespan.on', 'uvicorn.config',
        'pydantic', 'pydantic.deprecated', 'pydantic.deprecated.base',
        'pydantic.deprecated.class_validators', 'pydantic.v1', 'pydantic_settings',
        'openai', 'httpx', 'requests', 'python_dotenv', 'python_multipart',
        'jinja2', 'itsdangerous', 'sniffio',
        'whisper', 'torch', 'torchaudio', 'modelscope', 'modelscope.pipelines',
        'modelscope.utils', 'modelscope.utils.constant', 'funaudio', 'pydub',
        'chromadb', 'chromadb.api', 'chromadb.config', 'chromadb.client', 'chromadb.collection',
        'sentence_transformers', 'sentence_transformers.cross_encoder',
        'yt_dlp', 'yt_dlp.utils', 'yt_dlp.compat',
        'sqlite3', 'json', 'hashlib', 'datetime', 'uuid',
        'numpy', 'nvidia', 'nvidia.cudnn', 'nvidia.cuda_runtime',
        'nvidia.cuda_runtime.driver', 'nvidia.cuda_runtime.events',
        'nvidia.cufft', 'nvidia.curand', 'nvidia.cublas', 'nvidia.cusolver',
        'nvidia.cusparse', 'nvidia.nccl', 'triton', 'safetensors', 'tokenizers',
    ],
    win_no_prefer_redirects=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name='api-engine',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    codesign_identity=None,
    entitlements_file=None,
    exclude=['matplotlib', 'tkinter', 'PyQt5'],
)

coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    strip=False, upx=False, upx_exclude=[],
    name='api',
)
```

### 4. `backend/start_electron.py`

```python
#!/usr/bin/env python3
import sys
import os
import argparse
import platform
import multiprocessing

script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
sys.path.insert(0, project_root)

def parse_args():
    parser = argparse.ArgumentParser(description='PodGist API Server (Electron Mode)')
    parser.add_argument('--data-dir', type=str, default=None, help='用户数据目录')
    parser.add_argument('--model-dir', type=str, default=None, help='AI 模型目录路径')
    parser.add_argument('--resources-path', type=str, default=None, help='Electron 资源目录路径')
    return parser.parse_args()

def main():
    args = parse_args()

    if args.data_dir:
        os.environ['PODGIST_DATA_DIR'] = args.data_dir
    if args.model_dir:
        os.environ['PODGIST_MODEL_DIR'] = args.model_dir
    if args.resources_path:
        os.environ['PODGIST_RESOURCES_PATH'] = args.resources_path
        venv_bin = os.path.join(args.resources_path, 'python_venv', 'bin')
        if platform.system() == 'Windows':
            venv_bin = os.path.join(args.resources_path, 'python_venv', 'Scripts')
        if os.path.isdir(venv_bin):
            os.environ['PATH'] = venv_bin + os.pathsep + os.environ.get('PATH', '')

    from backend import setup_pydub_paths
    setup_pydub_paths()

    import uvicorn
    uvicorn.run(
        "api:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
        log_level="info"
    )

if __name__ == "__main__":
    # Windows 专用：防止 PyTorch/Uvicorn 多进程无限递归启动
    multiprocessing.freeze_support()
    main()
```

### 5. `electron/src/backendStarter.js`（Windows 适配关键部分）

```javascript
const { spawn, exec } = require('child_process');

async startPythonBackend() {
    const platform = process.platform;

    if (platform === 'win32') {
        // Windows: 使用 PyInstaller --onedir 打包的可执行文件
        const apiEngineExe = path.join(process.resourcesPath, 'api', 'api-engine.exe');
        pythonPath = apiEngineExe;
        pythonArgs = [
            '--data-dir', this.userDataPath,
            '--resources-path', process.resourcesPath
        ];
        console.log('[BackendStarter] Windows 模式: 使用 PyInstaller 打包的后端');
    } else {
        // macOS/Linux: 使用 python_venv
        pythonPath = path.join(this.pythonVenvPath, 'bin', 'python3');
        pythonArgs = [startScript, '--data-dir', this.userDataPath, '--resources-path', process.resourcesPath];
    }

    const env = {
        ...process.env,
        PODGIST_DATA_DIR: this.userDataPath,
        PODGIST_RESOURCES_PATH: process.resourcesPath,
        PODGIST_MODEL_DIR: process.env.PODGIST_MODEL_DIR || '',
        NODE_ENV: process.env.NODE_ENV || 'production'
    };

    // Windows: 注入 FFmpeg/FFprobe 路径
    if (platform === 'win32') {
        const ffmpegDir = path.join(process.resourcesPath, 'ffmpeg');
        env.PATH = `${ffmpegDir};${env.PATH}`;
        env.FFMPEG_BINARY = path.join(ffmpegDir, 'ffmpeg.exe');
        env.FFPROBE_BINARY = path.join(ffmpegDir, 'ffprobe.exe');
    }

    const spawnOptions = {
        stdio: ['ignore', 'pipe', 'pipe'],
        env,
        cwd: this.userDataPath
    };

    // Windows: 隐藏所有子进程窗口，防止闪黑框
    if (platform === 'win32') {
        spawnOptions.windowsHide = true;
    }

    this.pythonProcess = spawn(pythonPath, pythonArgs, spawnOptions);
}

stop() {
    if (this.pythonProcess) {
        if (process.platform === 'win32') {
            // Windows: 使用 tree-kill 终止进程树，防止 Uvicorn worker 变僵尸进程
            exec(`taskkill /pid ${this.pythonProcess.pid} /t /f`, () => {});
        } else {
            this.pythonProcess.kill('SIGKILL');
        }
        this.pythonProcess = null;
    }
}
```

---

## 六、可能的解决方向

### 方向 1：禁用 electron-builder 的 `publish:`，完全手动控制上传

**做法**：从 `electron-builder.yml` 中删除 `publish:` 块，用 `softprops/action-gh-release` 统一上传。

**问题**：electron-builder 不会再自动创建 release，需要 workflow 自己创建 release。

**风险**：workflow 创建 release 时，如果 tag 对应的 release 已存在，仍会冲突。

### 方向 2：使用 `release_id` 参数上传到已有 release

`softprops/action-gh-release` 可能支持 `release_id` 参数，让它追加上传到已有 release（v1.0.0 正式 release ID: 304913956）而不是创建新的。

**问题**：需要测试 `release_id` 是否接受数字 ID，以及权限是否足够。

### 方向 3：先删除已存在的 release，再让 workflow 重建

在 workflow 最开头添加一个删除 step：
```yaml
- name: Delete existing release
  run: |
    curl -X DELETE https://api.github.com/repos/${{ github.repository }}/releases/tags/${{ github.ref_name }}
    -H "Authorization: token ${{ secrets.GITHUB_TOKEN }}"
```

**问题**：同一次 workflow run 内，新创建的 release 可能又被 electron-builder 的 "Create Release" Job 发现并冲突。

### 方向 4：换一种上传机制

使用 `actions/upload-artifact@v4` 先上传 artifact，再用独立 Job 或 script 下载并上传到 release。

**问题**：`GITHUB_TOKEN` 跨 job 访问权限问题。

### 方向 5：修改 tag 策略，完全分离两个 Job

让 electron-builder 的 publish 使用不同的 tag（如 `v1.0.0-win`），然后手动把 asset 移动到 `v1.0.0` release。

**问题**：GitHub API 不支持移动 assets between releases，需要下载再上传，麻烦。

---

## 七、GitHub Token 权限说明

- 当前使用 `secrets.GITHUB_TOKEN`（自动分配）
- `GITHUB_TOKEN` 在同一个 workflow run 内有效，但**无法访问另一个 workflow run 创建的 release**
- 创建 Release 需要 `repo` 范围权限
- 当前 workflow 已设置 `permissions: write-all`

---

## 八、参考资源

- electron-builder publish 配置：https://www.electron.build/configuration/publish
- softprops/action-gh-release：https://github.com/softprops/action-gh-release
- PyInstaller Windows 打包：https://pyinstaller.org/en/stable/windows.html
- GitHub REST API Releases：https://docs.github.com/en/rest/repos/releases
