// Electron API 类型定义

interface ElectronAPI {
  // 获取用户数据目录
  getUserDataPath: () => Promise<string>;

  // 获取后端 URL
  getBackendUrl: () => Promise<string>;

  // 获取应用版本
  getAppVersion: () => Promise<string>;

  // 获取平台 (win32 / darwin / linux)
  getPlatform: () => Promise<string>;

  // 是否为 Electron 环境
  isElectron: boolean;

  // 平台信息
  platform: string;
}

declare global {
  interface Window {
    electronAPI?: ElectronAPI;
  }
}

export {};
