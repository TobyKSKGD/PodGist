const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  // 获取用户数据目录
  getUserDataPath: () => ipcRenderer.invoke('get-user-data-path'),

  // 获取后端 URL
  getBackendUrl: () => ipcRenderer.invoke('get-backend-url'),

  // 获取应用版本
  getAppVersion: () => ipcRenderer.invoke('get-app-version'),

  // 获取平台
  getPlatform: () => ipcRenderer.invoke('get-platform'),

  // 自动更新（所有下载与安装仍由主进程完成）
  getUpdateStatus: () => ipcRenderer.invoke('get-update-status'),
  checkForUpdates: () => ipcRenderer.invoke('check-for-updates'),
  downloadUpdate: () => ipcRenderer.invoke('download-update'),
  installUpdate: () => ipcRenderer.invoke('install-update'),
  openReleasePage: () => ipcRenderer.invoke('open-release-page'),
  onUpdateStatus: (listener) => {
    const handler = (_event, status) => listener(status);
    ipcRenderer.on('update-status', handler);
    return () => ipcRenderer.removeListener('update-status', handler);
  },

  // 判断是否为 Electron 环境
  isElectron: true,

  // 平台信息
  platform: process.platform
});

// 暴露给控制台调试
console.log('[Preload] PodGist Electron 环境已加载');
console.log('[Preload] 平台:', process.platform);
