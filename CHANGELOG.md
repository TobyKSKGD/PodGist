# 更新日志

所有重大变更都会记录在此文件中。遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/) 和 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/) 规范。

---

## [0.2.1] - 2026-04-13

> 测试版 - 从"音频总结工具"走向"AI 时间轴播放器"

本次更新的核心主题是**打通从导入到播放的完整体验**，不再只停留在生成总结。

### 新增

- **全新时间轴模式**：以"时间轴模式"导入内容，在播放音频时按时间节点浏览讨论主题，当前节点随播放进度自动切换
- **时间轴详情页重构**：详情页改为播放器 + 当前节点内容 + 右侧目录为核心架构，支持展示节点总结、重要原因、相关实体、关键事实
- **播放器体验全套**：播放/暂停、快退 15 秒、快进 30 秒、点击进度条跳转、键盘快捷键、继续收听与进度恢复
- **首页重构为资料库视角**：继续收听卡片、全部归档浏览、搜索与筛选（有音频/有时间轴）
- **导入模式选择**：导入时可选择总结模式或时间轴模式，为不同使用场景打下基础
- **封面抓取与展示**：支持从部分音频/视频来源抓取封面，随归档一起保存并用于展示
- **相关实体信息增强**：时间轴节点中展示相关实体解释与参考链接

### 修复

- **打包版媒体 URL 解析错误**：后端返回 `/api/archives/...` 相对路径，在 Electron 打包后的 `file://` 页面 origin 下全部解析失效；新增 `utils/apiAsset.ts` 统一将媒体资源 URL 归一化为 `http://localhost:8000/...` 绝对地址
- **TypeScript strict mode 编译错误**：新增 EpisodePage.tsx 改动后，本地 `vite` 开发服务器能跑但 `tsc -b` 严格检查报错；修复了 `archive` 可能为 `null`、未使用变量、隐式 any 类型等问题
- **entity 图片链路**：新增 `_http_get_bytes()` 二进制下载 + Pillow 图像完整性验证 + Content-Type 白名单校验，彻底解决图片下载被 HTML/JSON/SVG 内容截断的问题
- **mimetypes 模块未导入**：`api.py` 中 `serve_entity_media()` 使用了 `mimetypes.guess_type()` 但未 import，导致所有媒体 API 返回 500
- **Timeline 节点点击状态优先级**：修复 `currentNode ?? selectedNode` 导致的 auto-advance 覆盖用户手动点击的问题，改为 `selectedNode ?? currentNode`
- **React key 稳定性**：entity 列表使用 `key={index}` 导致不同节点切换时 DOM 复用；改为 `${activeNode.id}-${displayName}-${i}` 隔离

### 优化

- **Node TypeScript 泛型解析**：复杂 `ReturnType<typeof (...)>` 在 JSX 中无法被 Vite oxc 解析器识别；改用 `NonNullable<(typeof displayEntities)[number]>` 自引用类型提取
- **前端构建流程**：TypeScript 严格模式审查提前到 CI 阶段，避免带编译隐患的代码进入打包
- **发布前测试打包验证**：引入 "测试打包 → 验证 → 正式发版" 两阶段流程，减小发布翻车风险

### 开发心得

这次更新让我们更深刻地体会到几个工程原则：

1. **本地能跑 ≠ 打包后能跑**。相对 URL 在开发服务器和打包后表现截然不同——所有资源 URL 必须使用绝对地址，且越早统一越好。
2. **CI build success 不等于运行时正确**。TypeScript 能在本地 vite 热更新跑不代表 `tsc -b` 严格编译能过。开发阶段就应该以 CI 的标准跑 `npm run build` 验证。
3. **Electron 打包版的 file:// origin 是特殊的隔离上下文**。音频、图片、API 请求在这个环境里的行为和开发时不一致，需要专门的测试策略。
4. **测试打包（workflow_dispatch）是在真正发版前发现问题的最便宜方式**。不需要正式 tag，只填 platform 就能验证整个打包链路是否完整。

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
