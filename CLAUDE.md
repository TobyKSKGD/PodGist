# PodGist 项目开发指南

## 项目概述

PodGist 是一个基于本地算力与 AI 技术的音频内容结构化工具。它通过语音转录（Whisper/SenseVoice）和大语言模型分析（DeepSeek），将各类音频转化为带精确时间轴的结构化摘要。

> **起源**：PodGist 最初为播客总结而设计，但现已不局限于播客，可以提炼所有类型的音频（播客、讲座、会议录音等）。

## 项目结构

```
PodGist/
├── app.py                      # Streamlit 前端主程序（Web UI 入口）
├── backend/
│   ├── __init__.py              # 后端模块初始化
│   ├── transcriber.py           # Whisper 转录与硬件检测
│   ├── llm_agent.py             # LLM API 调用与 RAG 搜索
│   ├── diagnostics.py           # 系统诊断功能
│   └── downloader.py            # 音频下载功能（待实现）
├── archives/                    # 生成的 Markdown 归档目录（用户数据）
├── temp_audio/                  # 临时音频文件缓存
├── assets/                      # 前端静态资源（如 loading gif）
├── .env                         # API Key 本地存储文件
└── requirements.txt             # Python 依赖清单
```

## 核心依赖

- **Streamlit** - Web UI 框架
- **OpenAI Whisper** / **SenseVoice** - 语音识别
- **OpenAI SDK** - LLM API 调用（兼容 DeepSeek）
- **PyTorch** - 深度学习硬件加速
- **ModelScope** - SenseVoice 模型加载

## 需要修改的文件清单

### 1. 安装新 Python 包
- **文件**: `requirements.txt`
- **规范**: 新增依赖包时，必须同时更新此文件
- **格式**: `包名>=版本号`（如 `new-package>=1.0.0`）

### 2. 修改前端界面
- **文件**: `app.py`
- **说明**: 包含所有 Streamlit UI 组件、页面配置、状态管理

### 3. 修改转录逻辑
- **文件**: `backend/transcriber.py`
- **功能**: Whisper 模型加载、硬件检测、音频转录

### 4. 修改 LLM 调用逻辑
- **文件**: `backend/llm_agent.py`
- **功能**: 摘要生成、语义搜索的 Prompt 和 API 调用
- **注意**: 当前硬编码使用 DeepSeek API

### 5. 添加新后端功能
- **文件**: `backend/downloader.py` 或新建模块
- **说明**: 如需实现音频下载功能

### 6. 系统诊断功能
- **文件**: `backend/diagnostics.py`
- **功能**: 测试所有组件是否正常工作（API 连接、模型加载、硬件检测等）
- **使用**: 在 app.py 中导入 `from backend.diagnostics import run_all_diagnostics`

### 6. 修改应用配置
- **文件**: `.env`
- **说明**: 存储用户 API Key，不要提交到版本控制

## 行为规范

### 依赖管理
- 安装新包后必须更新 `requirements.txt`
- 使用 `pip freeze > requirements.txt` 或手动添加
- 注意：PyTorch 故意不在 requirements.txt 中锁死版本（需根据硬件选择安装）

### API 配置
- DeepSeek API 作为默认 LLM 提供商
- API 密钥存储在 `.env` 文件中
- 已配置 .gitignore 排除此文件

### 用户数据
- `archives/` 目录存放用户归档的 Markdown 文件
- `temp_audio/` 目录存放临时音频文件
- 这些目录已被 .gitignore 排除

### 硬件支持
- transcriber.py 自动检测并支持：Apple Silicon (MPS)、NVIDIA GPU (CUDA)、CPU

## 运行命令

```bash
# 启动应用
streamlit run app.py

# 安装依赖
pip install -r requirements.txt

# 安装 PyTorch（macOS）
pip install torch torchvision torchaudio

# 安装 PyTorch（Windows NVIDIA）
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu126
```

## Git 操作指南

### 推送到 GitHub

由于终端可能无法直接通过 HTTPS 认证（会出现 `fatal: could not read Username` 错误），需要使用 SSH 方式推送：

```bash
# 1. 将远程 URL 切换为 SSH 格式（只需执行一次）
git remote set-url origin git@github.com:TobyKSKGD/PodGist.git

# 2. 推送代码
git add <files>
git commit -m "Your commit message"
git push origin main
```

> 注意：如果远程 URL 已经是 SSH 格式，则无需执行步骤 1。

### 常用 Git 命令

```bash
# 查看状态
git status

# 查看差异
git diff

# 添加文件
git add .gitignore  # 添加特定文件
git add -A          # 添加所有文件

# 提交
git commit -m "Your commit message"

# 推送到远程
git push origin main
```

### 撤销更改

当需要撤销已做的修改时，使用 Git 命令比手动删代码更安全：

```bash
# 撤销最近的一个提交（推荐，会创建新提交来撤销）
git revert HEAD

# 撤销最近 N 个提交
git revert HEAD~N..HEAD

# 撤销某个文件到上次提交的状态
git checkout -- <file>

# 本地未推送时，彻底回退到某个提交（慎用，会丢失之后的修改）
git reset --hard <commit>
```

### 试验性修改

**重要**：当你进行试验性的功能开发或不确定的修改时：

1. **先在本地测试**：不要急于提交推送到 GitHub，在本地验证功能正常后再提交
2. **保持本地干净**：如果试验失败，可以用 `git checkout -- .` 轻松撤销所有未提交的修改
3. **分步提交**：复杂功能建议分多次小提交，便于追踪和回溯
4. **描述清晰**：试验性提交的 commit message 可以标注 `[WIP]` 或 `Experiment: xxx`

这样做的目的是：即使试验失败，也能轻松回溯到稳定版本，不影响项目历史。

### 归档命名规范

归档目录命名使用 `{日期}_{原始文件名}` 格式：
- 本地文件上传：`{日期}_{原始文件名（含扩展名）}`
- B站视频下载：`{日期}_{视频标题}`

这样用户可以更方便地识别归档内容对应的原始文件。文件名会经过清理处理：
- 移除无效字符（\ / * ? : " < > |）
- 限制最大长度（50字符），保留文件扩展名

### SenseVoice 转录引擎

**状态**：已集成（默认引擎）

**功能**：
- 在转录引擎设置中选择 "⚡ SenseVoice (极速模式)"
- 使用阿里开源的 SenseVoice 模型进行转录
- 需要安装 ModelScope: `pip install modelscope`

### 小宇宙播客平台支持

**状态**：已集成

**功能**：
- 前端"播客直连"Tab 支持粘贴小宇宙分享链接
- 自动解析 `<meta property="og:audio">` 获取 MP3 直链
- 支持未来扩展其他播客平台（苹果播客、网易云、喜马拉雅等）

**后端模块**：
- `detect_platform(url)` - 识别链接平台
- `download_xiaoyuzhou_audio(url, save_dir)` - 小宇宙音频下载
- `route_and_download(url, save_dir)` - 智能路由下载

**归档命名**：
- 小宇宙下载：`{日期}_{播客标题}`

## 开发注意事项

### 代码修改后
- **不要自动启动 Streamlit**：修改完代码后等待用户自己启动，除非用户明确要求
- 每次修改后直接告知用户已完成，让用户自己决定何时测试

### UI 开发规范
- Streamlit 侧边栏使用 `with st.sidebar:` 包裹
- 诊断功能放在侧边栏最底部（"转录引擎设置"下方）
- 主区域功能放在侧边栏外面

### Streamlit 中显示 HTML/SVG 图片的注意事项

**常见错误与解决方案：**

1. **HTML 代码被转义显示为纯文本**
   - **原因**：Streamlit 底层是 Markdown 渲染，遇到 4 个空格会自动当成代码块显示
   - **解决**：使用 `st.markdown(html_string, unsafe_allow_html=True)` 渲染 HTML

2. **Python 多行字符串前导空格导致 HTML 失效**
   - **原因**：多行字符串中的缩进会被 Markdown 解析为代码块
   - **解决**：HTML 字符串不要用缩进，每行要定到最左边。例如：
   ```python
   # 错误（有多余缩进）
   html = """
       <div>内容</div>
   """
   # 正确（无缩进）
   html = """<div>内容</div>"""
   ```

3. **f-string 插入 SVG 导致渲染失败**
   - **原因**：`f"{svg_code}"` 会触发 Streamlit 的安全转义
   - **解决**：使用字符串拼接或直接渲染，不要用 f-string 插入 SVG
   ```python
   # 错误
   st.markdown(f"<div>{svg_code}</div>", unsafe_allow_html=True)
   # 正确
   st.markdown("<div>" + svg_code + "</div>", unsafe_allow_html=True)
   ```

4. **网页标签页 (favicon) 无法使用 SVG**
   - **原因**：浏览器 favicon 要求必须是图片文件（PNG/ICO）
   - **解决**：将 SVG 截图保存为 PNG，使用 PIL Image 对象加载
   ```python
   from PIL import Image
   fav_image = Image.open("assets/favicon.png")
   st.set_page_config(page_title="PodGist", page_icon=fav_image, layout="wide")
   ```

5. **图片模糊问题**
   - **原因**：PNG 放大后变模糊
   - **解决**：主页使用 SVG（矢量图），标签页使用 PNG

### 测试建议
- 在本地测试通过后再提交推送到 GitHub
- 使用虚拟环境 `env/` 运行：`source env/bin/activate && streamlit run app.py`
