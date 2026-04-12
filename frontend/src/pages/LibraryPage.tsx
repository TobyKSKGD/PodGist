import { useState, useEffect, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import {
  IconPlayerPlay,
  IconSearch,
  IconX,
  IconMicrophone,
  IconTrash,
  IconChartBar,
  IconTimelineEvent,
} from '@tabler/icons-react';
import ConfirmDialog from '../components/ConfirmDialog';
import { useToast } from '../components/Toast';

const api = axios.create({ baseURL: 'http://localhost:8000' });

// ===== 类型 =====

interface ArchiveItem {
  id: string;
  name: string;
  createTime: string;
  hasAudio: boolean;
  hasSegments: boolean;
  mode: string;       // "summary" | "timeline"
  hasTimeline: boolean;
  canMigrate: boolean;
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

function getTopProgress(archives: ArchiveItem[], limit = 3): (PlayProgress & { archive: ArchiveItem })[] {
  const progress = loadProgress();
  const entries = Object.values(progress)
    .filter(p => p.duration > 0 && p.lastPositionSeconds > 0)
    .map(p => ({ ...p, archive: archives.find(a => a.id === p.archiveId)! }))
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
  const { showToast } = useToast();
  const navigate = useNavigate();

  const [archives, setArchives] = useState<ArchiveItem[]>([]);
  const [loading, setLoading] = useState(true);

  // 删除确认框
  const [deleteTarget, setDeleteTarget] = useState<{ id: string; name: string } | null>(null);

  // 迁移归档
  const [migratingId, setMigratingId] = useState<string | null>(null);

  // 搜索与筛选
  const [search, setSearch] = useState('');
  const [filterAudio, setFilterAudio] = useState(false);
  const [filterHasContent, setFilterHasContent] = useState(false);

  // 获取归档列表
  useEffect(() => {
    api.get<{ status: string; archives: ArchiveItem[] }>('/api/archives')
      .then(res => {
        if (res.data.status === 'success') {
          setArchives(res.data.archives);
        }
      })
      .catch(() => { /* ignore */ })
      .finally(() => setLoading(false));
  }, []);

  // 刷新归档列表
  const refreshArchives = () => {
    api.get<{ status: string; archives: ArchiveItem[] }>('/api/archives')
      .then(res => {
        if (res.data.status === 'success') {
          setArchives(res.data.archives);
        }
      })
      .catch(() => { /* ignore */ });
  };

  // 确认删除
  const confirmDelete = () => {
    if (!deleteTarget) return;
    api.delete(`/api/archives/${encodeURIComponent(deleteTarget.id)}`)
      .then(() => {
        showToast('success', `已删除「${deleteTarget.name}」`);
        refreshArchives();
        setDeleteTarget(null);
      })
      .catch(() => {
        showToast('error', '删除失败，请重试');
        setDeleteTarget(null);
      });
  };

  // 迁移为 timeline 模式
  const handleMigrate = (archive: ArchiveItem) => {
    if (!archive.canMigrate) {
      showToast('info', '该归档缺少音频来源，无法重新生成时间轴');
      return;
    }
    setMigratingId(archive.id);
    api.post(`/api/archives/${encodeURIComponent(archive.id)}/migrate`)
      .then(() => {
        showToast('success', '时间轴模式归档已生成，可在资料库中查看');
        refreshArchives();
      })
      .catch(() => {
        showToast('error', '迁移失败，请重试');
      })
      .finally(() => setMigratingId(null));
  };

  // 计算继续收听
  const continueListening = useMemo(
    () => getTopProgress(archives, 5),
    [archives]
  );

  // 过滤 + 搜索后的归档列表
  const displayedArchives = useMemo(() => {
    let list = [...archives];

    if (search.trim()) {
      const q = search.trim().toLowerCase();
      list = list.filter(a => a.name.toLowerCase().includes(q));
    }

    if (filterAudio) {
      list = list.filter(a => a.hasAudio);
    }

    if (filterHasContent) {
      list = list.filter(a => a.hasSegments);
    }

    list.sort((a, b) => new Date(b.createTime).getTime() - new Date(a.createTime).getTime());

    return list;
  }, [archives, search, filterAudio, filterHasContent]);

  const hasActiveFilters = filterAudio || filterHasContent;

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-[#00ADA6]" />
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto bg-[#F5F5F5]">
      <div className="w-full px-8 py-8 pb-16">

        {/* ===== 顶部概览区 ===== */}
        <div className="mb-5">
          <h1 className="text-lg font-bold text-slate-800 mb-0.5">我的资料库</h1>
          <div className="flex items-center gap-3 text-xs text-slate-400">
            <span>{archives.length} 条归档</span>
            <span className="w-px h-3 bg-slate-300" />
            <span>{archives.filter(a => a.hasAudio).length} 条有音频</span>
            <span className="w-px h-3 bg-slate-300" />
            <span>{archives.filter(a => a.hasSegments).length} 条有时间轴</span>
          </div>
        </div>

        {/* ===== 继续收听 ===== */}
        <section className="mb-5">
          <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-3 flex items-center gap-2">
            <IconPlayerPlay size={12} className="text-[#00ADA6]" />
            继续收听
          </h2>

          {continueListening.length > 0 ? (
            <div className="flex gap-3 overflow-x-auto pb-1">
              {/* 固定显示前 5 条，每张卡 180px 正方形，不拉伸 */}
              {continueListening.slice(0, 5).map((item) => {
                const pct = Math.min(100, (item.lastPositionSeconds / item.duration) * 100);
                return (
                  <button
                    key={item.archiveId}
                    onClick={() => navigate(`/episode/${item.archiveId}`)}
                    className="relative w-[180px] h-[180px] flex-shrink-0 rounded-2xl overflow-hidden group cursor-pointer focus:outline-none"
                  >
                    {/* 封面层：占位图标 */}
                    <div className="absolute inset-0 bg-gradient-to-br from-[#00ADA6]/15 to-[#0891B2]/8 flex items-center justify-center">
                      <div className="w-12 h-12 rounded-xl bg-white/90 shadow-sm flex items-center justify-center">
                        <IconMicrophone size={22} className="text-[#00ADA6]" />
                      </div>
                    </div>

                    {/* 默认状态：仅底部极细进度线 */}
                    <div className="absolute bottom-0 left-0 right-0 h-[3px] bg-slate-200/60">
                      <div
                        className="h-full bg-[#00ADA6]/70 rounded-full transition-all"
                        style={{ width: `${pct}%` }}
                      />
                    </div>

                    {/* hover 状态：底部信息浮层 */}
                    <div className="absolute inset-0 bg-gradient-to-t from-black/75 via-black/30 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-200 flex flex-col justify-end">
                      {/* 标题 */}
                      <p className="text-sm font-medium text-white leading-snug line-clamp-2 px-3 pb-1">
                        {item.archive.name}
                      </p>

                      {/* 进度时间 */}
                      <p className="text-xs text-white/70 px-3 pb-2">
                        {formatTime(item.lastPositionSeconds)} / {formatTime(item.duration)}
                      </p>

                      {/* 进度条 */}
                      <div className="mx-3 mb-2 bg-white/30 rounded-full h-1">
                        <div
                          className="h-full bg-[#00ADA6] rounded-full"
                          style={{ width: `${pct}%` }}
                        />
                      </div>

                      {/* 继续播放入口 */}
                      <div className="flex items-center gap-1 px-3 pb-3">
                        <div className="w-5 h-5 rounded-full bg-[#00ADA6] flex items-center justify-center">
                          <IconPlayerPlay size={10} className="text-white ml-0.5" />
                        </div>
                        <span className="text-xs text-white/80">继续播放</span>
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>
          ) : (
            /* 空状态 */
            <div className="py-8 px-6 bg-white border border-slate-200 rounded-xl text-center">
              <p className="text-sm text-slate-400 mb-1">还没有继续收听内容</p>
              <p className="text-xs text-slate-300">去资料库打开一条音频开始播放吧</p>
            </div>
          )}
        </section>

        {/* ===== 搜索与筛选 ===== */}
        <section className="mb-4">
          <div className="flex items-center gap-2">
            {/* 搜索框 — 降权：更小、更轻 */}
            <div className="w-48 relative">
              <IconSearch size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                type="text"
                value={search}
                onChange={e => setSearch(e.target.value)}
                placeholder="搜索..."
                className="w-full pl-7 pr-7 py-1.5 text-xs bg-slate-50 border border-slate-200 rounded-lg focus:outline-none focus:border-[#00ADA6] transition-colors placeholder:text-slate-400"
              />
              {search && (
                <button
                  onClick={() => setSearch('')}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
                >
                  <IconX size={11} />
                </button>
              )}
            </div>
            {/* 筛选按钮 */}
            <button
              onClick={() => setFilterAudio(v => !v)}
              className={`px-2.5 py-1.5 text-xs rounded-lg border transition-colors ${
                filterAudio
                  ? 'bg-[#00ADA6] border-[#00ADA6] text-white'
                  : 'bg-white border-slate-200 text-slate-400 hover:border-slate-300'
              }`}
            >
              有音频
            </button>
            <button
              onClick={() => setFilterHasContent(v => !v)}
              className={`px-2.5 py-1.5 text-xs rounded-lg border transition-colors ${
                filterHasContent
                  ? 'bg-[#00ADA6] border-[#00ADA6] text-white'
                  : 'bg-white border-slate-200 text-slate-400 hover:border-slate-300'
              }`}
            >
              有时间轴
            </button>
          </div>
          {hasActiveFilters && (
            <div className="flex items-center gap-2 mt-2">
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

        {/* ===== 全部归档 ===== */}
        <section>
          <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-3 flex items-center gap-2">
            <IconChartBar size={13} className="text-slate-400" />
            全部归档
          </h2>
          <div className="bg-white border border-slate-200 rounded-2xl overflow-hidden">
            {displayedArchives.length === 0 ? (
              <div className="py-12 text-center">
                <div className="w-10 h-10 rounded-xl bg-slate-100 flex items-center justify-center mx-auto mb-2">
                  <IconMicrophone size={18} className="text-slate-300" />
                </div>
                <p className="text-sm text-slate-400">
                  {search ? '没有找到匹配的归档' : '暂无归档，导入音频开始使用'}
                </p>
              </div>
            ) : (
              displayedArchives.map((item) => (
                <div
                  key={item.id}
                  className="relative px-4 py-3.5 hover:bg-slate-50 transition-colors flex items-center gap-3 border-b border-slate-100 last:border-b-0 group"
                >
                  {/* 主内容：整行可点击 */}
                  <button
                    onClick={() => navigate(`/episode/${item.id}`)}
                    className="flex items-center gap-3 flex-1 min-w-0 text-left"
                  >
                    {/* 占位图标 */}
                    <div className={`w-8 h-8 rounded-lg flex items-center justify-center shrink-0 ${item.hasAudio ? 'bg-[#00ADA6]/10' : 'bg-slate-100'}`}>
                      <IconMicrophone size={14} className={item.hasAudio ? 'text-[#00ADA6]' : 'text-slate-400'} />
                    </div>

                    {/* 主信息：标题 + 时间分行 */}
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-slate-700 truncate group-hover:text-[#00ADA6] transition-colors leading-snug">
                        {item.name}
                      </p>
                      <p className="text-xs text-slate-400 mt-0.5">
                        {formatRelativeTime(item.createTime)}
                      </p>
                    </div>

                    {/* 状态标签 */}
                    <div className="flex items-center gap-1 shrink-0">
                      {/* 模式标签 */}
                      {item.mode === 'timeline' ? (
                        <span className="inline-flex items-center gap-1 px-1.5 py-0.5 text-xs rounded bg-purple-50 text-purple-500">
                          <IconTimelineEvent size={10} />
                          时间轴
                        </span>
                      ) : (
                        <span className="inline-flex items-center px-1.5 py-0.5 text-xs rounded bg-slate-100 text-slate-400">
                          总结
                        </span>
                      )}
                      {!item.hasAudio && (
                        <span className="inline-flex items-center px-1.5 py-0.5 text-xs rounded bg-slate-100 text-slate-400">
                          无音频
                        </span>
                      )}
                    </div>
                  </button>

                  {/* 迁移按钮 — summary 模式且可迁移时显示 */}
                  {item.mode === 'summary' && item.canMigrate && (
                    <button
                      onClick={(e) => { e.stopPropagation(); handleMigrate(item); }}
                      disabled={migratingId === item.id}
                      className="flex items-center gap-1 px-2 py-1 rounded-md text-xs text-purple-500 hover:bg-purple-50 transition-colors opacity-0 group-hover:opacity-100 shrink-0"
                      title="转换为时间轴模式"
                    >
                      {migratingId === item.id ? (
                        <div className="w-3.5 h-3.5 border border-purple-300 border-t-purple-500 rounded-full animate-spin" />
                      ) : (
                        <IconTimelineEvent size={12} />
                      )}
                      <span className="hidden group-hover:inline text-xs">转时间轴</span>
                    </button>
                  )}

                  {/* 删除按钮 — hover 时显示在右侧 */}
                  <button
                    onClick={(e) => { e.stopPropagation(); setDeleteTarget({ id: item.id, name: item.name }); }}
                    className="p-1.5 rounded-md text-slate-300 hover:text-red-400 hover:bg-red-50 transition-colors opacity-0 group-hover:opacity-100 shrink-0"
                    title="删除归档"
                  >
                    <IconTrash size={14} />
                  </button>

                  {/* 进入箭头 */}
                  <IconPlayerPlay size={12} className="text-slate-200 group-hover:text-[#00ADA6] transition-colors shrink-0" />
                </div>
              ))
            )}
          </div>
        </section>

        {/* 删除确认对话框 */}
        {deleteTarget && (
          <ConfirmDialog
            isOpen={true}
            title="删除归档"
            message={`确定要删除 "${deleteTarget.name}" 吗？此操作不可恢复。`}
            confirmText="删除"
            cancelText="取消"
            onConfirm={confirmDelete}
            onCancel={() => setDeleteTarget(null)}
            danger
          />
        )}

      </div>
    </div>
  );
}
