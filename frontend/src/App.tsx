import { Suspense, lazy, useState, useEffect, useRef, useCallback } from 'react';
import { Routes, Route, useLocation, useNavigate, useParams } from 'react-router-dom';
import axios from 'axios';
import { IconSettings, IconPlus, IconLayoutList, IconListCheck, IconChevronLeft, IconChevronRight, IconBell, IconX, IconCircleCheck, IconBrain, IconWorldSearch } from '@tabler/icons-react';
import Logo from './components/Logo';
import { ToastProvider, useToast } from './components/Toast';
import ConfirmDialog from './components/ConfirmDialog';
import { archiveIdFromResultPath } from './utils/archivePath';

// 页面级功能只在用户真正进入时下载，避免首次打开应用加载播放器、对话和任务队列的全部代码。
const LibraryPage = lazy(() => import('./pages/LibraryPage'));
const ImportPage = lazy(() => import('./pages/ImportPage'));
const EpisodePage = lazy(() => import('./pages/EpisodePage'));
const SettingsModal = lazy(() => import('./components/SettingsModal'));
const ResultView = lazy(() => import('./components/ResultView'));
const TaskQueue = lazy(() => import('./components/TaskQueue'));
const ChatView = lazy(() => import('./components/ChatView'));
const DiscoveryPage = lazy(() => import('./pages/DiscoveryPage'));

// 配置 axios 基础路径，指向你的 FastAPI 后端
const api = axios.create({ baseURL: 'http://localhost:8000' });

function PageLoading() {
  return (
    <div className="flex flex-1 items-center justify-center bg-white">
      <div className="h-8 w-8 animate-spin rounded-full border-2 border-slate-200 border-t-[#00ADA6]" />
    </div>
  );
}

// ===== 路由子组件 =====
// 直接访问 /result/:id 时，从 URL 读取 archiveId，避免依赖 AppContent 状态初始渲染延迟
function ResultViewWrapper({ onBack, onJumpToChat }: {
  onBack: () => void;
  onJumpToChat: (sessionId: string) => void;
}) {
  const { id } = useParams<{ id: string }>();

  if (!id) return null;
  return (
    <ResultView
      archiveId={id}
      onBack={onBack}
      onJumpToChat={onJumpToChat}
    />
  );
}

// 内部组件 - 可以使用 useToast
function AppContent() {
  const { showToast } = useToast();
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
  const [activeQueueCount, setActiveQueueCount] = useState(0);
  const [, setHasApiKey] = useState(false);
  const [chatSourceNavigation, setChatSourceNavigation] = useState({
    seekToTimestamp: true,
    autoPlay: false,
  });
  const [deleteDialog, setDeleteDialog] = useState<{ open: boolean; archiveId: string; archiveName: string }>({
    open: false,
    archiveId: '',
    archiveName: ''
  });

  // ===== 路由钩子 =====
  const { pathname } = useLocation();
  const navigate = useNavigate();

  // URL → state：每次 pathname 变化时同步 currentView
  useEffect(() => {
    let nextView: 'upload' | 'result' | 'queue' | 'chat';
    if (pathname === '/queue') {
      nextView = 'queue';
    } else if (pathname === '/chat') {
      nextView = 'chat';
    } else if (pathname.startsWith('/result/') || pathname.startsWith('/episode/')) {
      nextView = 'result';
    } else {
      nextView = 'upload';
    }
    // 路由通知在本次提交后同步，避免 effect 内同步触发级联渲染。
    queueMicrotask(() => setCurrentView(nextView));
  }, [pathname]);

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

  const saveNotifiedTaskIds = useCallback((ids: Set<string>) => {
    try {
      localStorage.setItem('podgist_notified_tasks', JSON.stringify([...ids]));
    } catch {
      // localStorage 不可用时不影响通知功能。
    }
  }, []);

  const addNotification = useCallback((taskName: string, archiveId: string, taskId: string) => {
    // 避免重复通知同一任务
    if (notifiedTaskIds.current.has(taskId)) return;
    notifiedTaskIds.current.add(taskId);
    saveNotifiedTaskIds(notifiedTaskIds.current);
    const id = `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
    setNotifications(prev => [{ id, taskName, archiveId, taskId }, ...prev]);
    // 显示顶部 toast 提示，并刷新侧边栏归档列表
    showToast('success', `任务已完成：${taskName}`);
  }, [saveNotifiedTaskIds, showToast]);

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
        setChatSourceNavigation({
          seekToTimestamp: !!res.data.data.chat_source_seek_to_timestamp,
          autoPlay: !!res.data.data.chat_source_autoplay,
        });
      }
    } catch (error) {
      console.error("[App] refreshGlobalSettings failed:", error);
    }
  };

  const removeNotification = (id: string) => {
    setNotifications(prev => prev.filter(n => n.id !== id));
  };

  const handleViewNotification = (archiveId: string, id: string) => {
    setSelectedArchiveId(archiveId);
    setCurrentView('result');
    navigate(`/episode/${archiveId}`, { replace: true });
    removeNotification(id);
  };

  // ========== 步骤一：全局启动拦截与心跳检测 ==========
  useEffect(() => {
    const bootSequence = async () => {
      try {
        await axios.get('http://localhost:8000/');
        // 后端终于活了！
        setIsBackendReady(true);
        clearInterval(checkInterval);
        // 后端就绪后，一次性获取全局数据
        await refreshGlobalSettings();
      } catch {
        // 后端还在启动中，保持沉默
      }
    };

    const checkInterval = setInterval(bootSequence, 800);
    void bootSequence();

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
              const archiveId = archiveIdFromResultPath(task.result_path);
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
  }, [addNotification]);

  // 侧栏任务角标：等待中 + 处理中。独立于任务队列页面，保证全局可见。
  useEffect(() => {
    if (!isBackendReady) return;
    const refreshQueueCount = async () => {
      try {
        const res = await api.get('/api/tasks/stats');
        if (res.data.status === 'success') {
          const next = Number(res.data.data.pending || 0)
            + Number(res.data.data.processing || 0)
            + Number(res.data.data.cancelling || 0);
          setActiveQueueCount(current => current === next ? current : next);
        }
      } catch {
        // 后端短暂重启时保留上一次数字，避免角标闪烁。
      }
    };
    void refreshQueueCount();
    const interval = window.setInterval(refreshQueueCount, 3000);
    return () => window.clearInterval(interval);
  }, [isBackendReady]);

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
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-[#00ADA6]"></div>
          <p className="text-slate-500 font-medium">PodGist 核心引擎启动中...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-screen w-full bg-white text-slate-800 font-sans">
      {/* ================= 左侧导航栏 ================= */}
      <aside className={`border-r border-slate-200 bg-[#F9F9F9] flex flex-col transition-all duration-300 ${sidebarCollapsed ? 'w-16' : 'w-56'}`}>
        {/* Header */}
        <div className="h-14 px-3 border-b border-slate-100 flex items-center relative">
          {sidebarCollapsed ? (
            /* 收起状态：整行是展开入口，hover 时 logo 变为展开图标 */
            <button
              onClick={() => setSidebarCollapsed(false)}
              className="w-full h-full flex items-center justify-center group"
              title="展开侧边栏"
            >
              {/* 默认：logo；hover：展开箭头 */}
              <span className="transition-opacity duration-200 group-hover:opacity-0">
                <Logo size={28} />
              </span>
              <span className="absolute inset-0 flex items-center justify-center transition-opacity duration-200 opacity-0 group-hover:opacity-100">
                <IconChevronRight size={18} className="text-slate-400" />
              </span>
            </button>
          ) : (
            /* 展开状态：logo 回首页 + 右上角收起按钮 */
            <>
              <button
                onClick={() => { setCurrentView('upload'); navigate('/', { replace: true }); }}
                className="flex items-center gap-2 hover:opacity-80 transition-opacity"
              >
                <Logo size={28} />
                <span className="text-base font-bold text-slate-700 tracking-tight">PodGist</span>
              </button>
              <button
                onClick={() => setSidebarCollapsed(true)}
                className="ml-auto p-1.5 hover:bg-slate-200 rounded-md transition-colors text-slate-400 hover:text-slate-600"
                title="收起侧边栏"
              >
                <IconChevronLeft size={16} />
              </button>
            </>
          )}
        </div>

        {!sidebarCollapsed && (
          <>
            {/* 主操作按钮 */}
            <div className="px-3 pt-4 pb-2">
              <button
                onClick={() => navigate('/import', { replace: true })}
                className="w-full bg-[#00ADA6] hover:bg-[#009A94] text-white py-2.5 px-4 rounded-lg font-medium transition-all shadow-sm flex items-center justify-center gap-2 text-sm"
              >
                <IconPlus size={16} /> 导入内容
              </button>
            </div>

            {/* 导航列表 */}
            <nav className="px-3 flex-1 pt-1">
              <div className="space-y-0.5">
                {/* 首页 */}
                <button
                  onClick={() => navigate('/', { replace: true }) }
                  className={`w-full flex items-center gap-2.5 px-3 py-2.5 text-sm rounded-md transition-colors ${
                    pathname === '/'
                      ? 'bg-[#00ADA6]/10 text-[#00ADA6]'
                      : 'text-slate-500 hover:bg-slate-100 hover:text-[#00ADA6]'
                  }`}
                >
                  <IconLayoutList size={18} className="shrink-0" />
                  <span className="font-medium">首页</span>
                </button>

                {/* 内容获取 */}
                <button
                  onClick={() => navigate('/discover', { replace: true })}
                  className={`w-full flex items-center gap-2.5 px-3 py-2.5 text-sm rounded-md transition-colors ${
                    pathname === '/discover'
                      ? 'bg-[#00ADA6]/10 text-[#00ADA6]'
                      : 'text-slate-500 hover:bg-slate-100 hover:text-[#00ADA6]'
                  }`}
                >
                  <IconWorldSearch size={18} className="shrink-0" />
                  <span className="font-medium">内容获取</span>
                </button>

                {/* 智能对话 */}
                <button
                  onClick={() => {
                    setCurrentView('chat');
                    navigate('/chat', { replace: true });
                  }}
                  className={`w-full flex items-center gap-2.5 px-3 py-2.5 text-sm rounded-md transition-colors ${
                    currentView === 'chat'
                      ? 'bg-[#00ADA6]/10 text-[#00ADA6]'
                      : 'text-slate-500 hover:bg-slate-100 hover:text-[#00ADA6]'
                  }`}
                >
                  <IconBrain size={18} className="shrink-0" />
                  <span className="font-medium">智能对话</span>
                </button>

                {/* 任务队列 */}
                <button
                  onClick={() => {
                    setCurrentView('queue');
                    navigate('/queue', { replace: true });
                  }}
                  className={`w-full flex items-center gap-2.5 px-3 py-2.5 text-sm rounded-md transition-colors ${
                    currentView === 'queue'
                      ? 'bg-[#00ADA6]/10 text-[#00ADA6]'
                      : 'text-slate-500 hover:bg-slate-100 hover:text-[#00ADA6]'
                  }`}
                >
                  <IconListCheck size={18} className="shrink-0" />
                  <span className="font-medium">任务队列</span>
                  {activeQueueCount > 0 && <span className="ml-auto min-w-5 rounded-full bg-[#00ADA6] px-1.5 py-0.5 text-center text-[11px] font-semibold leading-4 text-white">{activeQueueCount > 99 ? '99+' : activeQueueCount}</span>}
                </button>
              </div>
            </nav>

            {/* 底部设置 */}
            <div className="px-3 pb-4 pt-2 border-t border-slate-100">
              <button
                onClick={() => setIsIconSettingsOpen(true)}
                className="w-full flex items-center gap-2.5 px-3 py-2.5 text-sm text-slate-400 hover:bg-slate-100 hover:text-[#00ADA6] rounded-md transition-colors"
              >
                <IconSettings size={18} /> <span className="font-medium">偏好设置</span>
              </button>
            </div>
          </>
        )}

        {/* 收缩状态下的图标按钮 — 展开入口已移至顶部 header */}
        {sidebarCollapsed && (
          <div className="flex flex-col items-center py-3 gap-1">
            <button
              onClick={() => { navigate('/discover', { replace: true }); }}
              className={`p-2.5 rounded-lg transition-colors ${pathname === '/discover' ? 'bg-[#00ADA6]/10 text-[#00ADA6]' : 'text-slate-400 hover:bg-slate-200 hover:text-[#00ADA6]'}`}
              title="内容获取"
            >
              <IconWorldSearch size={18} />
            </button>
            <button
              onClick={() => { navigate('/import', { replace: true }); }}
              className="p-2.5 hover:bg-slate-200 rounded-lg transition-colors text-slate-500"
              title="导入内容"
            >
              <IconPlus size={18} />
            </button>
            <button
              onClick={() => { navigate('/', { replace: true }); }}
              className={`p-2.5 rounded-lg transition-colors ${pathname === '/' ? 'bg-[#00ADA6]/10 text-[#00ADA6]' : 'text-slate-400 hover:bg-slate-200 hover:text-[#00ADA6]'}`}
              title="首页"
            >
              <IconLayoutList size={18} />
            </button>
            <button
              onClick={() => { navigate('/chat', { replace: true }); setCurrentView('chat'); }}
              className={`p-2.5 rounded-lg transition-colors ${currentView === 'chat' ? 'bg-[#00ADA6]/10 text-[#00ADA6]' : 'text-slate-400 hover:bg-slate-200 hover:text-[#00ADA6]'}`}
              title="智能对话"
            >
              <IconBrain size={18} />
            </button>
            <button
              onClick={() => { navigate('/queue', { replace: true }); setCurrentView('queue'); }}
              className={`relative p-2.5 rounded-lg transition-colors ${currentView === 'queue' ? 'bg-[#00ADA6]/10 text-[#00ADA6]' : 'text-slate-400 hover:bg-slate-200 hover:text-[#00ADA6]'}`}
              title={`任务队列${activeQueueCount > 0 ? `（${activeQueueCount}）` : ''}`}
            >
              <IconListCheck size={18} />
              {activeQueueCount > 0 && <span className="absolute -right-1 -top-1 min-w-4 rounded-full bg-[#00ADA6] px-1 text-center text-[10px] font-semibold leading-4 text-white">{activeQueueCount > 99 ? '99+' : activeQueueCount}</span>}
            </button>
            <button
              onClick={() => setIsIconSettingsOpen(true)}
              className="p-2.5 hover:bg-slate-200 rounded-lg transition-colors text-slate-400 mt-auto"
              title="偏好设置"
            >
              <IconSettings size={18} />
            </button>
          </div>
        )}
      </aside>

      {/* ================= 右侧主工作区 ================= */}
      <div className="flex-1 flex flex-col min-h-0 max-w-full overflow-hidden">
        <Suspense fallback={<PageLoading />}>
          <Routes>
            <Route path="/" element={<LibraryPage />} />
            <Route path="/import" element={<ImportPage />} />
            <Route path="/discover" element={<DiscoveryPage />} />
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
            <Route path="/queue" element={<TaskQueue
              onTaskComplete={addNotification}
              onViewArchive={(archiveId) => {
                setSelectedArchiveId(archiveId);
                setCurrentView('result');
              }}
            />} />
            <Route path="/chat" element={<ChatView onJumpToArchive={({ archiveId, timestamp }) => {
              setSelectedArchiveId(archiveId);
              setCurrentView('result');
              const params = new URLSearchParams();
              if (chatSourceNavigation.seekToTimestamp && timestamp) {
                params.set('t', timestamp);
                if (chatSourceNavigation.autoPlay) params.set('autoplay', '1');
              }
              const query = params.toString();
              navigate(`/episode/${archiveId}${query ? `?${query}` : ''}`);
            }} />} />
          </Routes>
        </Suspense>
      </div>

      {/* 全局通知铃铛（仅在非任务队列/非智能对话视图显示） */}
      {currentView !== 'queue' && currentView !== 'chat' && (
        <div className="fixed top-4 right-4 z-50">
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

          {/* 通知下拉菜单（向上展开） */}
          {showIconBellMenu && (
            <div ref={bellMenuRef} className="absolute top-full right-0 mt-2 w-80 bg-white border border-slate-200 rounded-lg shadow-lg overflow-hidden">
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
                            onClick={() => removeNotification(n.id)}
                            className="opacity-0 group-hover:opacity-100 p-1 text-slate-400 hover:text-slate-600 transition-colors"
                            title="关闭"
                          >
                            <IconX size={14} />
                          </button>
                          <button
                            onClick={() => handleViewNotification(n.archiveId, n.id)}
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

      {isIconSettingsOpen && (
        <Suspense fallback={null}>
          <SettingsModal isOpen onClose={() => setIsIconSettingsOpen(false)} showToast={showToast} onSaveSuccess={refreshGlobalSettings} />
        </Suspense>
      )}

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
