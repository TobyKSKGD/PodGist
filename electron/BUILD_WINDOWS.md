# PodGist Windows 构建指南

## 前提条件

### 1. 安装 Node.js
- 下载地址：https://nodejs.org/ (建议 LTS 版本 18+)
- 安装后打开 PowerShell 验证：
```powershell
node -v
npm -v
```

### 2. 安装 Python 3.10+
- 下载地址：https://www.python.org/downloads/
- **重要**：安装时勾选 "Add Python to PATH"
- 验证安装：
```powershell
python --version
pip --version
```

### 3. 安装 Git
- 下载地址：https://git-scm.com/download/win
- 验证：
```powershell
git --version
```

---

## Phase 1 构建步骤（首次运行下载模型）

Phase 1 安装包约 300-400MB，模型在用户首次运行时从网络下载。

### Step 1: 克隆项目

```powershell
git clone https://github.com/TobyKSKGD/PodGist.git
cd PodGist
```

### Step 2: 准备 FFmpeg

1. 访问 https://www.gyan.dev/ffmpeg/builds/
2. 下载 `ffmpeg-release-essentials.zip`
3. 解压得到 `ffmpeg.exe`
4. 将 `ffmpeg.exe` 复制到 `PodGist\electron\resources\ffmpeg\`

### Step 3: 创建 Python 虚拟环境

```powershell
cd PodGist\electron
python -m venv resources\python_venv

# 激活并安装依赖
resources\python_venv\Scripts\activate
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
pip install -r ..\requirements.txt
deactivate
```

### Step 4: 安装 Node.js 依赖

```powershell
cd PodGist\electron
npm install
```

### Step 5: 构建 Windows 安装包

```powershell
npm run build:win
```

构建产物会在 `release\1.0.0\windows\` 目录下。

---

## Phase 2 构建步骤（打包所有模型）

Phase 2 安装包约 1.9GB，模型全部打包，开箱即用。

### 前提：完成 Phase 1 所有步骤

### Step A: 下载所有模型到本地缓存

```powershell
cd PodGist
env\Scripts\activate

# Whisper large-v3（约 1.5GB，可能需要 10-30 分钟）
python -c "import whisper; whisper.load_model('large-v3')"

# SenseVoice（约 200MB）
python -c "from modelscope.pipelines import pipeline; pipeline('auto_speech_recognition', 'iic/SenseVoiceSmall')"

# Sentence Transformer（约 90MB）
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

deactivate
```

### Step B: 拷贝模型到资源目录

```powershell
# 创建模型目录
mkdir electron\resources\models

# 拷贝 Whisper 模型
xcopy /E /I "%USERPROFILE%\.cache\whisper" electron\resources\models\whisper

# 拷贝 SenseVoice 模型
xcopy /E /I "%USERPROFILE%\.cache\modelscope\hub\models\iic" electron\resources\models\modelscope\hub\models\iic

# 拷贝 Sentence Transformer 模型
xcopy /E /I "%USERPROFILE%\.cache\huggingface\hub\models--sentence-transformers--all-MiniLM-L6-v2" electron\resources\models\huggingface\hub\models--sentence-transformers--all-MiniLM-L6-v2
```

### Step C: 重新构建

```powershell
cd electron
npm run build:win
```

---

## 快速命令汇总

### Phase 1
```powershell
git clone https://github.com/TobyKSKGD/PodGist.git
cd PodGist

# FFmpeg 放到 electron\resources\ffmpeg\

cd electron
python -m venv resources\python_venv
resources\python_venv\Scripts\activate
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
pip install -r ..\requirements.txt
deactivate
npm install
npm run build:win
```

### Phase 2（额外步骤）
```powershell
# 下载模型（首次运行时做）
cd ..
env\Scripts\activate
python -c "import whisper; whisper.load_model('large-v3')"
python -c "from modelscope.pipelines import pipeline; pipeline('auto_speech_recognition', 'iic/SenseVoiceSmall')"
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"
deactivate

# 拷贝模型到 electron\resources\models\

# 重新构建
cd electron && npm run build:win
```

---

## 常见问题

### Q: pip install 报错 "不是内部或外部命令"
确保 Python 已添加到系统 PATH，或者使用 `python -m pip`

### Q: 模型下载中断/失败
重新运行下载命令，会从断点继续

### Q: 打包后运行报错
检查：
1. FFmpeg.exe 是否放在正确位置
2. python_venv 是否正确创建
3. npm install 是否成功

### Q: 如何清理重新构建？
```powershell
rd /s /q electron\dist
rd /s /q electron\out
rd /s /q release
npm run build:win
```
