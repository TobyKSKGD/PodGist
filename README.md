# 🎙️ PodGist

> 本地算力驱动的 AI 播客知识库 | 让音频内容可搜索、可定位、可复用

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)

## 简介

**PodGist** 是一个基于本地算力与 AI 技术的播客内容结构化工具。它通过语音转录和大语言模型分析，将纯音频播客转化为带精确时间轴的结构化摘要，解决音频内容难以快速定位、检索和预览的核心痛点，构建个人播客知识库。

## 核心功能

- **硬件加速转录**：基于 Whisper 模型，自动检测并利用本机最强算力（Apple Silicon MPS / NVIDIA CUDA / CPU）进行高效语音识别
- **精确时间轴**：生成带 `[MM:SS]` 格式时间戳的逐字稿，实现音频内容到文本位置的精确映射
- **结构化摘要生成**：通过大语言模型提取节目短标题、核心关键词、详细概述和密集高光时间轴
- **语义搜索与定位**：基于 RAG 技术实现自然语言查询，直接向播客提问并精确定位相关时间段
- **自动化归档**：处理完成后自动清理临时文件，将原始文本和结构化摘要以 Markdown 格式持久化保存

## 技术架构

### 1. 语音转录层

采用 [OpenAI Whisper](https://github.com/openai/whisper) 模型进行高精度语音识别：

```
音频文件 → Whisper 模型 → 带时间戳的文本段落
```

- **硬件自适应** (`backend/transcriber.py`)：动态检测可用计算设备（MPS / CUDA / CPU），选择最优加速方案
- **时间戳对齐**：解析 Whisper 输出的 `segments`，将每段文本与起始时间精确关联，格式化为 `[MM:SS]` 标记

### 2. 内容理解层

通过大语言模型对转录文本进行深度分析和结构化提炼：

```
带时间戳文本 → LLM API → 结构化 Markdown 摘要
```

- **摘要生成** (`backend/llm_agent.py`)：定制化 Prompt 引导模型输出短标题、关键词、节目概述和详细时间轴
- **语义搜索**：将用户查询与原始文本一同送入 LLM，实现基于上下文的精确定位回答

### 3. 交互展示层

基于 [Streamlit](https://streamlit.io/) 构建的 Web 交互界面：

- **文件上传与处理状态管理**
- **实时进度展示与转录动画**
- **时间轴高亮渲染**（通过正则替换将 `[MM:SS]` 格式化为视觉突出的前端组件）
- **历史归档查看与删除**

## 项目结构

```
PodGist/
├── app.py                      # Streamlit 前端主程序
├── backend/
│   ├── transcriber.py          # Whisper 转录与硬件检测
│   ├── llm_agent.py            # LLM API 封装与 RAG 搜索
│   └── downloader.py           # (规划中) 在线音频链接解析
├── archives/                   # 生成的 Markdown 归档目录
├── temp_audio/                 # 临时音频文件缓存
├── assets/                     # 前端静态资源
├── .env                        # API Key 本地存储文件
└── requirements.txt            # Python 依赖清单
```

## 快速开始

### 前置要求

- **Python 3.10+**
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

2. **创建并激活虚拟环境**
   ```bash
   python -m venv env
   # macOS / Linux
   source env/bin/activate
   # Windows
   # env\Scripts\activate
   ```

3. **安装基础依赖**
   ```bash
   pip install -r requirements.txt
   ```

4. **安装 PyTorch（根据硬件平台选择）**

   **macOS (Apple Silicon) / Linux**:
   
   ```bash
   pip install torch torchvision torchaudio
   ```
   
   **Windows (NVIDIA GPU)**:
   ```bash
   pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu126
   ```
   
   > 若安装遇到问题，请参考 [PyTorch 官方安装指南](https://pytorch.org/get-started/locally/) 选择适合你硬件的命令。
   
5. **安装 FFmpeg**

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

6. **启动应用**
   
   ```bash
   streamlit run app.py
   ```
   首次运行会自动下载 Whisper 模型（根据所选模型大小，约 70MB ~ 3GB）。

### 使用流程

1. 启动应用 `streamlit run app.py`，自动开启浏览器 Web 版本。
2. 在侧边栏输入你的大模型 API Key 并保存（当前默认使用 DeepSeek API）
3. 上传 MP3 格式的播客文件
4. 选择转录模型规模（如 small、medium）和计算设备
5. 点击"开始提炼并打上时间戳"启动处理流程
6. 等待转录和摘要生成完成
7. 查看生成的节目摘要、核心关键词和详细时间轴
8. 通过"AI 模糊定位器"输入自然语言问题，精确定位相关内容时间段
9. 可下载完整 Markdown 报告或查看历史归档

## 未来规划

- [ ] **多模型支持**：扩展支持更多大语言模型 API
- [ ] **在线音频源解析**：集成 yt-dlp，支持直接输入播客平台或视频网站 URL 自动下载音频
- [ ] **处理流程优化**：引入异步任务队列和进度中断功能，提升长时间处理的用户体验
- [ ] **批量处理支持**：一次性上传多期节目，后台自动排队处理
- [ ] **跨播客语义搜索**：在全部历史归档中实现全局语义搜索，查找相关话题在不同节目中的讨论
- [ ] **导出格式扩展**：支持导出为 JSON、PDF、Notion 等多种格式

## 依赖

- [Streamlit](https://streamlit.io/) - 交互式 Web 应用框架
- [OpenAI Whisper](https://github.com/openai/whisper) - 语音识别模型
- [OpenAI Python SDK](https://github.com/openai/openai-python) - 大语言模型 API 调用
- [PyTorch](https://pytorch.org/) - 深度学习框架与硬件加速支持

## 许可证

MIT License
