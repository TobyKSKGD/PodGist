# 更新日志

所有重大变更都会记录在此文件中。遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/) 和 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/) 规范。

---

## [0.1.0] - 2026-04-08

> Early version - 新版本起点，验证双平台安装、转录、总结链路

### 新增

- **DashScope ASR 路由重构**：短音频（≤30分钟/60MB）使用 `qwen3-asr-flash`（MultiModalConversation），长音频使用 `paraformer-v1`（Transcription.async_call）
- **短音频阈值调整**：从 5 分钟放宽至 30 分钟，文件上限从 10MB 调整至 60MB
- **dashscope SDK 升级**：从 ≥1.20.0 升级至 ≥1.21.0

### 修复

- **qwen3-asr-flash 调用错误**：修复 `InvalidParameter / url error` — qwen3-asr-flash 短音频模型应使用 `MultiModalConversation.call` 而非 `QwenTranscription.async_call`
- **paraformer 上传用途错误**：修复 `Files.upload purpose='audio'` 无效问题，改为 `purpose='inference'`

---

## [1.0.0] - 2026-04-03

> 首发版本 - macOS Lite

### 新增

- **macOS 桌面应用**：基于 Electron + DMG 安装包，无需 Python/Node.js 环境
- **全局启动拦截**：后端启动期间显示"PodGist 核心引擎启动中"加载动画，避免满屏错误
- **API Key 配置持久化**：Electron 环境下正确读写用户数据目录，重启后配置不丢失
- **SenseVoice 极速转录**：阿里 FunAudioLLM/SenseVoiceSmall，比 Whisper 快 10 倍以上，支持 50+ 语言
- **双引擎支持**：可切换 SenseVoice（极速）和 Whisper（高精度）两种转录模式
- **多平台播客解析**：小宇宙、Apple Podcasts、喜马拉雅、网易云音乐链接自动解析
- **B站视频音频提取**：粘贴 Bilibili 链接，自动下载音频并生成摘要
- **智能对话（RAG）**：基于 ChromaDB 向量库，支持全量归档语义搜索，流式 SSE 响应
- **标签管理**：为归档打标签，按标签筛选对话范围
- **批量处理**：多文件/多链接排队依次处理
- **前端加载动画**：纯 CSS spinner 替代 GIF 小恐龙，降低包体积

### 修复

- Worker 任务处理路径问题 — `task_queue.py` 和 `worker.py` 未使用 `PODGIST_DATA_DIR`
- API Key 读取路径问题 — uvicorn 重导入导致 CLI `--data-dir` 参数丢失
- SSE 流式解析 bug — TCP chunk 边界截断导致 `eventData` 状态被重置（`prevEventType` 逻辑混乱）
- pydub ffprobe/ffmpeg 路径未设置 — `FFMPEG_BINARY`/`FFPROBE_BINARY` 环境变量未配置
- Electron 打包后 yt-dlp/ffprobe 找不到 — venv bin 目录未加入 PATH
- Electron 打包后 ffmpeg 资源路径错误 — `PODGIST_RESOURCES_PATH` 未正确传递给 Python

### 优化

- Electron 后端启动流程 — 自动将 venv bin 加入 PATH，ffprobe 打包到 resources
- 前端构建流程 — 修复 `frontend/dist` 未及时构建导致新代码未打入包的问题
- prebuild.js — 支持 ffprobe 复制时的权限覆盖

---

## [0.1.0] - 2026-04-01

> 内部测试版本
