import { useEffect, useState } from 'react';
import axios from 'axios';
import {
  IconAlertCircle, IconArrowLeft, IconCheck, IconClock, IconExternalLink,
  IconLoader2, IconPlus, IconRefresh, IconSearch,
  IconWorldSearch, IconBell, IconBellOff, IconChevronRight,
} from '@tabler/icons-react';
import { useToast } from '../components/Toast';

const api = axios.create({ baseURL: 'http://localhost:8000' });

interface EpisodeSource { provider: string; label: string; url: string; role: 'audio' | 'feed' | 'catalog'; recommended: boolean }
interface DiscoveredEpisode {
  id: string; title: string; show_title: string; description: string; published_at: string;
  duration_seconds: number; cover_url: string; audio_url: string; page_url: string;
  feed_url: string; recommended_provider: string; sources: EpisodeSource[]; cover_candidates?: string[];
}
interface PodcastShow {
  id: string; title: string; author: string; description: string; feed_url: string;
  page_url: string; cover_url: string; episode_count: number; provider: string;
}
interface ShowDetail extends PodcastShow { episodes: DiscoveredEpisode[]; total_episodes: number; has_more: boolean }
interface ProviderStatus { id: string; label: string; status: 'available' | 'not_configured' | 'unavailable' }
interface QueueTask { id: string; source: string; status: 'PENDING' | 'PROCESSING' | 'COMPLETED' | 'FAILED' }

function formatDuration(seconds: number): string {
  if (!seconds) return '时长未知';
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.round((seconds % 3600) / 60);
  return hours > 0 ? `${hours}小时${minutes}分钟` : `${minutes}分钟`;
}
function formatDate(value: string): string {
  if (!value) return '发布时间未知';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: 'short', day: 'numeric' }).format(date);
}

function RemoteImage({ src, candidates = [], fallbackSrc, alt = '', eager = false }: { src?: string; candidates?: string[]; fallbackSrc?: string; alt?: string; eager?: boolean }) {
  const [loaded, setLoaded] = useState(false);
  const [failed, setFailed] = useState(false);
  const [fallbackLoaded, setFallbackLoaded] = useState(false);
  const [sourceIndex, setSourceIndex] = useState(0);
  const sourceList = [...new Set([src, ...candidates, fallbackSrc].filter((value): value is string => !!value))];
  const activeSource = sourceList[sourceIndex];
  return <div className="relative h-full w-full overflow-hidden bg-gradient-to-br from-slate-100 to-slate-200">
    {!loaded && !fallbackLoaded && <div className="absolute inset-0 animate-pulse bg-gradient-to-r from-transparent via-white/60 to-transparent" />}
    {fallbackSrc && fallbackSrc !== activeSource && <img src={fallbackSrc} alt="" loading={eager ? 'eager' : 'lazy'} decoding="async" onLoad={() => setFallbackLoaded(true)} className={`absolute inset-0 h-full w-full object-cover transition-opacity duration-200 ${fallbackLoaded ? 'opacity-100' : 'opacity-0'}`} />}
    {(!activeSource || failed) && !fallbackSrc && <IconWorldSearch size={24} className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 text-slate-300" />}
    {activeSource && !failed && <img key={activeSource} src={activeSource} alt={alt} loading={eager ? 'eager' : 'lazy'} fetchPriority={eager ? 'high' : 'auto'} decoding="async" onLoad={() => setLoaded(true)} onError={() => { setLoaded(false); if (sourceIndex + 1 < sourceList.length) setSourceIndex(index => index + 1); else setFailed(true); }} className={`absolute inset-0 h-full w-full object-cover transition-opacity duration-300 ${loaded ? 'opacity-100' : 'opacity-0'}`} />}
  </div>;
}

function TaskStatusIcon({ task, submitting }: { task?: QueueTask; submitting: boolean }) {
  if (submitting || task?.status === 'PROCESSING') return <IconLoader2 size={19} className="animate-spin" />;
  if (!task) return <IconPlus size={20} />;
  if (task.status === 'COMPLETED') return <IconCheck size={19} />;
  if (task.status === 'FAILED') return <IconAlertCircle size={19} />;
  return <IconClock size={19} />;
}

function EpisodeCard({ episode, task, submitting, fallbackCover, eager = false, onOpen, onEnqueue }: {
  episode: DiscoveredEpisode; task?: QueueTask; submitting: boolean; fallbackCover?: string; eager?: boolean;
  onOpen: (episode: DiscoveredEpisode) => void; onEnqueue: (episode: DiscoveredEpisode) => void;
}) {
  return <article onClick={() => onOpen(episode)} className="flex min-h-40 cursor-pointer gap-4 rounded-xl border border-slate-200 bg-white p-4 shadow-sm transition hover:border-[#00ADA6]/40 hover:shadow-md">
    <div className="h-24 w-24 shrink-0 overflow-hidden rounded-lg bg-slate-100"><RemoteImage src={episode.cover_url} candidates={episode.cover_candidates} fallbackSrc={fallbackCover} alt={episode.title} eager={eager} /></div>
    <div className="min-w-0 flex-1">
      <div className="flex items-start justify-between gap-3">
        <h3 className="line-clamp-2 text-sm font-semibold leading-5 text-slate-800">{episode.title}</h3>
        <button onClick={event => { event.stopPropagation(); onEnqueue(episode); }} disabled={!!task || submitting} className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full ${task ? 'bg-cyan-50 text-cyan-600' : 'bg-[#00ADA6] text-white hover:bg-[#009A94]'}`}><TaskStatusIcon task={task} submitting={submitting} /></button>
      </div>
      <p className="mt-1 truncate text-xs font-medium text-slate-500">{episode.show_title}</p>
      <p className="mt-1 text-xs text-slate-400">{formatDate(episode.published_at)} · {formatDuration(episode.duration_seconds)}</p>
      {episode.description && <p className="mt-2 line-clamp-2 text-xs leading-5 text-slate-500">{episode.description}</p>}
    </div>
  </article>;
}

export default function DiscoveryPage() {
  const { showToast } = useToast();
  const [query, setQuery] = useState('');
  const [submittedQuery, setSubmittedQuery] = useState('');
  const [episodes, setEpisodes] = useState<DiscoveredEpisode[]>([]);
  const [shows, setShows] = useState<PodcastShow[]>([]);
  const [providers, setProviders] = useState<ProviderStatus[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [queuedBySource, setQueuedBySource] = useState<Record<string, QueueTask>>({});
  const [submittingId, setSubmittingId] = useState<string | null>(null);
  const [selectedEpisode, setSelectedEpisode] = useState<DiscoveredEpisode | null>(null);
  const [selectedShow, setSelectedShow] = useState<PodcastShow | null>(null);
  const [showDetail, setShowDetail] = useState<ShowDetail | null>(null);
  const [showPage, setShowPage] = useState(1);
  const [showQuery, setShowQuery] = useState('');
  const [loadingShow, setLoadingShow] = useState(false);
  const [subscriptions, setSubscriptions] = useState<PodcastShow[]>([]);
  const [homeEpisodes, setHomeEpisodes] = useState<DiscoveredEpisode[]>([]);
  const [loadingHome, setLoadingHome] = useState(true);

  const refreshTasks = async () => {
    try {
      const response = await api.get('/api/tasks');
      const next: Record<string, QueueTask> = {};
      (response.data.tasks || []).forEach((task: QueueTask) => { if (task.source?.startsWith('http')) next[task.source] = task; });
      setQueuedBySource(current => {
        const currentEntries = Object.entries(current);
        const nextEntries = Object.entries(next);
        if (currentEntries.length === nextEntries.length && nextEntries.every(([source, task]) => current[source]?.id === task.id && current[source]?.status === task.status)) return current;
        return next;
      });
    } catch { /* 不影响内容浏览 */ }
  };

  const refreshHome = async () => {
    setLoadingHome(true);
    try {
      const response = await api.get('/api/discovery/home');
      setSubscriptions(response.data.subscriptions || []);
      setHomeEpisodes(response.data.episodes || []);
    } catch { /* 首页允许离线 */ }
    finally { setLoadingHome(false); }
  };

  useEffect(() => {
    refreshTasks(); refreshHome();
    const timer = window.setInterval(refreshTasks, 5000);
    return () => window.clearInterval(timer);
  }, []);

  const isSubscribed = (show: PodcastShow) => subscriptions.some(item => item.feed_url === show.feed_url);

  const search = async (event?: React.FormEvent) => {
    event?.preventDefault();
    const value = query.trim();
    if (value.length < 2) return showToast('error', '请输入至少两个字符');
    setIsSearching(true); setSubmittedQuery(value); setSelectedShow(null); setShowDetail(null);
    try {
      const response = await api.get('/api/discovery/search', { params: { q: value, limit: 30 } });
      setEpisodes(response.data.episodes || []); setShows(response.data.shows || []); setProviders(response.data.providers || []);
    } catch { showToast('error', '搜索失败，请检查网络后重试'); }
    finally { setIsSearching(false); }
  };

  const loadShow = async (show: PodcastShow, page = 1, insideQuery = '', append = false) => {
    setSelectedShow(show); setLoadingShow(true);
    try {
      const response = await api.get('/api/discovery/show', { params: { feed_url: show.feed_url, page_url: show.page_url, apple_id: show.id, page, page_size: 30, q: insideQuery } });
      const detail: ShowDetail = response.data.show;
      detail.id = show.id;
      // 搜索页的 Apple 封面通常已经进入浏览器缓存，节目头图优先复用，避免切换到较慢的 RSS 图源。
      detail.cover_url = show.cover_url || detail.cover_url;
      detail.episodes = detail.episodes.map(episode => {
        const appleEpisode = episodes.find(candidate => candidate.audio_url === episode.audio_url)
          || episodes.find(candidate => candidate.feed_url === episode.feed_url && candidate.title === episode.title);
        const coverCandidates = [...new Set([appleEpisode?.cover_url, ...(episode.cover_candidates || []), episode.cover_url, detail.cover_url].filter((value): value is string => !!value))];
        return { ...episode, cover_url: coverCandidates[0] || '', cover_candidates: coverCandidates.slice(1) };
      });
      setShowDetail(current => append && current ? { ...detail, episodes: [...current.episodes, ...detail.episodes] } : detail);
      setShowPage(page);
    } catch { showToast('error', '节目资料读取失败，请稍后重试'); }
    finally { setLoadingShow(false); }
  };

  const toggleSubscription = async (show: PodcastShow) => {
    try {
      const existing = subscriptions.find(item => item.feed_url === show.feed_url);
      if (existing) {
        await api.delete(`/api/discovery/subscriptions/${encodeURIComponent(existing.id)}`);
        showToast('success', `已取消订阅「${show.title}」`);
      } else {
        await api.post('/api/discovery/subscriptions', show);
        showToast('success', `已订阅「${show.title}」`);
      }
      await refreshHome();
    } catch { showToast('error', '订阅操作失败'); }
  };

  const enqueue = async (episode: DiscoveredEpisode) => {
    if (queuedBySource[episode.audio_url]) return;
    setSubmittingId(episode.id);
    try {
      const response = await api.post('/api/discovery/enqueue', {
        audio_url: episode.audio_url, title: episode.title, show_title: episode.show_title,
        cover_url: episode.cover_url, page_url: episode.page_url, feed_url: episode.feed_url,
        provider: episode.recommended_provider, description: episode.description,
        published_at: episode.published_at, duration_seconds: episode.duration_seconds, mode: 'timeline',
      });
      setQueuedBySource(current => ({ ...current, [episode.audio_url]: { id: response.data.task_id, source: episode.audio_url, status: 'PENDING' } }));
      showToast('success', `已加入任务队列：${episode.title}`);
    } catch { showToast('error', '加入任务队列失败'); }
    finally { setSubmittingId(null); }
  };

  if (selectedEpisode) {
    const queued = !!queuedBySource[selectedEpisode.audio_url];
    return <div className="flex-1 overflow-y-auto bg-slate-50"><div className="mx-auto max-w-5xl p-8">
      <button onClick={() => setSelectedEpisode(null)} className="mb-6 flex items-center gap-1.5 text-sm text-slate-500 hover:text-[#00ADA6]"><IconArrowLeft size={17} />返回</button>
      <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div className="flex gap-7 bg-gradient-to-b from-slate-100 to-white p-8">
          <div className="h-44 w-44 shrink-0 overflow-hidden rounded-2xl bg-slate-200 shadow-md"><RemoteImage src={selectedEpisode.cover_url} alt={selectedEpisode.title} eager /></div>
          <div className="self-end"><p className="mb-2 text-sm font-medium text-[#00ADA6]">{selectedEpisode.show_title}</p><h1 className="text-2xl font-bold text-slate-900">{selectedEpisode.title}</h1><p className="mt-3 text-sm text-slate-500">{formatDate(selectedEpisode.published_at)} · {formatDuration(selectedEpisode.duration_seconds)}</p>
            <button onClick={() => enqueue(selectedEpisode)} disabled={queued} className="mt-5 inline-flex items-center gap-2 rounded-full bg-[#00ADA6] px-5 py-2.5 text-sm font-semibold text-white disabled:bg-slate-200 disabled:text-slate-500"><TaskStatusIcon task={queuedBySource[selectedEpisode.audio_url]} submitting={submittingId === selectedEpisode.id} />{queued ? '已加入任务队列' : '加入任务队列并生成时间轴'}</button>
          </div>
        </div>
        <div className="p-8">{selectedEpisode.description && <><h2 className="mb-3 font-semibold text-slate-800">节目简介与 Shownotes</h2><div className="whitespace-pre-wrap text-sm leading-7 text-slate-600">{selectedEpisode.description}</div></>}
          <div className="mt-7 flex flex-wrap gap-2">{selectedEpisode.sources.map(source => <a key={`${source.provider}-${source.role}`} href={source.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 rounded-full border border-slate-200 px-3 py-1.5 text-xs text-slate-500">{source.label}<IconExternalLink size={12} /></a>)}</div>
        </div>
      </section>
    </div></div>;
  }

  if (selectedShow) {
    const detail = showDetail || selectedShow;
    return <div className="flex-1 overflow-y-auto bg-slate-50"><div className="mx-auto max-w-6xl p-8 pb-16">
      <button onClick={() => { setSelectedShow(null); setShowDetail(null); }} className="mb-6 flex items-center gap-1.5 text-sm text-slate-500 hover:text-[#00ADA6]"><IconArrowLeft size={17} />返回内容获取</button>
      <section className="mb-7 flex gap-7 rounded-2xl border border-slate-200 bg-white p-7 shadow-sm">
        <div className="h-48 w-48 shrink-0 overflow-hidden rounded-2xl bg-slate-100 shadow-md"><RemoteImage src={detail.cover_url} alt={detail.title} eager /></div>
        <div className="min-w-0 flex-1"><p className="text-xs font-semibold uppercase tracking-wider text-[#00ADA6]">播客节目</p><h1 className="mt-2 text-3xl font-bold text-slate-900">{detail.title}</h1><p className="mt-2 text-sm text-slate-500">{detail.author}</p>{detail.description && <p className="mt-4 line-clamp-4 max-w-3xl text-sm leading-7 text-slate-600">{detail.description}</p>}
          <button onClick={() => toggleSubscription(detail)} className={`mt-5 inline-flex items-center gap-2 rounded-full px-5 py-2.5 text-sm font-semibold ${isSubscribed(detail) ? 'border border-slate-200 text-slate-600 hover:bg-slate-50' : 'bg-[#00ADA6] text-white hover:bg-[#009A94]'}`}>{isSubscribed(detail) ? <IconBellOff size={17} /> : <IconBell size={17} />}{isSubscribed(detail) ? '取消订阅' : '订阅节目'}</button>
        </div>
      </section>
      <div className="mb-5 flex items-center justify-between gap-4"><div><h2 className="text-lg font-semibold text-slate-800">全部单集</h2><p className="text-xs text-slate-400">RSS 当前提供 {showDetail?.total_episodes ?? detail.episode_count ?? 0} 期</p></div>
        <form onSubmit={event => { event.preventDefault(); loadShow(selectedShow, 1, showQuery); }} className="relative w-80"><IconSearch size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" /><input value={showQuery} onChange={event => setShowQuery(event.target.value)} placeholder="在这个节目中搜索单集" className="w-full rounded-lg border border-slate-200 bg-white py-2.5 pl-9 pr-3 text-sm outline-none focus:border-[#00ADA6]" /></form>
      </div>
      {loadingShow && !showDetail ? <div className="py-20 text-center"><IconLoader2 className="mx-auto animate-spin text-[#00ADA6]" /></div> : <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">{showDetail?.episodes.map((episode, index) => <EpisodeCard key={episode.id} episode={episode} task={queuedBySource[episode.audio_url]} submitting={submittingId === episode.id} fallbackCover={detail.cover_url} eager={index < 6} onOpen={setSelectedEpisode} onEnqueue={enqueue} />)}</div>}
      {showDetail?.has_more && <button onClick={() => loadShow(selectedShow, showPage + 1, showQuery, true)} disabled={loadingShow} className="mx-auto mt-7 flex items-center gap-2 rounded-full border border-slate-200 bg-white px-6 py-2.5 text-sm text-slate-600 hover:border-[#00ADA6] hover:text-[#00ADA6]">{loadingShow && <IconLoader2 size={16} className="animate-spin" />}加载更多</button>}
    </div></div>;
  }

  return <div className="flex-1 overflow-y-auto bg-slate-50"><div className="mx-auto w-full max-w-6xl p-8 pb-16">
    <div className="mb-7 flex items-start justify-between"><div><div className="flex items-center gap-2"><IconWorldSearch size={23} className="text-[#00ADA6]" /><h1 className="text-xl font-bold text-slate-800">内容获取</h1></div><p className="mt-1 text-sm text-slate-500">搜索、订阅播客节目，一键生成可检索的时间轴</p></div>{(submittedQuery || subscriptions.length > 0) && <button onClick={() => submittedQuery ? search() : refreshHome()} className="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-600"><IconRefresh size={16} />刷新</button>}</div>
    <form onSubmit={search} className="relative mb-4"><IconSearch size={20} className="absolute left-4 top-1/2 -translate-y-1/2 text-slate-400" /><input value={query} onChange={event => setQuery(event.target.value)} placeholder="搜索播客节目、单集或创作者，例如：大内密谈" className="w-full rounded-xl border border-slate-200 bg-white py-3.5 pl-12 pr-28 text-sm shadow-sm outline-none focus:border-[#00ADA6] focus:ring-4 focus:ring-[#00ADA6]/10" /><button className="absolute right-2 top-1/2 -translate-y-1/2 rounded-lg bg-[#00ADA6] px-4 py-2 text-sm text-white">搜索</button></form>
    <div className="mb-7 flex flex-wrap items-center gap-2 text-xs text-slate-500"><span>当前来源：</span>{(providers.length ? providers : [{ id: 'apple', label: 'Apple Podcasts 中国区', status: 'available' as const }, { id: 'rss', label: '公开 RSS / 音频源', status: 'available' as const }]).filter(provider => provider.status !== 'not_configured').map(provider => <span key={provider.id} className="rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-emerald-700">{provider.label}</span>)}</div>

    {!submittedQuery && <>
      {loadingHome ? <div className="py-20 text-center"><IconLoader2 className="mx-auto animate-spin text-[#00ADA6]" /></div> : subscriptions.length === 0 ? <div className="rounded-2xl border border-dashed border-slate-300 bg-white px-8 py-16 text-center"><IconBell size={42} className="mx-auto mb-4 text-slate-300" /><h2 className="mb-2 font-semibold text-slate-700">订阅喜欢的播客，最新节目会出现在这里</h2><p className="mx-auto whitespace-nowrap text-sm leading-6 text-slate-500">在上方搜索节目，点击节目卡片进入主页，再选择“订阅节目”。订阅仅保存在本机。</p></div> : <>
        <div className="mb-7"><h2 className="mb-3 text-sm font-semibold text-slate-700">我的订阅</h2><div className="flex gap-4 overflow-x-auto pb-2">{subscriptions.map(show => <button key={show.id} onClick={() => loadShow(show)} className="flex w-64 shrink-0 items-center gap-3 rounded-xl border border-slate-200 bg-white p-3 text-left hover:border-[#00ADA6]/40"><div className="h-14 w-14 shrink-0 overflow-hidden rounded-lg bg-slate-100"><RemoteImage src={show.cover_url} alt={show.title} /></div><div className="min-w-0 flex-1"><p className="truncate text-sm font-semibold text-slate-800">{show.title}</p><p className="mt-1 truncate text-xs text-slate-400">{show.author}</p></div><IconChevronRight size={16} className="text-slate-300" /></button>)}</div></div>
        <h2 className="mb-4 text-sm font-semibold text-slate-700">订阅更新</h2><div className="grid grid-cols-1 gap-4 lg:grid-cols-2">{homeEpisodes.map((episode, index) => <EpisodeCard key={episode.id} episode={episode} task={queuedBySource[episode.audio_url]} submitting={submittingId === episode.id} fallbackCover={subscriptions.find(show => show.feed_url === episode.feed_url)?.cover_url} eager={index < 6} onOpen={setSelectedEpisode} onEnqueue={enqueue} />)}</div>
      </>}
    </>}

    {submittedQuery && <>{isSearching ? <div className="py-20 text-center"><IconLoader2 className="mx-auto animate-spin text-[#00ADA6]" /></div> : <>
      {shows.length > 0 && <section className="mb-8"><div className="mb-3 flex items-end justify-between"><div><h2 className="text-base font-semibold text-slate-800">节目</h2><p className="text-xs text-slate-400">进入节目主页可浏览历史单集并订阅</p></div></div><div className="grid grid-cols-1 gap-4 md:grid-cols-2">{shows.map(show => <button key={show.id} onClick={() => loadShow(show)} className="flex items-center gap-5 rounded-2xl border border-slate-200 bg-white p-5 text-left shadow-sm transition hover:border-[#00ADA6]/40 hover:shadow-md"><div className="h-28 w-28 shrink-0 overflow-hidden rounded-xl bg-slate-100"><RemoteImage src={show.cover_url} alt={show.title} /></div><div className="min-w-0 flex-1"><span className="text-[11px] font-semibold uppercase tracking-wider text-[#00ADA6]">播客节目</span><h2 className="mt-1 line-clamp-2 text-lg font-bold text-slate-800">{show.title}</h2><p className="mt-2 truncate text-sm text-slate-500">{show.author}</p><p className="mt-2 text-xs text-slate-400">约 {show.episode_count || '—'} 期 · 查看全部</p></div><IconChevronRight size={22} className="text-slate-300" /></button>)}</div></section>}
      <section><h2 className="mb-3 text-base font-semibold text-slate-800">匹配单集</h2><div className="grid grid-cols-1 gap-4 lg:grid-cols-2">{episodes.map((episode, index) => <EpisodeCard key={episode.id} episode={episode} task={queuedBySource[episode.audio_url]} submitting={submittingId === episode.id} fallbackCover={shows.find(show => show.feed_url === episode.feed_url)?.cover_url} eager={index < 6} onOpen={setSelectedEpisode} onEnqueue={enqueue} />)}</div>{shows.length === 0 && episodes.length === 0 && <div className="rounded-xl border border-slate-200 bg-white py-16 text-center text-sm text-slate-500">没有找到“{submittedQuery}”</div>}</section>
    </>}</>}
  </div></div>;
}
