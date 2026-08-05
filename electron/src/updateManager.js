const { autoUpdater } = require('electron-updater');
const https = require('node:https');

const RELEASE_URL = 'https://github.com/TobyKSKGD/PodGist/releases';
const GITHUB_LATEST_RELEASE_API = 'https://api.github.com/repos/TobyKSKGD/PodGist/releases/latest';

/**
 * 把 electron-updater 与渲染进程隔离开。
 * 下载、校验和安装只能在主进程执行；渲染进程仅接收可展示的状态。
 */
class UpdateManager {
  constructor({ app, log, sendStatus }) {
    this.app = app;
    this.log = log;
    this.sendStatus = sendStatus;
    this.status = {
      state: app.isPackaged ? 'idle' : 'unsupported',
      currentVersion: app.getVersion(),
      availableVersion: '',
      releaseNotes: '',
      progress: 0,
      message: app.isPackaged ? '可检查新版本' : '开发环境不支持检查更新',
      releaseUrl: RELEASE_URL,
    };

    this.usesManualMacUpdate = app.isPackaged && process.platform === 'darwin';

    if (!app.isPackaged || this.usesManualMacUpdate) {
      return;
    }

    // 用户主动点击“检查更新”后，发现新版即自动下载，实现一键更新。
    autoUpdater.autoDownload = true;
    autoUpdater.autoInstallOnAppQuit = false;

    autoUpdater.on('checking-for-update', () => {
      this._setStatus({ state: 'checking', progress: 0, message: '正在检查更新…' });
    });
    autoUpdater.on('update-available', (info) => {
      this._setStatus({
        state: 'downloading',
        availableVersion: info.version || '',
        releaseNotes: this._formatReleaseNotes(info.releaseNotes),
        progress: 0,
        message: `发现新版本 v${info.version}，正在下载…`,
      });
    });
    autoUpdater.on('update-not-available', () => {
      this._setStatus({
        state: 'not-available',
        availableVersion: '',
        releaseNotes: '',
        progress: 0,
        message: '当前已是最新版本',
      });
    });
    autoUpdater.on('download-progress', (progress) => {
      this._setStatus({
        state: 'downloading',
        progress: Math.round(progress.percent || 0),
        message: `正在下载更新：${Math.round(progress.percent || 0)}%`,
      });
    });
    autoUpdater.on('update-downloaded', (info) => {
      this._setStatus({
        state: 'downloaded',
        availableVersion: info.version || this.status.availableVersion,
        progress: 100,
        message: '更新已下载，重启应用即可完成安装',
      });
    });
    autoUpdater.on('error', (error) => {
      this.log(`自动更新失败: ${error?.message || String(error)}`);
      this._setStatus({
        state: 'error',
        progress: 0,
        message: '自动更新遇到问题，请手动下载更新',
      });
    });
  }

  getStatus() {
    return { ...this.status };
  }

  async checkForUpdates() {
    if (!this.app.isPackaged) {
      return this.getStatus();
    }
    if (this.usesManualMacUpdate) {
      return this._checkMacRelease();
    }
    if (this.status.state === 'downloading') {
      return this.getStatus();
    }

    try {
      await autoUpdater.checkForUpdates();
    } catch (error) {
      this.log(`检查更新失败: ${error?.message || String(error)}`);
      this._setStatus({
        state: 'error',
        progress: 0,
        message: '无法检查更新，请手动下载更新',
      });
    }
    return this.getStatus();
  }

  async downloadUpdate() {
    if (!this.app.isPackaged || this.status.state !== 'available') {
      return this.getStatus();
    }

    try {
      this._setStatus({ state: 'downloading', progress: 0, message: '正在准备下载更新…' });
      await autoUpdater.downloadUpdate();
    } catch (error) {
      this.log(`下载更新失败: ${error?.message || String(error)}`);
      this._setStatus({
        state: 'error',
        progress: 0,
        message: '下载更新失败，请手动下载更新',
      });
    }
    return this.getStatus();
  }

  installUpdate() {
    if (this.app.isPackaged && this.status.state === 'downloaded') {
      autoUpdater.quitAndInstall();
    }
  }

  _setStatus(next) {
    this.status = { ...this.status, ...next };
    this.sendStatus(this.getStatus());
  }

  _formatReleaseNotes(notes) {
    if (Array.isArray(notes)) {
      return notes.map((item) => item.note || '').filter(Boolean).join('\n\n');
    }
    return typeof notes === 'string' ? notes : '';
  }

  async _checkMacRelease() {
    this._setStatus({ state: 'checking', progress: 0, message: '正在检查最新版本…' });
    try {
      const release = await this._requestLatestRelease();
      const version = this._normaliseVersion(release.tag_name || '');
      if (version && this._isVersionNewer(version, this.status.currentVersion)) {
        this._setStatus({
          state: 'manual-update',
          availableVersion: version,
          releaseNotes: typeof release.body === 'string' ? release.body : '',
          progress: 0,
          message: `发现新版本 v${version}，请下载后替换 Applications 中的 PodGist`,
          // macOS 需要用户手动替换应用，但不必再让用户从 Release 页面寻找 DMG。
          // GitHub API 的 browser_download_url 会直接触发对应安装包的下载。
          releaseUrl: this._getMacDownloadUrl(release, version),
        });
      } else {
        this._setStatus({
          state: 'not-available',
          availableVersion: '',
          releaseNotes: '',
          progress: 0,
          message: '当前已是最新版本',
          releaseUrl: RELEASE_URL,
        });
      }
    } catch (error) {
      this.log(`检查 macOS 更新失败: ${error?.message || String(error)}`);
      this._setStatus({
        state: 'error',
        progress: 0,
        message: '无法检查更新，请手动下载更新',
        releaseUrl: RELEASE_URL,
      });
    }
    return this.getStatus();
  }

  _requestLatestRelease() {
    return new Promise((resolve, reject) => {
      const request = https.get(GITHUB_LATEST_RELEASE_API, {
        headers: {
          'User-Agent': `PodGist/${this.app.getVersion()}`,
          Accept: 'application/vnd.github+json',
        },
        timeout: 10000,
      }, (response) => {
        let body = '';
        response.setEncoding('utf8');
        response.on('data', (chunk) => { body += chunk; });
        response.on('end', () => {
          if (response.statusCode !== 200) {
            reject(new Error(`GitHub Release API 返回 HTTP ${response.statusCode}`));
            return;
          }
          try {
            resolve(JSON.parse(body));
          } catch {
            reject(new Error('GitHub Release API 返回了无效数据'));
          }
        });
      });
      request.on('timeout', () => request.destroy(new Error('检查更新请求超时')));
      request.on('error', reject);
    });
  }

  _getMacDownloadUrl(release, version) {
    const expectedName = `PodGist-${version}-mac-arm64.dmg`;
    const assets = Array.isArray(release.assets) ? release.assets : [];
    const asset = assets.find((item) => item?.name === expectedName)
      || assets.find((item) => typeof item?.name === 'string' && item.name.endsWith('-mac-arm64.dmg'));
    const downloadUrl = asset?.browser_download_url;

    if (typeof downloadUrl === 'string' && /^https:\/\/github\.com\//i.test(downloadUrl)) {
      return downloadUrl;
    }
    return release.html_url || RELEASE_URL;
  }

  _normaliseVersion(version) {
    return String(version).trim().replace(/^v/i, '');
  }

  _isVersionNewer(candidate, current) {
    const parse = (version) => {
      const [core, prerelease = ''] = this._normaliseVersion(version).split('-', 2);
      const parts = core.split('.').map((item) => Number.parseInt(item, 10));
      return { parts, prerelease };
    };
    const next = parse(candidate);
    const installed = parse(current);
    const length = Math.max(next.parts.length, installed.parts.length);
    for (let index = 0; index < length; index += 1) {
      const difference = (next.parts[index] || 0) - (installed.parts[index] || 0);
      if (difference !== 0) return difference > 0;
    }
    // GitHub 的 latest 接口默认不返回 prerelease；同版本号不应重复提示更新。
    return false;
  }
}

module.exports = { UpdateManager, RELEASE_URL };
