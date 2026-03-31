const { spawn } = require('child_process');
const path = require('node:path');
const fs = require('node:fs');
const os = require('os');

class BackendStarter {
  constructor() {
    this.pythonProcess = null;
    this.userDataPath = null;
    this.resourcesPath = null;
    this.buildType = process.env.BUILD_TYPE || 'lite';
    this.restartCount = 0;
    this.maxRestarts = 3;
  }

  get isPackaged() {
    return app && app.isPackaged;
  }

  getResourcePath(...segments) {
    const resourcesPath = process.resourcesPath || path.join(__dirname, '../../resources');
    return path.join(resourcesPath, ...segments);
  }

  async start() {
    console.log('[BackendStarter] 开始启动后端...');
    console.log('[BackendStarter] 构建类型:', this.buildType);

    this.userDataPath = getUserDataPath();
    this.resourcesPath = process.resourcesPath || path.join(__dirname, '../../resources');

    // 确保用户数据目录存在
    fs.mkdirSync(this.userDataPath, { recursive: true });
    fs.mkdirSync(path.join(this.userDataPath, 'temp_audio'), { recursive: true });
    fs.mkdirSync(path.join(this.userDataPath, 'archives'), { recursive: true });

    // Phase 1: 准备 FFmpeg
    await this.prepareFFmpeg();

    // Phase 1: 准备 Python 虚拟环境
    await this.preparePythonVenv();

    // 准备模型（lite 版从网络下载，full 版从打包资源拷贝）
    if (this.buildType === 'full') {
      await this.prepareModelsFull();
    } else {
      console.log('[BackendStarter] Lite 模式: 模型将在首次运行时自动下载');
    }

    // 启动 Python 后端
    await this.startPythonBackend();
  }

  async prepareFFmpeg() {
    const platform = process.platform;

    if (platform === 'win32') {
      // Windows: 从打包资源拷贝 ffmpeg.exe
      const bundledFFmpeg = this.getResourcePath('ffmpeg', 'ffmpeg.exe');
      const destDir = path.join(this.userDataPath, 'bin');
      const destFFmpeg = path.join(destDir, 'ffmpeg.exe');

      if (!fs.existsSync(destDir)) {
        fs.mkdirSync(destDir, { recursive: true });
      }

      if (!fs.existsSync(destFFmpeg)) {
        if (fs.existsSync(bundledFFmpeg)) {
          fs.copyFileSync(bundledFFmpeg, destFFmpeg);
          console.log('[BackendStarter] FFmpeg 已准备:', destFFmpeg);
        } else {
          console.warn('[BackendStarter] 警告: 未找到打包的 FFmpeg，尝试使用系统 FFmpeg');
        }
      }

      // 添加到 PATH
      process.env.PATH = `${destDir};${process.env.PATH}`;
      process.env.FFMPEG_BINARY = destFFmpeg;

    } else if (platform === 'darwin') {
      // macOS: 拷贝 ffmpeg 并添加执行权限
      const bundledFFmpeg = this.getResourcePath('ffmpeg', 'ffmpeg');
      const destDir = path.join(this.userDataPath, 'bin');
      const destFFmpeg = path.join(destDir, 'ffmpeg');

      if (!fs.existsSync(destDir)) {
        fs.mkdirSync(destDir, { recursive: true });
      }

      if (!fs.existsSync(destFFmpeg)) {
        if (fs.existsSync(bundledFFmpeg)) {
          fs.copyFileSync(bundledFFmpeg, destFFmpeg);
          fs.chmodSync(destFFmpeg, 0o755);
          console.log('[BackendStarter] FFmpeg 已准备:', destFFmpeg);
        } else {
          console.warn('[BackendStarter] 警告: 未找到打包的 FFmpeg，尝试使用系统 FFmpeg');
        }
      }

      process.env.PATH = `${destDir}:${process.env.PATH}`;
      process.env.FFMPEG_BINARY = destFFmpeg;
    }
  }

  async preparePythonVenv() {
    const platform = process.platform;
    const bundledVenv = this.getResourcePath('python_venv');

    if (!fs.existsSync(bundledVenv)) {
      throw new Error(`[BackendStarter] Python 虚拟环境未找到: ${bundledVenv}`);
    }

    console.log('[BackendStarter] Python 虚拟环境已就绪:', bundledVenv);
    this.pythonVenvPath = bundledVenv;
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
      console.log('[BackendStarter] Whisper 模型已拷贝');
    }

    // 拷贝 SenseVoice 模型
    const sensevoiceSrc = path.join(bundledModels, 'SenseVoiceSmall');
    const sensevoiceDest = path.join(userModelsDir, 'SenseVoiceSmall');
    if (fs.existsSync(sensevoiceSrc) && !fs.existsSync(sensevoiceDest)) {
      await this.copyDirectory(sensevoiceSrc, sensevoiceDest);
      console.log('[BackendStarter] SenseVoice 模型已拷贝');
    }

    // 拷贝 Sentence Transformer 模型
    const embeddingSrc = path.join(bundledModels, 'all-MiniLM-L6-v2');
    const embeddingDest = path.join(userModelsDir, 'all-MiniLM-L6-v2');
    if (fs.existsSync(embeddingSrc) && !fs.existsSync(embeddingDest)) {
      await this.copyDirectory(embeddingSrc, embeddingDest);
      console.log('[BackendStarter] Sentence Transformer 模型已拷贝');
    }

    // 设置环境变量指向用户模型目录
    process.env.PODGIST_MODEL_DIR = userModelsDir;
    process.env.PODGIST_DATA_DIR = this.userDataPath;
  }

  async startPythonBackend() {
    const platform = process.platform;

    // 确定 Python 路径
    let pythonPath;
    if (platform === 'win32') {
      pythonPath = path.join(this.pythonVenvPath, 'Scripts', 'python.exe');
    } else {
      pythonPath = path.join(this.pythonVenvPath, 'bin', 'python3');
    }

    // Electron 专用入口脚本
    // 解包后的文件在 app.asar.unpacked/ 目录
    const startScript = path.join(
      process.resourcesPath,
      'app.asar.unpacked',
      'backend',
      'start_electron.py'
    );

    const backendUrl = 'http://localhost:8000';

    const env = {
      ...process.env,
      PODGIST_DATA_DIR: this.userDataPath,
      PODGIST_MODEL_DIR: process.env.PODGIST_MODEL_DIR || '',
      NODE_ENV: process.env.NODE_ENV || 'production'
    };

    console.log('[BackendStarter] 启动 Python 后端:', startScript);
    console.log('[BackendStarter] 用户数据目录:', this.userDataPath);

    this.pythonProcess = spawn(pythonPath, [
      startScript,
      '--data-dir', this.userDataPath
    ], {
      stdio: ['ignore', 'pipe', 'pipe'],
      env,
      cwd: this.userDataPath
    });

    this.pythonProcess.stdout.on('data', (data) => {
      console.log('[Python]', data.toString().trim());
    });

    this.pythonProcess.stderr.on('data', (data) => {
      console.error('[Python Error]', data.toString().trim());
    });

    this.pythonProcess.on('exit', (code) => {
      if (code !== 0 && this.restartCount < this.maxRestarts) {
        this.restartCount++;
        console.warn(`[BackendStarter] 后端异常退出，${this.maxRestarts - this.restartCount} 秒后重启...`);
        setTimeout(() => this.startPythonBackend(), 5000);
      }
    });

    // 等待后端就绪
    await this.waitForBackend(backendUrl, 60000);
  }

  async waitForBackend(url, timeout) {
    const start = Date.now();
    const http = require('http');

    while (Date.now() - start < timeout) {
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
          req.setTimeout(1000, () => {
            req.destroy();
            reject(new Error('超时'));
          });
        });
        console.log('[BackendStarter] 后端已就绪:', url);
        return;
      } catch (error) {
        // 忽略错误，继续等待
      }
      await new Promise(r => setTimeout(r, 2000));
    }

    throw new Error(`[BackendStarter] 后端启动超时 (${timeout}ms)`);
  }

  stop() {
    if (this.pythonProcess) {
      console.log('[BackendStarter] 停止 Python 后端...');
      this.pythonProcess.kill();
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

  // 尝试使用 app.getPath（Electron 环境）
  try {
    const { app } = require('electron');
    _userDataPath = app.getPath('userData');
  } catch (e) {
    // 非 Electron 环境，使用默认路径
    _userDataPath = path.join(os.homedir(), 'PodGist');
  }
  return _userDataPath;
}

module.exports = BackendStarter;
