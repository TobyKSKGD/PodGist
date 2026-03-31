# PodGist Windows 构建指南

> **重要**：Windows 打包必须在 Windows 电脑上执行，无法在 Mac/Linux 上交叉编译。

---

## Phase 1（精简版，推荐先做这个）

精简版安装包约 300-400MB，AI 模型在用户首次运行时从网络下载。

**优点**：安装包小，打包快
**缺点**：用户首次使用需要下载模型（约 1.5GB）

---

## Phase 2（完整版）

完整版安装包约 1.9GB，所有 AI 模型全部打包进安装包，开箱即用。

**优点**：完全离线，开箱即用
**缺点**：安装包大，打包耗时长

---

## Windows 电脑上的准备工作

### 1. 确认系统

- Windows 10 或 Windows 11
- 64 位系统（x64）
- 至少 20GB 可用磁盘空间

### 2. 安装必要软件

#### Node.js（必需）

1. 打开 https://nodejs.org/
2. 下载 **LTS 版本**（推荐 20.x 或 18.x）
3. 安装时**务必勾选** "Add to PATH"
4. 验证安装：
   ```powershell
   node -v
   npm -v
   ```

#### Python（必需）

1. 打开 https://www.python.org/downloads/
2. 下载 **Python 3.10 或更高版本**
3. 安装时**务必勾选** "Add Python to PATH"
4. 验证安装：
   ```powershell
   python --version
   pip --version
   ```

#### Git（推荐）

1. 打开 https://git-scm.com/download/win
2. 下载并安装
3. 验证安装：
   ```powershell
   git --version
   ```

---

## 开始构建

### Step 1: 克隆项目

打开 **PowerShell**（开始菜单 → 搜索 "PowerShell" → 以管理员运行）：

```powershell
cd C:\Users\你的用户名\Desktop  # 或者你喜欢的目录

git clone https://github.com/TobyKSKGD/PodGist.git

cd PodGist
```

> 如果 git 失败，可以直接从 GitHub 下载 ZIP：
> https://github.com/TobyKSKGD/PodGist/archive/refs/heads/main.zip
> 解压后用 `cd PodGist-main` 进入目录

### Step 2: 下载 FFmpeg

1. 打开 https://www.gyan.dev/ffmpeg/builds/
2. 点击 **ffmpeg-release-essentials.zip** 下载（约 80MB）
3. 解压下载的 ZIP 文件
4. 进入解压后的文件夹，找到 `bin\ffmpeg.exe`
5. 将 `ffmpeg.exe` **复制到**：
   ```
   C:\Users\你的用户名\Desktop\PodGist\electron\resources\ffmpeg\ffmpeg.exe
   ```
6. 如果 `ffmpeg` 文件夹不存在，手动创建：
   ```powershell
   mkdir electron\resources\ffmpeg
   # 然后复制 ffmpeg.exe 到这个目录
   ```

### Step 3: 创建 Python 虚拟环境

```powershell
cd C:\Users\你的用户名\Desktop\PodGist\electron

python -m venv resources\python_venv
```

### Step 4: 激活虚拟环境并安装依赖

```powershell
resources\python_venv\Scripts\activate

# 安装 PyTorch（CPU 版本，无需 NVIDIA GPU）
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu

# 安装所有 Python 依赖
pip install -r ..\requirements.txt

# 验证安装成功
python -c "import fastapi; import whisper; import chromadb; print('安装成功')"
```

> 如果遇到网络问题导致 PyTorch 下载失败，使用镜像：
> ```powershell
> pip install torch torchvision torchaudio -i https://pypi.tuna.tsinghua.edu.cn/simple
> ```

### Step 5: 安装 Node.js 依赖

```powershell
# 确保你在 PodGist\electron 目录下
cd electron
npm install
```

### Step 6: 打包！

#### 精简版（Phase 1）

```powershell
npm run build:win
```

打包完成后，安装包在：
```
C:\Users\你的用户名\Desktop\PodGist\release\1.0.0\win-unpacked\PodGist.exe
```

或者生成带安装向导的版本：
```powershell
ls release\1.0.0\
# 应该能看到 .exe 安装文件
```

#### 完整版（Phase 2）- 可选

如果需要打包所有模型（开箱即用）：

**Step A: 先下载模型到本地缓存**

```powershell
# 在 PodGist 目录下（非 electron），激活 env 环境
cd ..
python -m venv env
env\Scripts\activate

# 下载 Whisper large-v3（约 1.5GB，需要 10-30 分钟）
python -c "import whisper; model = whisper.load_model('large-v3'); print('Whisper 下载完成')"

# 下载 SenseVoice（约 200MB）
python -c "from modelscope.pipelines import pipeline; p = pipeline('auto_speech_recognition', 'iic/SenseVoiceSmall'); print('SenseVoice 下载完成')"

# 下载 Sentence Transformer（约 90MB）
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2'); print('Sentence Transformer 下载完成')"

deactivate
```

**Step B: 拷贝模型到资源目录**

```powershell
cd electron

# 创建模型目录
mkdir resources\models

# 拷贝 Whisper 模型（所有版本）
xcopy /E /I "%USERPROFILE%\.cache\whisper" resources\models\whisper

# 拷贝 SenseVoice 模型
xcopy /E /I "%USERPROFILE%\.cache\modelscope\hub\models\iic" resources\models\modelscope\hub\models\iic

# 拷贝 Sentence Transformer 模型
xcopy /E /I "%USERPROFILE%\.cache\huggingface\hub\models--sentence-transformers--all-MiniLM-L6-v2" resources\models\huggingface\hub\models--sentence-transformers--all-MiniLM-L6-v2
```

**Step C: 重新打包**

```powershell
npm run build:win
```

---

## 验证打包结果

### 精简版测试

1. 找到生成的 `.exe` 文件（通常在 `release\1.0.0\` 目录）
2. 双击运行
3. 应该能看到 PodGist 窗口打开
4. 首次使用时会提示下载模型（需要网络）

### 完整版测试

1. 找到生成的 `.exe` 文件
2. 双击运行
3. PodGist 窗口打开
4. 模型已预装，可以直接使用

---

## 常见问题排查

### Q: npm install 报错 "不是内部或外部命令"

确保 Node.js 已添加到系统 PATH。重新安装 Node.js，**务必勾选** "Add to PATH"。

### Q: python 命令找不到

确保 Python 已添加到系统 PATH。重新安装 Python，**务必勾选** "Add to PATH"。

### Q: "无法运行此脚本" 错误

PowerShell 执行策略问题，以管理员身份运行 PowerShell，执行：
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### Q: pip install 报错网络错误

使用国内镜像：
```powershell
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### Q: 打包后运行闪退

1. 检查 FFmpeg.exe 是否在正确位置
2. 检查 Python venv 是否完整
3. 查看日志：
   ```powershell
   # 在 PowerShell 中运行，查看错误输出
   .\PodGist.exe
   ```

### Q: 模型下载中断/失败

重新运行下载命令，会从断点继续。确保网络稳定。

### Q: 如何清理后重新打包？

```powershell
# 删除构建产物
rd /s /q electron\dist
rd /s /q electron\out
rd /s /q release

# 重新打包
npm run build:win
```

---

## 打包产物位置

| 类型 | 路径 |
|------|------|
| 便携版（无需安装） | `release\1.0.0\win-unpacked\PodGist.exe` |
| 安装版（NSIS向导） | `release\1.0.0\PodGist-*-win-*.exe` |

---

## 文件结构参考

打完包后，`electron\resources\` 目录应该包含：

```
electron\resources\
├── ffmpeg\
│   └── ffmpeg.exe          ← Step 2 放置
├── python_venv\            ← Step 3 创建
│   ├── Scripts\
│   ├── Lib\
│   └── python.exe
└── models\                 ← Phase 2 才需要
    ├── whisper\
    ├── modelscope\
    └── huggingface\
```

---

## 技术支持

如果遇到问题：
1. 截图完整错误信息
2. 确认执行到了哪一步
3. 检查网络连接是否正常
