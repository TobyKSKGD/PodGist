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

## 构建步骤（按顺序执行）

### Step 1: 克隆项目

```powershell
git clone https://github.com/TobyKSKGD/PodGist.git
cd PodGist
```

---

### Step 2: 安装 Python 依赖（先做这个！）

```powershell
cd PodGist

# 创建虚拟环境
python -m venv env

# 激活虚拟环境
env\Scripts\activate

# 安装 PyTorch（根据你的硬件选择）：

# 方式 A：NVIDIA GPU 用户
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu126

# 方式 B：仅 CPU 用户（推荐，没有 GPU 的人用这个）
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu

# 安装所有 Python 依赖
pip install -r requirements.txt
```

**验证安装成功**：
```powershell
python -c "import whisper; import modelscope; import chromadb; print('所有依赖安装成功')"
```

---

### Step 3: 下载 AI 模型

依赖安装好后，才能下载模型。

```powershell
# 确保在 PodGist 目录下且虚拟环境已激活
cd PodGist
env\Scripts\activate

# 3.1 下载 Whisper large-v3 模型（约 1.5GB，可能需要 10-30 分钟）
python -c "
import whisper
print('正在下载 Whisper large-v3 模型...')
model = whisper.load_model('large-v3')
print('Whisper 模型下载完成')
"

# 3.2 下载 SenseVoice 模型（约 200MB）
python -c "
from modelscope.pipelines import pipeline
from modelscope.utils.constant import Tasks
print('正在下载 SenseVoice 模型...')
p = pipeline(Tasks.auto_speech_recognition, model='iic/SenseVoiceSmall')
print('SenseVoice 模型下载完成')
"

# 3.3 下载 Sentence Transformer 模型（约 90MB）
python -c "
from sentence_transformers import SentenceTransformer
print('正在下载 Sentence Transformer 模型...')
model = SentenceTransformer('all-MiniLM-L6-v2')
print('Sentence Transformer 模型下载完成')
"
```

**模型默认保存到**：`%USERPROFILE%\.cache\` 目录下

---

### Step 4: 准备 FFmpeg

1. 访问 https://www.gyan.dev/ffmpeg/builds/
2. 下载 `ffmpeg-release-essentials.zip`
3. 解压得到 `ffmpeg.exe`
4. 将 `ffmpeg.exe` 复制到 `PodGist\electron\resources\ffmpeg\`
   - 如果没有这个文件夹，先创建：`mkdir electron\resources\ffmpeg`

---

### Step 5: 创建 Python 虚拟环境（Electron 打包用）

```powershell
# 在 electron 目录下创建虚拟环境
cd electron
python -m venv resources\python_venv

# 安装依赖到这个虚拟环境
resources\python_venv\Scripts\activate
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
pip install -r ..\requirements.txt
deactivate
```

---

### Step 6: 拷贝模型到资源目录

```powershell
# 创建模型目录
mkdir electron\resources\models

# 拷贝 Whisper 模型
xcopy /E /I "%USERPROFILE%\.cache\whisper" electron\resources\models\whisper-large-v3

# 拷贝 SenseVoice 模型
xcopy /E /I "%USERPROFILE%\.cache\modelscope\iic" electron\resources\models\SenseVoiceSmall

# 拷贝 Sentence Transformer 模型
mkdir electron\resources\models\all-MiniLM-L6-v2
xcopy /E /I "%USERPROFILE%\.cache\huggingface\hub\models--sentence-transformers--all-MiniLM-L6-v2" electron\resources\models\all-MiniLM-L6-v2
```

---

### Step 7: 安装 Node.js 依赖

```powershell
cd electron
npm install
```

---

### Step 8: 构建 Windows 安装包

```powershell
# 构建完整包（包含所有模型）
set BUILD_TYPE=full
npm run build:win
```

或者一行命令：
```powershell
cd electron
set BUILD_TYPE=full && npm run build:win
```

构建产物会在 `release\1.0.0\windows\` 目录下。

---

## 快速命令汇总

```powershell
# 完整流程
git clone https://github.com/TobyKSKGD/PodGist.git
cd PodGist

# 1. 安装 Python 依赖
python -m venv env
env\Scripts\activate
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt

# 2. 下载模型
python -c "import whisper; whisper.load_model('large-v3')"
python -c "from modelscope.pipelines import pipeline; pipeline('auto_speech_recognition', 'iic/SenseVoiceSmall')"
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

# 3. FFmpeg 放到 electron\resources\ffmpeg\

# 4. 创建打包用虚拟环境
cd electron
python -m venv resources\python_venv
resources\python_venv\Scripts\activate
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
pip install -r ..\requirements.txt
deactivate

# 5. 拷贝模型到 electron\resources\models\

# 6. 构建
npm install
set BUILD_TYPE=full && npm run build:win
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
2. 模型是否完整拷贝到 electron\resources\models\
3. python_venv 是否正确创建

### Q: 如何清理重新构建？
```powershell
rd /s /q electron\dist
rd /s /q electron\out
rd /s /q release
npm run build:win
```
