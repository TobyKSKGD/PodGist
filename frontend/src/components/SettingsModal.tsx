import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { IconX, IconKey, IconActivity, IconCircleCheck, IconCircleX, IconLoader2, IconHelp } from '@tabler/icons-react';

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

const SettingsModal: React.FC<SettingsModalProps> = ({ isOpen, onClose, showToast, onSaveSuccess }) => {
  const [activeMenu, setActiveMenu] = useState('core');
  const [diagnostics, setDiagnostics] = useState<DiagnosticItem[]>([]);
  const [diagnosticsLoading, setDiagnosticsLoading] = useState(false);
  const [diagnosticsError, setDiagnosticsError] = useState('');
  const [dashscopeApiKey, setDashscopeApiKey] = useState('');
  const [cacheEntityImages, setCacheEntityImages] = useState(false);

  // 加载设置
  useEffect(() => {
    if (isOpen) {
      fetchSettings();
    }
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
        </div>
      </div>
    </div>
  );
};

export default SettingsModal;
