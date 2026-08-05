# 更新日志

所有重大变更都会记录在此文件中。遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/) 和 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/) 规范。

---

## [Dev Note] 一次非常离谱但必须记住的发布事故复盘

这次发布流程里，出现了一次相当离谱的事故：  
本地仅供参考、明确禁止上传的 `CLAUDE.local.md` 被错误加入了版本控制流程，甚至一度被推送到了远端。更糟的是，文件中还包含敏感信息。这不是普通的小失误，而是一次足以让我彻底警醒的安全事件。

### 发生了什么
- 本地私有的发布手册文件 `CLAUDE.local.md` 本来只用于给 agent 参考
- 我已经多次强调该文件**不能上传 GitHub**
- 但在一次发布操作中，agent 仍然错误地将其加入提交流程
- 后续在处理远端风险时，又误把本地文件一并删除，导致本地重要文档丢失
- 最终不得不重写 Git 历史、强制推送、重新恢复本地规范文档，并重新设计本地保护方案

### 为什么这件事严重
这次事故说明了一件事：  
**“我以为它不会传”这种想法没有任何安全性。**

只要文件没有被真正锁死：
- `.gitignore` 可能不够
- 口头提醒不够
- 对话中的强调也不够

一旦进入 git 追踪范围，或者 agent 误解了意图，风险就会立刻变成现实。

### 本次补救措施
- 立即从 Git 历史中清除相关文件痕迹
- 重建本地发布手册，改为 `CLAUDE.local.md`
- 为该文件增加多层保护：
  - 仓库级 `.gitignore`
  - 本地 `.git/info/exclude`
  - `pre-commit` / `pre-push` 拦截
  - 禁止再次被 git 追踪
- 后续发布流程中，严格区分：
  - **本地私有文件**
  - **可进入仓库的正式文档**

### 这次事故留下的教训
1. 本地私有文档不能只“提醒不要上传”，必须从 git 层面彻底锁死  
2. 涉及敏感信息时，宁可保守，也不要相信“应该不会出事”  
3. agent 可以加速开发，但在文件安全和发布边界上，必须加硬约束，不能靠默认理解  
4. 发布流程不仅要关注“能不能打包成功”，也要关注“有没有把不该上传的东西带上去”

### 对自己说的话
这次真的很离谱，也很生气。  
但换个角度看，这次踩坑也逼着我把本地发布规范、版本发布边界和文件安全策略彻底补全了。  
以后再遇到类似情况，至少不会再因为“以为已经忽略了”而翻车。

—— 这是一次很蠢的事故，但也应该成为一次长期有效的警告。

（PS：这里也都是大模型帮我写的哈哈哈🤣）

---

## [0.2.6] - 2026-08-05

> 测试版 - 改进智能对话的来源体验与时间轴图片富化。

### 智能对话

- **来源展示更清晰**：来源标记现在独占紧凑的一行，兼容模型输出的不同引用格式，不再遗留单独换行的括号或列表符号。
- **长标题按需省略**：优先完整显示归档标题；只有在实际可用宽度不足时才省略末尾文字，时间戳始终保留。
- **来源可直接跳转**：点击回答中的来源即可打开对应归档，并定位到引用所对应的时间轴节点或转录片段。
- **新增跳转播放偏好**：偏好设置新增“智能对话”页，可选择跳转时定位到引用时间、定位后自动播放；两项默认关闭，不会打断原有播放器进度。

### 时间轴图片富化

- **大陆可达图片优先**：图片来源与资料引用分开选择；命中大陆可达页面后优先使用其图片，Wiki 仅作为无可用图片时的回退。
- **新增豆瓣读书图片路径**：书籍与部分内容类实体可通过豆瓣读书页面获取 `doubanio` 图片 CDN，减少对 Wikimedia 图片的依赖。
- **减少不必要的外部等待**：国内图片页使用更短的访问预算；已得到可用国内图片时不再继续请求中英文 Wikipedia。
- **升级实体图片缓存**：新策略使用独立缓存版本，并记录图片来源页面与区域；旧缓存不会阻止后续富化使用新策略。

### 检查更新

- **更新说明正确渲染**：检查更新中的 HTML / Markdown 更新说明会以排版后的富文本显示，不再向用户展示 `<h1>` 等原始标签。
- **macOS 下载一步到位**：发现更新后，下载按钮会直接打开对应 Apple Silicon DMG，而不是先跳转到 Release 列表页。

### 验证

- 后端语法检查、Python `compileall`、前端 TypeScript/Vite 构建和 ESLint 检查通过。
- 实测“《三体》”实体可解析为豆瓣读书页面与 `doubanio` 图片 URL；无可用国内图片时仍可回退到 Wiki 图片。

### 安装说明

#### Windows（x64）

- 新用户：下载并运行 `PodGist-0.2.6-win-x64.exe`，按安装向导完成安装。
- 已安装旧版本：打开 PodGist → 偏好设置 → 检查更新；发现 0.2.6 后下载，完成后点击“重启并更新”。
- 若软件内更新失败，直接运行本页的 Windows 安装包即可覆盖旧版本；个人归档和设置会保留。

#### macOS（仅 Apple Silicon：M 系列芯片）

- 下载 `PodGist-0.2.6-mac-arm64.dmg`，打开后将 PodGist 拖入 Applications（应用程序）文件夹。
- 已安装旧版本时，先退出 PodGist，再用 DMG 内的应用替换 Applications 中的旧版本。
- 也可在 PodGist 的偏好设置中检查更新，点击下载会直接开始下载对应 DMG。
- 本版本尚未进行 Apple Developer 签名与公证。若 macOS 阻止打开，请前往系统设置 → 隐私与安全性，点击“仍要打开”。

### 发布说明

- Windows 安装包、`latest.yml` 和 blockmap 会随正式 GitHub Release 发布，供软件内更新使用。
- macOS 当前使用“软件内检查 + DMG 手动替换”的更新方式。

---

## [0.2.5] - 2026-08-05

> 测试版 - 智能对话正式接入本地归档与时间轴检索

### 新增

- **时间轴优先的智能对话**：提问时会自动检索历史归档，优先使用 `timeline.json` 的节点标题、摘要、重点、事实和实体资料回答；逐字稿作为补充资料。
- **自动补齐历史索引**：首次提问会按归档文件的修改时间补齐本地索引，无需用户手动迁移或逐条重建历史归档。
- **可追溯来源**：回答会标注归档标题和精确时间戳；在应用内点击来源即可回到对应归档查看内容。
- **本地 SQLite 检索索引**：归档、时间轴和检索索引均保存在用户设备上，不再需要首次运行下载额外的嵌入模型。

### 修复

- **修复 macOS 与 Windows 打包版智能对话不可用**：移除依赖 Chroma 默认 ONNX 嵌入模型的运行时链路。该模型在打包后首次检索时可能缺失或无法下载，导致索引失败且对话没有可用资料。
- **修复时间轴未参与智能对话检索**：现在会把带起始时间的时间轴节点单独入库，并在同等相关性下优先引用它们。
- **改进流式失败反馈**：通义千问或网络请求失败时，服务端通过 SSE 返回明确错误，前端不再出现无回复的空白状态。
- **补齐来源兜底**：若模型遗漏来源标注，系统会追加实际参与回答的归档和时间戳。

### 验证

- 后端语法检查、Python `compileall`、前端 TypeScript/Vite 构建和 ESLint 检查通过。
- 使用隔离的历史归档验证：打包运行时可自动建索引、优先命中时间轴节点，并返回归档标题与精确时间戳。

### 安装说明

#### Windows（x64）

- 新用户：下载并运行 `PodGist-0.2.5-win-x64.exe`，按安装向导完成安装。
- 已安装旧版本：打开 PodGist → 偏好设置 → 检查更新；发现 0.2.5 后下载，完成后点击“重启并更新”。
- 若软件内更新失败，直接运行本页的 Windows 安装包即可覆盖旧版本；个人归档和设置会保留。

#### macOS（仅 Apple Silicon：M 系列芯片）

- 下载 `PodGist-0.2.5-mac-arm64.dmg`，打开后将 PodGist 拖入 Applications（应用程序）文件夹。
- 已安装旧版本时，先退出 PodGist，再用 DMG 内的应用替换 Applications 中的旧版本。
- 本版本尚未进行 Apple Developer 签名与公证。若 macOS 阻止打开，请前往系统设置 → 隐私与安全性，点击“仍要打开”。

### 发布说明

- Windows 安装包、`latest.yml` 和 blockmap 会随正式 GitHub Release 发布，供软件内更新使用。
- macOS 当前使用“软件内检查 + Release 手动替换”的更新方式。

---

## [0.2.4] - 2026-08-02

> 测试版 - 加速转录与时间轴生成，并加入软件内检查更新

### 新增

- **软件内检查更新**：偏好设置新增“检查更新”，展示当前版本、检查状态、下载进度、更新说明与 Release 手动下载入口。
- **Windows 一键更新**：发现新版后自动下载，完成后可选择“重启并更新”；更新异常时可直接前往 Release 页面手动安装。
- **macOS 更新引导**：应用会检查 GitHub 最新正式 Release；未使用正式签名的版本发现新版后，引导下载 DMG 并手动替换 Applications 中的 PodGist。
- **时间轴实体资料后台富化**：核心时间轴生成后立即可用，实体链接、参考资料和图片在后台逐步补齐；当前播放或点击的节点及其相邻节点会优先处理。
- **实体图片本地缓存选项**：可在偏好设置中选择将时间轴实体图片保存到本地。

### 优化

- **转录链路加速**：大文件按需生成轻量上传副本；超过一小时的本地音频会分段并发转录，并自动合并时间戳和重叠内容。
- **在线音频直连优先**：可公开访问的在线音频优先由云端直接获取转录，失败后自动回退为本地上传。
- **下载后处理提速**：保留平台原始音频格式，避免不必要的 MP3 重编码；Bilibili DASH 音轨优先无损重封装为 M4A，不兼容时再回退转码。
- **时间轴生成加速**：节点内容采用受控并发生成，首屏资料有限等待，其余由可恢复的后台队列处理。
- **更清晰的任务反馈**：任务队列可展示上传、云端识别和时间轴生成等更细的处理进度。
- **启动与播放体验**：页面按需加载，时间轴资料刷新不会打断当前播放或用户选择；播放进度可本地保存以便继续收听。

### 改进

- 过滤仅包含节目名称、嘉宾介绍、录制地点、欢迎语、口播或赞助信息的低信息量片头节点，使时间轴更聚焦于实际讨论内容。
- 富化任务与主转录任务分离，并支持在应用中断后恢复未完成的节点资料处理。

### 发布说明

- Windows 安装包会随正式 Release 发布 `latest.yml`、blockmap 和安装包，供软件内更新使用。
- macOS 当前采用“软件内检查 + Release 手动替换”的免费更新方案；首次或替换版本后如出现 Gatekeeper 提示，可在系统设置中选择“仍要打开”。

---

## [0.2.3] - 2026-06-25

> 测试版 - 修复 Bilibili 风控调整导致的视频音频下载失败

### 修复

- **修复 Bilibili HTTP 412 下载失败**：Bilibili 调整风控后，`yt-dlp` 的 WBI 播放接口会返回 `HTTP 412: Precondition Failed`。PodGist 现在优先通过 Bilibili 公共 API 获取视频信息和音轨，不再依赖当前受影响的 WBI 下载链路。
- **增加多级下载兜底**：自动选择最高码率 DASH 音轨，主 CDN 失败时依次尝试备用 CDN；公共 API 路径失败后仍保留 `yt-dlp` 作为兼容回退。
- **统一标题与封面获取**：任务标题和 Bilibili 封面改为复用公共 API，避免在正式下载前重复触发风控请求。
- **支持分 P 视频**：识别链接中的 `p` 参数，选择对应分 P 的 `cid` 并生成清晰的归档标题。
- **改进错误提示**：公共 API 与备用下载路径均失败时，返回更明确的 Bilibili 风控错误和失败原因。

### 依赖

- 将 `yt-dlp` 最低版本更新至 `2026.6.9`，用于公共 API 路径不可用时的兼容回退。
- 同步修正 Electron lockfile 的应用版本元数据，确保构建配置与 `v0.2.3` 一致。

### 验证

- 使用 `BV1ZSjd6PEhH` 完整链接实测成功下载并转换为 MP3。
- 实测音频时长约 607.85 秒，文件约 11 MB，标题与封面均可正常获取。
- 后端语法检查与 Python `compileall` 检查通过。

---

## [0.2.2] - 2026-04-14

> 测试版 - 修复 macOS 打包版 entity refUrl/media 全部无法获取的问题

### 修复

- **统一 HTTP 库为 requests**：将 `timeline_agent.py` 中的 `_http_get` 和 `_http_get_bytes` 统一改为 `requests` 库，修复 Mac 打包版 entity 无链接、无图片的问题
- **增加 HTTP 失败日志**：两个函数均增加了 print 日志，记录 URL、status_code、异常类型，不再静默失败

### 问题排查过程

**现象**：macOS 打包版中，时间轴节点的 entity 卡片没有图片、没有参考链接，而 Windows 正常。

**排查路径**：

1. **排除前端渲染问题**：确认 EpisodePage.tsx 中 `if (!displayName) return null` 过滤逻辑正确，无标题 entity 不会渲染
2. **确认打包代码正确**：workflow run 确认 macOS DMG 来自 commit 79ea7a0（v0.2.1），代码本身包含正确的 entity 渲染逻辑
3. **确认打包产物正确**：通过 GitHub Actions 重新触发 macOS 构建，替换原有 DMG，问题依旧
4. **深入数据分析**：读取用户 Mac 上新生成的归档 `timeline.json`，发现 42 个 entity 中仅有 2 个有 `refUrl`，0 个有 `media.filename`，40 个两者都没有——**问题不在前端渲染，是后端生成时就没写出这些字段**
5. **定位根因**：`fetch_cover.py`（封面抓取）使用 `requests`，用户 Mac 上封面正常显示；`timeline_agent.py`（entity URL 解析）使用 `urllib.request.urlopen`，全部静默失败。两者形成鲜明对比，指向 `urllib.request` 在 macOS 打包环境下的问题

**根因**：`urllib.request.urlopen` 在 PyInstaller 打包后的 macOS 环境下会静默失败（不抛异常，直接返回 None），而 `requests` 库不受此影响。这是 PyInstaller 打包 Python stdlib 时的已知问题。

**修复方式**：
- `_http_get`：改用 `requests.get`，保留 User-Agent，设置合理 timeout，失败时打印 `[HTTP GET] URL → status=xxx` 或异常类型
- `_http_get_bytes`：改用 `requests.get`，失败时打印 `[HTTP GET BYTES] URL → timeout` 等日志
- 图片下载的 Content-Type 校验、Pillow verify、尺寸过滤等逻辑全部保留，未退化

### 开发心得

1. **"CI build success" 不等于"安装包运行正常"**：PyInstaller 打包后，某些 stdlib 在特定平台会静默失败，CI 只验证了"打得出来"，没有验证"用得没问题"。这次 macOS 构建成功、workflow 显示绿色，但实际运行时 entity 全部没有链接和图片。
2. **静默失败是定位噩梦**：`_http_get` 和 `_http_get_bytes` 原来的 `except: pass` 让问题延迟了整整两个版本才被发现。以后所有底层 HTTP 函数必须打印失败日志，至少记录 URL + 状态码。
3. **同款软件不同平台差异**：封面抓取用 `requests` 正常，entity URL 解析用 `urllib` 失败——同一个打包应用里，两套 HTTP 库表现完全不同。统一使用 `requests` 是最稳妥的选择。
4. **Win/Mac 数据一致性必须做双平台验证**：不能只在一个平台测试就发布另一个平台。这次如果不是用户反馈，问题的发现会推迟更久。

### 相关文件

- `backend/timeline_agent.py` — `_http_get`、`_http_get_bytes` 改用 `requests`
- `backend/fetch_cover.py` — 原本就使用 `requests`，不受影响

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
