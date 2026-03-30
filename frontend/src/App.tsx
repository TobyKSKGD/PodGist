import { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import { IconSettings, IconPlus, IconMessageCircle, IconCloudUpload, IconLayoutList, IconChevronLeft, IconChevronRight, IconLayersLinked, IconTrash, IconAlertTriangle, IconBell, IconX, IconCircleCheck, IconUpload, IconRadio, IconVideo, IconBrain } from '@tabler/icons-react';
import SettingsModal from './components/SettingsModal';
import ResultView from './components/ResultView';
import PodcastDownloadForm from './components/PodcastDownloadForm';
import TaskQueue from './components/TaskQueue';
import BatchProcess from './components/BatchProcess';
import Logo from './components/Logo';
import DinoLoader from './components/DinoLoader';
import { ToastProvider, useToast } from './components/Toast';
import ConfirmDialog from './components/ConfirmDialog';
import ChatView from './components/ChatView';

// 配置 axios 基础路径，指向你的 FastAPI 后端
const api = axios.create({ baseURL: 'http://localhost:8000' });

// 内部组件 - 可以使用 useToast
function AppContent() {
  const { showToast } = useToast();
  const [activeInputTab, setActiveInputTab] = useState<'local' | 'podcast' | 'bilibili' | 'batch' | 'chat'>('local');
  const [archives, setArchives] = useState<{id: string, name: string}[]>([]);
  const [isIconUploading, setIsIconUploading] = useState(false);
  const [isIconSettingsOpen, setIsIconSettingsOpen] = useState(false);
  const [settings, setIconSettings] = useState({
    engine: 'SenseVoice',
    whisper_model: 'small',
    device: 'auto',
    max_timeline_items: 15
  });
  const [currentView, setCurrentView] = useState<'upload' | 'result' | 'queue' | 'chat'>('upload');
  const [selectedArchiveId, setSelectedArchiveId] = useState<string | null>(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [hasApiKey, setHasApiKey] = useState(false);
  const [deleteDialog, setDeleteDialog] = useState<{ open: boolean; archiveId: string; archiveName: string }>({
    open: false,
    archiveId: '',
    archiveName: ''
  });
  const fileInputRef = useRef<HTMLInputElement>(null);

  // 通知系统 - 从 localStorage 加载已通知的任务 ID
  const [notifications, setNotifications] = useState<{ id: string; taskName: string; archiveId: string; taskId: string }[]>([]);
  const [showIconBellMenu, setShowIconBellMenu] = useState(false);
  const bellMenuRef = useRef<HTMLDivElement>(null);
  const bellButtonRef = useRef<HTMLButtonElement>(null);

  // 从 localStorage 加载已通知的任务 ID
  const loadNotifiedTaskIds = (): Set<string> => {
    try {
      const stored = localStorage.getItem('podgist_notified_tasks');
      return stored ? new Set(JSON.parse(stored)) : new Set();
    } catch {
      return new Set();
    }
  };

  const notifiedTaskIds = useRef<Set<string>>(loadNotifiedTaskIds());

  const saveNotifiedTaskIds = (ids: Set<string>) => {
    try {
      localStorage.setItem('podgist_notified_tasks', JSON.stringify([...ids]));
    } catch {}
  };

  const addNotification = (taskName: string, archiveId: string, taskId: string) => {
    // 避免重复通知同一任务
    if (notifiedTaskIds.current.has(taskId)) return;
    notifiedTaskIds.current.add(taskId);
    saveNotifiedTaskIds(notifiedTaskIds.current);
    const id = `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
    setNotifications(prev => [{ id, taskName, archiveId, taskId }, ...prev]);
    // 显示顶部 toast 提示，并刷新侧边栏归档列表
    showToast('success', `任务已完成：${taskName}`);
    fetchArchives();
  };

  const fetchArchives = async () => {
    try {
      const res = await api.get('/api/archives');
      setArchives(res.data.archives);
    } catch (error) {
      console.error("获取归档失败:", error);
    }
  };

  const fetchIconSettings = async () => {
    try {
      const res = await api.get('/api/settings');
      if (res.data.status === 'success') {
        setIconSettings({
          engine: res.data.data.engine || 'SenseVoice',
          whisper_model: res.data.data.whisper_model || 'small',
          device: res.data.data.device || 'auto',
          max_timeline_items: res.data.data.max_timeline_items || 15
        });
        setHasApiKey(!!res.data.data.api_key);
      }
    } catch (error) {
      console.error("获取设置失败:", error);
    }
  };

  const removeNotification = (id: string, _taskId: string) => {
    setNotifications(prev => prev.filter(n => n.id !== id));
  };

  const handleViewNotification = (archiveId: string, id: string, taskId: string) => {
    setSelectedArchiveId(archiveId);
    setCurrentView('result');
    removeNotification(id, taskId);
  };

  // 点击外部关闭铃铛菜单
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (
        bellMenuRef.current &&
        !bellMenuRef.current.contains(e.target as Node) &&
        bellButtonRef.current &&
        !bellButtonRef.current.contains(e.target as Node)
      ) {
        setShowIconBellMenu(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // 1. 组件加载时，去后端拉取历史归档记录和设置
  useEffect(() => {
    fetchArchives();
    fetchIconSettings();
  }, []);

  // App 级轮询：检测已完成任务并触发通知（与 TaskQueue 解耦）
  useEffect(() => {
    const checkCompletedTasks = async () => {
      try {
        const res = await api.get('/api/tasks');
        if (res.data.status === 'success') {
          for (const task of res.data.tasks) {
            if (
              task.status === 'COMPLETED' &&
              task.result_path &&
              !notifiedTaskIds.current.has(task.id)
            ) {
              const archiveId = task.result_path.split('/').pop();
              if (archiveId) {
                addNotification(task.name || '未命名任务', archiveId, task.id);
              }
            }
          }
        }
      } catch (error) {
        console.error('检测已完成任务失败:', error);
      }
    };

    // 立即检查一次，然后每 15 秒轮询
    checkCompletedTasks();
    const interval = setInterval(checkCompletedTasks, 15000);
    return () => clearInterval(interval);
  }, []);

  // 2. 处理文件上传与后端交互
  const handleFileIconUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    setIsIconUploading(true);

    const formData = new FormData();
    formData.append('file', file);
    formData.append('engine', settings.engine);
    formData.append('whisper_model', settings.whisper_model);
    formData.append('device', settings.device);
    formData.append('max_timeline_items', settings.max_timeline_items.toString());

    try {
      const res = await api.post('/api/transcribe/local', formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      });
      showToast('success', `已添加任务：${res.data.filename}`);
      fetchArchives();
    } catch (error) {
      console.error(error);
      showToast('error', '处理失败，请检查后端终端日志');
    } finally {
      setIsIconUploading(false);
    }
  };

  // 处理点击归档项
  const handleArchiveClick = (archiveId: string) => {
    setSelectedArchiveId(archiveId);
    setCurrentView('result');
  };

  // 处理删除归档 - 打开确认对话框
  const handleDeleteArchive = (archiveId: string, archiveName: string, event: React.MouseEvent) => {
    event.stopPropagation();
    setDeleteDialog({ open: true, archiveId, archiveName });
  };

  // 确认删除归档
  const confirmDeleteArchive = async () => {
    const { archiveId } = deleteDialog;
    setDeleteDialog({ open: false, archiveId: '', archiveName: '' });

    try {
      await api.delete(`/api/archives/${encodeURIComponent(archiveId)}`);
      showToast('success', '归档已删除');
      if (selectedArchiveId === archiveId) {
        setCurrentView('upload');
        setSelectedArchiveId(null);
      }
      fetchArchives();
    } catch (error) {
      console.error("删除归档失败:", error);
      showToast('error', '删除失败，请重试');
    }
  };

  // 返回上传页面
  const handleBackToIconUpload = () => {
    setCurrentView('upload');
    setSelectedArchiveId(null);
  };

  // 渲染主内容区
  const renderMainContent = () => {
    if (currentView === 'result' && selectedArchiveId) {
      return <ResultView archiveId={selectedArchiveId} onBack={handleBackToIconUpload} />;
    }

    if (currentView === 'queue') {
      return <TaskQueue
        onTaskComplete={addNotification}
        onViewArchive={(archiveId) => {
          setSelectedArchiveId(archiveId);
          setCurrentView('result');
        }}
        onRefreshArchives={fetchArchives}
      />;
    }

    // 智能对话视图（占满整屏）
    if (currentView === 'chat') {
      return (
        <main className="flex-1 overflow-hidden bg-white">
          <ChatView />
        </main>
      );
    }

    return (
      <main className="flex-1 overflow-y-auto bg-white">
        <div className="max-w-4xl w-full mx-auto p-8 pb-16">

          <div className="text-center mb-12 mt-12">
            <h2 className="text-3xl font-bold mb-3 tracking-tight">上传音频，提取精华</h2>
            <p className="text-slate-500">支持本地文件、播客直连与 Bilibili 视频剥离</p>
          </div>

          {!hasApiKey && (
            <div className="mb-6 p-4 bg-[#E1F5FE] border border-[#009A94] rounded-xl flex items-start gap-3">
              <IconAlertTriangle className="text-[#009A94] shrink-0 mt-0.5" size={20} />
              <div>
                <p className="text-sm font-medium text-[#E11D48]">尚未配置 DeepSeek API Key</p>
                <p className="text-xs text-[#009A94] mt-0.5">请点击左侧底部「偏好设置」配置 API Key，否则无法使用提炼功能</p>
              </div>
            </div>
          )}

          <div className="flex border-b border-slate-200 mb-8">
            <button
              onClick={() => setActiveInputTab('local')}
              className={`px-4 py-3 text-sm font-medium border-b-2 transition-colors ${activeInputTab === 'local' ? 'border-[#00ADA6] text-[#00ADA6]' : 'border-transparent text-slate-500 hover:text-slate-700'}`}>
              <span className="flex items-center gap-1.5">
                <IconUpload size={16} />
                本地提炼
              </span>
            </button>
            <button
              onClick={() => setActiveInputTab('podcast')}
              className={`px-4 py-3 text-sm font-medium border-b-2 transition-colors ${activeInputTab === 'podcast' ? 'border-[#00ADA6] text-[#00ADA6]' : 'border-transparent text-slate-500 hover:text-slate-700'}`}>
              <span className="flex items-center gap-1.5">
                <IconRadio size={16} />
                播客直连
              </span>
            </button>
            <button
              onClick={() => setActiveInputTab('bilibili')}
              className={`px-4 py-3 text-sm font-medium border-b-2 transition-colors ${activeInputTab === 'bilibili' ? 'border-[#00ADA6] text-[#00ADA6]' : 'border-transparent text-slate-500 hover:text-slate-700'}`}>
              <span className="flex items-center gap-1.5">
                <IconVideo size={16} />
                视频剥离
              </span>
            </button>
            <button
              onClick={() => setActiveInputTab('batch')}
              className={`px-4 py-3 text-sm font-medium border-b-2 transition-colors ${activeInputTab === 'batch' ? 'border-[#00ADA6] text-[#00ADA6]' : 'border-transparent text-slate-500 hover:text-slate-700'}`}>
              <span className="flex items-center gap-1.5">
                <IconLayersLinked size={16} />
                批量处理
              </span>
            </button>
          </div>

          {activeInputTab === 'local' ? (
            <div className="flex-1">
              <input
                type="file"
                accept=".mp3,.wav,.m4a"
                className="hidden"
                ref={fileInputRef}
                onChange={handleFileIconUpload}
                disabled={isIconUploading}
              />

              <div
                onClick={() => !isIconUploading && fileInputRef.current?.click()}
                className={`border-2 border-dashed rounded-xl flex flex-col items-center justify-center p-14 transition-all ${
                  isIconUploading ? 'border-slate-300 bg-slate-50 cursor-not-allowed' : 'border-slate-300 hover:border-[#00ADA6] hover:bg-[#D1FAF5] cursor-pointer bg-slate-50'
                }`}
              >
                {isIconUploading ? (
                  <DinoLoader message="音频转录中，请先喝杯水..." />
                ) : (
                  <>
                    <IconCloudUpload className="text-slate-400 mb-4" size={48} strokeWidth={1.5} />
                    <p className="text-lg font-medium text-slate-700 mb-1">
                      点击或拖拽音频文件到此处
                    </p>
                    <p className="text-sm text-slate-400">
                      支持 MP3, WAV, M4A (最大 200MB)
                    </p>
                  </>
                )}
              </div>
            </div>
          ) : activeInputTab === 'podcast' ? (
            <div className="flex-1">
              <PodcastDownloadForm
                settings={settings}
                downloadType="podcast"
                onSuccess={() => {
                  fetchArchives();
                }}
              />
            </div>
          ) : activeInputTab === 'bilibili' ? (
            <div className="flex-1">
              <PodcastDownloadForm
                settings={settings}
                downloadType="bilibili"
                onSuccess={() => {
                  fetchArchives();
                }}
              />
            </div>
          ) : (
            <div className="flex-1">
              <BatchProcess settings={settings} />
            </div>
          )}

        </div>
      </main>
    );
  };

  return (
    <div className="flex h-screen w-full bg-white text-slate-800 font-sans">
      {/* ================= 左侧导航栏 ================= */}
      <aside className={`border-r border-slate-200 bg-[#F9F9F9] flex flex-col transition-all duration-300 ${sidebarCollapsed ? 'w-16' : 'w-80'}`}>
        {/* Header */}
        <div className="p-3 border-b border-slate-200 flex items-center justify-between">
          {!sidebarCollapsed && (
            <button
              onClick={() => { setActiveInputTab('local'); setCurrentView('upload'); setSelectedArchiveId(null); }}
              className="text-lg font-bold flex items-center gap-2 hover:opacity-80 transition-opacity"
            >
              <Logo size={28} /> PodGist
            </button>
          )}
          <button
            onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
            className="p-1.5 hover:bg-slate-200 rounded-md transition-colors text-slate-500 hover:text-slate-700"
          >
            {sidebarCollapsed ? <IconChevronRight size={18} /> : <IconChevronLeft size={18} />}
          </button>
        </div>

        {!sidebarCollapsed && (
          <>
            <div className="p-4">
              <button
                onClick={() => { setActiveInputTab('local'); setCurrentView('upload'); }}
                className="w-full bg-[#00ADA6] hover:bg-[#009A94] text-white py-2.5 px-4 rounded-lg font-medium transition-all shadow-sm flex items-center justify-center gap-2"
              >
                <IconPlus size={18} /> 新建提炼任务
              </button>
            </div>

            {/* 智能对话入口 */}
            <div className="px-3 mb-1">
              <button
                onClick={() => setCurrentView(currentView === 'chat' ? 'upload' : 'chat')}
                className={`w-full flex items-center gap-2 px-3 py-2.5 text-sm rounded-md transition-colors ${
                  currentView === 'chat'
                    ? 'bg-slate-200 text-[#00ADA6]'
                    : 'text-slate-600 hover:bg-slate-200 hover:text-[#00ADA6]'
                }`}
              >
                <IconBrain size={16} className="shrink-0" />
                <span>智能对话</span>
              </button>
            </div>

            {/* 任务队列入口 */}
            <div className="px-3 mb-2">
              <button
                onClick={() => setCurrentView(currentView === 'queue' ? 'upload' : 'queue')}
                className={`w-full flex items-center gap-2 px-3 py-2.5 text-sm rounded-md transition-colors ${
                  currentView === 'queue'
                    ? 'bg-slate-200 text-[#00ADA6]'
                    : 'text-slate-600 hover:bg-slate-200 hover:text-[#00ADA6]'
                }`}
              >
                <IconLayoutList size={16} className="shrink-0" />
                <span>任务队列</span>
              </button>
            </div>

            {/* 动态渲染后端拉取的历史归档 */}
            <div className="flex-1 overflow-y-auto px-3">
              <div className="text-xs font-bold text-slate-400 mb-2 px-2 tracking-wider mt-2">近期归档</div>
              <div className="space-y-1">
                {archives.length === 0 ? (
                  <p className="text-xs text-slate-400 px-3 py-2">暂无历史记录</p>
                ) : (
                  archives.map((item) => (
                    <div
                      key={item.id}
                      className={`group flex items-center gap-1 px-3 py-2.5 text-sm rounded-md transition-colors cursor-pointer truncate ${
                        selectedArchiveId === item.id && currentView === 'result'
                          ? 'bg-slate-200 text-[#00ADA6]'
                          : 'text-slate-600 hover:bg-slate-200 hover:text-[#00ADA6]'
                      }`}
                      onClick={() => handleArchiveClick(item.id)}
                    >
                      <IconMessageCircle size={16} className="shrink-0" />
                      <span className="truncate flex-1">{item.name}</span>
                      <button
                        onClick={(e) => handleDeleteArchive(item.id, item.name, e)}
                        className="opacity-0 group-hover:opacity-100 p-1 hover:bg-[#FFF1F3] hover:text-[#E11D48] rounded transition-all shrink-0"
                        title="删除归档"
                      >
                        <IconTrash size={14} />
                      </button>
                    </div>
                  ))
                )}
              </div>
            </div>

            {/* 底部设置按钮 */}
            <div className="p-4 border-t border-slate-200 bg-[#F9F9F9]">
              <button
                onClick={() => setIsIconSettingsOpen(true)}
                className="w-full flex items-center gap-2 px-3 py-2 text-sm text-slate-600 hover:bg-slate-200 hover:text-[#00ADA6] rounded-md transition-colors font-medium"
              >
                <IconSettings size={18} /> 偏好设置
              </button>
            </div>
          </>
        )}

        {/* 收缩状态下的图标按钮 */}
        {sidebarCollapsed && (
          <div className="flex-1 flex flex-col items-center py-4 gap-2">
            <button
              onClick={() => { setActiveInputTab('local'); setCurrentView('upload'); }}
              className="p-2.5 hover:bg-slate-200 rounded-lg transition-colors text-slate-600"
              title="新建任务"
            >
              <IconPlus size={20} />
            </button>
            <button
              onClick={() => setCurrentView(currentView === 'chat' ? 'upload' : 'chat')}
              className={`p-2.5 rounded-lg transition-colors ${currentView === 'chat' ? 'bg-slate-200 text-[#00ADA6]' : 'text-slate-600 hover:bg-slate-200'}`}
              title="智能对话"
            >
              <IconBrain size={20} />
            </button>
            <button
              onClick={() => setCurrentView(currentView === 'queue' ? 'upload' : 'queue')}
              className={`p-2.5 rounded-lg transition-colors ${currentView === 'queue' ? 'bg-slate-200 text-[#00ADA6]' : 'text-slate-600 hover:bg-slate-200'}`}
              title="任务队列"
            >
              <IconLayoutList size={20} />
            </button>
            <button
              onClick={() => setIsIconSettingsOpen(true)}
              className="p-2.5 hover:bg-slate-200 rounded-lg transition-colors text-slate-600"
              title="偏好设置"
            >
              <IconSettings size={20} />
            </button>
          </div>
        )}
      </aside>

      {/* ================= 右侧主工作区 ================= */}
      <div className="flex-1 flex flex-col min-h-0 max-w-full overflow-hidden">
        {renderMainContent()}
      </div>

      {/* 全局通知铃铛（仅在非任务队列/非智能对话视图显示） */}
      {currentView !== 'queue' && currentView !== 'chat' && (
        <div className="fixed bottom-6 right-6 z-50">
          <button
            ref={bellButtonRef}
            onClick={() => setShowIconBellMenu(!showIconBellMenu)}
            className="relative p-2 bg-white border border-slate-200 rounded-lg shadow-md hover:bg-slate-50 transition-colors"
          >
            <IconBell size={20} className="text-slate-600" />
            {notifications.length > 0 && (
              <span className="absolute -top-1 -right-1 w-5 h-5 bg-[#E11D48] text-white text-xs rounded-full flex items-center justify-center font-medium">
                {notifications.length > 9 ? '9+' : notifications.length}
              </span>
            )}
          </button>

          {/* 通知下拉菜单 */}
          {showIconBellMenu && (
            <div ref={bellMenuRef} className="absolute bottom-full right-0 mb-2 w-80 bg-white border border-slate-200 rounded-lg shadow-lg overflow-hidden">
              <div className="px-4 py-3 bg-slate-50 border-b border-slate-200 flex items-center justify-between">
                <span className="text-sm font-medium text-slate-700">任务通知</span>
                <button
                  onClick={() => setShowIconBellMenu(false)}
                  className="p-1 hover:bg-slate-200 rounded transition-colors"
                >
                  <IconX size={14} className="text-slate-500" />
                </button>
              </div>
              <div className="max-h-80 overflow-y-auto">
                {notifications.length === 0 ? (
                  <div className="px-4 py-8 text-center text-sm text-slate-400">
                    暂无新通知
                  </div>
                ) : (
                  notifications.map((n) => (
                    <div
                      key={n.id}
                      className="px-4 py-3 border-b border-slate-100 last:border-b-0 hover:bg-slate-50 transition-colors group"
                    >
                      <div className="flex items-start gap-3">
                        <IconCircleCheck size={16} className="text-[#10B981] shrink-0 mt-0.5" />
                        <div className="flex-1 min-w-0">
                          <p className="text-sm text-slate-700 font-medium truncate">{n.taskName}</p>
                          <p className="text-xs text-slate-400 mt-0.5">任务已完成</p>
                        </div>
                        <div className="flex items-center gap-1 shrink-0">
                          <button
                            onClick={() => removeNotification(n.id, n.taskId)}
                            className="opacity-0 group-hover:opacity-100 p-1 text-slate-400 hover:text-slate-600 transition-colors"
                            title="关闭"
                          >
                            <IconX size={14} />
                          </button>
                          <button
                            onClick={() => handleViewNotification(n.archiveId, n.id, n.taskId)}
                            className="opacity-0 group-hover:opacity-100 px-2 py-1 bg-[#00ADA6] text-white text-xs rounded hover:bg-[#009A94] transition-all"
                          >
                            查看
                          </button>
                        </div>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          )}
        </div>
      )}

      <SettingsModal isOpen={isIconSettingsOpen} onClose={() => setIsIconSettingsOpen(false)} showToast={showToast} />

      {/* 删除归档确认对话框 */}
      <ConfirmDialog
        isOpen={deleteDialog.open}
        title="删除归档"
        message={`确定要删除归档 "${deleteDialog.archiveName}" 吗？此操作不可恢复。`}
        confirmText="删除"
        cancelText="取消"
        onConfirm={confirmDeleteArchive}
        onCancel={() => setDeleteDialog({ open: false, archiveId: '', archiveName: '' })}
        danger
      />
    </div>
  );
}

// 顶层组件 - 提供 ToastProvider
function App() {
  return (
    <ToastProvider>
      <AppContent />
    </ToastProvider>
  );
}

export default App;
