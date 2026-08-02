// Electron API 类型定义

interface UpdateStatus {
  state: 'idle' | 'checking' | 'not-available' | 'available' | 'downloading' | 'downloaded' | 'manual-update' | 'error' | 'unsupported';
  currentVersion: string;
  availableVersion: string;
  releaseNotes: string;
  progress: number;
  message: string;
  releaseUrl: string;
}

interface ElectronAPI {
  // 获取用户数据目录
  getUserDataPath: () => Promise<string>;

  // 获取后端 URL
  getBackendUrl: () => Promise<string>;

  // 获取应用版本
  getAppVersion: () => Promise<string>;

  // 获取平台 (darwin / win32 / linux)
  getPlatform: () => Promise<'darwin' | 'win32' | 'linux'>;

  getUpdateStatus: () => Promise<UpdateStatus>;
  checkForUpdates: () => Promise<UpdateStatus | undefined>;
  downloadUpdate: () => Promise<UpdateStatus | undefined>;
  installUpdate: () => Promise<void>;
  openReleasePage: () => Promise<void>;
  onUpdateStatus: (listener: (status: UpdateStatus) => void) => () => void;

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
