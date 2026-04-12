import { useState, useEffect, useRef } from 'react';
import { Routes, Route, useLocation, useNavigate, useParams } from 'react-router-dom';
import LibraryPage from './pages/LibraryPage';
import ImportPage from './pages/ImportPage';
import EpisodePage from './pages/EpisodePage';
import axios from 'axios';
import { IconSettings, IconPlus, IconMessageCircle, IconLayoutList, IconChevronLeft, IconChevronRight, IconTrash, IconBell, IconX, IconCircleCheck, IconBrain } from '@tabler/icons-react';
import SettingsModal from './components/SettingsModal';
import ResultView from './components/ResultView';
import TaskQueue from './components/TaskQueue';
import Logo from './components/Logo';
import { ToastProvider, useToast } from './components/Toast';
import ConfirmDialog from './components/ConfirmDialog';
import ChatView from './components/ChatView';

// 配置 axios 基础路径，指向你的 FastAPI 后端
const api = axios.create({ baseURL: 'http://localhost:8000' });

// ===== 路由子组件 =====
// 直接访问 /result/:id 时，从 URL 读取 archiveId，避免依赖 AppContent 状态初始渲染延迟
function ResultViewWrapper({ onBack, onJumpToChat }: {
  onBack: () => void;
  onJumpToChat: (sessionId: string) => void;
}) {
  const { id } = useParams<{ id: string }>();
  const [archiveIdFromUrl, setArchiveIdFromUrl] = useState<string | null>(null);

  // 直接访问 /result/:id 时，用 URL 参数初始化状态
  useEffect(() => {
    if (id) {
      setArchiveIdFromUrl(id);
    }
  }, [id]);

  if (!id) return null;
  return (
    <ResultView
      archiveId={archiveIdFromUrl || id}
      onBack={onBack}
      onJumpToChat={onJumpToChat}
    />
  );
}

// 内部组件 - 可以使用 useToast
function AppContent() {
  const { showToast } = useToast();
  const [archives, setArchives] = useState<{id: string, name: string}[]>([]);
  const [isIconSettingsOpen, setIsIconSettingsOpen] = useState(false);
  const [, setIconSettings] = useState({
    engine: 'SenseVoice',
    whisper_model: 'small',
    device: 'auto'
  });
  const [currentView, setCurrentView] = useState<'upload' | 'result' | 'queue' | 'chat'>('upload');
  const [selectedArchiveId, setSelectedArchiveId] = useState<string | null>(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [isBackendReady, setIsBackendReady] = useState(false);
  const [, setHasApiKey] = useState(false);
  const [deleteDialog, setDeleteDialog] = useState<{ open: boolean; archiveId: string; archiveName: string }>({
    open: false,
    archiveId: '',
    archiveName: ''
  });

  // ===== 路由钩子 =====
  const { pathname } = useLocation();
  const navigate = useNavigate();

  // URL → state：仅在页面刷新时（mount 时）从 URL 恢复视图状态
  // 后续导航由各 click handler 中的 navigate() 驱动，不再依赖 effect 同步
  useEffect(() => {
    if (pathname === '/queue') {
      setCurrentView('queue');
    } else if (pathname === '/chat') {
      setCurrentView('chat');
    } else if (pathname.startsWith('/result/')) {
      const id = pathname.split('/result/')[1];
      if (id) {
        setSelectedArchiveId(id);
        setCurrentView('result');
      }
    } else {
      setCurrentView('upload');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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

  // 暴露给子组件的全局刷新函数
  const refreshGlobalSettings = async () => {
    try {
      const res = await axios.get('http://localhost:8000/api/settings');
      if (res.data.status === 'success') {
        setIconSettings({
          engine: res.data.data.engine || 'SenseVoice',
          whisper_model: res.data.data.whisper_model || 'small',
          device: res.data.data.device || 'auto'
        });
        setHasApiKey(!!res.data.data.dashscope_api_key);
      }
    } catch (error) {
      console.error("[App] refreshGlobalSettings failed:", error);
    }
  };

  const removeNotification = (id: string, _taskId: string) => {
    setNotifications(prev => prev.filter(n => n.id !== id));
  };

  const handleViewNotification = (archiveId: string, id: string, taskId: string) => {
    setSelectedArchiveId(archiveId);
    setCurrentView('result');
    navigate(`/result/${archiveId}`, { replace: true });
    removeNotification(id, taskId);
  };

  // ========== 步骤一：全局启动拦截与心跳检测 ==========
  useEffect(() => {
    let checkInterval: ReturnType<typeof setInterval>;

    const bootSequence = async () => {
      try {
        await axios.get('http://localhost:8000/');
        // 后端终于活了！
        setIsBackendReady(true);
        clearInterval(checkInterval);
        // 后端就绪后，一次性获取全局数据
        await refreshGlobalSettings();
        fetchArchives();
      } catch (error) {
        // 后端还在启动中，保持沉默
      }
    };

    checkInterval = setInterval(bootSequence, 800);
    bootSequence();

    return () => clearInterval(checkInterval);
  }, []);

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
  // 处理点击归档项
  const handleArchiveClick = (archiveId: string) => {
    setSelectedArchiveId(archiveId);
    setCurrentView('result');
    navigate(`/result/${archiveId}`, { replace: true });
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
    navigate('/', { replace: true });
  };

  // 渲染主内容区
  // ========== 关键拦截：后端未就绪时显示加载动画 ==========
  if (!isBackendReady) {
    return (
      <div className="flex h-screen w-full items-center justify-center bg-[#F9F9F9]">
        <div className="flex flex-col items-center gap-4">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-[#008080]"></div>
          <p className="text-slate-500 font-medium">PodGist 核心引擎启动中...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-screen w-full bg-white text-slate-800 font-sans">
      {/* ================= 左侧导航栏 ================= */}
      <aside className={`border-r border-slate-200 bg-[#F9F9F9] flex flex-col transition-all duration-300 ${sidebarCollapsed ? 'w-16' : 'w-80'}`}>
        {/* Header */}
        <div className="h-12 px-3 border-b border-slate-100 flex items-center justify-between">
          {!sidebarCollapsed && (
            <button
              onClick={() => { navigate('/', { replace: true }); }}
              className="flex items-center gap-2 hover:opacity-80 transition-opacity"
            >
              <Logo size={24} />
              <span className="text-sm font-semibold text-slate-700">PodGist</span>
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
            {/* 主操作按钮 */}
            <div className="p-3">
              <button
                onClick={() => { navigate('/import', { replace: true }); }}
                className="w-full bg-[#00ADA6] hover:bg-[#009A94] text-white py-2 px-4 rounded-lg font-medium transition-all shadow-sm flex items-center justify-center gap-2"
              >
                <IconPlus size={16} /> 导入内容
              </button>
            </div>

            {/* 导航列表 */}
            <nav className="px-3 flex-1">
              <div className="space-y-0.5">
                {/* 资料库 */}
                <button
                  onClick={() => {
                    setCurrentView('upload');
                    navigate('/', { replace: true });
                  }}
                  className={`w-full flex items-center gap-2 px-3 py-2 text-sm rounded-md transition-colors ${
                    pathname === '/' || currentView === 'upload'
                      ? 'bg-slate-200 text-[#00ADA6]'
                      : 'text-slate-600 hover:bg-slate-100 hover:text-[#00ADA6]'
                  }`}
                >
                  <IconLayoutList size={16} className="shrink-0" />
                  <span>资料库</span>
                </button>

                {/* 任务队列 */}
                <button
                  onClick={() => {
                    setCurrentView('queue');
                    navigate('/queue', { replace: true });
                  }}
                  className={`w-full flex items-center gap-2 px-3 py-2 text-sm rounded-md transition-colors ${
                    currentView === 'queue'
                      ? 'bg-slate-200 text-[#00ADA6]'
                      : 'text-slate-600 hover:bg-slate-100 hover:text-[#00ADA6]'
                  }`}
                >
                  <IconLayoutList size={16} className="shrink-0" />
                  <span>任务队列</span>
                </button>

                {/* 智能对话 */}
                <button
                  onClick={() => {
                    setCurrentView('chat');
                    navigate('/chat', { replace: true });
                  }}
                  className={`w-full flex items-center gap-2 px-3 py-2 text-sm rounded-md transition-colors ${
                    currentView === 'chat'
                      ? 'bg-slate-200 text-[#00ADA6]'
                      : 'text-slate-600 hover:bg-slate-100 hover:text-[#00ADA6]'
                  }`}
                >
                  <IconBrain size={16} className="shrink-0" />
                  <span>智能对话</span>
                </button>
              </div>
            </nav>

            {/* 底部设置 */}
            <div className="p-3 border-t border-slate-100">
              <button
                onClick={() => setIsIconSettingsOpen(true)}
                className="w-full flex items-center gap-2 px-3 py-2 text-sm text-slate-500 hover:bg-slate-100 hover:text-[#00ADA6] rounded-md transition-colors"
              >
                <IconSettings size={16} /> 偏好设置
              </button>
            </div>
          </>
        )}

        {/* 收缩状态下的图标按钮 */}
        {sidebarCollapsed && (
          <div className="flex-1 flex flex-col items-center py-4 gap-1">
            <button
              onClick={() => { navigate('/import', { replace: true }); }}
              className="p-2.5 hover:bg-slate-200 rounded-lg transition-colors text-slate-600"
              title="导入内容"
            >
              <IconPlus size={18} />
            </button>
            <button
              onClick={() => { navigate('/', { replace: true }); }}
              className={`p-2.5 rounded-lg transition-colors ${pathname === '/' || currentView === 'upload' ? 'bg-slate-200 text-[#00ADA6]' : 'text-slate-600 hover:bg-slate-200'}`}
              title="资料库"
            >
              <IconLayoutList size={18} />
            </button>
            <button
              onClick={() => { navigate('/queue', { replace: true }); setCurrentView('queue'); }}
              className={`p-2.5 rounded-lg transition-colors ${currentView === 'queue' ? 'bg-slate-200 text-[#00ADA6]' : 'text-slate-600 hover:bg-slate-200'}`}
              title="任务队列"
            >
              <IconLayoutList size={18} />
            </button>
            <button
              onClick={() => { navigate('/chat', { replace: true }); setCurrentView('chat'); }}
              className={`p-2.5 rounded-lg transition-colors ${currentView === 'chat' ? 'bg-slate-200 text-[#00ADA6]' : 'text-slate-600 hover:bg-slate-200'}`}
              title="智能对话"
            >
              <IconBrain size={18} />
            </button>
            <button
              onClick={() => setIsIconSettingsOpen(true)}
              className="p-2.5 hover:bg-slate-200 rounded-lg transition-colors text-slate-600 mt-auto"
              title="偏好设置"
            >
              <IconSettings size={18} />
            </button>
          </div>
        )}
      </aside>

      {/* ================= 右侧主工作区 ================= */}
      <div className="flex-1 flex flex-col min-h-0 max-w-full overflow-hidden">
        <Routes>
          <Route path="/" element={<LibraryPage />} />
          <Route path="/import" element={<ImportPage />} />
          <Route path="/episode/:id" element={<EpisodePage />} />
          {/* /result/:id — 旧版结果页（兼容） */}
          <Route path="/result/:id" element={
            <ResultViewWrapper
              onBack={handleBackToIconUpload}
              onJumpToChat={(sessionId) => {
                setSelectedArchiveId(null);
                setCurrentView('chat');
                sessionStorage.setItem('jump_to_session', sessionId);
              }}
            />
          } />
          <Route path="/result/:id" element={
            <ResultViewWrapper
              onBack={handleBackToIconUpload}
              onJumpToChat={(sessionId) => {
                setSelectedArchiveId(null);
                setCurrentView('chat');
                sessionStorage.setItem('jump_to_session', sessionId);
              }}
            />
          } />
          <Route path="/queue" element={<TaskQueue
            onTaskComplete={addNotification}
            onViewArchive={(archiveId) => {
              setSelectedArchiveId(archiveId);
              setCurrentView('result');
            }}
            onRefreshArchives={fetchArchives}
          />} />
          <Route path="/chat" element={<ChatView onJumpToArchive={(archiveId) => {
            setSelectedArchiveId(archiveId);
            setCurrentView('result');
          }} />} />
        </Routes>
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

      <SettingsModal isOpen={isIconSettingsOpen} onClose={() => setIsIconSettingsOpen(false)} showToast={showToast} onSaveSuccess={refreshGlobalSettings} />

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
