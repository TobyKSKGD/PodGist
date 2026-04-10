const { spawn, exec } = require('child_process');
const path = require('node:path');
const fs = require('node:fs');
const os = require('os');

const LOG_DIR = 'logs';
const BACKEND_LOG = 'backend.log';
const BACKEND_ERROR_LOG = 'backend-error.log';
const BACKEND_STDOUT_LOG = 'backend-stdout.log';
const BACKEND_STDERR_LOG = 'backend-stderr.log';
const MAX_TAIL_CHARS = 4000;

class BackendStarter {
  constructor() {
    this.pythonProcess = null;
    this.userDataPath = null;
    this.resourcesPath = null;
    this.buildType = process.env.BUILD_TYPE || 'lite';
    this.restartCount = 0;
    this.maxRestarts = 3;
    // 最近 stderr/stdout，保留最近 MAX_TAIL_CHARS 字符
    this._lastStdErr = '';
    this._lastStdOut = '';
    this._backendLogPath = null;
    this._backendErrorLogPath = null;
    // 独立日志文件流（直接写文件，不走内存缓冲）
    this._stdoutStream = null;
    this._stderrStream = null;
    // 外部设置的致命错误回调（由 main.js 注入）
    this._onBackendFatal = null;
    // 运行时路径（由 preparePythonVenv / prepareFFmpeg 设置）
    this._apiEngineExe = null;
    this._startScript = null;
    this._ffmpegRuntimeDir = null;
    this._ffmpegExe = null;
    this._ffprobeExe = null;
    // 启动锁：防止重复 spawn
    this._isStarting = false;
    this._startResolve = null;
  }

  get isPackaged() {
    // 需要延迟获取，避免模块加载时 app 还未 ready
    try {
      const { app } = require('electron');
      return app.isPackaged;
    } catch {
      return false;
    }
  }

  getResourcePath(...segments) {
    const resourcesPath = process.resourcesPath || path.join(__dirname, '../../resources');
    return path.join(resourcesPath, ...segments);
  }

  _logDir() {
    return path.join(this.userDataPath, LOG_DIR);
  }

  _appendLog(fileName, message) {
    try {
      const logDir = this._logDir();
      if (!fs.existsSync(logDir)) {
        fs.mkdirSync(logDir, { recursive: true });
      }
      const filePath = path.join(logDir, fileName);
      const timestamp = new Date().toISOString();
      fs.appendFileSync(filePath, `[${timestamp}] ${message}\n`, { encoding: 'utf8' });
    } catch (e) {
      // 忽略日志写入失败
    }
  }

  _updateTail(buffer, maxChars) {
    const str = buffer + '';
    return str.length > maxChars ? str.slice(-maxChars) : str;
  }

  async start() {
    // 启动锁：防止重复 spawn
    if (this._isStarting) {
      console.log('[BackendStarter] 已在启动中，等待...');
      if (this._startResolve) {
        await new Promise(resolve => { this._startResolve = resolve; });
      }
      return;
    }
    if (this.pythonProcess) {
      console.log('[BackendStarter] 后端已在运行中，跳过重复启动');
      return;
    }
    this._isStarting = true;

    console.log('[BackendStarter] 开始启动后端...');
    console.log('[BackendStarter] 构建类型:', this.buildType);

    this.userDataPath = getUserDataPath();
    this.resourcesPath = process.resourcesPath || path.join(__dirname, '../../resources');

    // 初始化日志路径
    this._backendLogPath = path.join(this._logDir(), BACKEND_LOG);
    this._backendErrorLogPath = path.join(this._logDir(), BACKEND_ERROR_LOG);
    const backendStdoutLogPath = path.join(this._logDir(), BACKEND_STDOUT_LOG);
    const backendStderrLogPath = path.join(this._logDir(), BACKEND_STDERR_LOG);

    // 确保用户数据目录存在
    fs.mkdirSync(this.userDataPath, { recursive: true });
    fs.mkdirSync(path.join(this.userDataPath, 'temp_audio'), { recursive: true });
    fs.mkdirSync(path.join(this.userDataPath, 'archives'), { recursive: true });
    fs.mkdirSync(this._logDir(), { recursive: true });

    this._appendLog(BACKEND_LOG, '=== BackendStarter 启动 ===');
    this._appendLog(BACKEND_ERROR_LOG, '=== BackendStarter 启动 ===');

    // Phase 0: 检查 8000 端口是否已被 PodGist 占用
    await this._checkPort();

    // Phase 1: 准备 FFmpeg
    await this.prepareFFmpeg();

    // Phase 2: 准备 Python 虚拟环境
    await this.preparePythonVenv();

    // 准备模型（lite 版从网络下载，full 版从打包资源拷贝）
    if (this.buildType === 'full') {
      await this.prepareModelsFull();
    } else {
      console.log('[BackendStarter] Lite 模式: 模型将在首次运行时自动下载');
    }

    // Phase 3: 启动 Python 后端
    try {
      await this.startPythonBackend();
    } finally {
      this._isStarting = false;
      if (this._startResolve) {
        this._startResolve();
        this._startResolve = null;
      }
    }
  }

  async _checkPort() {
    // 检查 8000 是否已被占用，以及是否为 PodGist 自己的后端
    const http = require('http');
    try {
      await new Promise((resolve, reject) => {
        const req = http.get('http://127.0.0.1:8000/', (res) => {
          if (res.statusCode === 200) {
            let body = '';
            res.on('data', chunk => { body += chunk; });
            res.on('end', () => {
              if (body.includes('PodGist')) {
                this._appendLog(BACKEND_LOG, 'PodGist 后端已在运行中（端口 8000），跳过重复启动');
                console.log('[BackendStarter] PodGist 后端已在运行，跳过启动');
                this._backendAlreadyRunning = true;
                resolve('already_running');
              } else {
                this._appendLog(BACKEND_ERROR_LOG, `8000 端口被未知服务占用: ${body.substring(0, 100)}`);
                reject(new Error(`8000 端口被占用（未知服务），请关闭占用端口的程序后重试`));
              }
            });
          } else {
            reject(new Error(`8000 端口被占用（HTTP ${res.statusCode}），请关闭占用端口的程序后重试`));
          }
        });
        req.on('error', () => {
          // 端口未被占用，可以继续启动
          this._appendLog(BACKEND_LOG, '8000 端口空闲，可以启动后端');
          resolve('free');
        });
        req.setTimeout(3000, () => {
          req.destroy();
          this._appendLog(BACKEND_LOG, '8000 端口检查超时，假设空闲');
          resolve('free');
        });
      });
    } catch (err) {
      this._appendLog(BACKEND_ERROR_LOG, `端口检查: ${err.message}`);
      throw err;
    }
  }

  _assertFileExists(filePath, description) {
    if (!fs.existsSync(filePath)) {
      const msg = `[BackendStarter] 关键文件缺失 [${description}]: ${filePath}`;
      console.error(msg);
      this._appendLog(BACKEND_ERROR_LOG, msg);
      throw new Error(msg);
    }
  }

  _logResourcesDir() {
    // 记录 resources 目录内容，便于定位路径问题
    try {
      const resourcesPath = process.resourcesPath;
      this._appendLog(BACKEND_ERROR_LOG, `process.resourcesPath = ${resourcesPath}`);
      if (fs.existsSync(resourcesPath)) {
        const entries = fs.readdirSync(resourcesPath, { withFileTypes: true });
        const entryList = entries.map(e => e.isDirectory() ? `${e.name}/` : e.name).join(', ');
        this._appendLog(BACKEND_ERROR_LOG, `resources/ contents: ${entryList}`);
        // Also log subdirectory contents for key dirs
        for (const entry of entries) {
          if (entry.isDirectory()) {
            const subPath = path.join(resourcesPath, entry.name);
            try {
              const subEntries = fs.readdirSync(subPath, { withFileTypes: true });
              const subList = subEntries.slice(0, 10).map(e => e.isDirectory() ? `${e.name}/` : e.name).join(', ');
              this._appendLog(BACKEND_ERROR_LOG, `  resources/${entry.name}/: ${subList}${subEntries.length > 10 ? ' ...' : ''}`);
            } catch (e) {
              this._appendLog(BACKEND_ERROR_LOG, `  resources/${entry.name}/: (cannot read)`);
            }
          }
        }
      } else {
        this._appendLog(BACKEND_ERROR_LOG, `resourcesPath does not exist: ${resourcesPath}`);
      }
    } catch (e) {
      this._appendLog(BACKEND_ERROR_LOG, `_logResourcesDir error: ${e.message}`);
    }
  }

  _logVenvDiagnostics(venvPath) {
    // 记录 venv 可移植性诊断信息
    try {
      const binPython3 = path.join(venvPath, 'bin', 'python3');
      const binPython = path.join(venvPath, 'bin', 'python');
      const pyvenvCfg = path.join(venvPath, 'pyvenv.cfg');

      this._appendLog(BACKEND_ERROR_LOG, `--- venv 诊断 ---`);

      if (fs.existsSync(binPython3)) {
        const stat = fs.lstatSync(binPython3);
        if (stat.isSymbolicLink()) {
          const linkTarget = fs.readlinkSync(binPython3);
          this._appendLog(BACKEND_ERROR_LOG, `[WARN] python3 is SYMLINK -> ${linkTarget}`);
          if (linkTarget.startsWith('/')) {
            this._appendLog(BACKEND_ERROR_LOG, `[FAIL] Absolute symlink - will break on other machines!`);
          }
        } else {
          this._appendLog(BACKEND_ERROR_LOG, `[OK] python3 is a regular file`);
        }
      } else {
        this._appendLog(BACKEND_ERROR_LOG, `[FAIL] python3 not found`);
      }

      if (fs.existsSync(pyvenvCfg)) {
        const content = fs.readFileSync(pyvenvCfg, 'utf8');
        this._appendLog(BACKEND_ERROR_LOG, `pyvenv.cfg content: ${content.replace(/\n/g, ' | ')}`);
        if (content.includes('/Users/runner/') || content.includes('/home/')) {
          this._appendLog(BACKEND_ERROR_LOG, `[FAIL] CI/Linux path detected in pyvenv.cfg - will break on other machines!`);
        }
      } else {
        this._appendLog(BACKEND_ERROR_LOG, `[WARN] pyvenv.cfg not found`);
      }

      // List bin directory
      try {
        const binDir = path.join(venvPath, 'bin');
        const binEntries = fs.readdirSync(binDir);
        this._appendLog(BACKEND_ERROR_LOG, `venv bin/ first 15 entries: ${binEntries.slice(0, 15).join(', ')}`);
      } catch (e) {
        this._appendLog(BACKEND_ERROR_LOG, `venv bin/ cannot list: ${e.message}`);
      }
      this._appendLog(BACKEND_ERROR_LOG, `--- venv 诊断结束 ---`);
    } catch (e) {
      this._appendLog(BACKEND_ERROR_LOG, `_logVenvDiagnostics error: ${e.message}`);
    }
  }

  _findFirstExist(candidates) {
    for (const p of candidates) {
      if (fs.existsSync(p)) {
        return p;
      }
    }
    return null;
  }

  _isFile(p) {
    try {
      const stat = fs.statSync(p);
      return stat.isFile();
    } catch {
      return false;
    }
  }

  async prepareFFmpeg() {
    const platform = process.platform;

    if (platform === 'win32') {
      const bundledFFmpeg = this.getResourcePath('ffmpeg', 'ffmpeg.exe');
      const bundledFFprobe = this.getResourcePath('ffmpeg', 'ffprobe.exe');
      const destDir = path.join(this.userDataPath, 'bin');
      const destFFmpeg = path.join(destDir, 'ffmpeg.exe');
      const destFFprobe = path.join(destDir, 'ffprobe.exe');

      if (!fs.existsSync(destDir)) {
        fs.mkdirSync(destDir, { recursive: true });
      }

      if (!fs.existsSync(destFFmpeg) && fs.existsSync(bundledFFmpeg)) {
        fs.copyFileSync(bundledFFmpeg, destFFmpeg);
        this._appendLog(BACKEND_LOG, `FFmpeg 已准备: ${destFFmpeg}`);
      }
      if (!fs.existsSync(destFFprobe) && fs.existsSync(bundledFFprobe)) {
        fs.copyFileSync(bundledFFprobe, destFFprobe);
      }

      if (fs.existsSync(bundledFFmpeg)) {
        console.log('[BackendStarter] FFmpeg 已准备:', destFFmpeg);
        this._appendLog(BACKEND_LOG, `FFmpeg 已准备: ${destFFmpeg}`);
      } else {
        console.warn('[BackendStarter] 警告: 未找到打包的 FFmpeg，尝试使用系统 FFmpeg');
        this._appendLog(BACKEND_ERROR_LOG, '警告: 未找到打包的 FFmpeg');
        // Windows 必须有 FFmpeg，缺少则致命
        const msg = `[BackendStarter] 致命错误: 未找到打包的 FFmpeg: ${bundledFFmpeg}`;
        this._appendLog(BACKEND_ERROR_LOG, msg);
        throw new Error(msg);
      }

      // Windows: 验证 FFmpeg 复制确实成功
      if (!fs.existsSync(destFFmpeg)) {
        const msg = `[BackendStarter] 致命错误: FFmpeg 复制失败，目标文件不存在: ${destFFmpeg}`;
        this._appendLog(BACKEND_ERROR_LOG, msg);
        throw new Error(msg);
      }
      this._appendLog(BACKEND_LOG, `FFmpeg 复制验证 OK: ${destFFmpeg} (${fs.statSync(destFFmpeg).size} bytes)`);

      if (!fs.existsSync(destFFprobe)) {
        const msg = `[BackendStarter] 致命错误: ffprobe 复制失败，目标文件不存在: ${destFFprobe}`;
        this._appendLog(BACKEND_ERROR_LOG, msg);
        throw new Error(msg);
      }

      // 记录 Windows FFmpeg 运行时路径
      this._ffmpegRuntimeDir = destDir;
      this._ffmpegExe = destFFmpeg;
      this._ffprobeExe = destFFprobe;

      process.env.PATH = `${destDir};${process.env.PATH}`;
      process.env.FFMPEG_BINARY = destFFmpeg;

    } else if (platform === 'darwin') {
      const bundledFFmpeg = this.getResourcePath('ffmpeg', 'ffmpeg');
      const bundledFFprobe = this.getResourcePath('ffmpeg', 'ffprobe');
      const destDir = path.join(this.userDataPath, 'bin');
      const destFFmpeg = path.join(destDir, 'ffmpeg');
      const destFFprobe = path.join(destDir, 'ffprobe');

      if (!fs.existsSync(destDir)) {
        fs.mkdirSync(destDir, { recursive: true });
      }

      if (!fs.existsSync(destFFmpeg) && fs.existsSync(bundledFFmpeg)) {
        fs.copyFileSync(bundledFFmpeg, destFFmpeg);
        fs.chmodSync(destFFmpeg, 0o755);
        this._appendLog(BACKEND_LOG, `FFmpeg 已复制到: ${destFFmpeg}`);
      }
      if (!fs.existsSync(destFFprobe) && fs.existsSync(bundledFFprobe)) {
        fs.copyFileSync(bundledFFprobe, destFFprobe);
        fs.chmodSync(destFFprobe, 0o755);
        this._appendLog(BACKEND_LOG, `FFprobe 已复制到: ${destFFprobe}`);
      }

      // 记录 macOS FFmpeg 运行时路径（唯一真源）
      this._ffmpegRuntimeDir = destDir;
      this._ffmpegExe = destFFmpeg;
      this._ffprobeExe = destFFprobe;

      // 启动前检查：确认 ffmpeg/ffprobe 存在且可执行
      const fxOk = (p) => {
        if (!fs.existsSync(p)) return `MISSING: ${p}`;
        try {
          fs.accessSync(p, fs.constants.X_OK);
          return `OK: ${p}`;
        } catch {
          return `NOT EXECUTABLE: ${p}`;
        }
      };
      const ffmpegStatus = fxOk(destFFmpeg);
      const ffprobeStatus = fxOk(destFFprobe);
      this._appendLog(BACKEND_LOG, `FFmpeg 检查: ${ffmpegStatus}`);
      this._appendLog(BACKEND_LOG, `FFprobe 检查: ${ffprobeStatus}`);
      console.log(`[BackendStarter] FFmpeg: ${ffmpegStatus}`);
      console.log(`[BackendStarter] FFprobe: ${ffprobeStatus}`);

      if (!fs.existsSync(bundledFFmpeg)) {
        console.warn('[BackendStarter] 警告: 未找到打包的 FFmpeg，尝试使用系统 FFmpeg');
        this._appendLog(BACKEND_ERROR_LOG, '警告: 未找到打包的 FFmpeg');
      }

      process.env.PATH = `${destDir}:${process.env.PATH}`;
      process.env.FFMPEG_BINARY = destFFmpeg;
    }
  }

  async preparePythonVenv() {
    const platform = process.platform;

    // =================
    // Windows: 使用 PyInstaller 打包的 api-engine.exe
    // =================
    if (platform === 'win32') {
      const apiEngineCandidates = [
        path.join(process.resourcesPath, 'api', 'api-engine.exe'),
        path.join(process.resourcesPath, 'app.asar.unpacked', 'api', 'api-engine.exe'),
        path.join(process.resourcesPath, 'app.asar.unpacked', 'dist', 'api', 'api-engine.exe'),
      ];

      const apiEngineExe = this._findFirstExist(apiEngineCandidates);
      if (apiEngineExe) {
        this._apiEngineExe = apiEngineExe;
        this._appendLog(BACKEND_LOG, `Windows API engine found: ${apiEngineExe}`);
        console.log('[BackendStarter] Windows 模式: 使用 PyInstaller 打包的后端:', apiEngineExe);
      } else {
        this._logResourcesDir();
        const tried = apiEngineCandidates.join(', ');
        const msg = `[BackendStarter] Windows api-engine.exe 未找到，已尝试: ${tried}`;
        this._appendLog(BACKEND_ERROR_LOG, msg);
        console.error(msg);
        throw new Error(msg);
      }
      return;
    }

    // =================
    // macOS: 优先使用 PyInstaller 打包的独立后端二进制
    // 如果不存在再回退到 python_venv
    // =================
    const apiEngineCandidates = [
      path.join(process.resourcesPath, 'api', 'api-engine'),
      path.join(process.resourcesPath, 'app.asar.unpacked', 'api', 'api-engine'),
    ];

    const apiEngine = this._findFirstExist(apiEngineCandidates);
    if (apiEngine && this._isFile(apiEngine)) {
      const stat = fs.statSync(apiEngine);
      if (stat.size > 1000) {
        this._apiEngineExe = apiEngine;
        this._appendLog(BACKEND_LOG, `macOS API engine found: ${apiEngine} (${stat.size} bytes)`);
        console.log('[BackendStarter] macOS 模式: 使用 PyInstaller 打包的后端:', apiEngine);
        return;
      } else {
        this._appendLog(BACKEND_ERROR_LOG, `[WARN] api-engine exists but invalid size: ${stat.size} bytes`);
      }
    }

    // 后端二进制不存在，记录资源目录并警告
    this._logResourcesDir();
    console.warn('[BackendStarter] macOS 独立后端二进制未找到，检查 python_venv 作为回退...');
    this._appendLog(BACKEND_ERROR_LOG, 'macOS 独立后端二进制未找到，检查 python_venv 作为回退');

    const bundledVenv = this.getResourcePath('python_venv');

    // macOS: 候选 start_electron.py 路径
    const startScriptCandidates = [
      path.join(process.resourcesPath, 'app.asar.unpacked', 'backend', 'start_electron.py'),
      path.join(process.resourcesPath, 'backend', 'start_electron.py'),
    ];

    const startScript = this._findFirstExist(startScriptCandidates);
    if (!startScript) {
      this._logResourcesDir();
      const tried = startScriptCandidates.join(', ');
      const msg = `[BackendStarter] start_electron.py 未找到，已尝试: ${tried}`;
      this._appendLog(BACKEND_ERROR_LOG, msg);
      throw new Error(msg);
    }

    if (!fs.existsSync(bundledVenv)) {
      this._logResourcesDir();
      const msg = `[BackendStarter] Python 虚拟环境未找到: ${bundledVenv}`;
      this._appendLog(BACKEND_ERROR_LOG, msg);
      throw new Error(msg);
    }

    // 记录 venv 可移植性诊断信息（用于排查 CI 路径 / 符号链接问题）
    this._logVenvDiagnostics(bundledVenv);

    this._appendLog(BACKEND_LOG, `Python 虚拟环境已就绪: ${bundledVenv}`);
    this._appendLog(BACKEND_LOG, `start_electron.py: ${startScript}`);
    console.log('[BackendStarter] Python 虚拟环境已就绪:', bundledVenv);
    console.log('[BackendStarter] start_electron.py:', startScript);
    this.pythonVenvPath = bundledVenv;
    this._startScript = startScript;
  }

  async prepareModelsFull() {
    const bundledModels = this.getResourcePath('models');
    const userModelsDir = path.join(this.userDataPath, 'models');

    if (!fs.existsSync(userModelsDir)) {
      fs.mkdirSync(userModelsDir, { recursive: true });
    }

    // 拷贝 Whisper 模型
    const whisperSrc = path.join(bundledModels, 'whisper-large-v3');
    const whisperDest = path.join(userModelsDir, 'whisper-large-v3');
    if (fs.existsSync(whisperSrc) && !fs.existsSync(whisperDest)) {
      await this.copyDirectory(whisperSrc, whisperDest);
      this._appendLog(BACKEND_LOG, 'Whisper 模型已拷贝');
    }

    // 拷贝 SenseVoice 模型
    const sensevoiceSrc = path.join(bundledModels, 'SenseVoiceSmall');
    const sensevoiceDest = path.join(userModelsDir, 'SenseVoiceSmall');
    if (fs.existsSync(sensevoiceSrc) && !fs.existsSync(sensevoiceDest)) {
      await this.copyDirectory(sensevoiceSrc, sensevoiceDest);
      this._appendLog(BACKEND_LOG, 'SenseVoice 模型已拷贝');
    }

    // 拷贝 Sentence Transformer 模型
    const embeddingSrc = path.join(bundledModels, 'all-MiniLM-L6-v2');
    const embeddingDest = path.join(userModelsDir, 'all-MiniLM-L6-v2');
    if (fs.existsSync(embeddingSrc) && !fs.existsSync(embeddingDest)) {
      await this.copyDirectory(embeddingSrc, embeddingDest);
      this._appendLog(BACKEND_LOG, 'Sentence Transformer 模型已拷贝');
    }

    process.env.PODGIST_MODEL_DIR = userModelsDir;
    process.env.PODGIST_DATA_DIR = this.userDataPath;
  }

  async startPythonBackend() {
    // 如果 8000 已被 PodGist 后端占用，跳过启动
    if (this._backendAlreadyRunning) {
      this._appendLog(BACKEND_LOG, '后端已在运行，跳过 startPythonBackend');
      await this.waitForBackend('http://127.0.0.1:8000', 5000);
      return;
    }

    const platform = process.platform;
    const backendUrl = 'http://127.0.0.1:8000';

    // =================
    // 启动前诊断日志
    // =================
    this._appendLog(BACKEND_LOG, `=== startPythonBackend 开始 ===`);
    this._appendLog(BACKEND_LOG, `平台: ${platform}`);
    this._appendLog(BACKEND_LOG, `process.resourcesPath: ${process.resourcesPath}`);
    this._appendLog(BACKEND_LOG, `this._apiEngineExe: ${this._apiEngineExe}`);
    this._appendLog(BACKEND_LOG, `this.pythonVenvPath: ${this.pythonVenvPath}`);
    this._appendLog(BACKEND_LOG, `this._startScript: ${this._startScript}`);
    this._appendLog(BACKEND_LOG, `this.userDataPath: ${this.userDataPath}`);
    this._logResourcesDir();

    let pythonPath;
    let pythonArgs;
    let backendMode;

    if (this._apiEngineExe) {
      // =================
      // 模式 A: 独立后端二进制 (api-engine)
      // =================
      if (typeof this._apiEngineExe !== 'string') {
        throw new Error(`[BackendStarter] _apiEngineExe must be string, got: ${typeof this._apiEngineExe}`);
      }
      backendMode = 'api-engine';
      pythonPath = this._apiEngineExe;
      pythonArgs = [
        '--data-dir', this.userDataPath,
        '--resources-path', process.resourcesPath
      ];
      this._appendLog(BACKEND_LOG, `启动模式: api-engine | 二进制: ${pythonPath}`);
      console.log(`[BackendStarter] [${platform}] 模式 A (api-engine): ${pythonPath}`);

    } else if (platform === 'darwin' && this.pythonVenvPath && this._startScript) {
      // =================
      // 模式 B: macOS python_venv 回退
      // =================
      if (typeof this.pythonVenvPath !== 'string' || typeof this._startScript !== 'string') {
        throw new Error(`[BackendStarter] pythonVenvPath or _startScript is not a string`);
      }
      backendMode = 'python-venv';
      pythonPath = path.join(this.pythonVenvPath, 'bin', 'python3');
      pythonArgs = [
        this._startScript,
        '--data-dir', this.userDataPath,
        '--resources-path', process.resourcesPath
      ];
      this._appendLog(BACKEND_LOG, `启动模式: python-venv | Python: ${pythonPath} | 脚本: ${this._startScript}`);
      console.log(`[BackendStarter] [${platform}] 模式 B (python-venv): ${pythonPath} ${this._startScript}`);

    } else {
      // =================
      // 无法启动：缺少必要路径变量
      // =================
      const msg = [
        `[BackendStarter] 无法启动后端：缺少必要路径变量`,
        `platform=${platform}`,
        `_apiEngineExe=${this._apiEngineExe}`,
        `pythonVenvPath=${this.pythonVenvPath}`,
        `_startScript=${this._startScript}`,
      ].join('\n');
      this._appendLog(BACKEND_ERROR_LOG, msg);
      console.error(msg);
      throw new Error(msg);
    }

    const env = {
      ...process.env,
      PODGIST_DATA_DIR: this.userDataPath,
      PODGIST_RESOURCES_PATH: process.resourcesPath,
      PODGIST_MODEL_DIR: process.env.PODGIST_MODEL_DIR || '',
      NODE_ENV: process.env.NODE_ENV || 'production'
    };

    // macOS: 注入运行时 FFmpeg 路径（唯一真源 = userData/bin/）
    // 不再使用 process.resourcesPath/ffmpeg（那是打包资源，不一定可执行）
    if (platform === 'darwin') {
      if (this._ffmpegRuntimeDir && this._ffmpegExe && this._ffprobeExe) {
        // preserve original PATH, prepend ffmpeg dir
        const originalPath = process.env.PATH || '';
        env.PATH = `${this._ffmpegRuntimeDir}:${originalPath}`;
        env.FFMPEG_BINARY = this._ffmpegExe;
        env.FFPROBE_BINARY = this._ffprobeExe;
        env.PODGIST_FFMPEG_DIR = this._ffmpegRuntimeDir;
        this._appendLog(BACKEND_LOG, `macOS FFmpeg env: PATH=...:${this._ffmpegRuntimeDir}, FFMPEG_BINARY=${this._ffmpegExe}`);
      } else {
        const msg = `[BackendStarter] macOS _ffmpegRuntimeDir 未设置，但需要启动后端`;
        this._appendLog(BACKEND_ERROR_LOG, msg);
        throw new Error(msg);
      }
    } else if (platform === 'win32') {
      // Windows: 使用 prepareFFmpeg 复制到 userData/bin 的路径
      const destDir = path.join(this.userDataPath, 'bin');
      const destFFmpeg = path.join(destDir, 'ffmpeg.exe');
      const destFFprobe = path.join(destDir, 'ffprobe.exe');
      // 保留原始 PATH（Windows 下为 Path），prepend destDir
      const originalPath = process.env.PATH || process.env.Path || process.env.path || '';
      env.PATH = `${destDir};${originalPath}`;
      // 保留关键 Windows 系统变量，防止 subprocess 缺失必要环境
      env.SystemRoot = process.env.SystemRoot || 'C:\\Windows';
      env.WINDIR = process.env.WINDIR || env.SystemRoot;
      env.PATHEXT = process.env.PATHEXT || '.COM;.EXE;.BAT;.CMD';
      env.FFMPEG_BINARY = destFFmpeg;
      env.FFPROBE_BINARY = destFFprobe;
      env.PODGIST_FFMPEG_DIR = destDir;
    }

    this._appendLog(BACKEND_LOG, `用户数据目录: ${this.userDataPath}`);
    this._appendLog(BACKEND_LOG, `资源目录: ${process.resourcesPath}`);

    const spawnOptions = {
      stdio: ['ignore', 'pipe', 'pipe'],
      env,
      cwd: this.userDataPath
    };

    // Windows: 隐藏所有子进程窗口，防止闪黑框
    if (platform === 'win32') {
      spawnOptions.windowsHide = true;
    }

    // 关闭旧的文件流（防止重复打开）
    if (this._stdoutStream) { try { this._stdoutStream.end(); } catch(e){} this._stdoutStream = null; }
    if (this._stderrStream) { try { this._stderrStream.end(); } catch(e){} this._stderrStream = null; }

    // 创建新的文件流（直接写文件，不走内存）
    try {
      const backendStdoutLogPath = path.join(this._logDir(), BACKEND_STDOUT_LOG);
      const backendStderrLogPath = path.join(this._logDir(), BACKEND_STDERR_LOG);
      this._stdoutStream = fs.createWriteStream(backendStdoutLogPath, { flags: 'w', encoding: 'utf8' });
      this._stderrStream = fs.createWriteStream(backendStderrLogPath, { flags: 'w', encoding: 'utf8' });
      this._appendLog(BACKEND_LOG, `stdout 日志: ${backendStdoutLogPath}`);
      this._appendLog(BACKEND_LOG, `stderr 日志: ${backendStderrLogPath}`);
    } catch (e) {
      this._appendLog(BACKEND_ERROR_LOG, `创建日志文件流失败: ${e.message}`);
    }

    this.pythonProcess = spawn(pythonPath, pythonArgs, spawnOptions);

    // 记录启动诊断信息
    this._appendLog(BACKEND_LOG, `=== 后端启动 ===`);
    this._appendLog(BACKEND_LOG, `backend mode: ${backendMode}`);
    this._appendLog(BACKEND_LOG, `spawn: ${pythonPath} ${pythonArgs.join(' ')}`);
    this._appendLog(BACKEND_LOG, `cwd: ${this.userDataPath}`);
    this._appendLog(BACKEND_LOG, `env.PATH: ${env.PATH}`);
    this._appendLog(BACKEND_LOG, `env.PODGIST_DATA_DIR: ${env.PODGIST_DATA_DIR}`);
    this._appendLog(BACKEND_LOG, `env.FFMPEG_BINARY: ${env.FFMPEG_BINARY || '(未设置)'}`);
    this._appendLog(BACKEND_LOG, `env.FFPROBE_BINARY: ${env.FFPROBE_BINARY || '(未设置)'}`);
    this._appendLog(BACKEND_LOG, `backend pid: ${this.pythonProcess.pid}`);

    this.pythonProcess.stdout.on('data', (data) => {
      const text = data.toString();
      this._lastStdOut = this._updateTail(this._lastStdOut + text, MAX_TAIL_CHARS);
      // 写独立 stdout 日志文件
      if (this._stdoutStream) {
        this._stdoutStream.write(`[${new Date().toISOString()}] ${text}`);
      }
      this._appendLog(BACKEND_LOG, '[stdout] ' + text.trim());
      console.log('[Python]', text.trim());
    });

    this.pythonProcess.stderr.on('data', (data) => {
      const text = data.toString();
      this._lastStdErr = this._updateTail(this._lastStdErr + text, MAX_TAIL_CHARS);
      // 写独立 stderr 日志文件
      if (this._stderrStream) {
        this._stderrStream.write(`[${new Date().toISOString()}] ${text}`);
      }
      this._appendLog(BACKEND_ERROR_LOG, '[stderr] ' + text.trim());
      console.error('[Python Error]', text.trim());
    });

    this.pythonProcess.on('exit', (code, signal) => {
      // 在任何 this.pythonProcess 使用前先保存本地副本，防止 stopBackend() 将其置 null 后触发此 handler
      const procPid = this.pythonProcess ? this.pythonProcess.pid : '(已停止)';

      // 关闭文件流
      if (this._stdoutStream) { this._stdoutStream.end(); this._stdoutStream = null; }
      if (this._stderrStream) { this._stderrStream.end(); this._stderrStream = null; }

      // 读取真实 stderr 日志文件
      let realStderr = '';
      try {
        const stderrFile = path.join(this._logDir(), BACKEND_STDERR_LOG);
        if (fs.existsSync(stderrFile)) {
          realStderr = fs.readFileSync(stderrFile, 'utf8');
          if (realStderr.length > 0) {
            this._appendLog(BACKEND_ERROR_LOG, `真实 stderr 内容 (${realStderr.length} chars): ${realStderr.slice(0, 500)}`);
          }
        }
      } catch (e) {
        this._appendLog(BACKEND_ERROR_LOG, `读取 stderr 日志失败: ${e.message}`);
      }

      const msg = `[BackendStarter] 后端退出: code=${code} signal=${signal} restartCount=${this.restartCount} pid=${procPid}`;
      this._appendLog(BACKEND_ERROR_LOG, msg);
      console.warn(msg);

      // 错误展示优先级：
      // 1. backend-stderr.log（进程真实 stderr）
      // 2. backend-python.log（start_electron.py 的顶层异常，写到 PODGIST_DATA_DIR/logs/）
      // 3. 内存缓冲 _lastStdErr
      let displayStderr = '';
      let errorSource = '(无错误来源)';

      // 优先检查 backend-python.log（最可能有 Python 顶层异常）
      const pyLogPath = path.join(this.userDataPath, 'logs', 'backend-python.log');
      try {
        if (fs.existsSync(pyLogPath)) {
          const pyLog = fs.readFileSync(pyLogPath, 'utf8').trim();
          if (pyLog.length > 0) {
            displayStderr = `[来自 backend-python.log]\n${pyLog.slice(-3000)}`;
            errorSource = 'backend-python.log';
            this._appendLog(BACKEND_ERROR_LOG, `采用 backend-python.log 作为错误来源 (${pyLog.length} chars)`);
          }
        }
      } catch (e) {
        this._appendLog(BACKEND_ERROR_LOG, `读取 backend-python.log 失败: ${e.message}`);
      }

      // 如果 backend-python.log 为空或不存在，尝试 stderr 文件
      if (!displayStderr && realStderr.trim().length > 0) {
        displayStderr = realStderr.slice(-3000);
        errorSource = 'backend-stderr.log';
      }

      // 最后备用内存缓冲
      if (!displayStderr && this._lastStdErr.trim().length > 0) {
        displayStderr = this._lastStdErr.slice(-3000);
        errorSource = '内存缓冲(lastStdErr)';
      }

      this._appendLog(BACKEND_ERROR_LOG, `最终错误来源: ${errorSource}`);

      if (code !== 0 && this.restartCount < this.maxRestarts) {
        this.restartCount++;
        const remaining = this.maxRestarts - this.restartCount;
        const waitMsg = `[BackendStarter] ${remaining} 次重启机会，${5 * this.restartCount} 秒后重启...`;
        this._appendLog(BACKEND_ERROR_LOG, waitMsg);
        console.warn(waitMsg);
        setTimeout(() => this.startPythonBackend(), 5000 * this.restartCount);
      } else if (code !== 0) {
        const backendStderrPath = path.join(this._logDir(), BACKEND_STDERR_LOG);
        const backendStdoutPath = path.join(this._logDir(), BACKEND_STDOUT_LOG);
        const fatalMsg = `[BackendStarter] 后端连续启动失败，已达最大重启次数 (${this.maxRestarts})`;
        this._appendLog(BACKEND_ERROR_LOG, fatalMsg);
        console.error(fatalMsg);
        // 通知主进程 — 传入真实 stderr + 诊断路径
        if (this._onBackendFatal) {
          const errDetail = [
            `后端连续退出 code=${code}，已重启 ${this.maxRestarts} 次仍失败`,
            `后端模式: ${backendMode}`,
            `cwd: ${this.userDataPath}`,
            `pid: ${procPid}`,
            ``,
            `=== 后端 stderr ===`,
            displayStderr || '(空)',
            ``,
            `=== 日志文件 ===`,
            `stdout: ${backendStdoutPath}`,
            `stderr: ${backendStderrPath}`,
          ].join('\n');
          this._onBackendFatal(new Error(errDetail));
        }
      }
    });

    // 等待后端就绪（最多等 2 分钟，冷启动需要下载模型）
    await this.waitForBackend(backendUrl, 120000);
  }

  async waitForBackend(url, timeout) {
    const start = Date.now();
    const http = require('http');
    let attempt = 0;
    let lastErrorMsg = '';

    while (Date.now() - start < timeout) {
      attempt++;
      try {
        await new Promise((resolve, reject) => {
          const req = http.get(url, (res) => {
            if (res.statusCode === 200) {
              resolve();
            } else {
              reject(new Error(`状态码: ${res.statusCode}`));
            }
          });
          req.on('error', reject);
          req.setTimeout(5000, () => {
            req.destroy();
            reject(new Error('连接超时'));
          });
        });
        const elapsed = ((Date.now() - start) / 1000).toFixed(1);
        console.log(`[BackendStarter] 后端已就绪: ${url} (尝试 ${attempt}, ${elapsed}s)`);
        this._appendLog(BACKEND_LOG, `后端就绪: ${url} (尝试 ${attempt}, ${elapsed}s)`);
        return;
      } catch (error) {
        lastErrorMsg = error.message;
        if (attempt % 10 === 0) {
          // 每 10 次（20秒）记录一次
          this._appendLog(BACKEND_LOG, `健康检查失败 (尝试 ${attempt}): ${lastErrorMsg}`);
        }
      }
      await new Promise(r => setTimeout(r, 2000));
    }

    // 超时时的完整上下文信息
    const elapsed = Math.round(timeout / 1000);
    const errMsg = [
      `[BackendStarter] 后端启动超时 (${elapsed}s)`,
      `健康检查 URL: ${url}`,
      `已重试次数: ${attempt}`,
      `最近 stderr (最后 2000 字符):`,
      this._lastStdErr.slice(-2000),
      `日志文件: ${this._backendErrorLogPath}`
    ].join('\n');

    this._appendLog(BACKEND_ERROR_LOG, errMsg);
    throw new Error(errMsg);
  }

  stop() {
    if (!this.pythonProcess) {
      return;
    }
    console.log('[BackendStarter] 停止 Python 后端...');
    this._appendLog(BACKEND_LOG, '收到停止信号，正在终止后端...');

    const pid = this.pythonProcess.pid;

    if (process.platform === 'win32') {
      // Windows: tree-kill 杀死进程树
      exec(`taskkill /pid ${pid} /t /f`, (err) => {
        if (err) {
          this._appendLog(BACKEND_ERROR_LOG, `taskkill 错误: ${err.message}`);
        }
      });
    } else {
      // macOS/Linux: 杀死整个进程组（防止 uvicorn worker 变孤儿）
      try {
        // 负数 pid = 发送到进程组
        process.kill(-pid, 'SIGKILL');
      } catch (e) {
        // 如果进程组已不存在，直接杀进程
        try {
          this.pythonProcess.kill('SIGKILL');
        } catch (e2) {
          this._appendLog(BACKEND_ERROR_LOG, `kill 错误: ${e2.message}`);
        }
      }
    }

    this.pythonProcess = null;
    this._appendLog(BACKEND_LOG, '后端已停止');
  }

  async copyDirectory(src, dest) {
    fs.mkdirSync(dest, { recursive: true });
    const entries = fs.readdirSync(src, { withFileTypes: true });

    for (const entry of entries) {
      const srcPath = path.join(src, entry.name);
      const destPath = path.join(dest, entry.name);

      if (entry.isDirectory()) {
        await this.copyDirectory(srcPath, destPath);
      } else {
        fs.copyFileSync(srcPath, destPath);
      }
    }
  }
}

// 获取用户数据目录（延迟获取，因为 app.getPath 需要在 app ready 后）
let _userDataPath = null;
function getUserDataPath() {
  if (_userDataPath) return _userDataPath;

  try {
    const { app } = require('electron');
    _userDataPath = app.getPath('userData');
  } catch (e) {
    _userDataPath = path.join(os.homedir(), 'PodGist');
  }
  return _userDataPath;
}

module.exports = BackendStarter;
