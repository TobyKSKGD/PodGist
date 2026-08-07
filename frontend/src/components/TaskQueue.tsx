import { useState, useEffect, useCallback, useRef } from 'react';
import axios from 'axios';
import { useNavigate } from 'react-router-dom';
import { IconRefresh, IconTrash, IconPlayerPlay, IconPlayerPause, IconAlertCircle, IconCircleCheck, IconClock, IconLoader2, IconX, IconChevronDown, IconChevronUp, IconFileDescription, IconExternalLink } from '@tabler/icons-react';
import { useToast } from './Toast';
import ConfirmDialog from './ConfirmDialog';
import { archiveIdFromResultPath } from '../utils/archivePath';

interface Task {
  id: string;
  source: string;
  name: string;
  type: string;
  status: 'PENDING' | 'PROCESSING' | 'CANCEL_REQUESTED' | 'COMPLETED' | 'FAILED';
  engine: string;
  progress_status: string;
  create_time: string;
  complete_time: string;
  result_path: string;
  error_msg: string;
}

interface QueueStats {
  pending: number;
  processing: number;
  cancelling: number;
  completed: number;
  failed: number;
  worker_running: boolean;
  paused: boolean;
}

const api = axios.create({ baseURL: 'http://localhost:8000' });

interface TaskQueueProps {
  onTaskComplete?: (taskName: string, archiveId: string, taskId: string) => void;
  onViewArchive?: (archiveId: string) => void;
  onRefreshArchives?: () => void;
}

export default function TaskQueue({
  onTaskComplete,
  onViewArchive,
  onRefreshArchives,
}: TaskQueueProps) {
  const { showToast } = useToast();
  const navigate = useNavigate();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [stats, setStats] = useState<QueueStats | null>(null);
  const [loading, setLoading] = useState(false);
  const [activeTab, setActiveTab] = useState<'all' | 'pending' | 'processing' | 'completed' | 'failed'>('all');
  const [expandedTasks, setExpandedTasks] = useState<Record<string, string>>({});
  const [previewLoading, setPreviewLoading] = useState<Record<string, boolean>>({});
  const [deleteTarget, setDeleteTarget] = useState<Task | null>(null);

  // 从 localStorage 加载已通知的任务 ID，避免重复通知
  const loadNotifiedIds = (): Set<string> => {
    try {
      const stored = localStorage.getItem('podgist_notified_tasks');
      return stored ? new Set(JSON.parse(stored)) : new Set();
    } catch { return new Set(); }
  };
  const notifiedCompletions = useRef<Set<string>>(loadNotifiedIds());

  const fetchTasks = useCallback(async () => {
    try {
      const res = await api.get('/api/tasks');
      if (res.data.status === 'success') {
        setTasks(res.data.tasks);
      }
    } catch (error) {
      console.error('获取任务列表失败:', error);
    }
  }, []);

  const fetchStats = useCallback(async () => {
    try {
      const res = await api.get('/api/tasks/stats');
      if (res.data.status === 'success') {
        setStats(res.data.data);
      }
    } catch (error) {
      console.error('获取队列状态失败:', error);
    }
  }, []);

  const toggleTaskPreview = async (task: Task) => {
    // 如果已经展开，则收起
    if (expandedTasks[task.id]) {
      setExpandedTasks(prev => {
        const next = { ...prev };
        delete next[task.id];
        return next;
      });
      return;
    }

    // 如果没有 result_path，直接返回
    if (!task.result_path) return;

    // 标记为加载中
    setPreviewLoading(prev => ({ ...prev, [task.id]: true }));

    try {
      // 从归档路径提取 archive_id（result_path 是完整路径如 /path/to/archives/xxx）
      const archiveId = archiveIdFromResultPath(task.result_path);
      if (!archiveId) return;
      const res = await api.get(`/api/archives/${encodeURIComponent(archiveId)}`);
      if (res.data.status === 'success') {
        // 提取摘要的前 200 个字符作为预览
        const summary = res.data.data.summary || '';
        const preview = summary.length > 300 ? summary.substring(0, 300) + '...' : summary;
        setExpandedTasks(prev => ({ ...prev, [task.id]: preview }));
      }
    } catch (error) {
      console.error('获取任务预览失败:', error);
    } finally {
      setPreviewLoading(prev => ({ ...prev, [task.id]: false }));
    }
  };

  useEffect(() => {
    fetchTasks();
    fetchStats();
    // 定时刷新
    const interval = setInterval(() => {
      fetchTasks();
      fetchStats();
    }, 3000);
    return () => clearInterval(interval);
  }, [fetchTasks, fetchStats]);

  // 任务完成时触发通知（移除 break，确保每轮通知所有新完成的任务）
  useEffect(() => {
    if (!onTaskComplete) return;
    for (const task of tasks) {
      if (
        task.status === 'COMPLETED' &&
        task.result_path &&
        !notifiedCompletions.current.has(task.id)
      ) {
        notifiedCompletions.current.add(task.id);
        const archiveId = archiveIdFromResultPath(task.result_path);
        if (archiveId) {
          onTaskComplete(task.name || '未命名任务', archiveId, task.id);
          onRefreshArchives?.();
        }
      }
    }
  }, [tasks, onTaskComplete, onRefreshArchives]);

  const handleIconPlayerPauseResume = async () => {
    if (!stats) return;
    try {
      if (stats.paused) {
        await api.post('/api/tasks/resume');
        showToast('success', '队列已恢复');
      } else {
        await api.post('/api/tasks/pause');
        showToast('info', '已暂停领取新任务；当前任务会继续执行');
      }
      fetchStats();
    } catch {
      showToast('error', '操作失败');
    }
  };

  const handleRetryFailed = async () => {
    setLoading(true);
    try {
      const res = await api.post('/api/tasks/retry-failed');
      showToast('success', res.data.message);
      fetchTasks();
      fetchStats();
    } catch (error: unknown) {
      const detail = axios.isAxiosError<{ detail?: string }>(error)
        ? error.response?.data?.detail
        : undefined;
      showToast('error', detail || '重试失败');
    } finally {
      setLoading(false);
    }
  };

  const handleClearCompleted = async () => {
    try {
      const res = await api.post('/api/tasks/clear-completed');
      showToast('success', res.data.message);
      fetchTasks();
      fetchStats();
    } catch {
      showToast('error', '清空失败');
    }
  };

  const handleDeleteTask = async (task: Task) => {
    try {
      const res = await api.delete(`/api/tasks/${task.id}`);
      const cancelling = res.data.action === 'cancelling';
      showToast(cancelling ? 'info' : 'success', res.data.message || (cancelling ? '正在取消任务' : '任务记录已删除'));
      fetchTasks();
      fetchStats();
    } catch {
      showToast('error', '删除失败');
    }
  };

  const handleRetryLLM = async (taskId: string) => {
    try {
      const res = await api.post(`/api/tasks/${taskId}/retry-llm`);
      showToast('success', res.data.message);
      fetchTasks();
      fetchStats();
      onRefreshArchives?.();
    } catch (error: unknown) {
      const detail = axios.isAxiosError<{ detail?: string }>(error)
        ? error.response?.data?.detail
        : undefined;
      showToast('error', detail || '重试失败');
    }
  };

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'PENDING':
        return <IconClock size={16} className="text-[#0891B2]" />;
      case 'PROCESSING':
        return <IconLoader2 size={16} className="text-[#00ADA6] animate-spin" />;
      case 'CANCEL_REQUESTED':
        return <IconLoader2 size={16} className="text-[#E11D48] animate-spin" />;
      case 'COMPLETED':
        return <IconCircleCheck size={16} className="text-[#10B981]" />;
      case 'FAILED':
        return <IconAlertCircle size={16} className="text-[#E11D48]" />;
      default:
        return null;
    }
  };

  const getStatusBadge = (status: string) => {
    const classes = {
      PENDING: 'bg-[#E1F5FE] text-[#009A94]',
      PROCESSING: 'bg-[#D1FAF5] text-[#00ADA6]',
      CANCEL_REQUESTED: 'bg-[#FFF1F3] text-[#E11D48]',
      COMPLETED: 'bg-[#D1FAF5] text-[#10B981]',
      FAILED: 'bg-[#FFF1F3] text-[#E11D48]'
    };
    const labels = {
      PENDING: '等待中',
      PROCESSING: '处理中',
      CANCEL_REQUESTED: '正在取消',
      COMPLETED: '已完成',
      FAILED: '失败'
    };
    return (
      <span className={`px-2 py-0.5 rounded text-xs font-medium ${classes[status as keyof typeof classes]}`}>
        {labels[status as keyof typeof labels]}
      </span>
    );
  };

  const getTypeBadge = (type: string, source = '') => {
    const typeMap: Record<string, { label: string; className: string }> = {
      xiaoyuzhou: { label: '播客', className: 'bg-[#E1F5FE] text-[#009A94]' },
      bilibili: { label: '视频', className: 'bg-[#E1F5FE] text-[#009A94]' },
      netease: { label: '网易云', className: 'bg-[#E1F5FE] text-[#009A94]' },
      ximalaya: { label: '喜马拉雅', className: 'bg-[#E1F5FE] text-[#009A94]' },
      applepodcasts: { label: '苹果播客', className: 'bg-[#E1F5FE] text-[#009A94]' },
      apple: { label: '苹果播客', className: 'bg-[#E1F5FE] text-[#009A94]' },
      local: { label: '本地', className: 'bg-[#E1F5FE] text-[#009A94]' },
    };
    let info = typeMap[type];
    if (type === 'rss') {
      const normalizedSource = source.toLowerCase();
      if (normalizedSource.includes('ximalaya.com') || normalizedSource.includes('xmcdn.com') || normalizedSource.includes('xima.tv')) {
        info = { label: '喜马拉雅', className: 'bg-[#E1F5FE] text-[#009A94]' };
      } else if (normalizedSource.includes('xiaoyuzhoufm.com') || normalizedSource.includes('xyzcdn.net') || normalizedSource.includes('xyzfm.space')) {
        info = { label: '小宇宙', className: 'bg-[#E1F5FE] text-[#009A94]' };
      } else if (normalizedSource.includes('music.163.com') || normalizedSource.includes('163cn.tv')) {
        info = { label: '网易云', className: 'bg-[#E1F5FE] text-[#009A94]' };
      } else {
        info = { label: '播客 RSS', className: 'bg-[#E1F5FE] text-[#009A94]' };
      }
    }
    info ||= { label: '未知', className: 'bg-slate-100 text-slate-500' };
    return (
      <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${info.className}`}>
        {info.label}
      </span>
    );
  };

  const filteredTasks = tasks.filter(task => {
    if (activeTab === 'all') return true;
    if (activeTab === 'processing') {
      return task.status === 'PROCESSING' || task.status === 'CANCEL_REQUESTED';
    }
    return task.status === activeTab.toUpperCase();
  });

  const formatTime = (isoString: string) => {
    if (!isoString) return '-';
    const date = new Date(isoString);
    return date.toLocaleString('zh-CN');
  };

  return (
    <div className="flex-1 flex flex-col min-h-0 max-w-full overflow-hidden">
      {/* 头部统计 */}
      <div className="bg-white border-b border-slate-200 p-4">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-bold text-slate-800">任务队列</h2>
          <div className="flex gap-2 items-center">
            <button
              onClick={handleIconPlayerPauseResume}
              className={`px-3 py-1.5 rounded text-sm font-medium flex items-center gap-1.5 transition-colors ${
                stats?.paused
                  ? 'bg-[#10B981] text-white hover:bg-[#0891B2]'
                  : 'bg-[#00ADA6] text-white hover:bg-[#009A94]'
              }`}
            >
              {stats?.paused ? <IconPlayerPlay size={14} /> : <IconPlayerPause size={14} />}
              {stats?.paused ? '恢复队列' : '暂停新任务'}
            </button>
            <button
              onClick={() => { fetchTasks(); fetchStats(); }}
              className="p-1.5 rounded hover:bg-slate-100 text-slate-600 transition-colors"
            >
              <IconRefresh size={16} />
            </button>
          </div>
        </div>

        {/* 统计卡片 */}
        <div className="grid grid-cols-4 gap-3">
          <div className="bg-[#E1F5FE] rounded-lg p-3 border border-[#0891B2]">
            <div className="text-2xl font-bold text-[#009A94] w-8">{stats?.pending || 0}</div>
            <div className="text-xs text-[#009A94]">等待中</div>
          </div>
          <div className="bg-[#E1F5FE] rounded-lg p-3 border border-[#0891B2]">
            <div className="text-2xl font-bold text-[#009A94] w-8">{(stats?.processing || 0) + (stats?.cancelling || 0)}</div>
            <div className="text-xs text-[#009A94]">处理中</div>
          </div>
          <div className="bg-[#E1F5FE] rounded-lg p-3 border border-[#0891B2]">
            <div className="text-2xl font-bold text-[#009A94] w-8">{stats?.completed || 0}</div>
            <div className="text-xs text-[#009A94]">已完成</div>
          </div>
          <div className="bg-[#E1F5FE] rounded-lg p-3 border border-[#0891B2]">
            <div className="text-2xl font-bold text-[#009A94] w-8">{stats?.failed || 0}</div>
            <div className="text-xs text-[#009A94]">失败</div>
          </div>
        </div>

        {/* Worker 状态 */}
        <div className="mt-3 flex items-center gap-2 text-sm">
          <span className={`w-2 h-2 rounded-full ${stats?.worker_running ? 'bg-[#10B981]' : 'bg-slate-300'}`}></span>
          <span className="text-slate-600">
            Worker {stats?.worker_running ? '运行中' : '未运行'}
            {stats?.paused && '（已暂停领取新任务）'}
          </span>
        </div>
      </div>

      {/* Tab 标签 */}
      <div className="bg-white border-b border-slate-200 px-4 flex justify-between items-center">
        <div className="flex gap-1">
          {(['all', 'pending', 'processing', 'completed', 'failed'] as const).map(tab => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`px-3 py-2 text-sm font-medium border-b-2 transition-colors min-w-[60px] text-center ${
                activeTab === tab
                  ? 'border-[#00ADA6] text-[#00ADA6]'
                  : 'border-transparent text-slate-500 hover:text-slate-700'
              }`}
            >
              {tab === 'all' ? '全部' : tab === 'pending' ? '等待' : tab === 'processing' ? '处理中' : tab === 'completed' ? '完成' : '失败'}
              {tab !== 'all' && (
                <span className="ml-1.5 text-xs">
                  ({tab === 'pending' ? stats?.pending : tab === 'processing' ? (stats?.processing || 0) + (stats?.cancelling || 0) : tab === 'completed' ? stats?.completed : stats?.failed})
                </span>
              )}
            </button>
          ))}
        </div>
        <div className="flex gap-2">
          {(stats?.failed || 0) > 0 && (
            <button
              onClick={handleRetryFailed}
              disabled={loading}
              className="px-3 py-1.5 bg-[#E11D48] text-white rounded text-sm font-medium hover:bg-[#009A94] disabled:opacity-50 flex items-center gap-1.5"
            >
              <IconRefresh size={14} className={loading ? 'animate-spin' : ''} />
              重试失败
            </button>
          )}
          {(stats?.completed || 0) > 0 && (
            <button
              onClick={handleClearCompleted}
              className="px-3 py-1.5 text-slate-600 hover:text-slate-800 text-sm font-medium flex items-center gap-1.5"
            >
              <IconTrash size={14} />
              清空已完成
            </button>
          )}
        </div>
      </div>

      {/* 任务列表 */}
      <div className="flex-1 overflow-y-auto min-w-0">
        {filteredTasks.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-slate-400">
            <IconClock size={48} strokeWidth={1.5} />
            <p className="mt-3 text-sm">暂无任务</p>
          </div>
        ) : (
          <div className="divide-y divide-slate-100 min-w-0">
            {[...filteredTasks].reverse().map(task => (
              <div key={task.id} className="p-4 hover:bg-slate-50 transition-colors min-w-0">
                <div className="flex items-start justify-between gap-3 min-w-0">
                  <div className="flex items-start gap-3 min-w-0 flex-1">
                    <div className="mt-0.5 shrink-0">{getStatusIcon(task.status)}</div>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2 mb-1 min-w-0">
                        <span className="font-medium text-slate-800 truncate min-w-0">
                          {task.name || '未命名任务'}
                        </span>
                        {getStatusBadge(task.status)}
                        {getTypeBadge(task.type, task.source)}
                      </div>
                      <div className="text-xs text-slate-500 mb-1 truncate max-w-full">
                        {task.source}
                      </div>
                      {task.progress_status && (
                        <div className="text-xs text-slate-400 mb-1">
                          {task.progress_status}
                        </div>
                      )}
                      {task.error_msg && (
                        <div className="text-xs text-[#E11D48] mt-1 line-clamp-2">
                          {task.error_msg.split('\n')[0]}
                        </div>
                      )}
                      <div className="flex items-center gap-3 mt-1 flex-wrap">
                        <span className="text-xs text-slate-400">
                          创建: {formatTime(task.create_time)}
                          {task.complete_time && ` | 完成: ${formatTime(task.complete_time)}`}
                        </span>
                        {/* 展开预览按钮（仅已完成且有结果的） */}
                        {task.status === 'COMPLETED' && task.result_path && (
                          <>
                            <button
                              onClick={() => toggleTaskPreview(task)}
                              disabled={previewLoading[task.id]}
                              className="flex items-center gap-1 text-xs text-[#00ADA6] hover:text-[#009A94] transition-colors"
                            >
                              {previewLoading[task.id] ? (
                                <IconLoader2 size={12} className="animate-spin" />
                              ) : expandedTasks[task.id] ? (
                                <><IconChevronUp size={12} />收起</>
                              ) : (
                                <><IconChevronDown size={12} />预览</>
                              )}
                            </button>
                            <button
                              onClick={() => {
                                const archiveId = archiveIdFromResultPath(task.result_path);
                                if (archiveId) {
                                  navigate(`/episode/${archiveId}`);
                                  if (onViewArchive) onViewArchive(archiveId);
                                }
                              }}
                              className="flex items-center gap-1 text-xs text-[#10B981] hover:text-[#0891B2] transition-colors"
                            >
                              <IconExternalLink size={12} />
                              查看报告
                            </button>
                          </>
                        )}
                      </div>
                      {/* 展开的预览内容 */}
                      {expandedTasks[task.id] && (
                        <div className="mt-2 p-3 bg-slate-50 rounded-lg border border-slate-100">
                          <div className="flex items-center gap-1 mb-2 text-xs text-slate-500">
                            <IconFileDescription size={12} />
                            <span>摘要预览</span>
                          </div>
                          <p className="text-xs text-slate-600 whitespace-pre-wrap line-clamp-6">
                            {expandedTasks[task.id]}
                          </p>
                        </div>
                      )}
                    </div>
                  </div>
                  {task.status === 'FAILED' && task.error_msg?.includes('[可重试]') && (
                    <button
                      onClick={() => handleRetryLLM(task.id)}
                      className="p-1.5 text-[#E11D48] hover:text-[#009A94] hover:bg-[#FFF1F3] rounded transition-colors shrink-0"
                      title="重试生成摘要"
                    >
                      <IconRefresh size={16} />
                    </button>
                  )}
                  <button
                    onClick={() => setDeleteTarget(task)}
                    disabled={task.status === 'CANCEL_REQUESTED'}
                    className="p-1.5 text-slate-400 hover:text-[#E11D48] hover:bg-[#FFF1F3] rounded transition-colors shrink-0"
                    title={task.status === 'PENDING' || task.status === 'PROCESSING' ? '取消任务' : '删除任务记录'}
                  >
                    {task.status === 'CANCEL_REQUESTED'
                      ? <IconLoader2 size={16} className="animate-spin" />
                      : <IconX size={16} />}
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
      <ConfirmDialog
        isOpen={Boolean(deleteTarget)}
        title={deleteTarget?.status === 'PENDING' || deleteTarget?.status === 'PROCESSING' ? '取消这个任务？' : '删除任务记录？'}
        message={deleteTarget?.status === 'PENDING' || deleteTarget?.status === 'PROCESSING'
          ? '系统会停止后续处理，并清理该任务的临时音频和未完成归档。已经提交给云端的单次请求可能需要等待返回后才能完全停止。'
          : '这里只删除队列中的任务记录，不会删除已经生成的归档。'}
        confirmText={deleteTarget?.status === 'PENDING' || deleteTarget?.status === 'PROCESSING' ? '取消任务' : '删除记录'}
        onConfirm={() => {
          const task = deleteTarget;
          setDeleteTarget(null);
          if (task) void handleDeleteTask(task);
        }}
        onCancel={() => setDeleteTarget(null)}
        danger
      />
    </div>
  );
}
