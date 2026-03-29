# PodGist 项目开发指南

## 项目概述

PodGist 是一个基于本地算力与 AI 技术的音频内容结构化工具。它通过语音转录（Whisper/SenseVoice）和大语言模型分析（DeepSeek），将各类音频转化为带精确时间轴的结构化摘要。

> **起源**：PodGist 最初为播客总结而设计，但现已不局限于播客，可以提炼所有类型的音频（播客、讲座、会议录音等）。

## 技术架构

PodGist v1.0.0 采用 **React + FastAPI 分离架构**：

- **前端**：`frontend/` — React 19 + TypeScript + Vite + Tailwind CSS v4
- **后端**：`api.py` + `backend/` — FastAPI + Python

两个服务独立运行，通过 HTTP 通信：
- 前端开发服务器：http://localhost:5173
- 后端 API 服务器：http://localhost:8000

## 项目结构

```
PodGist/
├── api.py                      # FastAPI 主程序（后端服务入口）
├── backend/
│   ├── __init__.py
│   ├── transcriber.py           # Whisper/SenseVoice 转录与硬件检测
│   ├── llm_agent.py            # LLM API 调用与 RAG 搜索
│   ├── downloader.py           # 多平台音频下载
│   ├── worker.py               # 后台任务处理与队列管理
│   ├── task_queue.py           # SQLite 任务队列状态管理
│   └── diagnostics.py          # 系统诊断功能
├── frontend/                    # React + Vite 前端
│   ├── src/
│   │   ├── App.tsx             # 主应用组件
│   │   ├── main.tsx           # React 入口
│   │   ├── index.css          # Tailwind CSS 入口
│   │   └── components/        # UI 组件
│   │       ├── BatchProcess.tsx
│   │       ├── ConfirmDialog.tsx
│   │       ├── DinoLoader.tsx
│   │       ├── Logo.tsx
│   │       ├── PodcastDownloadForm.tsx
│   │       ├── ResultView.tsx
│   │       ├── SettingsModal.tsx
│   │       ├── TaskQueue.tsx
│   │       └── Toast.tsx
│   ├── public/                 # 静态资源（favicon, dino.gif）
│   ├── package.json
│   ├── vite.config.ts
│   └── tailwind.config.js
├── archives/                    # 生成的 Markdown 归档目录（用户数据）
├── temp_audio/                  # 临时音频文件缓存（用户数据）
├── assets/                      # 静态资源（Logo、Favicon）
├── config.json                  # 应用配置（引擎、设备等）
├── .env                         # API Key 本地存储文件
├── requirements.txt             # Python 依赖清单
└── README.md
```

## 核心依赖

### 前端

- **React 19** - UI 框架
- **Vite** - 构建工具与开发服务器
- **Tailwind CSS v4** - 样式框架（使用 `@theme` CSS 变量）
- **@tabler/icons-react** - 图标库
- **Axios** - HTTP 客户端

### 后端

- **FastAPI** - Web 框架
- **OpenAI Whisper** / **SenseVoice** - 语音识别
- **DeepSeek SDK** - LLM API 调用
- **PyTorch** - 深度学习硬件加速
- **ModelScope** - SenseVoice 模型加载
- **yt-dlp** - 音视频下载

## 需要修改的文件清单

### 1. 安装新 Python 包
- **文件**: `requirements.txt`
- **规范**: 新增依赖包时，必须同时更新此文件
- **格式**: `包名>=版本号`（如 `new-package>=1.0.0`）

### 2. 修改前端界面
- **文件**: `frontend/src/App.tsx` 或 `frontend/src/components/` 下的各组件
- **说明**: React + TypeScript + Tailwind CSS v4

### 3. 安装新前端包
- **文件**: `frontend/package.json`
- **规范**: 新增 npm 包后，在 `frontend/` 目录下运行 `npm install`
- **注意**: `@tabler/icons-react` 是当前图标库，不要混用其他图标库

### 4. 修改转录逻辑
- **文件**: `backend/transcriber.py`
- **功能**: Whisper/SenseVoice 模型加载、硬件检测、音频转录

### 5. 修改 LLM 调用逻辑
- **文件**: `backend/llm_agent.py`
- **功能**: 摘要生成、语义搜索的 Prompt 和 API 调用
- **注意**: 当前硬编码使用 DeepSeek API

### 6. 系统诊断功能
- **文件**: `backend/diagnostics.py`
- **功能**: 测试所有组件是否正常工作（API 连接、模型加载、硬件检测等）
- **使用**: 在 api.py 中导入 `from backend.diagnostics import run_all_diagnostics`

### 7. 修改应用配置
- **文件**: `.env`（API Key）和 `config.json`（引擎设置）
- **说明**: API Key 存储在 `.env`，不要提交到版本控制

## 行为规范

### 依赖管理
- Python 包：安装新包后必须更新 `requirements.txt`
- 前端包：在 `frontend/` 目录下 `npm install <package>`
- 注意：PyTorch 故意不在 requirements.txt 中锁死版本（需根据硬件选择安装）

### API 配置
- DeepSeek API 作为默认 LLM 提供商
- API 密钥存储在 `.env` 文件中
- 已配置 .gitignore 排除 `.env` 和 `config.json`

### 用户数据
- `archives/` 目录存放用户归档的 Markdown 文件
- `temp_audio/` 目录存放临时音频文件
- 这些目录已被 .gitignore 排除

### 硬件支持
- `backend/transcriber.py` 自动检测并支持：Apple Silicon (MPS)、NVIDIA GPU (CUDA)、CPU

## 运行命令

```bash
# 终端 1：启动后端 API
uvicorn api:app --reload --port 8000

# 终端 2：启动前端开发服务器
cd frontend
npm install      # 首次运行前安装依赖
npm run dev      # 启动 Vite 开发服务器

# 浏览器访问 http://localhost:5173
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
git add -A          # 添加所有文件（注意不要包含 node_modules/）

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

## 开发注意事项

### 代码修改后
- **不要自动启动服务**：修改完代码后等待用户自己启动，除非用户明确要求
- 每次修改后直接告知用户已完成，让用户自己决定何时测试

### 前端开发规范
- React 19 + TypeScript，使用函数组件和 Hooks
- Tailwind CSS v4，使用 `@theme` CSS 变量定义颜色
- 图标统一使用 `@tabler/icons-react`，不要混用其他图标库
- 组件放在 `frontend/src/components/` 目录下

### Tailwind CSS v4 颜色变量
- 定义在 `frontend/src/index.css` 的 `@theme` 块中
- 使用格式：`bg-primary`、`text-accent`、`border-danger` 等

### API 接口约定
- 后端 Base URL：`http://localhost:8000`
- 前端通过 `axios.create({ baseURL: 'http://localhost:8000' })` 创建实例
- CORS 已配置允许 `http://localhost:5173`

### 测试建议
- 在本地测试通过后再提交推送到 GitHub
- 前后端需要同时运行才能完整测试
- API 可通过 http://localhost:8000/docs 查看 Swagger 文档

## 打包分发（未来规划）

计划实现无需安装环境的可执行版本：

- **后端**：PyInstaller 打包 FastAPI 应用为单个可执行文件
- **前端**：Vite build 生成的 `dist/` 目录打包进后端，作为静态文件服务
- **启动**：用户双击一个脚本或 exe，同时启动前后端

具体实现细节待后续规划。
