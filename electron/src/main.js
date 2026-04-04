const { app, BrowserWindow, ipcMain } = require('electron');
const path = require('node:path');
const BackendStarter = require('./backendStarter');

// 禁用 GPU 加速，防止 macOS 空闲时杀掉 GPU 进程导致崩溃
app.disableHardwareAcceleration();

let mainWindow;
let backendStarter;

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
    // 打包模式：从 asar.unpacked 目录加载前端
    const indexPath = path.join(
      process.resourcesPath,
      'app.asar.unpacked',
      'frontend-dist',
      'index.html'
    );
    console.log('[PodGist] 加载前端:', indexPath);
    mainWindow.loadFile(indexPath);
  } else {
    // 开发模式
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

  // 窗口准备好后显示
  mainWindow.once('ready-to-show', () => {
    mainWindow.show();
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

async function init() {
  try {
    console.log('[PodGist] 正在启动...');

    // 先创建窗口，立即显示 UI
    createWindow();

    // 再启动后端（不阻塞窗口显示）
    backendStarter = new BackendStarter();
    await backendStarter.start();
    console.log('[PodGist] 后端启动成功');

  } catch (error) {
    console.error('[PodGist] 启动失败:', error);
    app.quit();
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
    // 已有窗口时，跳到最前
    const win = BrowserWindow.getAllWindows()[0];
    if (win) win.show();
  }
});

app.on('will-quit', () => {
  if (backendStarter) {
    backendStarter.stop();
  }
});

// IPC 处理器
ipcMain.handle('get-user-data-path', () => app.getPath('userData'));
ipcMain.handle('get-backend-url', () => 'http://localhost:8000');
ipcMain.handle('get-app-version', () => app.getVersion());
ipcMain.handle('get-platform', () => process.platform);
