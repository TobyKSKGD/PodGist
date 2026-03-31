const { app, BrowserWindow, ipcMain } = require('electron');
const path = require('node:path');
const BackendStarter = require('./backendStarter');

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
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false
    },
    show: false,
    backgroundColor: '#ffffff'
  });

  // 开发模式加载 localhost:5173，生产模式加载构建后的文件
  if (process.env.NODE_ENV === 'development') {
    mainWindow.loadURL('http://localhost:5173');
    mainWindow.webContents.openDevTools();
  } else {
    mainWindow.loadFile(path.join(__dirname, '../../frontend-dist/index.html'));
  }

  // 窗口准备好后显示，避免白屏闪烁
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

    // 初始化后端（Python 进程）
    backendStarter = new BackendStarter();
    await backendStarter.start();
    console.log('[PodGist] 后端启动成功');

    // 创建窗口
    createWindow();

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
