# PodGist

> 本地算力驱动的 AI 音频提炼工具 | 让音频内容可搜索、可定位、可复用

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
![React](https://img.shields.io/badge/React-19-61DAFB?logo=react)
![TypeScript](https://img.shields.io/badge/TypeScript-5-3178C6?logo=typescript)
![FastAPI](https://img.shields.io/badge/FastAPI-0.104-009688?logo=fastapi)

## 简介

**PodGist** 是一个基于本地算力与 AI 技术的音频内容结构化工具。它通过语音转录和大语言模型分析，将各类音频（播客、讲座、会议录音等）转化为带精确时间轴的结构化摘要，解决音频内容难以快速定位、检索和预览的核心痛点。

> **注**：PodGist 最初为播客总结而设计，现已不局限于播客，可以提炼所有类型的音频。

## 技术架构

PodGist v1.0.0 采用 **React + FastAPI** 分离架构：

```
┌─────────────────────────────────────────────────────┐
│                  React Frontend                     │
│              (http://localhost:5173)               │
│         Tabler Icons · Tailwind CSS v4              │
└──────────────────────┬──────────────────────────────┘
                       │ HTTP / REST
                       ▼
┌─────────────────────────────────────────────────────┐
│                 FastAPI Backend                     │
│               (http://localhost:8000)               │
│     Whisper · SenseVoice · DeepSeek · yt-dlp        │
└─────────────────────────────────────────────────────┘
```

### 前端 (`frontend/`)

- **React 19** + **TypeScript** + **Vite** — 极速开发体验
- **Tailwind CSS v4** — 原子化样式方案
- **Tabler Icons** — 简洁轮廓图标库
- **Axios** — HTTP 客户端

### 后端 (`api.py` + `backend/`)

| 模块 | 功能 |
|------|------|
| `api.py` | FastAPI 主服务，RESTful 接口，CORS 跨域支持 |
| `backend/transcriber.py` | Whisper/SenseVoice 转录与硬件检测 |
| `backend/llm_agent.py` | DeepSeek LLM API 封装与 RAG 搜索 |
| `backend/downloader.py` | 多平台在线音频解析与下载 |
| `backend/worker.py` | 后台任务处理与队列管理 |
| `backend/task_queue.py` | SQLite 任务队列状态管理 |
| `backend/diagnostics.py` | 系统诊断与组件检测 |

## 核心功能

- **双引擎转录**：支持 SenseVoice（极速）和 Whisper（高精度）两种转录引擎
- **SenseVoice 极速模式**：基于阿里开源 FunAudioLLM/SenseVoiceSmall，极速转录（比 Whisper 快 10 倍以上），支持中文、英文、粤语等 50+ 语言
- **精确时间轴**：生成带 `[MM:SS]` 或 `[HH:MM:SS]` 格式时间戳的逐字稿，实现音频内容到文本位置的精确映射
- **结构化摘要生成**：通过大语言模型提取节目短标题、核心关键词、详细概述和密集高光时间轴
- **语义搜索与定位**：基于 RAG 技术实现自然语言查询，直接向音频提问并精确定位相关时间段
- **自动化归档**：处理完成后自动清理临时文件，将原始文本和结构化摘要以 Markdown 格式持久化保存
- **多平台音频提取**：支持直接输入多个平台的播客/视频链接，自动提取音频并生成摘要
- **批量处理**：支持批量上传多个音频文件，排队依次处理

## 支持的平台

### 播客平台

| 平台 | 说明 |
|------|------|
| 小宇宙 | 自动解析 MP3 直链 |
| 喜马拉雅 | 自动解析并下载音频 |
| Apple Podcasts | 自动提取音频 |
| 网易云音乐 | 支持播客单集链接 |

### 视频平台

| 平台 | 说明 |
|------|------|
| Bilibili | 提取视频音频，支持大会员（需配置 cookies） |

## 快速开始

### 前置要求

- **Python 3.10+**
- **Node.js 18+**（含 npm）
- **FFmpeg**（系统级依赖，Whisper 需要其进行音频解码）
- 支持的计算硬件：
  - Apple Silicon（MPS 加速）
  - NVIDIA GPU（CUDA 加速）
  - 或普通 CPU（速度较慢）

### 安装步骤

1. **克隆仓库**
   ```bash
   git clone https://github.com/TobyKSKGD/PodGist.git
   cd PodGist
   ```

2. **创建 Python 虚拟环境并安装依赖**
   ```bash
   python -m venv env
   source env/bin/activate
   pip install -r requirements.txt
   ```

3. **安装 PyTorch（根据硬件平台选择）**

   **macOS (Apple Silicon) / Linux**:
   ```bash
   pip install torch torchvision torchaudio
   ```

   **Windows (NVIDIA GPU)**:
   ```bash
   pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu126
   ```

   > 若安装遇到问题，请参考 [PyTorch 官方安装指南](https://pytorch.org/get-started/locally/) 选择适合你硬件的命令。

4. **安装 FFmpeg**

   **macOS**:
   ```bash
   brew install ffmpeg
   ```

   **Windows**:
   ```bash
   winget install ffmpeg
   ```
   或从 [FFmpeg 官网](https://ffmpeg.org/download.html) 下载安装。

   **Linux** (Ubuntu/Debian):
   ```bash
   sudo apt install ffmpeg
   ```

5. **安装前端依赖**
   ```bash
   cd frontend
   npm install
   cd ..
   ```

### 启动应用

一个命令同时启动前后端（后端使用项目虚拟环境）：

```bash
cd frontend
npm run dev
```

浏览器访问 **http://localhost:5173**

> `npm run dev` 会自动先清理 8000/5173 端口的僵尸进程，然后并发启动后端（蓝色日志）和前端（青色日志）。

### 配置说明

在应用界面右上角打开设置，输入你的 **DeepSeek API Key** 并保存。API Key 存储在本地 `.env` 文件中，不会提交到版本控制。

## 一键启动（已完成）

`npm run dev` 已实现一键启动，无需手动管理进程，详见上方"启动应用"章节。

未来版本将提供打包后的可执行文件，无需手动安装 Python / Node.js 环境，可直接双击运行。

## 项目结构

```
PodGist/
├── api.py                      # FastAPI 主程序（后端服务）
├── backend/
│   ├── __init__.py
│   ├── transcriber.py          # Whisper/SenseVoice 转录与硬件检测
│   ├── llm_agent.py            # LLM API 封装与 RAG 搜索
│   ├── downloader.py           # 多平台在线音频解析与下载
│   ├── worker.py               # 后台任务处理
│   ├── task_queue.py           # 任务队列状态管理
│   └── diagnostics.py          # 系统诊断
├── frontend/                    # React + Vite 前端
│   ├── src/
│   │   ├── App.tsx             # 主应用组件
│   │   ├── components/         # UI 组件
│   │   └── index.css           # Tailwind CSS 入口
│   ├── public/                 # 静态资源
│   ├── package.json
│   └── vite.config.ts
├── archives/                    # 生成的 Markdown 归档目录（用户数据）
├── temp_audio/                  # 临时音频文件缓存（用户数据）
├── assets/                      # 静态资源（Logo、Favicon）
├── config.json                  # 应用配置（引擎、设备等）
├── .env                         # API Key 本地存储（不提交）
├── requirements.txt             # Python 依赖清单
└── README.md
```

## 使用流程

1. 启动后端 (`uvicorn api:app`) 和前端 (`npm run dev`)
2. 在设置中输入 DeepSeek API Key 并保存
3. 选择输入方式：
   - **本地文件**：上传 MP3、WAV、M4A 等音频文件（支持拖拽）
   - **播客直连**：粘贴小宇宙、喜马拉雅、Apple Podcasts、网易云音乐等平台链接
   - **B站视频**：粘贴 Bilibili 视频链接
   - **批量处理**：粘贴多个链接或本地音频路径，每行一个
4. 选择转录引擎（SenseVoice 极速模式或 Whisper 高精度模式）
5. 等待转录和摘要生成完成
6. 查看生成的节目摘要、核心关键词和详细时间轴
7. 通过 AI 模糊定位器输入自然语言问题，精确定位相关内容时间段
8. 可下载完整 Markdown 报告或查看历史归档

## 未来规划

- [ ] **打包分发**：提供无需安装环境的可执行版本（PyInstaller + Electron）
- [ ] **多模型支持**：扩展支持更多大语言模型 API
- [ ] **处理流程优化**：引入异步任务队列和进度中断功能
- [ ] **跨音频语义搜索**：在全部历史归档中实现全局语义搜索
- [ ] **导出格式扩展**：支持导出为 JSON、PDF、Notion 等多种格式

## 依赖

### 前端

- [React](https://react.dev/) - UI 框架
- [Vite](https://vitejs.dev/) - 构建工具
- [Tailwind CSS](https://tailwindcss.com/) - 样式框架
- [Tabler Icons](https://tabler-icons.io/) - 图标库
- [Axios](https://axios-http.com/) - HTTP 客户端

### 后端

- [FastAPI](https://fastapi.tiangolo.com/) - Web 框架
- [OpenAI Whisper](https://github.com/openai/whisper) - 语音识别
- [ModelScope / SenseVoice](https://www.modelscope.cn/models/iic/SenseVoiceSmall) - 极速语音识别
- [DeepSeek API](https://platform.deepseek.com/) - 大语言模型
- [PyTorch](https://pytorch.org/) - 深度学习框架
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) - 音视频下载

## 许可证

MIT License
