import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { IconX, IconKey, IconActivity, IconCircleCheck, IconCircleX, IconLoader2, IconHelp, IconRefresh, IconDownload, IconExternalLink, IconArrowUp } from '@tabler/icons-react';

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  showToast: (type: 'success' | 'error' | 'info', message: string) => void;
  onSaveSuccess?: () => void;
}

interface DiagnosticItem {
  name: string;
  success: boolean;
  message: string;
}

interface UpdateStatus {
  state: 'idle' | 'checking' | 'not-available' | 'available' | 'downloading' | 'downloaded' | 'manual-update' | 'error' | 'unsupported';
  currentVersion: string;
  availableVersion: string;
  releaseNotes: string;
  progress: number;
  message: string;
  releaseUrl: string;
}

const RELEASE_URL = 'https://github.com/TobyKSKGD/PodGist/releases';

const SettingsModal: React.FC<SettingsModalProps> = ({ isOpen, onClose, showToast, onSaveSuccess }) => {
  const [activeMenu, setActiveMenu] = useState('core');
  const [diagnostics, setDiagnostics] = useState<DiagnosticItem[]>([]);
  const [diagnosticsLoading, setDiagnosticsLoading] = useState(false);
  const [diagnosticsError, setDiagnosticsError] = useState('');
  const [dashscopeApiKey, setDashscopeApiKey] = useState('');
  const [cacheEntityImages, setCacheEntityImages] = useState(false);
  const [updateStatus, setUpdateStatus] = useState<UpdateStatus>({
    state: 'idle',
    currentVersion: '读取中…',
    availableVersion: '',
    releaseNotes: '',
    progress: 0,
    message: '正在读取版本信息…',
    releaseUrl: RELEASE_URL,
  });

  // 加载设置
  useEffect(() => {
    if (isOpen) {
      fetchSettings();
    }
  }, [isOpen]);

  // 更新器仅在 Electron 主进程运行。浏览器开发环境保留 Release 链接，方便手动验证发布页。
  useEffect(() => {
    if (!isOpen) return;

    const electronApi = window.electronAPI;
    if (!electronApi) {
      setUpdateStatus({
        state: 'unsupported',
        currentVersion: '开发环境',
        availableVersion: '',
        releaseNotes: '',
        progress: 0,
        message: '开发环境不支持检查更新',
        releaseUrl: RELEASE_URL,
      });
      return;
    }

    void electronApi.getUpdateStatus().then((status) => {
      setUpdateStatus(status);
    }).catch(() => {
      setUpdateStatus((current) => ({
        ...current,
        state: 'error',
        message: '无法读取更新服务，请手动下载更新',
      }));
    });

    return electronApi.onUpdateStatus(setUpdateStatus);
  }, [isOpen]);

  const fetchSettings = async () => {
    try {
      const response = await axios.get('http://localhost:8000/api/settings');
      if (response.data.status === 'success') {
        const data = response.data.data;
        setDashscopeApiKey(data.dashscope_api_key || '');
        setCacheEntityImages(!!data.cache_entity_images);
      }
    } catch (error) {
      console.error('加载设置失败:', error);
    }
  };

  const runDiagnostics = async () => {
    setDiagnosticsLoading(true);
    setDiagnosticsError('');
    try {
      const response = await axios.get('http://localhost:8000/api/diagnostics');
      if (response.data.status === 'success') {
        setDiagnostics(response.data.data);
        showToast('success', '诊断完成');
      } else {
        setDiagnosticsError('诊断请求失败');
        showToast('error', '诊断请求失败');
      }
    } catch (error) {
      console.error('诊断失败:', error);
      setDiagnosticsError('无法连接到后端诊断服务，请检查后端是否运行');
      showToast('error', '无法连接到后端诊断服务');
    } finally {
      setDiagnosticsLoading(false);
    }
  };

  const saveSettings = async () => {
    try {
      const formData = new FormData();
      formData.append('dashscope_api_key', dashscopeApiKey);
      formData.append('cache_entity_images', String(cacheEntityImages));
      const response = await axios.post('http://localhost:8000/api/settings', formData);
      if (response.data.status === 'success') {
        showToast('success', '设置已保存并应用');
        onSaveSuccess?.();
        setTimeout(() => onClose(), 500);
      } else {
        showToast('error', '保存失败: ' + response.data.message);
      }
    } catch (error) {
      console.error('保存设置失败:', error);
      showToast('error', '无法连接到后端服务');
    }
  };

  const checkForUpdates = async () => {
    if (!window.electronAPI) return;
    try {
      const status = await window.electronAPI.checkForUpdates();
      if (status) setUpdateStatus(status);
    } catch {
      setUpdateStatus((current) => ({ ...current, state: 'error', message: '无法检查更新，请手动下载更新' }));
    }
  };

  const downloadUpdate = async () => {
    if (!window.electronAPI) return;
    try {
      const status = await window.electronAPI.downloadUpdate();
      if (status) setUpdateStatus(status);
    } catch {
      setUpdateStatus((current) => ({ ...current, state: 'error', message: '下载更新失败，请手动下载更新' }));
    }
  };

  const openReleasePage = async () => {
    if (window.electronAPI) {
      await window.electronAPI.openReleasePage();
      return;
    }
    window.open(RELEASE_URL, '_blank', 'noopener,noreferrer');
  };

  const updateAction = () => {
    if (updateStatus.state === 'available') {
      return (
        <button onClick={downloadUpdate} className="inline-flex items-center justify-center gap-2 rounded-lg bg-[#00ADA6] px-4 py-2.5 text-sm font-medium text-white shadow-sm transition-colors hover:bg-[#009A94]">
          <IconDownload size={17} /> 下载 v{updateStatus.availableVersion}
        </button>
      );
    }
    if (updateStatus.state === 'downloaded') {
      return (
        <button onClick={() => void window.electronAPI?.installUpdate()} className="inline-flex items-center justify-center gap-2 rounded-lg bg-[#00ADA6] px-4 py-2.5 text-sm font-medium text-white shadow-sm transition-colors hover:bg-[#009A94]">
          <IconArrowUp size={17} /> 重启并更新
        </button>
      );
    }
    if (updateStatus.state === 'manual-update') {
      return (
        <button onClick={() => void openReleasePage()} className="inline-flex items-center justify-center gap-2 rounded-lg bg-[#00ADA6] px-4 py-2.5 text-sm font-medium text-white shadow-sm transition-colors hover:bg-[#009A94]">
          <IconDownload size={17} /> 下载 v{updateStatus.availableVersion}
        </button>
      );
    }
    const isBusy = updateStatus.state === 'checking' || updateStatus.state === 'downloading';
    return (
      <button onClick={checkForUpdates} disabled={isBusy || updateStatus.state === 'unsupported'} className="inline-flex items-center justify-center gap-2 rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-sm font-medium text-slate-700 shadow-sm transition-colors hover:border-[#00ADA6] hover:text-[#00ADA6] disabled:cursor-not-allowed disabled:opacity-50">
        {isBusy ? <IconLoader2 className="animate-spin" size={17} /> : <IconRefresh size={17} />}
        {updateStatus.state === 'checking' ? '检查中…' : updateStatus.state === 'downloading' ? '下载中…' : updateStatus.state === 'not-available' ? '再次检查' : '检查更新'}
      </button>
    );
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/50 transition-opacity">
      <div className="bg-white rounded-2xl shadow-2xl w-[800px] h-[600px] flex overflow-hidden relative animate-in fade-in zoom-in-95 duration-200">
        {/* 关闭按钮 */}
        <button
          onClick={onClose}
          className="absolute top-4 right-4 p-2 text-slate-400 hover:text-slate-700 hover:bg-slate-100 rounded-full transition-colors z-10"
        >
          <IconX size={20} />
        </button>

        {/* 左侧导航栏 */}
        <div className="w-1/3 bg-[#F9F9F9] border-r border-slate-200 p-6 flex flex-col">
          <h2 className="text-xl font-bold text-slate-800 mb-6 px-3">偏好设置</h2>
          <nav className="flex flex-col gap-1">
            <button
              onClick={() => setActiveMenu('core')}
              className={`flex items-center gap-3 px-3 py-3 rounded-lg text-sm font-medium transition-colors ${activeMenu === 'core' ? 'bg-slate-200 text-slate-900' : 'text-slate-600 hover:bg-slate-100'}`}
            >
              <IconKey size={18} className={activeMenu === 'core' ? 'text-[#00ADA6]' : ''} /> API 配置
            </button>
            <button
              onClick={() => setActiveMenu('diagnostics')}
              className={`flex items-center gap-3 px-3 py-3 rounded-lg text-sm font-medium transition-colors ${activeMenu === 'diagnostics' ? 'bg-slate-200 text-slate-900' : 'text-slate-600 hover:bg-slate-100'}`}
            >
              <IconActivity size={18} className={activeMenu === 'diagnostics' ? 'text-[#00ADA6]' : ''} /> 系统诊断
            </button>
            <button
              onClick={() => setActiveMenu('updates')}
              className={`flex items-center gap-3 px-3 py-3 rounded-lg text-sm font-medium transition-colors ${activeMenu === 'updates' ? 'bg-slate-200 text-slate-900' : 'text-slate-600 hover:bg-slate-100'}`}
            >
              <IconArrowUp size={18} className={activeMenu === 'updates' ? 'text-[#00ADA6]' : ''} /> 检查更新
            </button>
          </nav>

        </div>

        {/* 右侧内容区 */}
        <div className="w-2/3 p-8 overflow-y-auto bg-white">
          {activeMenu === 'core' && (
            <div className="space-y-6">
              <h3 className="text-lg font-semibold border-b border-slate-100 pb-4">API 配置</h3>

              {/* DashScope API Key */}
              <div className="space-y-3">
                <div className="flex items-center gap-2">
                  <label className="text-sm font-medium text-slate-700">DashScope API Key</label>
                  <div className="relative group">
                    <IconHelp size={16} className="text-slate-400 cursor-help" />
                    <div className="absolute left-0 top-6 w-80 p-4 bg-slate-800 text-white text-xs rounded-lg shadow-xl opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all duration-200 z-50 space-y-3">
                      <p className="font-medium text-white">如何获取 DashScope API Key？</p>
                      <ol className="list-decimal list-inside space-y-1 text-slate-300">
                        <li>访问 <a href="https://bailian.console.aliyun.com/cn-beijing?tab=model#/api-key" target="_blank" rel="noopener noreferrer" className="text-[#00ADA6] hover:underline">阿里云百炼</a></li>
                        <li>点击「创建 API Key」</li>
                        <li>复制密钥（sk-...）并粘贴到下方</li>
                      </ol>
                      <p className="text-slate-400 text-[10px] pt-2 border-t border-slate-600">
                        一个密钥 = 通义千问（LLM）+ Qwen3-ASR-Flash（语音识别）
                      </p>
                    </div>
                  </div>
                </div>
                <input
                  type="password"
                  placeholder="sk-..."
                  value={dashscopeApiKey}
                  onChange={(e) => setDashscopeApiKey(e.target.value)}
                  className="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#00ADA6]/50 focus:border-[#00ADA6] transition-all"
                />
                <p className="text-xs text-slate-400">云端语音识别 + 大模型摘要分析，只需这一个密钥。</p>
              </div>

              <label className="flex items-start gap-3 rounded-lg border border-slate-200 bg-slate-50 p-4 cursor-pointer">
                <input
                  type="checkbox"
                  checked={cacheEntityImages}
                  onChange={(event) => setCacheEntityImages(event.target.checked)}
                  className="mt-0.5 h-4 w-4 accent-[#00ADA6]"
                />
                <span>
                  <span className="block text-sm font-medium text-slate-700">将时间轴实体图片保存到本地</span>
                  <span className="mt-1 block text-xs leading-relaxed text-slate-400">默认仅保存远程链接。图片加载失败会自动隐藏，不影响时间轴生成和使用。</span>
                </span>
              </label>

              <button
                onClick={saveSettings}
                className="bg-[#00ADA6] hover:bg-[#009A94] text-white px-6 py-2.5 rounded-lg font-medium transition-colors shadow-sm"
              >
                保存并应用
              </button>
            </div>
          )}

          {activeMenu === 'diagnostics' && (
            <div className="space-y-6">
              <h3 className="text-lg font-semibold border-b border-slate-100 pb-4">系统诊断</h3>
              <button
                onClick={runDiagnostics}
                disabled={diagnosticsLoading}
                className="w-full bg-white border border-slate-200 hover:border-[#00ADA6] hover:text-[#00ADA6] text-slate-700 px-6 py-2.5 rounded-lg font-medium transition-colors shadow-sm disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {diagnosticsLoading ? (
                  <span className="flex items-center justify-center gap-2">
                    <IconLoader2 className="animate-spin" size={18} /> 诊断中...
                  </span>
                ) : '一键诊断'}
              </button>

              {diagnosticsError && (
                <div className="p-4 bg-[#FFF1F3] border border-[#E11D48] rounded-lg">
                  <p className="text-sm text-[#E11D48]">{diagnosticsError}</p>
                </div>
              )}

              {diagnostics.length > 0 && (
                <div className="space-y-3">
                  <h4 className="font-medium text-slate-700">检测结果</h4>
                  <div className="space-y-2">
                    {diagnostics.map((item, index) => (
                      <div key={index} className="flex items-center gap-3 p-3 bg-slate-50 rounded-lg">
                        {item.success ? (
                          <IconCircleCheck className="text-[#10B981]" size={18} />
                        ) : (
                          <IconCircleX className="text-[#E11D48]" size={18} />
                        )}
                        <div className="flex-1">
                          <div className="flex justify-between items-center">
                            <span className="text-sm font-medium text-slate-800">{item.name}</span>
                            <span className={`text-xs font-medium px-2 py-0.5 rounded ${item.success ? 'bg-[#D1FAF5] text-[#00ADA6]' : 'bg-[#FFF1F3] text-[#E11D48]'}`}>
                              {item.success ? '通过' : '失败'}
                            </span>
                          </div>
                          <p className="text-xs text-slate-500 mt-1">{item.message}</p>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {activeMenu === 'updates' && (
            <div className="space-y-6">
              <div className="border-b border-slate-100 pb-4">
                <h3 className="text-lg font-semibold">检查更新</h3>
                <p className="mt-1 text-sm text-slate-400">获取最新版本，并在下载完成后安全地重启安装。</p>
              </div>

              <div className="overflow-hidden rounded-xl border border-slate-200 bg-slate-50">
                <div className="flex items-center justify-between border-b border-slate-200 bg-white px-4 py-3">
                  <span className="text-sm font-medium text-slate-600">当前版本</span>
                  <span className="rounded-full bg-[#D1FAF5] px-2.5 py-1 font-mono text-xs font-semibold text-[#009A94]">v{updateStatus.currentVersion}</span>
                </div>
                <div className="space-y-3 px-4 py-4">
                  <div className={`flex gap-3 rounded-lg p-3 ${updateStatus.state === 'error' ? 'bg-[#FFF1F3] text-[#E11D48]' : updateStatus.state === 'not-available' ? 'bg-[#D1FAF5] text-[#008B85]' : updateStatus.state === 'manual-update' ? 'bg-[#E1F5FE] text-[#0E7490]' : 'bg-white text-slate-600'}`}>
                    {updateStatus.state === 'not-available' ? <IconCircleCheck className="mt-0.5 shrink-0" size={18} /> : updateStatus.state === 'error' ? <IconCircleX className="mt-0.5 shrink-0" size={18} /> : <IconRefresh className={updateStatus.state === 'checking' || updateStatus.state === 'downloading' ? 'mt-0.5 shrink-0 animate-spin' : 'mt-0.5 shrink-0'} size={18} />}
                    <div className="min-w-0">
                      <p className="text-sm font-medium">{updateStatus.message}</p>
                      {updateStatus.state === 'downloading' && (
                        <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-slate-200">
                          <div className="h-full rounded-full bg-[#00ADA6] transition-all" style={{ width: `${updateStatus.progress}%` }} />
                        </div>
                      )}
                    </div>
                  </div>

                  {updateStatus.releaseNotes && (
                    <div className="rounded-lg border border-slate-200 bg-white p-3">
                      <p className="mb-1 text-xs font-semibold tracking-wide text-slate-400">更新说明</p>
                      <p className="max-h-28 overflow-y-auto whitespace-pre-wrap text-xs leading-relaxed text-slate-500">{updateStatus.releaseNotes}</p>
                    </div>
                  )}

                  <div className="flex flex-wrap items-center gap-3 pt-1">
                    {updateAction()}
                    <button onClick={() => void openReleasePage()} className="inline-flex items-center gap-1.5 text-sm font-medium text-[#00ADA6] transition-colors hover:text-[#009A94] hover:underline">
                      前往 Release 手动下载 <IconExternalLink size={15} />
                    </button>
                  </div>
                  {updateStatus.state === 'error' && <p className="text-xs leading-relaxed text-slate-400">自动更新失败不会影响当前版本。你可以通过 Release 页面下载并手动安装最新版本。</p>}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default SettingsModal;
