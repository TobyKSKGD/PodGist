# Windows 本地打包指南

> 本指南用于在 Windows PC 上本地构建 PodGist Windows 安装包（.exe）。
> 适用于：已有 Python/Node.js 环境，想在本地打包（支持 GPU/CUDA）的用户。

---

## 前提条件

### 必须安装的工具

| 工具 | 最低版本 | 安装方式 |
|------|---------|---------|
| Python | 3.10+ | [python.org](https://www.python.org/downloads/) |
| Node.js | 20+ | [nodejs.org](https://nodejs.org/) |
| Git | 任意 | [git-scm.com](https://git-scm.com/download/win) |
| 7-Zip | 任意 | [7-zip.org](https://www.7-zip.org/) |

> **注意**：如果 `python` 或 `pip` 命令找不到，需要把 Python 安装目录加入 PATH。装 Python 时勾选 "Add Python to PATH"。

### 验证环境（CMD 或 PowerShell 中运行）

```bash
python --version
node --version
git --version
7z --help
pip --version
```

---

## 完整打包流程

### 第一步：克隆代码

```bash
git clone git@github.com:TobySKKGD/PodGist.git
cd PodGist
```

### 第二步：构建前端

```bash
cd frontend
npm install
npm run build
cd ..
```

> 前端构建产物会输出到 `frontend/dist/`，prebuild 脚本会自动把它复制到 `electron/frontend-dist/`。

### 第三步：下载 FFmpeg

1. 打开浏览器访问：
   https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip

2. 下载完成后，用 7-Zip 解压（右键 → 7-Zip → 解压到当前位置）

3. 把解压出来的 `ffmpeg-master-latest-win64-gpl/bin/` 目录下的所有 `.exe` 文件复制到项目目录 `electron/resources/ffmpeg/`（如果目录不存在就新建）

```
electron/resources/ffmpeg/
├── ffmpeg.exe
├── ffprobe.exe   （如果有）
└── ffplay.exe   （如果有）
```

### 第四步：安装 Python 依赖

> **GPU 版（推荐）**：如果你的 Windows PC 有 NVIDIA 显卡，用这个命令：
```bash
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124
```

> **CPU 版**：如果没有 NVIDIA 显卡，用这个命令：
```bash
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
```

继续安装其他依赖：
```bash
pip install -r requirements.txt
pip install pyinstaller
```

### 第五步：打包 Python 后端（PyInstaller）

```bash
pyinstaller --noconsole --onedir backend/api.spec
```

产物输出到 `dist/api/`。

### 第六步：复制后端到 electron 目录

```bash
mkdir electron\dist
xcopy /E /I dist\api electron\dist\api
```

### 第七步：构建 Windows 安装包

```bash
cd electron
npm install
node scripts\prebuild.js
npx electron-builder --win
```

> `npx electron-builder --win` 会输出 NSIS 安装包到 `release/` 目录。

### 第八步：找到安装包

```
release/1.0.0/PodGist-1.0.0-win-x64.exe
```

---

## 完整一键脚本（复制到 PodGist 根目录运行）

> 将以下内容保存为 `build.bat`，双击运行即可。

```bat
@echo off
chcp 65001 >nul
echo ===== PodGist Windows 打包开始 =====

REM 1. 构建前端
echo [1/7] 构建前端...
cd frontend
call npm install
call npm run build
cd ..

REM 2. 下载 FFmpeg（如已手动放置可跳过）
echo [2/7] 检查 FFmpeg...
if not exist "electron\resources\ffmpeg\ffmpeg.exe" (
    echo FFmpeg 未找到，请手动下载并放置到 electron\resources\ffmpeg\
    echo 访问: https://github.com/BtbN/FFmpeg-Builds/releases
    pause
    exit /b 1
)
echo FFmpeg 已就绪

REM 3. 安装 Python 依赖（GPU CUDA 版）
echo [3/7] 安装 Python 依赖（CUDA 12.4）...
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124
pip install -r requirements.txt
pip install pyinstaller

REM 4. 打包 Python 后端
echo [4/7] PyInstaller 打包...
pyinstaller --noconsole --onedir backend\api.spec

REM 5. 复制后端到 electron 目录
echo [5/7] 复制后端到 electron\dist\...
mkdir electron\dist 2>nul
xcopy /E /I dist\api electron\dist\api

REM 6. prebuild & electron-builder
echo [6/7] prebuild...
cd electron
call npm install
call node scripts\prebuild.js
echo [7/7] 构建 Windows 安装包...
call npx electron-builder --win
cd ..

echo.
echo ===== 打包完成 =====
echo 安装包位置: release\1.0.0\
dir release\1.0.0\*.exe
pause
```

---

## 常见问题

### Q: `pip` 命令找不到

Python 安装时没勾选 "Add to PATH"。重新运行 Python 安装程序，选择 Modify → Add Python to PATH。

### Q: PyInstaller 打包失败，提示找不到模块

确保 `requirements.txt` 里的依赖全部装上了：
```bash
pip install -r requirements.txt
```

### Q: `npm install` 在 electron 目录失败

先删掉 node_modules 试试：
```bash
cd electron
rmdir /s /q node_modules
npm install
```

### Q: 打包出来的安装包没有图标

确认 `electron/assets/icon.ico` 文件存在，然后检查 `electron-builder.yml` 里的路径配置是否正确。

### Q: SenseVoice / Whisper 转录功能报错

大概率是 FunASR 或 ModelScope 的 hiddenimports 不全。可以尝试在 `backend/api.spec` 的 `hiddenimports` 里添加更多模块，然后重新打包。

### Q: 打包后运行报错 "api-engine.exe not found"

检查 `electron/dist/api/` 目录下是否有 `api-engine.exe` 文件。如果有，检查 `electron-builder.yml` 的 `extraResources` 配置。

---

## 环境清理（可选）

如果需要重新干净打包，先清理缓存：

```bash
# 清理 PyInstaller 缓存
rmdir /s /q backend\dist 2>nul
rmdir /s /q backend\build 2>nul
rmdir /s /q electron\dist 2>nul
rmdir /s /q electron\frontend-dist 2>nul

# 清理 Python 缓存（不要删 node_modules）
rmdir /s /q electron\node_modules\.cache 2>nul
```
