const { app, BrowserWindow, ipcMain, shell, dialog } = require('electron');
const path = require('node:path');
const fs = require('node:fs');
const BackendStarter = require('./backendStarter');
const { UpdateManager, RELEASE_URL } = require('./updateManager');

// 禁用 GPU 加速，防止 macOS 空闲时杀掉 GPU 进程导致崩溃
app.disableHardwareAcceleration();

let mainWindow;
let backendStarter;
let updateManager;

const LOG_DIR = 'logs';
const STARTUP_LOG = 'startup.log';

// 获取日志目录路径
function getLogPath(fileName) {
  const userDataPath = app.getPath('userData');
  return path.join(userDataPath, LOG_DIR, fileName);
}

// 确保日志目录存在
function ensureLogDir() {
  try {
    const logDir = path.join(app.getPath('userData'), LOG_DIR);
    if (!fs.existsSync(logDir)) {
      fs.mkdirSync(logDir, { recursive: true });
    }
    return logDir;
  } catch (e) {
    return null;
  }
}

// 写入启动日志（追加）
function appendStartupLog(message) {
  try {
    const logPath = getLogPath(STARTUP_LOG);
    const timestamp = new Date().toISOString();
    const logLine = `[${timestamp}] ${message}\n`;
    fs.appendFileSync(logPath, logLine, { encoding: 'utf8' });
  } catch (e) {
    // 忽略日志写入失败
  }
}

// 加载错误页面（后端启动失败时显示给用户）
function loadErrorPage(errorMessage, logPath) {
  if (!mainWindow || mainWindow.isDestroyed()) {
    createWindowWithError(errorMessage, logPath);
    return;
  }

  // 分析错误类型，返回用户友好的分类和解决提示
  const errorInfo = categorizeError(errorMessage);
  const hintHtml = errorInfo.hints.map(h =>
    `<li style="margin-bottom:0.5rem">${escapeHtml(h)}</li>`
  ).join('');

  const errorHtml = `<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>PodGist - ${errorInfo.title}</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      background: #1a1a2e;
      color: #e0e0e0;
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 2rem;
    }
    .container { max-width: 600px; width: 100%; }
    h1 { font-size: 1.5rem; color: #e74c3c; margin-bottom: 1rem; }
    h2 { font-size: 1rem; color: #aaa; margin-bottom: 0.75rem; margin-top: 1.25rem; }
    .error-box {
      background: #2d2d44; border: 1px solid #e74c3c; border-radius: 8px;
      padding: 1.25rem; margin-bottom: 1rem;
      font-family: 'SF Mono', 'Menlo', monospace; font-size: 0.875rem;
      white-space: pre-wrap; word-break: break-all; color: #ff8a80;
      max-height: 200px; overflow-y: auto;
    }
    .hint-box {
      background: #222; border-radius: 8px; padding: 1rem;
      margin-bottom: 1rem;
    }
    .hint-box ul { margin: 0; padding-left: 1.25rem; font-size: 0.875rem; color: #ccc; }
    .detail-box {
      background: #2d2d44; border-radius: 4px; padding: 0.75rem;
      font-size: 0.8rem; color: #888; font-family: monospace;
      white-space: pre-wrap; word-break: break-all; margin-top: 0.5rem;
    }
    .label {
      font-size: 0.75rem; color: #666; text-transform: uppercase;
      letter-spacing: 0.05em; margin-bottom: 0.25rem;
    }
    .btn {
      display: inline-block; margin-top: 1rem; padding: 0.5rem 1rem;
      background: #4361ee; color: white; border: none; border-radius: 6px;
      cursor: pointer; font-size: 0.875rem;
    }
    .btn:hover { background: #3250ee; }
    code { background: #333; padding: 0.1em 0.3em; border-radius: 3px; font-size: 0.85em; }
  </style>
</head>
<body>
  <div class="container">
    <h1>${escapeHtml(errorInfo.title)}</h1>
    <div class="error-box">${escapeHtml(errorInfo.summary)}</div>

    <h2>可能的原因和解决方法</h2>
    <div class="hint-box">
      <ul>${hintHtml}</ul>
    </div>

    <div class="label">详细错误（供开发者参考）</div>
    <div class="detail-box">${escapeHtml(errorMessage)}</div>

    <div class="label" style="margin-top:1rem">日志文件位置</div>
    <div class="detail-box">${escapeHtml(logPath)}</div>

    <button class="btn" onclick="window.close()">关闭应用</button>
  </div>
  <script>
    function escapeHtml(text) {
      const div = document.createElement('div');
      div.textContent = text;
      return div.innerHTML;
    }
  </script>
</body>
</html>`;

  mainWindow.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(errorHtml)}`);
}

function categorizeError(errorMessage) {
  const msg = errorMessage || '';
  const lower = msg.toLowerCase();

  // 端口占用
  if (lower.includes('8000') && (lower.includes('占用') || lower.includes('in use') || lower.includes('address already') || lower.includes('port'))) {
    return {
      title: '后端端口被占用',
      summary: '端口 8000 已被其他程序占用，PodGist 无法启动。',
      hints: [
        '关闭其他占用 8000 端口的程序（如其他 PodGist 进程、Python 调试服务器等）',
        '在终端执行 <code>lsof -i :8000</code> 查找占用端口的进程',
        '如果是残留进程，执行 <code>kill $(lsof -ti :8000)</code> 强制关闭'
      ]
    };
  }

  // FFmpeg 找不到
  if (lower.includes('ffmpeg') && (lower.includes('not found') || lower.includes('no such file') || lower.includes('找不到') || lower.includes('does not exist'))) {
    return {
      title: 'FFmpeg 未找到',
      summary: '音视频处理工具 FFmpeg 不存在或不可执行。',
      hints: [
        '重新安装 PodGist（预览版需要完整安装流程）',
        '如果手动放行，执行：<code>sudo xattr -rd com.apple.quarantine /Applications/PodGist.app</code>',
        '然后再次打开 PodGist'
      ]
    };
  }

  // 后端连续崩溃
  if (lower.includes('连续退出') || lower.includes('restart') || lower.includes('maxrestart') || lower.includes('restartcount')) {
    return {
      title: '后端启动后立即崩溃',
      summary: '后端进程启动后迅速退出，可能是环境配置问题。',
      hints: [
        '查看上方"详细错误"区域中的 stderr 内容',
        '根据 stderr 中的具体错误信息排查',
        '可能是 FFmpeg 缺失、API Key 未配置、或端口被占用'
      ]
    };
  }

  // api-engine 找不到
  if (lower.includes('api-engine') || lower.includes('start_electron') || lower.includes('pythonexe')) {
    return {
      title: '后端二进制文件缺失',
      summary: '找不到 PodGist 后端执行文件。',
      hints: [
        '重新下载并安装 PodGist',
        '安装包可能已损坏，删除后重新从 GitHub Release 下载'
      ]
    };
  }

  // 默认兜底
  return {
    title: '后端启动失败',
    summary: 'PodGist 后端引擎启动时遇到未知错误。',
    hints: [
      '重启 PodGist 应用',
      '查看上方"详细错误"了解具体原因',
      '如果问题持续，请将详细错误信息反馈给开发者'
    ]
  };
}

function escapeHtml(text) {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function createWindowWithError(errorMessage, logPath) {
  mainWindow = new BrowserWindow({
    width: 700,
    height: 450,
    icon: path.join(process.resourcesPath, 'icon.ico'),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false
    },
    show: true,
    backgroundColor: '#1a1a2e'
  });

  loadErrorPage(errorMessage, logPath);

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

// 保持单例模式（macOS）
const gotTheLock = app.requestSingleInstanceLock();
if (!gotTheLock) {
  app.quit();
}

app.on('second-instance', () => {
  if (mainWindow) {
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.focus();
  }
});

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    minWidth: 900,
    minHeight: 600,
    icon: path.join(process.resourcesPath, 'icon.ico'),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false
    },
    show: false,
    backgroundColor: '#ffffff'
  });

  // 加载前端页面
  if (app.isPackaged) {
    const indexPath = path.join(
      process.resourcesPath,
      'app.asar.unpacked',
      'frontend-dist',
      'index.html'
    );
    console.log('[PodGist] 加载前端:', indexPath);
    mainWindow.loadFile(indexPath);
  } else {
    mainWindow.loadURL('http://localhost:5173');
    mainWindow.webContents.openDevTools();
  }

  // 2秒后强制显示窗口（如果还没显示）
  setTimeout(() => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.show();
    }
  }, 2000);

  // 加载失败时记录错误
  mainWindow.webContents.on('did-fail-load', (event, errorCode, errorDesc) => {
    console.error('[PodGist] 前端加载失败:', errorCode, errorDesc);
  });

  // 处理 window.open() 调用：外部链接在系统浏览器中打开
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith('http://') || url.startsWith('https://')) {
      shell.openExternal(url);
    }
    return { action: 'deny' };
  });

  // 窗口准备好后显示
  mainWindow.once('ready-to-show', () => {
    mainWindow.show();
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

async function init() {
  // 确保日志目录存在
  ensureLogDir();
  appendStartupLog('=== PodGist 启动 ===');
  appendStartupLog(`平台: ${process.platform}`);
  appendStartupLog(`Electron 版本: ${process.versions.electron}`);
  appendStartupLog(`用户数据目录: ${app.getPath('userData')}`);

  try {
    console.log('[PodGist] 正在启动...');

    // 先创建窗口，立即显示 UI
    createWindow();

    // 更新检查必须在主进程中执行。此处仅初始化，不在启动时自动下载。
    updateManager = new UpdateManager({
      app,
      log: (message) => appendStartupLog(message),
      sendStatus: (status) => {
        if (mainWindow && !mainWindow.isDestroyed()) {
          mainWindow.webContents.send('update-status', status);
        }
      },
    });

    // 再启动后端（不阻塞窗口显示）
    backendStarter = new BackendStarter();
    // 注册致命错误回调：后端连续崩溃时通知主进程
    backendStarter._onBackendFatal = (error) => {
      const errorMessage = error.message || String(error);
      appendStartupLog('后端连续启动失败: ' + errorMessage);
      const logPath = getLogPath(STARTUP_LOG);
      dialog.showErrorBox('PodGist 后端启动失败', `后端连续启动失败:\n\n${errorMessage}\n\n日志: ${logPath}`);
      if (mainWindow && !mainWindow.isDestroyed()) {
        loadErrorPage(errorMessage, logPath);
      }
    };
    await backendStarter.start();
    appendStartupLog('后端启动成功');
    console.log('[PodGist] 后端启动成功');

  } catch (error) {
    const errorMessage = error.stack || error.message || String(error);
    console.error('[PodGist] 启动失败:', errorMessage);
    appendStartupLog('启动失败: ' + errorMessage);

    const logPath = getLogPath(STARTUP_LOG);

    // 把错误写入 startup.log
    try {
      const logDir = path.join(app.getPath('userData'), LOG_DIR);
      if (!fs.existsSync(logDir)) fs.mkdirSync(logDir, { recursive: true });
      fs.appendFileSync(
        path.join(logDir, STARTUP_LOG),
        `[${new Date().toISOString()}] 致命错误:\n${errorMessage}\n`,
        { encoding: 'utf8' }
      );
    } catch (e) { /* ignore */ }

    // 弹出错误提示框
    const dialogTitle = 'PodGist 启动失败';
    const dialogMessage = `后端启动失败:\n\n${error.message || error}\n\n完整日志: ${logPath}`;
    dialog.showErrorBox(dialogTitle, dialogMessage);

    // 如果窗口已创建，改为显示错误页而不是直接退出
    if (mainWindow && !mainWindow.isDestroyed()) {
      loadErrorPage(errorMessage, logPath);
    } else {
      // 窗口还没创建，先创建再显示错误页
      createWindowWithError(errorMessage, logPath);
    }
  }
}

app.whenReady().then(init);

app.on('window-all-closed', () => {
  if (backendStarter) {
    backendStarter.stop();
  }
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow();
  } else {
    const win = BrowserWindow.getAllWindows()[0];
    if (win) win.show();
  }
});

app.on('will-quit', () => {
  appendStartupLog('应用退出');
  if (backendStarter) {
    backendStarter.stop();
  }
});

// IPC 处理器
ipcMain.handle('get-user-data-path', () => app.getPath('userData'));
ipcMain.handle('get-backend-url', () => 'http://localhost:8000');
ipcMain.handle('get-app-version', () => app.getVersion());
ipcMain.handle('get-platform', () => process.platform);
ipcMain.handle('get-update-status', () => updateManager?.getStatus() || ({
  state: app.isPackaged ? 'idle' : 'unsupported',
  currentVersion: app.getVersion(),
  availableVersion: '',
  releaseNotes: '',
  progress: 0,
  message: '更新服务正在初始化',
  releaseUrl: RELEASE_URL,
}));
ipcMain.handle('check-for-updates', () => updateManager?.checkForUpdates());
ipcMain.handle('download-update', () => updateManager?.downloadUpdate());
ipcMain.handle('install-update', () => updateManager?.installUpdate());
ipcMain.handle('open-release-page', () => shell.openExternal(updateManager?.getStatus().releaseUrl || RELEASE_URL));
