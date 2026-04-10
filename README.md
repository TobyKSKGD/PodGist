# PodGist

> AI 音频提炼工具 · 以时间轴为核心 | 让音频内容可搜索、可定位、可复用

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
![React](https://img.shields.io/badge/React-19-61DAFB?logo=react)
![TypeScript](https://img.shields.io/badge/TypeScript-5-3178C6?logo=typescript)
![FastAPI](https://img.shields.io/badge/FastAPI-0.104-009688?logo=fastapi)

## 简介

**PodGist** 是一个基于云端 AI 的音频内容结构化工具。它通过语音转录（阿里云 DashScope ASR）和大语言模型（通义千问）分析，将各类音频（播客、讲座、会议录音等）转化为带**精确时间轴**的结构化摘要。

> **设计理念**：在所有音频总结工具都在卷"总结得多详细"的时候，我们选择回到音频内容最独特的价值——**时间**。每一期播客、每一段录音，其核心价值不仅在于说了什么，更在于**什么时候说的**。时间轴让你可以直接跳转到感兴趣的部分，而不用在漫长的音频里猜测"这部分大概在几分几秒"。

![PodGist Homepage](assets/screenshot-homepage.png)

## 核心特性：以时间轴为中心

PodGist 所有功能都围绕时间轴展开：

| 功能 | 说明 |
|------|------|
| **精确时间戳** | 逐字稿带 `[MM:SS]` 时间戳，每个字都能在音频中找到对应位置 |
| **高光时间轴** | AI 从全部内容中提炼最值得关注的时刻，直接跳转无需猜测 |
| **语义定位** | 向 AI 提问"这段话在第几分钟"，AI 告诉你具体时间戳 |
| **归档溯源** | 每条引用自动标注来源归档和时间，回复中所有观点都有据可查 |

---

## 安装与使用

### macOS 版本

#### 系统要求

- macOS 12.0 (Monterey) 或更高版本
- Apple Silicon (M1/M2/M3/M4)
- 推荐 8GB 以上内存

#### 安装步骤

**1. 下载安装包**

点击 [PodGist Releases](https://github.com/TobyKSKGD/PodGist/releases) 下载 `PodGist-X.Y.Z-mac-arm64.dmg` 文件。

**2. 安装应用**

```
打开下载的 .dmg 文件
将 PodGist.app 拖入 Applications（应用程序）文件夹
```

**3. 启动应用**

```
双击 PodGist
首次启动若提示"无法打开"，
前往 系统设置 → 隐私与安全性
滚动到底部，点击"仍要打开"
```

**4. 配置 API Key**

应用启动后，右侧边栏底部点击**偏好设置**，输入你的阿里云 DashScope API Key 并保存。

> 没有 API Key？访问 [阿里云百炼控制台](https://bailian.console.aliyun.com/cn-beijing?tab=model#/api-key) 注册获取，新用户有免费额度。

**5. 开始使用**

- **本地文件**：拖拽 MP3、WAV、M4A 等音频文件
- **播客链接**：粘贴小宇宙、喜马拉雅、Apple Podcasts、网易云等平台链接
- **B站视频**：粘贴 Bilibili 视频链接
- **智能对话**：向全部历史归档提问，基于 RAG 精准定位相关内容

### Windows 版本

#### 系统要求

- Windows 10 或 Windows 11
- 推荐 8GB 以上内存

#### 安装步骤

**1. 下载安装包**

点击 [PodGist Releases](https://github.com/TobyKSKGD/PodGist/releases) 下载 `PodGist-X.Y.Z-win-x64.exe` 安装包。

**2. 安装应用**

运行下载的 `.exe` 安装程序，按提示完成安装。

**3. 启动应用**

从开始菜单或桌面快捷方式启动 PodGist。

**4. 配置 API Key**

应用启动后，右侧边栏底部点击**偏好设置**，输入你的阿里云 DashScope API Key 并保存。

> 没有 API Key？访问 [阿里云百炼控制台](https://bailian.console.aliyun.com/cn-beijing?tab=model#/api-key) 注册获取，新用户有免费额度。

**5. 开始使用**

- **本地文件**：拖拽 MP3、WAV、M4A 等音频文件
- **播客链接**：粘贴小宇宙、喜马拉雅、Apple Podcasts、网易云等平台链接
- **B站视频**：粘贴 Bilibili 视频链接
- **智能对话**：向全部历史归档提问，基于 RAG 精准定位相关内容

---

## 功能概览

| 功能 | 状态 |
|------|------|
| 本地音频文件转录摘要 | ✅ 已支持 |
| 播客链接解析（小宇宙/Apple/喜马拉雅/网易云） | ✅ 已支持 |
| B站视频音频提取 | ✅ 已支持 |
| 阿里云 DashScope ASR 转录 | ✅ 已支持 |
| 通义千问 LLM 摘要生成 | ✅ 已支持 |
| **精确时间轴逐字稿** | ✅ 已支持 |
| **高光时间轴提炼** | ✅ 已支持 |
| 智能对话与 RAG 语义搜索 | ✅ 已支持 |
| 标签管理与归档整理 | ✅ 已支持 |
| 批量处理 | ✅ 已支持 |

---

## 快速开始（开发者）

### 前置要求

- **Python 3.10+**
- **Node.js 18+**（含 npm）
- **FFmpeg**

### 安装步骤

```bash
# 克隆项目
git clone https://github.com/TobyKSKGD/PodGist.git
cd PodGist

# 安装 Python 依赖
pip install -r requirements.txt

# 安装前端依赖
cd frontend && npm install && cd ..

# 启动
npm run dev
```

访问 `http://localhost:5173`，在偏好设置中配置 DashScope API Key。

---

## 技术架构

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
│    DashScope ASR · 通义千问 · yt-dlp · FFmpeg       │
└─────────────────────────────────────────────────────┘
```

### 技术选型

- **DashScope ASR**：阿里云 qwen3-asr-flash / paraformer 云端转录，中文识别准确率领先
- **通义千问（qwen-plus）**：LLM 摘要生成，质量稳定
- **ChromaDB + Sentence Transformers**：本地向量数据库，RAG 语义搜索
- **yt-dlp**：多平台音视频下载

### 后端模块

| 模块 | 功能 |
|------|------|
| `api.py` | FastAPI 主服务，RESTful 接口 |
| `backend/transcriber.py` | DashScope ASR 云端转录 |
| `backend/llm_agent.py` | 通义千问 LLM 摘要生成 |
| `backend/rag_db.py` | SQLite + ChromaDB（RAG 存储） |
| `backend/rag_retriever.py` | RAG 检索与流式生成 |
| `backend/downloader.py` | 多平台音频下载 |
| `backend/worker.py` | 后台任务队列 |
| `backend/task_queue.py` | SQLite 任务状态管理 |

---

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
| Bilibili | 提取视频音频 |

---

## 为什么放弃本地大模型

PodGist 最初设计时，目标是利用本地算力（Whisper + 开源模型）完成全部处理——这样用户不需要付任何 API 费用。

但在开发过程中，我们深刻体会到了这条路线的根本问题：

**硬件门槛太高**。苹果 M 系列芯片能跑，但 8GB 内存捉襟见肘；NVIDIA 显卡是最佳选择，但大多数用户没有配备中高端 GPU。"最低要求"和"流畅使用"之间的差距，让本地方案始终是少数人的专利。

**环境配置复杂到令人窒息**。PyTorch 版本、CUDA 版本、modelscope、funasr、whisper，每一层都有各自的依赖地狱。开发团队自己都难以在不同机器上复现问题，用户就更不用说了。"为什么安装失败"成了 GitHub Issues 里最难回答的问题。

**更新维护成本巨大**。模型版本、依赖兼容性、硬件驱动……每次升级都可能引入新的问题，而这些与产品核心价值无关。

**最终，我们选择了云端 API**：

- 用户只需要一个 API Key，5 秒开始使用
- 阿里云 DashScope 同时提供 ASR 转录和 LLM 摘要，同一密钥打通全流程
- 代码库大幅简化，维护成本降到最低
- 开发者可以把精力放在真正重要的功能上——时间轴

---

## 未来重心：时间轴生态

时间轴是 PodGist 的核心。我们计划围绕时间轴构建更多能力：

- [ ] **时间轴协作**：在时间轴上添加个人笔记和标注
- [ ] **多语言时间轴**：同一时间轴支持中英文字幕对照
- [ ] **时间轴分享**：生成带有时间链接的分享卡片

---

## 依赖

### 前端

- [React](https://react.dev/) - UI 框架
- [Vite](https://vitejs.dev/) - 构建工具
- [Tailwind CSS](https://tailwindcss.com/) - 样式框架
- [Tabler Icons](https://tabler-icons.io/) - 图标库
- [Axios](https://axios-http.com/) - HTTP 客户端

### 后端

- [FastAPI](https://fastapi.tiangolo.com/) - Web 框架
- [DashScope SDK](https://help.aliyun.com/zh/dashscope/) - ASR + LLM
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) - 音视频下载
- [ChromaDB](https://www.trychroma.com/) - 向量数据库（RAG）
- [Sentence Transformers](https://www.sbert.net/) - 文本向量化（RAG）

---

## 许可证

MIT License
