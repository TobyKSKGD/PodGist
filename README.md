# 🎙️ PodGist | 本地算力驱动的 AI 播客知识库

PodGist 是一个现代化的个人播客与音视频提炼工具。它利用本地底层算力（支持 Apple Silicon 与 NVIDIA GPU）进行高效的语音转录，并结合大语言模型（如 DeepSeek）生成带有精确时间戳的结构化总结，最终构建出一个支持 RAG 模糊搜索的个人数字归档知识库。

## ✨ 核心特性与已实现功能

- **🚀 跨平台硬件加速转录**：底层集成 Whisper 模型，自动嗅探并调用本机最强算力（Apple M 系芯片 MPS 加速 / Windows N卡 CUDA 加速 / CPU 保底）。
- **⏱️ 精确到秒的高光时间轴**：不仅提取纯文本，还能自动生成 `[MM:SS]` 格式的严谨时间轴，打破 AI 总结音视频的“黑盒”。
- **🧠 智能结构化提炼**：利用 DeepSeek 大模型，一键生成核心关键词、全局概述，并自动提取 15 字以内的神仙标题。
- **🔍 档案级 RAG 模糊搜索**：基于生成的精确时间戳文本，允许用户像聊天一样，直接向某期历史播客提问并精准定位播放节点。
- **🗂️ 全自动生命周期管理**：
  - **战前防残留**：自动清理因异常中断导致的僵尸文件。
  - **战后倒垃圾**：提炼完成后，自动销毁体积庞大的音频文件，释放磁盘空间。
  - **智能归档库**：按时间戳与 AI 标题自动生成精美 Markdown 归档，支持在前端随时查阅和一键删除。
- **🔐 密钥本地持久化**：API Key 本地隐藏保存，无需反复输入，告别繁琐。

## 📂 项目结构说明

```text
PodGist/
├── app.py                # [前端] Streamlit 交互界面、状态管理与归档文件生命周期控制
├── backend/              # [后端] 核心能力解耦包
│   ├── __init__.py
│   ├── transcriber.py    # 负责硬件嗅探、Whisper 模型加载与时间戳文本提取
│   ├── llm_agent.py      # 负责封装与 DeepSeek API 的交互、总结生成与 RAG 检索
│   └── downloader.py     # (🚧 施工中) 负责从 B站/播客 URL 解析并提取 MP3 流
├── archives/             # [数据] 自动生成的个人知识库归档（由程序自动管理）
├── temp_audio/           # [缓冲] 处理过程中的音频暂存区（用完即焚）
├── assets/               # [资源] 存放前端 UI 所需的静态文件 (如 dino.gif)
├── .env                  # [私密] 本地保存 API Key 的配置文件 (已加入 gitignore)
├── .gitignore            # Git 忽略配置
└── requirements.txt      # 跨平台核心依赖清单
```

## 🚀 快速开始

### 1. 克隆项目与安装基础依赖

```bash
git clone https://github.com/TobyKSKGD/PodGist.git
cd PodGist
pip install -r requirements.txt
```

### 2. 配置硬件加速环境 (极度重要)

为了获得飞一般的转录速度，请务必安装对应你电脑硬件的 PyTorch 版本：

- **Mac (Apple Silicon)**: 通常普通的 `pip install torch` 即可原生支持 MPS。
- **Windows (NVIDIA GPU)**: 请前往 [PyTorch 官网](https://pytorch.org/) 获取带 CUDA 支持的安装命令。
- **全局环境要求**: 必须在电脑上安装 `FFmpeg`，否则 Whisper 无法解析音频流。

### 3. 运行项目

Bash

```
streamlit run app.py
```

## 🛠️ 待开发功能列表 (To-Do List)

- [ ] **在线视频/播客链接解析 (`downloader.py`)**：接入 `yt-dlp`，实现输入 B 站或播客 URL，自动在后台剥离音频并传入处理管线，彻底告别手动下载。
- [ ] **进程级优雅中断**：重构转录逻辑，引入 `multiprocessing`，让前端的 Stop 按钮能够强杀底层的 C++ 算力线程，杜绝“隐形狂奔”。
- [ ] **多文件批量处理排队机制**：允许一次性拖拽多期播客，后台自动排队榨干算力。