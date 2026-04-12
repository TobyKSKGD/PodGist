import { useState, useEffect, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import {
  IconClock, IconMessageCircle,
  IconPlayerPlay,
  IconSearch, IconX
} from '@tabler/icons-react';

const api = axios.create({ baseURL: 'http://localhost:8000' });

// ===== 类型 =====

interface ArchiveItem {
  id: string;
  name: string;
  createTime: string;
  hasAudio: boolean;
  hasSegments: boolean;
}

interface PlayProgress {
  archiveId: string;
  lastPositionSeconds: number;
  duration: number;
  updatedAt: number;
}

// ===== 播放进度本地存储 =====

const PROGRESS_KEY = 'podgist_play_progress';

function loadProgress(): Record<string, PlayProgress> {
  try {
    const raw = localStorage.getItem(PROGRESS_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

function saveProgress(archiveId: string, position: number, duration: number) {
  const all = loadProgress();
  all[archiveId] = {
    archiveId,
    lastPositionSeconds: position,
    duration,
    updatedAt: Date.now(),
  };
  localStorage.setItem(PROGRESS_KEY, JSON.stringify(all));
}

function getTopProgress(archives: ArchiveItem[], limit = 3): (PlayProgress & { archive: ArchiveItem })[] {
  const progress = loadProgress();
  const entries = Object.values(progress)
    .filter(p => p.duration > 0 && p.lastPositionSeconds > 0)
    .map(p => ({ ...p, archive: archives.find(a => a.id === p.archiveId) }))
    .filter(p => p.archive != null)
    .sort((a, b) => b.updatedAt - a.updatedAt)
    .slice(0, limit);
  return entries;
}

// ===== 格式化 =====

function formatTime(seconds: number): string {
  if (!seconds || seconds <= 0) return '--:--';
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
}

function formatRelativeTime(dateStr: string): string {
  try {
    const date = new Date(dateStr);
    const now = new Date();
    const diff = now.getTime() - date.getTime();
    const days = Math.floor(diff / 86400000);
    if (days === 0) return '今天';
    if (days === 1) return '昨天';
    if (days < 7) return `${days} 天前`;
    if (days < 30) return `${Math.floor(days / 7)} 周前`;
    return date.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' });
  } catch {
    return dateStr;
  }
}

// ===== 组件 =====

export default function LibraryPage() {
  const navigate = useNavigate();

  const [archives, setArchives] = useState<ArchiveItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // 搜索与筛选
  const [search, setSearch] = useState('');
  const [filterAudio, setFilterAudio] = useState(false);
  const [filterHasContent, setFilterHasContent] = useState(false);
  const [sortRecent, setSortRecent] = useState(true);

  // 获取归档列表
  useEffect(() => {
    api.get<{ status: string; archives: ArchiveItem[] }>('/api/archives')
      .then(res => {
        if (res.data.status === 'success') {
          setArchives(res.data.archives);
        }
      })
      .catch(() => setError('加载归档失败'))
      .finally(() => setLoading(false));
  }, []);

  // 计算继续收听
  const continueListening = useMemo(
    () => getTopProgress(archives, 3),
    [archives]
  );

  // 过滤 + 搜索后的归档列表
  const displayedArchives = useMemo(() => {
    let list = [...archives];

    // 搜索
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      list = list.filter(a => a.name.toLowerCase().includes(q));
    }

    // 筛选：有音频
    if (filterAudio) {
      list = list.filter(a => a.hasAudio);
    }

    // 筛选：有内容（segments）
    if (filterHasContent) {
      list = list.filter(a => a.hasSegments);
    }

    // 排序：默认最新优先（API 已按最新排序，过滤后重排）
    if (sortRecent) {
      list.sort((a, b) => new Date(b.createTime).getTime() - new Date(a.createTime).getTime());
    }

    return list;
  }, [archives, search, filterAudio, filterHasContent, sortRecent]);

  const hasActiveFilters = filterAudio || filterHasContent;

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-[#00ADA6]" />
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-4xl w-full mx-auto px-6 py-8 pb-16">

        {/* ===== 顶部欢迎区（弱化） ===== */}
        <div className="mb-7">
          <h1 className="text-lg font-semibold text-slate-700 mb-1">
            我的资料库
          </h1>
          <p className="text-xs text-slate-400">
            {archives.length} 条归档 {continueListening.length > 0 && `· ${continueListening.length} 条继续收听`}
          </p>
        </div>

        {/* ===== 继续收听 ===== */}
        {continueListening.length > 0 && (
          <section className="mb-8">
            <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3 flex items-center gap-1.5">
              <IconPlayerPlay size={12} className="text-[#00ADA6]" />
              继续收听
            </h2>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              {continueListening.map((item) => (
                <button
                  key={item.archiveId}
                  onClick={() => navigate(`/episode/${item.archiveId}`)}
                  className="text-left bg-white border border-slate-200 rounded-xl px-4 py-3 hover:border-[#00ADA6] hover:shadow-sm transition-all group"
                >
                  <div className="flex items-start gap-2.5 mb-2.5">
                    <div className="w-9 h-9 rounded-lg bg-[#D1FAF5] flex items-center justify-center shrink-0">
                      <IconMessageCircle size={16} className="text-[#00ADA6]" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-slate-800 truncate group-hover:text-[#00ADA6] transition-colors">
                        {item.archive.name}
                      </p>
                      <p className="text-xs text-slate-400 mt-0.5">
                        {formatTime(item.duration)}
                      </p>
                    </div>
                  </div>
                  {/* 进度条 */}
                  <div className="w-full bg-slate-100 rounded-full h-1">
                    <div
                      className="bg-[#00ADA6] h-1 rounded-full transition-all"
                      style={{ width: `${Math.min(100, (item.lastPositionSeconds / item.duration) * 100)}%` }}
                    />
                  </div>
                  <p className="text-xs text-slate-400 mt-1.5">
                    {formatTime(item.lastPositionSeconds)} / {formatTime(item.duration)}
                  </p>
                </button>
              ))}
            </div>
          </section>
        )}

        {/* ===== 搜索 + 筛选 ===== */}
        <section className="mb-6">
          <div className="flex items-center gap-2 mb-2">
            {/* 搜索框 */}
            <div className="flex-1 relative">
              <IconSearch size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                type="text"
                value={search}
                onChange={e => setSearch(e.target.value)}
                placeholder="搜索归档标题..."
                className="w-full pl-8 pr-8 py-2 text-sm bg-white border border-slate-200 rounded-lg focus:outline-none focus:border-[#00ADA6] transition-colors placeholder:text-slate-400"
              />
              {search && (
                <button
                  onClick={() => setSearch('')}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
                >
                  <IconX size={13} />
                </button>
              )}
            </div>
            {/* 筛选按钮 */}
            <button
              onClick={() => setFilterAudio(v => !v)}
              className={`px-3 py-2 text-xs rounded-lg border transition-colors ${
                filterAudio
                  ? 'bg-[#00ADA6] border-[#00ADA6] text-white'
                  : 'bg-white border-slate-200 text-slate-500 hover:border-slate-300'
              }`}
            >
              有音频
            </button>
            <button
              onClick={() => setFilterHasContent(v => !v)}
              className={`px-3 py-2 text-xs rounded-lg border transition-colors ${
                filterHasContent
                  ? 'bg-[#00ADA6] border-[#00ADA6] text-white'
                  : 'bg-white border-slate-200 text-slate-500 hover:border-slate-300'
              }`}
            >
              有时间轴
            </button>
          </div>
          {hasActiveFilters && (
            <div className="flex items-center gap-1.5">
              <span className="text-xs text-slate-400">
                找到 {displayedArchives.length} 条结果
              </span>
              <button
                onClick={() => { setFilterAudio(false); setFilterHasContent(false); }}
                className="text-xs text-[#00ADA6] hover:underline"
              >
                清除筛选
              </button>
            </div>
          )}
        </section>

        {/* ===== 归档列表 ===== */}
        <section className="mb-8">
          <div className="bg-white border border-slate-200 rounded-xl divide-y divide-slate-100 overflow-hidden">
            {displayedArchives.length === 0 ? (
              <div className="py-12 text-center">
                <IconMessageCircle size={28} className="text-slate-300 mx-auto mb-2" />
                <p className="text-sm text-slate-400">
                  {search ? '没有找到匹配的归档' : '暂无归档，导入音频开始使用'}
                </p>
              </div>
            ) : (
              displayedArchives.map((item) => (
                <button
                  key={item.id}
                  onClick={() => navigate(`/episode/${item.id}`)}
                  className="w-full text-left px-4 py-3.5 hover:bg-slate-50 transition-colors flex items-center justify-between group"
                >
                  <div className="flex items-center gap-3 flex-1 min-w-0">
                    <div className={`w-8 h-8 rounded-lg flex items-center justify-center shrink-0 ${item.hasAudio ? 'bg-[#D1FAF5]' : 'bg-slate-100'}`}>
                      <IconMessageCircle size={14} className={item.hasAudio ? 'text-[#00ADA6]' : 'text-slate-400'} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-slate-700 truncate group-hover:text-[#00ADA6] transition-colors">
                        {item.name}
                      </p>
                      <p className="text-xs text-slate-400 mt-0.5 flex items-center gap-2">
                        <span>{formatRelativeTime(item.createTime)}</span>
                        {!item.hasAudio && (
                          <span className="text-amber-500">· 无音频</span>
                        )}
                        {item.hasSegments && (
                          <span className="text-[#00ADA6]">· 有时间轴</span>
                        )}
                      </p>
                    </div>
                  </div>
                  <IconPlayerPlay size={14} className="text-slate-300 group-hover:text-[#00ADA6] transition-colors shrink-0 ml-2" />
                </button>
              ))
            )}
          </div>
        </section>


      </div>
    </div>
  );
}
