# PodGist Windows 构建指南

## 前提条件

在 Windows 上构建前，需要准备：

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

## 构建步骤

### Step 1: 克隆项目

```powershell
git clone https://github.com/TobyKSKGD/PodGist.git
cd PodGist
```

### Step 2: 下载 AI 模型

**这步很关键**：完整包需要提前下载所有模型。

```powershell
# 进入项目目录
cd PodGist

# 创建模型下载脚本并运行
python -c "
import whisper
print('下载 Whisper large-v3 模型...')
model = whisper.load_model('large-v3')
print('Whisper 模型下载完成')
"
```

```powershell
# SenseVoice 模型
pip install modelscope
python -c "
from modelscope.pipelines import pipeline
from modelscope.utils.constant import Tasks
print('下载 SenseVoice 模型...')
p = pipeline(Tasks.auto_speech_recognition, model='iic/SenseVoiceSmall')
print('SenseVoice 模型下载完成')
"
```

```powershell
# Sentence Transformer 模型
pip install sentence-transformers
python -c "
from sentence_transformers import SentenceTransformer
print('下载 Sentence Transformer 模型...')
model = SentenceTransformer('all-MiniLM-L6-v2')
print('Sentence Transformer 模型下载完成')
"
```

### Step 3: 安装 Python 依赖

```powershell
cd PodGist

# 创建虚拟环境
python -m venv electron\resources\python_venv

# 激活虚拟环境
electron\resources\python_venv\Scripts\activate

# 安装 PyTorch (CPU 版本，Windows NVIDIA GPU 用户用 cu126)
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu

# 安装其他依赖
pip install -r requirements.txt
```

### Step 4: 下载 FFmpeg

下载 FFmpeg Windows 版本并解压到 `electron\resources\ffmpeg\`:

1. 访问 https://www.gyan.dev/ffmpeg/builds/
2. 下载 `ffmpeg-release-essentials.zip`
3. 解压得到 `ffmpeg.exe`
4. 将 `ffmpeg.exe` 复制到 `PodGist\electron\resources\ffmpeg\`

### Step 5: 拷贝模型到资源目录

```powershell
# 创建模型目录
mkdir electron\resources\models

# 拷贝 Whisper 模型 (~1.5GB)
# 模型默认在 %USERPROFILE%\.cache\whisper\
xcopy /E /I "%USERPROFILE%\.cache\whisper" electron\resources\models\whisper

# 拷贝 SenseVoice 模型 (~200MB)
xcopy /E /I "%USERPROFILE%\.cache\modelscope" electron\resources\models\SenseVoiceSmall

# 拷贝 Sentence Transformer 模型 (~90MB)
xcopy /E /I "%USERPROFILE%\.cache\huggingface" electron\resources\models\all-MiniLM-L6-v2
```

### Step 6: 安装 Node.js 依赖

```powershell
cd electron
npm install
```

### Step 7: 构建 Windows 安装包

```powershell
# 完整包（包含所有模型）
npm run build:full
```

构建产物会在 `release\1.0.0\windows\` 目录下。

---

## 完整包构建命令速览

```powershell
# 1. 克隆项目
git clone https://github.com/TobyKSKGD/PodGist.git
cd PodGist

# 2. 下载模型（每步可能需要 10-30 分钟）
python -c "import whisper; whisper.load_model('large-v3')"
python -c "from modelscope.pipelines import pipeline; pipeline('auto_speech_recognition', 'iic/SenseVoiceSmall')"
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

# 3. 安装 Python 虚拟环境和依赖
python -m venv electron\resources\python_venv
electron\resources\python_venv\Scripts\activate
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt

# 4. 下载 FFmpeg 并放到 electron\resources\ffmpeg\

# 5. 拷贝模型到 electron\resources\models\

# 6. 构建
cd electron
npm install
npm run build:full
```

---

## 常见问题

### Q: 模型下载太慢？
可以使用镜像或代理。如果下载中断，可以重新运行下载命令，会从断点继续。

### Q: 报错 "python 不是内部或外部命令"
确保 Python 已添加到系统 PATH。重新安装 Python 时勾选 "Add Python to PATH"。

### Q: 打包后运行报错
检查是否缺少 FFmpeg 或模型文件。确保 `electron\resources\` 目录结构完整。

### Q: 如何清理并重新构建？
```powershell
# 删除构建缓存
rd /s /q electron\dist
rd /s /q electron\out
rd /s /q release

# 重新构建
npm run build:full
```
