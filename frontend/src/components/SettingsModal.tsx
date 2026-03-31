import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import { IconX, IconKey, IconCpu, IconActivity, IconCircleCheck, IconCircleX, IconLoader2, IconHelp, IconDownload, IconFile } from '@tabler/icons-react';

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  showToast: (type: 'success' | 'error' | 'info', message: string) => void;
}

interface Device {
  key: string;
  name: string;
}

interface ModelInfo {
  name: string;
  display_name: string;
  description: string;
  size_mb: number;
  downloaded: boolean;
  local_size_mb: number;
  path: string;
  download_url: string;
}

const SettingsModal: React.FC<SettingsModalProps> = ({ isOpen, onClose, showToast }) => {
  const [activeMenu, setActiveMenu] = useState('core');
  const [diagnostics, setDiagnostics] = useState<Array<{name: string, success: boolean, message: string}>>([]);
  const [diagnosticsLoading, setDiagnosticsLoading] = useState(false);
  const [diagnosticsError, setDiagnosticsError] = useState('');
  const [apiIconKey, setApiIconKey] = useState('');
  const [selectedEngine, setSelectedEngine] = useState('SenseVoice');
  const [whisperModel, setWhisperModel] = useState('small');
  const [selectedDevice, setSelectedDevice] = useState('auto');
  const [maxTimelineItems, setMaxTimelineItems] = useState(15);
  const [availableDevices, setAvailableDevices] = useState<Device[]>([]);

  // 模型管理状态
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [downloadingModel, setDownloadingModel] = useState<string | null>(null);
  const [downloadProgress, setDownloadProgress] = useState<{percent: number, downloaded_mb: number, total_mb: number} | null>(null);
  const [expandedManualModel, setExpandedManualModel] = useState<string | null>(null);
  const [manualDownloadInfo, setManualDownloadInfo] = useState<{url: string, instructions: string} | null>(null);

  // 当弹窗打开时，从后端加载设置
  useEffect(() => {
    if (isOpen) {
      fetchSettings();
    }
  }, [isOpen]);

  // 切换到模型管理菜单时加载状态
  useEffect(() => {
    if (activeMenu === 'models' && models.length === 0) {
      fetchModelsStatus();
    }
  }, [activeMenu]);

  const fetchSettings = async () => {
    try {
      const response = await axios.get('http://localhost:8000/api/settings');
      if (response.data.status === 'success') {
        const data = response.data.data;
        setApiIconKey(data.api_key || '');
        setSelectedEngine(data.engine || 'SenseVoice');
        setWhisperModel(data.whisper_model || 'small');
        setSelectedDevice(data.device || 'auto');
        setMaxTimelineItems(data.max_timeline_items || 15);
        setAvailableDevices(data.available_devices || []);
      }
    } catch (error) {
      console.error('加载设置失败:', error);
    }
  };

  const fetchModelsStatus = async () => {
    setModelsLoading(true);
    try {
      const response = await axios.get('http://localhost:8000/api/models/status');
      if (response.data.status === 'success') {
        setModels(response.data.data);
      }
    } catch (error) {
      console.error('获取模型状态失败:', error);
      showToast('error', '无法获取模型状态');
    } finally {
      setModelsLoading(false);
    }
  };

  const downloadModel = async (modelName: string) => {
    setDownloadingModel(modelName);
    setDownloadProgress(null);
    setManualDownloadInfo(null);

    try {
      const response = await axios.post(
        `http://localhost:8000/api/models/download/${modelName}`,
        {},
        { responseType: 'text' }
      );
    } catch (error: any) {
      // 如果是 SSE 响应，需要解析 progress
      console.log('下载响应:', error);
    }

    // 轮询检查进度（因为 SSE 可能被 axios 中断）
    const progressInterval = setInterval(async () => {
      try {
        const statusResponse = await axios.get('http://localhost:8000/api/models/status');
        if (statusResponse.data.status === 'success') {
          const updatedModels = statusResponse.data.data;
          const currentModel = updatedModels.find((m: ModelInfo) => m.name === modelName);

          if (currentModel?.downloaded) {
            // 下载完成
            clearInterval(progressInterval);
            setDownloadingModel(null);
            setDownloadProgress(null);
            setModels(updatedModels);
            showToast('success', `${currentModel.display_name} 下载完成`);
            return;
          }
        }
      } catch (e) {
        console.log('轮询进度中...');
      }
    }, 3000);

    // 30 秒后停止轮询
    setTimeout(() => {
      clearInterval(progressInterval);
      if (downloadingModel === modelName) {
        setDownloadingModel(null);
        showToast('error', '下载超时，请刷新页面检查状态或使用手动下载');
      }
    }, 30000);
  };

  const showManualDownload = async (modelName: string) => {
    // 如果已经展开，则收起
    if (expandedManualModel === modelName) {
      setExpandedManualModel(null);
      setManualDownloadInfo(null);
      return;
    }

    try {
      const response = await axios.get(`http://localhost:8000/api/models/manual-download/${modelName}`);
      if (response.data.status === 'success') {
        setExpandedManualModel(modelName);
        setManualDownloadInfo({
          url: response.data.data.url,
          instructions: response.data.data.instructions
        });
      }
    } catch (error) {
      console.error('获取手动下载信息失败:', error);
      showToast('error', '无法获取下载链接');
    }
  };

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    showToast('info', '链接已复制到剪贴板');
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
      formData.append('api_key', apiIconKey);
      formData.append('engine', selectedEngine);
      formData.append('whisper_model', whisperModel);
      formData.append('device', selectedDevice);
      formData.append('max_timeline_items', maxTimelineItems.toString());
      const response = await axios.post('http://localhost:8000/api/settings', formData);
      if (response.data.status === 'success') {
        showToast('success', '设置已保存并应用');
      } else {
        showToast('error', '保存失败: ' + response.data.message);
      }
    } catch (error) {
      console.error('保存设置失败:', error);
      showToast('error', '无法连接到后端服务');
    }
  };

  // 所有 hooks 之后才能条件返回
  if (!isOpen) return null;

  const isWhisper = selectedEngine === 'Whisper';

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/40 backdrop-blur-sm transition-opacity">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-4xl h-[600px] flex overflow-hidden relative animate-in fade-in zoom-in-95 duration-200">
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
              <IconKey size={18} className={activeMenu === 'core' ? 'text-[#00ADA6]' : ''} /> 核心设置
            </button>
            <button
              onClick={() => setActiveMenu('engine')}
              className={`flex items-center gap-3 px-3 py-3 rounded-lg text-sm font-medium transition-colors ${activeMenu === 'engine' ? 'bg-slate-200 text-slate-900' : 'text-slate-600 hover:bg-slate-100'}`}
            >
              <IconCpu size={18} className={activeMenu === 'engine' ? 'text-[#00ADA6]' : ''} /> 转录引擎
            </button>
            <button
              onClick={() => { setActiveMenu('models'); }}
              className={`flex items-center gap-3 px-3 py-3 rounded-lg text-sm font-medium transition-colors ${activeMenu === 'models' ? 'bg-slate-200 text-slate-900' : 'text-slate-600 hover:bg-slate-100'}`}
            >
              <IconFile size={18} className={activeMenu === 'models' ? 'text-[#00ADA6]' : ''} /> 模型管理
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
              <h3 className="text-lg font-semibold border-b border-slate-100 pb-4">核心安全设置</h3>
              <div className="space-y-3">
                <div className="flex items-center gap-2">
                  <label className="text-sm font-medium text-slate-700">DeepSeek API Key</label>
                  <div className="relative group">
                    <IconHelp size={16} className="text-slate-400 cursor-help" />
                    <div className="absolute left-0 top-6 w-72 p-3 bg-slate-800 text-white text-xs rounded-lg shadow-xl opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all duration-200 z-50 space-y-2">
                      <p className="font-medium text-white">如何获取 DeepSeek API Key？</p>
                      <ol className="list-decimal list-inside space-y-1 text-slate-300">
                        <li>访问 <a href="https://platform.deepseek.com/" target="_blank" rel="noopener noreferrer" className="text-[#00ADA6] hover:underline">platform.deepseek.com</a></li>
                        <li>注册/登录账号</li>
                        <li>点击左侧「API Keys」→「创建 API Key」</li>
                        <li>复制生成的密钥（sk-...）</li>
                        <li>粘贴到左侧输入框并保存</li>
                      </ol>
                      <p className="text-slate-400 text-[10px] pt-1 border-t border-slate-600">密钥仅保存在本地，绝不会上传</p>
                    </div>
                  </div>
                </div>
                <input
                  type="password"
                  placeholder="sk-..."
                  value={apiIconKey}
                  onChange={(e) => setApiIconKey(e.target.value)}
                  className="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#00ADA6]/50 focus:border-[#00ADA6] transition-all"
                />
                <p className="text-xs text-slate-400">您的密钥仅保存在本地 .env 文件中，绝不上传。</p>
              </div>
              <button
                onClick={saveSettings}
                className="bg-[#00ADA6] hover:bg-[#009A94] text-white px-6 py-2.5 rounded-lg font-medium transition-colors shadow-sm"
              >
                保存并应用
              </button>
            </div>
          )}

          {activeMenu === 'engine' && (
            <div className="space-y-8">
              <h3 className="text-lg font-semibold border-b border-slate-100 pb-4">硬件与模型引擎</h3>

              {/* 1. 选择转录引擎 */}
              <div className="space-y-3">
                <label className="text-sm font-medium text-slate-700">1. 选择转录引擎</label>
                <div className="flex gap-4">
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="radio"
                      name="engine"
                      value="SenseVoice"
                      checked={selectedEngine === 'SenseVoice'}
                      onChange={(e) => setSelectedEngine(e.target.value)}
                      className="text-[#00ADA6] focus:ring-[#00ADA6]"
                    />
                    <span className="text-sm">SenseVoice (极速模式)</span>
                  </label>
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="radio"
                      name="engine"
                      value="Whisper"
                      checked={selectedEngine === 'Whisper'}
                      onChange={(e) => setSelectedEngine(e.target.value)}
                      className="text-[#00ADA6] focus:ring-[#00ADA6]"
                    />
                    <span className="text-sm">Whisper (高精度时间戳)</span>
                  </label>
                </div>
                <p className="text-xs text-slate-400">
                  {isWhisper
                    ? "Whisper：OpenAI 模型，精度更高，但速度较慢。"
                    : "SenseVoice：阿里开源模型，转录速度极快，适合大多数场景。"}
                </p>
              </div>

              {/* 2. Whisper 模式：显示模型规模选择 */}
              {isWhisper && (
                <div className="space-y-3">
                  <label className="text-sm font-medium text-slate-700">2. 模型规模</label>
                  <select
                    value={whisperModel}
                    onChange={(e) => setWhisperModel(e.target.value)}
                    className="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#00ADA6]/50 focus:border-[#00ADA6] transition-all"
                  >
                    <option value="tiny">tiny - 速度最快，精度较低</option>
                    <option value="base">base - 速度快，精度一般</option>
                    <option value="small">small - 平衡选择（推荐）</option>
                    <option value="medium">medium - 精度较好</option>
                    <option value="large-v3">large-v3 - 精度最高，需更多显存</option>
                  </select>
                  <p className="text-xs text-slate-400">
                    选择 Whisper 模型规模。tiny/base 速度快，small/medium 平衡，large-v3 精度最高。
                  </p>
                </div>
              )}

              {/* SenseVoice 模式：显示提示 */}
              {!isWhisper && (
                <div className="p-3 bg-[#EFF6FF] border border-[#3B82F6] rounded-lg">
                  <p className="text-sm text-[#64748B]">
                    SenseVoice 使用 Small 版本，无需选择模型规模
                  </p>
                </div>
              )}

              {/* 3. 算力硬件 */}
              <div className="space-y-3">
                <label className="text-sm font-medium text-slate-700">
                  {isWhisper ? '3' : '2'}. 算力硬件
                </label>
                <select
                  value={selectedDevice}
                  onChange={(e) => setSelectedDevice(e.target.value)}
                  className="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#00ADA6]/50 focus:border-[#00ADA6] transition-all"
                >
                  <option value="auto">自动选择最佳设备</option>
                  {availableDevices.map((device) => (
                    <option key={device.key} value={device.key}>
                      {device.name}
                    </option>
                  ))}
                </select>
                <p className="text-xs text-slate-400">
                  选择用于转录的计算设备。Apple Silicon (MPS) 推荐 Mac 用户使用，GPU (CUDA) 为 NVIDIA 显卡加速。
                </p>
              </div>

              {/* 4. 时间轴上限 */}
              <div className="space-y-3">
                <label className="text-sm font-medium text-slate-700">
                  {isWhisper ? '4' : '3'}. 时间轴上限
                </label>
                <div className="flex gap-3">
                  {[8, 10, 15, 20, 25].map((num) => (
                    <label key={num} className="flex items-center gap-1 cursor-pointer">
                      <input
                        type="radio"
                        name="timeline"
                        value={num}
                        checked={maxTimelineItems === num}
                        onChange={() => setMaxTimelineItems(num)}
                        className="text-[#00ADA6] focus:ring-[#00ADA6]"
                      />
                      <span className="text-sm">{num}</span>
                    </label>
                  ))}
                </div>
                <p className="text-xs text-slate-400">
                  AI 生成的时间轴最多不超过此条数。数量越少，生成速度越快、越稳定。
                </p>
              </div>

              <button
                onClick={saveSettings}
                className="bg-[#00ADA6] hover:bg-[#009A94] text-white px-6 py-2.5 rounded-lg font-medium transition-colors shadow-sm"
              >
                保存并应用
              </button>
            </div>
          )}

          {activeMenu === 'models' && (
            <div className="space-y-6">
              <div className="flex items-center justify-between border-b border-slate-100 pb-4 pr-8">
                <h3 className="text-lg font-semibold">模型管理</h3>
                <button
                  onClick={fetchModelsStatus}
                  className="text-sm text-[#00ADA6] hover:underline"
                >
                  刷新状态
                </button>
              </div>

              {modelsLoading ? (
                <div className="flex items-center justify-center py-12">
                  <IconLoader2 className="animate-spin text-[#00ADA6]" size={24} />
                  <span className="ml-2 text-slate-500">加载中...</span>
                </div>
              ) : (
                <div className="space-y-4">
                  {models.map((model) => (
                    <div key={model.name} className="border border-slate-200 rounded-lg p-4">
                      <div className="flex items-start justify-between">
                        <div className="flex-1">
                          <div className="flex items-center gap-2">
                            <h4 className="font-medium text-slate-800">{model.display_name}</h4>
                            {model.downloaded ? (
                              <span className="text-xs bg-[#D1FAF5] text-[#00ADA6] px-2 py-0.5 rounded">
                                已下载
                              </span>
                            ) : (
                              <span className="text-xs bg-slate-100 text-slate-500 px-2 py-0.5 rounded">
                                未下载
                              </span>
                            )}
                          </div>
                          <p className="text-sm text-slate-500 mt-1">{model.description}</p>
                          <p className="text-xs text-slate-400 mt-1">
                            大小: {model.size_mb} MB
                            {model.downloaded && model.local_size_mb > 0 && (
                              <span className="ml-2 text-[#00ADA6]">
                                (本地: {model.local_size_mb} MB)
                              </span>
                            )}
                          </p>
                        </div>

                        <div className="ml-4">
                          {downloadingModel === model.name ? (
                            <div className="text-center">
                              <IconLoader2 className="animate-spin text-[#00ADA6] mx-auto" size={20} />
                              <span className="text-xs text-slate-500 mt-1 block">
                                {downloadProgress?.percent || 0}%
                              </span>
                              {downloadProgress && (
                                <span className="text-xs text-slate-400">
                                  {downloadProgress.downloaded_mb} / {downloadProgress.total_mb} MB
                                </span>
                              )}
                            </div>
                          ) : model.downloaded ? (
                            <span className="text-[#10B981]">
                              <IconCircleCheck size={24} />
                            </span>
                          ) : (
                            <div className="flex gap-2">
                              <button
                                onClick={() => downloadModel(model.name)}
                                className="flex items-center gap-1 bg-[#00ADA6] hover:bg-[#009A94] text-white text-sm px-3 py-1.5 rounded-lg transition-colors"
                              >
                                <IconDownload size={16} />
                                下载
                              </button>
                              <button
                                onClick={() => showManualDownload(model.name)}
                                className="text-sm text-slate-500 hover:text-slate-700 px-2 py-1.5 border border-slate-200 rounded-lg"
                                title="手动下载"
                              >
                                ?
                              </button>
                            </div>
                          )}
                        </div>
                      </div>

                      {/* 手动下载信息 */}
                      {expandedManualModel === model.name && manualDownloadInfo && (
                        <div className="mt-4 p-3 bg-slate-50 border border-slate-200 rounded-lg">
                          <div className="flex items-center justify-between mb-2">
                            <p className="text-sm font-medium text-slate-700">手动下载链接</p>
                            <button
                              onClick={() => copyToClipboard(manualDownloadInfo.url)}
                              className="text-xs text-[#00ADA6] hover:underline"
                            >
                              复制链接
                            </button>
                          </div>
                          <p className="text-xs text-slate-600 bg-white px-2 py-1 rounded border break-all">
                            {manualDownloadInfo.url}
                          </p>
                          <div className="mt-2 text-xs text-slate-500 whitespace-pre-line">
                            {manualDownloadInfo.instructions}
                          </div>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}

              <div className="p-4 bg-[#EFF6FF] border border-[#3B82F6] rounded-lg">
                <p className="text-sm text-[#64748B]">
                  <strong>提示：</strong>如果自动下载经常中断，建议使用「?」按钮获取下载链接，
                  然后用浏览器或下载工具（如 IDM、迅雷）下载，下载完成后刷新页面即可自动识别。
                </p>
              </div>
            </div>
          )}

          {activeMenu === 'diagnostics' && (
            <div className="space-y-6">
              <h3 className="text-lg font-semibold border-b border-slate-100 pb-4">运行环境检测</h3>
              <button
                onClick={runDiagnostics}
                disabled={diagnosticsLoading}
                className="w-full bg-white border border-slate-200 hover:border-[#00ADA6] hover:text-[#00ADA6] text-slate-700 px-6 py-2.5 rounded-lg font-medium transition-colors shadow-sm disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {diagnosticsLoading ? (
                  <span className="flex items-center justify-center gap-2">
                    <IconLoader2 className="animate-spin" size={18} /> 诊断中...
                  </span>
                ) : '一键诊断底层组件'}
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
