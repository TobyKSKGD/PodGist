# PodGist Windows 打包指南

---

## Phase 1：精简版（约 300-400MB）

模型在用户首次运行时从网络下载。

### Step 1：放置 FFmpeg

从 https://www.gyan.dev/ffmpeg/builds/ 下载 `ffmpeg-release-essentials.zip`，解压得到 `ffmpeg.exe`，复制到：

```
PodGist\electron\resources\ffmpeg\ffmpeg.exe
```

### Step 2：创建 Python 虚拟环境

```powershell
cd PodGist\electron
python -m venv resources\python_venv
```

### Step 3：安装 Python 依赖

```powershell
resources\python_venv\Scripts\activate

pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
pip install -r ..\requirements.txt
```

> 如果 PyTorch 下载慢，用镜像：
> `pip install torch torchvision torchaudio -i https://pypi.tuna.tsinghua.edu.cn/simple`

### Step 4：安装 Node 依赖

```powershell
cd electron
npm install
```

### Step 5：打包

```powershell
npm run build:win
```

---

## Phase 2：完整版（约 1.9GB，所有模型打包）

先完成 Phase 1，然后：

### Step A：下载模型到本地缓存

```powershell
cd PodGist
python -m venv env
env\Scripts\activate

python -c "import whisper; whisper.load_model('large-v3')"
python -c "from modelscope.pipelines import pipeline; pipeline('auto_speech_recognition', 'iic/SenseVoiceSmall')"
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

deactivate
```

### Step B：拷贝模型到资源目录

```powershell
cd electron

mkdir resources\models

xcopy /E /I "%USERPROFILE%\.cache\whisper" resources\models\whisper
xcopy /E /I "%USERPROFILE%\.cache\modelscope\hub\models\iic" resources\models\modelscope\hub\models\iic
xcopy /E /I "%USERPROFILE%\.cache\huggingface\hub\models--sentence-transformers--all-MiniLM-L6-v2" resources\models\huggingface\hub\models--sentence-transformers--all-MiniLM-L6-v2
```

### Step C：重新打包

```powershell
npm run build:win
```

---

## 打包产物

| 类型 | 路径 |
|------|------|
| 便携版 | `release\1.0.0\win-unpacked\PodGist.exe` |
| 安装版 | `release\1.0.0\PodGist-*-win-*.exe` |

---

## 常见问题

**npm install 报错** → 确保 Node.js 已添加到 PATH

**pip install 报错网络错误** → 用镜像 `-i https://pypi.tuna.tsinghua.edu.cn/simple`

**打包后运行闪退** → 检查 `resources\ffmpeg\ffmpeg.exe` 是否存在，检查 `resources\python_venv\Scripts\python.exe` 是否存在

**清理后重新打包** → `rd /s /q electron\dist`, `rd /s /q electron\out`, `rd /s /q release`，然后重新 `npm run build:win`
