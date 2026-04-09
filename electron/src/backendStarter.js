const { spawn, exec } = require('child_process');
const path = require('node:path');
const fs = require('node:fs');
const os = require('os');

const LOG_DIR = 'logs';
const BACKEND_LOG = 'backend.log';
const BACKEND_ERROR_LOG = 'backend-error.log';
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
    // 外部设置的致命错误回调（由 main.js 注入）
    this._onBackendFatal = null;
    // 运行时路径（由 preparePythonVenv 设置）
    this._apiEngineExe = null;
    this._startScript = null;
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
    console.log('[BackendStarter] 开始启动后端...');
    console.log('[BackendStarter] 构建类型:', this.buildType);

    this.userDataPath = getUserDataPath();
    this.resourcesPath = process.resourcesPath || path.join(__dirname, '../../resources');

    // 初始化日志路径
    this._backendLogPath = path.join(this._logDir(), BACKEND_LOG);
    this._backendErrorLogPath = path.join(this._logDir(), BACKEND_ERROR_LOG);

    // 确保用户数据目录存在
    fs.mkdirSync(this.userDataPath, { recursive: true });
    fs.mkdirSync(path.join(this.userDataPath, 'temp_audio'), { recursive: true });
    fs.mkdirSync(path.join(this.userDataPath, 'archives'), { recursive: true });
    fs.mkdirSync(this._logDir(), { recursive: true });

    this._appendLog(BACKEND_LOG, '=== BackendStarter 启动 ===');
    this._appendLog(BACKEND_ERROR_LOG, '=== BackendStarter 启动 ===');

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
    await this.startPythonBackend();
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
      }

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
        this._appendLog(BACKEND_LOG, `FFmpeg 已准备: ${destFFmpeg}`);
      }
      if (!fs.existsSync(destFFprobe) && fs.existsSync(bundledFFprobe)) {
        fs.copyFileSync(bundledFFprobe, destFFprobe);
        fs.chmodSync(destFFprobe, 0o755);
      }

      if (fs.existsSync(bundledFFmpeg)) {
        console.log('[BackendStarter] FFmpeg 已准备:', destFFmpeg);
      } else {
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
    const platform = process.platform;

    let pythonPath;
    let pythonArgs;
    const backendUrl = 'http://127.0.0.1:8000';

    if (platform === 'win32') {
      pythonPath = this._apiEngineExe;
      pythonArgs = [
        '--data-dir', this.userDataPath,
        '--resources-path', process.resourcesPath
      ];
      this._appendLog(BACKEND_LOG, `Windows 模式启动: ${this._apiEngineExe}`);
      console.log('[BackendStarter] Windows 模式: 使用 PyInstaller 打包的后端:', this._apiEngineExe);
    } else {
      pythonPath = path.join(this.pythonVenvPath, 'bin', 'python3');
      pythonArgs = [
        this._startScript,
        '--data-dir', this.userDataPath,
        '--resources-path', process.resourcesPath
      ];
      this._appendLog(BACKEND_LOG, `启动 Python 后端: ${pythonPath} ${pythonArgs.join(' ')}`);
      console.log('[BackendStarter] 启动 Python 后端:', pythonPath, pythonArgs.join(' '));
    }

    const env = {
      ...process.env,
      PODGIST_DATA_DIR: this.userDataPath,
      PODGIST_RESOURCES_PATH: process.resourcesPath,
      PODGIST_MODEL_DIR: process.env.PODGIST_MODEL_DIR || '',
      NODE_ENV: process.env.NODE_ENV || 'production'
    };

    // macOS/Windows: 注入 FFmpeg/FFprobe 路径到环境变量
    const ffmpegDir = path.join(process.resourcesPath, 'ffmpeg');
    if (platform === 'win32') {
      env.PATH = `${ffmpegDir};${env.PATH}`;
      env.FFMPEG_BINARY = path.join(ffmpegDir, 'ffmpeg.exe');
      env.FFPROBE_BINARY = path.join(ffmpegDir, 'ffprobe.exe');
    } else {
      // macOS: 将 ffmpeg 目录添加到 PATH 最前面
      env.PATH = `${ffmpegDir}:${env.PATH}`;
      env.FFMPEG_BINARY = path.join(ffmpegDir, 'ffmpeg');
      env.FFPROBE_BINARY = path.join(ffmpegDir, 'ffprobe');
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

    this.pythonProcess = spawn(pythonPath, pythonArgs, spawnOptions);

    this.pythonProcess.stdout.on('data', (data) => {
      const text = data.toString();
      this._lastStdOut = this._updateTail(this._lastStdOut + text, MAX_TAIL_CHARS);
      this._appendLog(BACKEND_LOG, '[stdout] ' + text.trim());
      console.log('[Python]', text.trim());
    });

    this.pythonProcess.stderr.on('data', (data) => {
      const text = data.toString();
      this._lastStdErr = this._updateTail(this._lastStdErr + text, MAX_TAIL_CHARS);
      this._appendLog(BACKEND_ERROR_LOG, '[stderr] ' + text.trim());
      console.error('[Python Error]', text.trim());
    });

    this.pythonProcess.on('exit', (code, signal) => {
      const msg = `[BackendStarter] 后端退出: code=${code} signal=${signal} restartCount=${this.restartCount}`;
      this._appendLog(BACKEND_ERROR_LOG, msg);
      console.warn(msg);

      if (code !== 0 && this.restartCount < this.maxRestarts) {
        this.restartCount++;
        const remaining = this.maxRestarts - this.restartCount;
        const waitMsg = `[BackendStarter] ${remaining} 次重启机会，${5 * this.restartCount} 秒后重启...`;
        this._appendLog(BACKEND_ERROR_LOG, waitMsg);
        console.warn(waitMsg);
        setTimeout(() => this.startPythonBackend(), 5000 * this.restartCount);
      } else if (code !== 0) {
        const fatalMsg = `[BackendStarter] 后端连续启动失败，已达最大重启次数 (${this.maxRestarts})`;
        this._appendLog(BACKEND_ERROR_LOG, fatalMsg);
        console.error(fatalMsg);
        // 通知主进程
        if (this._onBackendFatal) {
          this._onBackendFatal(new Error(`后端连续退出 code=${code}，已重启 ${this.maxRestarts} 次仍失败\n\n最近 stderr:\n${this._lastStdErr.slice(-2000)}`));
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
    if (this.pythonProcess) {
      console.log('[BackendStarter] 停止 Python 后端...');
      this._appendLog(BACKEND_LOG, '收到停止信号，正在终止后端...');
      if (process.platform === 'win32') {
        exec(`taskkill /pid ${this.pythonProcess.pid} /t /f`, (err) => {
          if (err) {
            this._appendLog(BACKEND_ERROR_LOG, `taskkill 错误: ${err.message}`);
          }
        });
      } else {
        this.pythonProcess.kill('SIGKILL');
      }
      this.pythonProcess = null;
    }
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
