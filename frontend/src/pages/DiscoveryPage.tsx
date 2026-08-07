import { useEffect, useMemo, useState } from 'react';
import axios from 'axios';
import {
  IconAlertCircle,
  IconCheck,
  IconClock,
  IconLoader2,
  IconPlus,
  IconRefresh,
  IconSearch,
  IconTimelineEvent,
  IconWorldSearch,
} from '@tabler/icons-react';
import { useToast } from '../components/Toast';

const api = axios.create({ baseURL: 'http://localhost:8000' });

interface EpisodeSource {
  provider: string;
  label: string;
  url: string;
  role: 'audio' | 'feed' | 'catalog';
  recommended: boolean;
}

interface DiscoveredEpisode {
  id: string;
  title: string;
  show_title: string;
  description: string;
  published_at: string;
  duration_seconds: number;
  cover_url: string;
  audio_url: string;
  recommended_provider: string;
  sources: EpisodeSource[];
}

interface ProviderStatus {
  id: string;
  label: string;
  status: 'available' | 'not_configured' | 'unavailable';
}

interface QueueTask {
  id: string;
  source: string;
  status: 'PENDING' | 'PROCESSING' | 'COMPLETED' | 'FAILED';
}

function formatDuration(seconds: number): string {
  if (!seconds) return '时长未知';
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.round((seconds % 3600) / 60);
  return hours > 0 ? `${hours}小时${minutes}分钟` : `${minutes}分钟`;
}

function formatDate(value: string): string {
  if (!value) return '发布时间未知';
  return new Intl.DateTimeFormat('zh-CN', { month: 'short', day: 'numeric' }).format(new Date(value));
}

export default function DiscoveryPage() {
  const { showToast } = useToast();
  const [query, setQuery] = useState('');
  const [submittedQuery, setSubmittedQuery] = useState('');
  const [episodes, setEpisodes] = useState<DiscoveredEpisode[]>([]);
  const [providers, setProviders] = useState<ProviderStatus[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [queuedBySource, setQueuedBySource] = useState<Record<string, QueueTask>>({});
  const [submittingId, setSubmittingId] = useState<string | null>(null);

  const refreshTasks = async () => {
    try {
      const response = await api.get('/api/tasks');
      const next: Record<string, QueueTask> = {};
      (response.data.tasks || []).forEach((task: QueueTask) => {
        if (task.source?.startsWith('http')) next[task.source] = task;
      });
      setQueuedBySource(next);
    } catch {
      // 任务状态刷新失败不影响搜索和浏览。
    }
  };

  useEffect(() => {
    refreshTasks();
    const timer = window.setInterval(refreshTasks, 5000);
    return () => window.clearInterval(timer);
  }, []);

  const activeProviders = useMemo(
    () => providers.filter((provider) => provider.status === 'available'),
    [providers],
  );

  const search = async (event?: React.FormEvent) => {
    event?.preventDefault();
    const value = query.trim();
    if (value.length < 2) {
      showToast('error', '请输入至少两个字符');
      return;
    }
    setIsSearching(true);
    setSubmittedQuery(value);
    try {
      const response = await api.get('/api/discovery/search', { params: { q: value, limit: 30 } });
      setEpisodes(response.data.episodes || []);
      setProviders(response.data.providers || []);
      if (!(response.data.episodes || []).length) showToast('info', '暂未找到可处理的播客单集');
    } catch (error) {
      console.error(error);
      showToast('error', '搜索失败，请检查网络后重试');
    } finally {
      setIsSearching(false);
    }
  };

  const enqueue = async (episode: DiscoveredEpisode) => {
    if (queuedBySource[episode.audio_url]) return;
    setSubmittingId(episode.id);
    try {
      const response = await api.post('/api/discovery/enqueue', {
        audio_url: episode.audio_url,
        title: episode.title,
        mode: 'timeline',
      });
      setQueuedBySource((current) => ({
        ...current,
        [episode.audio_url]: {
          id: response.data.task_id,
          source: episode.audio_url,
          status: 'PENDING',
        },
      }));
      showToast('success', `已加入任务队列：${episode.title}`);
    } catch (error) {
      console.error(error);
      showToast('error', '加入任务队列失败');
    } finally {
      setSubmittingId(null);
    }
  };

  const taskButton = (episode: DiscoveredEpisode) => {
    const task = queuedBySource[episode.audio_url];
    if (submittingId === episode.id) return <IconLoader2 size={20} className="animate-spin" />;
    if (!task) return <IconPlus size={21} />;
    if (task.status === 'COMPLETED') return <IconCheck size={20} />;
    if (task.status === 'FAILED') return <IconAlertCircle size={20} />;
    if (task.status === 'PROCESSING') return <IconLoader2 size={20} className="animate-spin" />;
    return <IconClock size={20} />;
  };

  return (
    <div className="flex-1 overflow-y-auto bg-slate-50">
      <div className="mx-auto w-full max-w-6xl p-8 pb-16">
        <div className="mb-7 flex items-start justify-between gap-4">
          <div>
            <div className="mb-1 flex items-center gap-2">
              <IconWorldSearch size={23} className="text-[#00ADA6]" />
              <h1 className="text-xl font-bold text-slate-800">内容获取</h1>
              <span className="rounded-full bg-cyan-50 px-2 py-0.5 text-xs font-medium text-cyan-700">开发预览</span>
            </div>
            <p className="text-sm text-slate-500">搜索播客单集，一键生成可检索的时间轴</p>
          </div>
          {submittedQuery && (
            <button onClick={() => search()} disabled={isSearching} className="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-600 hover:border-[#00ADA6] hover:text-[#00ADA6]">
              <IconRefresh size={16} className={isSearching ? 'animate-spin' : ''} /> 刷新
            </button>
          )}
        </div>

        <form onSubmit={search} className="relative mb-4">
          <IconSearch size={20} className="absolute left-4 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索节目、单集或创作者，例如：忽左忽右"
            className="w-full rounded-xl border border-slate-200 bg-white py-3.5 pl-12 pr-28 text-sm shadow-sm outline-none transition focus:border-[#00ADA6] focus:ring-4 focus:ring-[#00ADA6]/10"
          />
          <button disabled={isSearching} className="absolute right-2 top-1/2 flex -translate-y-1/2 items-center gap-2 rounded-lg bg-[#00ADA6] px-4 py-2 text-sm font-medium text-white hover:bg-[#009A94] disabled:opacity-60">
            {isSearching && <IconLoader2 size={16} className="animate-spin" />} 搜索
          </button>
        </form>

        <div className="mb-7 flex flex-wrap items-center gap-2 text-xs text-slate-500">
          <span>当前来源：</span>
          {(providers.length ? providers : [
            { id: 'apple', label: 'Apple Podcasts 中国区', status: 'available' },
            { id: 'rss', label: '公开 RSS / 音频源', status: 'available' },
          ]).map((provider) => (
            <span key={provider.id} className={`rounded-full border px-2.5 py-1 ${provider.status === 'available' ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-slate-200 bg-white text-slate-400'}`}>
              {provider.label}{provider.status === 'not_configured' ? ' · 未配置' : ''}
            </span>
          ))}
          {!!activeProviders.length && <span className="ml-1">系统会优先选择可直接处理的大陆可达音频。</span>}
        </div>

        {!submittedQuery && (
          <div className="rounded-2xl border border-dashed border-slate-300 bg-white px-8 py-16 text-center">
            <IconTimelineEvent size={42} className="mx-auto mb-4 text-slate-300" />
            <h2 className="mb-2 font-semibold text-slate-700">从发现到时间轴，只需一次点击</h2>
            <p className="mx-auto max-w-lg text-sm leading-6 text-slate-500">当前开发版聚合 Apple Podcasts 中国区目录与公开 RSS 音频，并识别小宇宙等大陆音频托管来源。</p>
          </div>
        )}

        {submittedQuery && !isSearching && episodes.length === 0 && (
          <div className="rounded-xl border border-slate-200 bg-white py-16 text-center text-sm text-slate-500">没有找到“{submittedQuery}”的可处理单集</div>
        )}

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {episodes.map((episode) => {
            const task = queuedBySource[episode.audio_url];
            const isQueued = !!task;
            return (
              <article key={episode.id} className="flex min-h-44 gap-4 rounded-xl border border-slate-200 bg-white p-4 shadow-sm transition hover:border-slate-300 hover:shadow-md">
                <div className="h-24 w-24 shrink-0 overflow-hidden rounded-lg bg-slate-100">
                  {episode.cover_url ? <img src={episode.cover_url} alt="" className="h-full w-full object-cover" /> : <IconWorldSearch size={28} className="m-auto h-full text-slate-300" />}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="mb-1 flex items-start justify-between gap-3">
                    <h2 className="line-clamp-2 text-sm font-semibold leading-5 text-slate-800" title={episode.title}>{episode.title}</h2>
                    <button
                      onClick={() => enqueue(episode)}
                      disabled={isQueued || submittingId === episode.id}
                      title={task ? `任务状态：${task.status}` : '加入任务队列并生成时间轴'}
                      className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full transition ${task?.status === 'COMPLETED' ? 'bg-emerald-50 text-emerald-600' : task?.status === 'FAILED' ? 'bg-rose-50 text-rose-600' : isQueued ? 'bg-cyan-50 text-cyan-600' : 'bg-[#00ADA6] text-white hover:bg-[#009A94]'}`}
                    >
                      {taskButton(episode)}
                    </button>
                  </div>
                  <p className="truncate text-xs font-medium text-slate-500">{episode.show_title}</p>
                  <p className="mt-1 text-xs text-slate-400">{formatDate(episode.published_at)} · {formatDuration(episode.duration_seconds)}</p>
                  {episode.description && <p className="mt-2 line-clamp-2 text-xs leading-5 text-slate-500">{episode.description}</p>}
                  <div className="mt-3 flex flex-wrap items-center gap-1.5">
                    <span className="text-[11px] text-slate-400">来源</span>
                    {episode.sources.map((source) => (
                      <span key={`${source.provider}-${source.role}`} className={`rounded px-1.5 py-0.5 text-[11px] ${source.recommended ? 'bg-emerald-50 font-medium text-emerald-700' : 'bg-slate-100 text-slate-500'}`}>
                        {source.label}{source.recommended ? ' · 推荐' : ''}
                      </span>
                    ))}
                  </div>
                </div>
              </article>
            );
          })}
        </div>
      </div>
    </div>
  );
}
