/**
 * EpisodePage — 播放器详情页
 *
 * 数据来源：/api/archives/:id
 *  - name, summary, rawText, createTime, audioUrl, timeline, transcriptSegments
 *
 * 时间轴：
 *  - highlights：从 summary.md 解析真实时间戳条目
 *  - transcriptSegments：从 segments.json 获取完整转录分段
 *  - chapters / terms：后端当前返回空数组，待后续扩展
 *
 * 三向联动：
 *  - <audio> 当前播放时间 ↔ highlights 高亮 ↔ transcript segments 高亮
 */
import { useState, useEffect, useRef, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import axios from 'axios';
import {
  IconChevronLeft, IconPlayerPlay, IconClock,
  IconMessageCircle, IconPlayerSkipForward, IconCheck,
  IconChevronDown, IconChevronRight
} from '@tabler/icons-react';

const api = axios.create({ baseURL: 'http://localhost:8000' });

// ===== 类型 =====

interface TimelineItem {
  id: string;
  title: string;
  time: string;        // "MM:SS"
  seconds: number;     // 总秒数
  description?: string;
}

interface Timeline {
  chapters: TimelineItem[];
  highlights: TimelineItem[];
  terms: TimelineItem[];
}

interface ArchiveDetail {
  id: string;
  name: string;
  summary: string;
  rawText: string;
  createTime: string;
  audioUrl: string | null;
  timeline: Timeline;
  transcriptSegments: TimelineItem[];
}

type TimelineTab = 'chapters' | 'highlights' | 'terms' | 'segments';

// ===== 工具函数 =====

/** 根据当前秒数，从列表中找出"当前属于哪一项"（最后一项 startTime <= currentTime） */
function findActiveItem(items: TimelineItem[], currentTime: number): TimelineItem | null {
  if (!items || items.length === 0) return null;
  let active: TimelineItem | null = null;
  for (const item of items) {
    if (item.seconds <= currentTime) {
      active = item;
    } else {
      break;
    }
  }
  return active;
}

/** 格式化秒数为 M:SS */
function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
}

// ===== 主组件 =====

export default function EpisodePage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  // 数据
  const [archive, setArchive] = useState<ArchiveDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // 播放器状态
  const audioRef = useRef<HTMLAudioElement>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);

  // 时间轴状态
  const [activeTab, setActiveTab] = useState<TimelineTab>('highlights');

  // 选中项（用户主动点击）
  const [selectedItem, setSelectedItem] = useState<TimelineItem | null>(null);

  // 播放时间自动高亮的项（由 currentTime 驱动）
  const [autoHighlightItem, setAutoHighlightItem] = useState<TimelineItem | null>(null);

  // 摘要折叠
  const [summaryCollapsed, setSummaryCollapsed] = useState(true);

  // 列表滚动容器的 ref
  const listScrollRef = useRef<HTMLDivElement>(null);

  // 最后一次滚动处理的时间戳（用于防抖）
  const lastScrollTime = useRef(0);

  // 获取 archive 详情
  useEffect(() => {
    if (!id) return;
    setLoading(true);
    api.get<{ status: string; data: ArchiveDetail }>(`/api/archives/${id}`)
      .then(res => {
        if (res.data.status === 'success') {
          setArchive(res.data.data);
          // 默认选中第一个高光
          if (res.data.data.timeline.highlights.length > 0) {
            setSelectedItem(res.data.data.timeline.highlights[0]);
            setAutoHighlightItem(res.data.data.timeline.highlights[0]);
          } else if (res.data.data.transcriptSegments.length > 0) {
            setSelectedItem(res.data.data.transcriptSegments[0]);
            setAutoHighlightItem(res.data.data.transcriptSegments[0]);
          }
        }
      })
      .catch(() => setError('加载归档失败'))
      .finally(() => setLoading(false));
  }, [id]);

  // ===== 音频事件 =====

  // 节流：只在使用 requestAnimationFrame 时更新 currentTime，避免过于频繁触发
  const rafRef = useRef<number | null>(null);
  const lastUpdateRef = useRef<number>(0);

  const handleTimeUpdate = useCallback(() => {
    if (!audioRef.current) return;
    const now = performance.now();
    // 节流：每 200ms 更新一次
    if (now - lastUpdateRef.current < 200) return;
    lastUpdateRef.current = now;
    const t = audioRef.current.currentTime;
    setCurrentTime(t);
  }, []);

  const handleLoadedMetadata = () => {
    if (audioRef.current) setDuration(audioRef.current.duration);
  };

  const togglePlay = () => {
    if (!audioRef.current || !archive?.audioUrl) return;
    if (isPlaying) {
      audioRef.current.pause();
    } else {
      audioRef.current.play();
    }
    setIsPlaying(!isPlaying);
  };

  const seekTo = (seconds: number) => {
    if (audioRef.current) {
      audioRef.current.currentTime = seconds;
      setCurrentTime(seconds);
    }
  };

  // ===== 双向联动逻辑 =====

  /** 滚动列表使指定 item 可见（节流：每 300ms 最多一次） */
  const scrollToItem = useCallback((item: TimelineItem | null) => {
    if (!item) return;
    const now = Date.now();
    if (now - lastScrollTime.current < 300) return;
    lastScrollTime.current = now;

    const container = listScrollRef.current;
    if (!container) return;

    // 在容器内找到对应按钮
    const buttons = container.querySelectorAll('[data-item-id]');
    for (const btn of buttons) {
      if (btn.getAttribute('data-item-id') === item.id) {
        (btn as HTMLButtonElement).scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        break;
      }
    }
  }, []);

  /** 用户点击时间轴条目 */
  const handleItemClick = (item: TimelineItem) => {
    // 1. 记录用户选中（不再被自动高亮覆盖）
    setSelectedItem(item);

    // 2. seek 播放器
    if (archive?.audioUrl && audioRef.current) {
      audioRef.current.currentTime = item.seconds;
    }

    // 3. 若当前是 highlights tab，点击后联动滚动到对应 transcript segment
    if (activeTab === 'highlights' && archive) {
      const seg = findActiveItem(archive.transcriptSegments, item.seconds);
      if (seg) {
        // 同步更新 autoHighlightItem，避免等待 onTimeUpdate 的竞态
        setAutoHighlightItem(seg);
        setActiveTab('segments');
        // 切换 tab 后等 DOM 更新再滚动
        setTimeout(() => scrollToItem(seg), 50);
      }
    } else if (activeTab === 'segments') {
      // 在 segments tab 点击，直接滚动
      scrollToItem(item);
    }
  };

  /** 用户点击 transcript segment */
  const handleSegmentClick = (seg: TimelineItem) => {
    // 1. 记录用户选中
    setSelectedItem(seg);

    // 2. seek 播放器
    if (archive?.audioUrl && audioRef.current) {
      audioRef.current.currentTime = seg.seconds;
    }

    // 3. 联动 highlight：找到包含该时间的 highlight，同步更新 autoHighlightItem
    if (archive) {
      const hl = findActiveItem(archive.timeline.highlights, seg.seconds);
      if (hl) {
        setSelectedItem(hl);
        setAutoHighlightItem(hl);
      }
      // 始终在 segments tab 中滚动
      scrollToItem(seg);
    }
  };

  // ===== 自动高亮逻辑（由 currentTime 驱动，tab 切换时保持已选中的项） =====

  // 驱动 autoHighlightItem 的主 effect：仅在 currentTime 变化时更新
  useEffect(() => {
    if (!archive) return;

    if (activeTab === 'segments') {
      const seg = findActiveItem(archive.transcriptSegments, currentTime);
      if (seg && seg.id !== autoHighlightItem?.id) {
        setAutoHighlightItem(seg);
      }
    } else if (activeTab === 'highlights') {
      const hl = findActiveItem(archive.timeline.highlights, currentTime);
      if (hl && hl.id !== autoHighlightItem?.id) {
        setAutoHighlightItem(hl);
      }
    }
  }, [currentTime, archive]);

  // tab 切换 effect：若切换到的 tab 没有当前播放时间对应的高亮项，
  // 则复用用户选中的 selectedItem（避免切换 tab 时清空已选内容）
  useEffect(() => {
    if (!archive) return;
    // 只有 chapters / terms tab 需要用 selectedItem 补充
    if (activeTab !== 'chapters' && activeTab !== 'terms') return;
    if (selectedItem) {
      setAutoHighlightItem(selectedItem);
    }
  }, [activeTab, archive]);

  // ===== 渲染辅助 =====

  // 当前 tab 的列表
  const currentItems = activeTab === 'segments'
    ? (archive?.transcriptSegments ?? [])
    : (archive?.timeline[activeTab] ?? []);

  // 当前高亮的项：优先用 autoHighlightItem（播放驱动），fallback 到 selectedItem（用户点击）
  const highlightedItem = autoHighlightItem ?? selectedItem;

  // 渲染单个时间轴条目
  const renderItem = (item: TimelineItem) => {
    const isHighlighted = highlightedItem?.id === item.id;
    const isSelected = selectedItem?.id === item.id;

    const handleClick = () => {
      if (activeTab === 'segments') {
        handleSegmentClick(item);
      } else {
        handleItemClick(item);
      }
    };

    return (
      <button
        key={item.id}
        data-item-id={item.id}
        onClick={handleClick}
        className={`w-full text-left px-3 py-2.5 rounded-lg transition-all flex items-center gap-3 ${
          isHighlighted
            ? 'bg-[#D1FAF5] border border-[#00ADA6]/30'
            : isSelected
              ? 'bg-[#D1FAF5] border border-[#00ADA6]/30'
              : 'hover:bg-slate-50'
        }`}
      >
        <span className={`text-sm font-mono font-medium w-12 shrink-0 ${
          isHighlighted ? 'text-[#00ADA6]' : 'text-slate-400'
        }`}>
          {item.time}
        </span>
        <span className={`text-sm flex-1 ${
          isHighlighted ? 'text-[#00ADA6] font-medium' : 'text-slate-700'
        }`}>
          {activeTab === 'segments' ? item.text : item.title}
        </span>
        {isHighlighted && (
          <span className="w-1.5 h-1.5 rounded-full bg-[#00ADA6] shrink-0" />
        )}
      </button>
    );
  };

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center h-full">
        <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-[#00ADA6]" />
      </div>
    );
  }

  if (error || !archive) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center h-full text-slate-500">
        <p>{error || '无效的归档'}</p>
        <button onClick={() => navigate('/')} className="mt-4 text-[#00ADA6] hover:underline">
          返回首页
        </button>
      </div>
    );
  }

  const hasAudio = !!archive.audioUrl;

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden bg-white">

      {/* ===== 顶部信息区 ===== */}
      <div className="border-b border-slate-200 px-8 py-4 flex items-center gap-4 bg-white">
        <button
          onClick={() => navigate('/')}
          className="flex items-center gap-1 text-slate-500 hover:text-slate-700 transition-colors"
        >
          <IconChevronLeft size={20} />
          <span className="text-sm">返回</span>
        </button>
        <div className="h-6 w-px bg-slate-200" />
        <div className="flex items-center gap-2">
          <div className="w-10 h-10 rounded-lg bg-[#D1FAF5] flex items-center justify-center shrink-0">
            <IconMessageCircle size={18} className="text-[#00ADA6]" />
          </div>
          <div>
            <h1 className="text-base font-semibold text-slate-800 leading-snug">{archive.name}</h1>
            <p className="text-xs text-slate-400 flex items-center gap-1">
              {archive.createTime && <><IconClock size={12} />{archive.createTime}</>}
              {duration > 0 && <span className="ml-2">· {formatTime(duration)}</span>}
              {!hasAudio && <span className="ml-2 text-amber-500">· 音频不可用</span>}
            </p>
          </div>
        </div>
      </div>

      {/* ===== 主内容 ===== */}
      <div className="flex-1 flex overflow-hidden">

        {/* 左侧：播放器 + 时间轴 */}
        <div className="flex-1 flex flex-col overflow-hidden">

          {/* ===== 播放器区 ===== */}
          <div className="px-8 py-5 border-b border-slate-100 shrink-0">
            <div className="flex items-center gap-4">
              {hasAudio && (
                <audio
                  ref={audioRef}
                  src={archive.audioUrl!}
                  onTimeUpdate={handleTimeUpdate}
                  onLoadedMetadata={handleLoadedMetadata}
                  onPlay={() => setIsPlaying(true)}
                  onPause={() => setIsPlaying(false)}
                  onEnded={() => setIsPlaying(false)}
                />
              )}
              <button
                onClick={togglePlay}
                disabled={!hasAudio}
                className={`w-12 h-12 rounded-full flex items-center justify-center transition-colors shrink-0 ${
                  hasAudio
                    ? 'bg-[#00ADA6] hover:bg-[#009A94] text-white'
                    : 'bg-slate-200 text-slate-400 cursor-not-allowed'
                }`}
              >
                {isPlaying
                  ? <IconPlayerSkipForward size={20} className="ml-0.5" />
                  : <IconPlayerPlay size={20} className="ml-0.5" />
                }
              </button>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-3">
                  <span className="text-xs text-slate-400 font-mono w-10 shrink-0">{formatTime(currentTime)}</span>
                  <div className="flex-1 h-1.5 bg-slate-100 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-[#00ADA6] rounded-full transition-all duration-200"
                      style={{ width: duration > 0 ? `${(currentTime / duration) * 100}%` : '0%' }}
                    />
                  </div>
                  <span className="text-xs text-slate-400 font-mono w-10 shrink-0">{formatTime(duration)}</span>
                </div>
              </div>
            </div>
          </div>

          {/* ===== 时间轴区（可滚动） ===== */}
          <div className="flex-1 overflow-hidden flex flex-col">
            <div className="px-8 py-4 border-b border-slate-100 shrink-0">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-semibold text-slate-700">时间轴</h2>
                <div className="flex gap-1 bg-slate-100 rounded-lg p-1">
                  {(['chapters', 'highlights', 'terms', 'segments'] as TimelineTab[]).map(tab => {
                    const count = tab === 'segments'
                      ? archive.transcriptSegments.length
                      : archive.timeline[tab].length;
                    return (
                      <button
                        key={tab}
                        onClick={() => setActiveTab(tab)}
                        className={`px-3 py-1 text-xs rounded-md transition-colors ${
                          activeTab === tab
                            ? 'bg-white text-[#00ADA6] shadow-sm font-medium'
                            : 'text-slate-500 hover:text-slate-700'
                        }`}
                      >
                        {tab === 'chapters' ? '章节' : tab === 'highlights' ? '高光' : tab === 'terms' ? '术语' : '转录'}
                        {count > 0 && <span className="ml-1 text-[10px] opacity-60">({count})</span>}
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>

            {/* 可滚动的列表区域 */}
            <div
              ref={listScrollRef}
              className="flex-1 overflow-y-auto px-8 py-3"
            >
              {currentItems.length === 0 ? (
                <p className="text-sm text-slate-400 py-6 text-center">
                  {activeTab === 'chapters' ? '暂无章节信息' :
                   activeTab === 'highlights' ? '暂无高光时间轴' :
                   activeTab === 'terms' ? '暂无术语解释' : '暂无转录分段'}
                </p>
              ) : (
                <div className="space-y-1 pb-4">
                  {currentItems.map(renderItem)}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* ===== 右侧节点说明区 ===== */}
        <div className="w-80 border-l border-slate-200 overflow-y-auto p-6 bg-slate-50 flex flex-col gap-4">

          {/* 当前节点说明 */}
          <div>
            <h2 className="text-sm font-semibold text-slate-700 mb-3">节点说明</h2>
            {highlightedItem ? (
              <div className="space-y-3">
                <div className="inline-flex items-center px-2.5 py-1 bg-[#D1FAF5] text-[#00ADA6] text-sm font-mono font-medium rounded">
                  {highlightedItem.time}
                </div>
                <h3 className="text-base font-semibold text-slate-800 leading-snug">
                  {activeTab === 'segments' ? highlightedItem.text : highlightedItem.title}
                </h3>
                {highlightedItem.description && activeTab !== 'segments' && (
                  <p className="text-sm text-slate-600 leading-relaxed">{highlightedItem.description}</p>
                )}
                {hasAudio && (
                  <button
                    onClick={() => seekTo(highlightedItem.seconds)}
                    className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-[#00ADA6] hover:bg-[#009A94] text-white text-sm font-medium rounded-lg transition-colors"
                  >
                    <IconPlayerPlay size={16} />
                    跳转到此处播放
                  </button>
                )}
              </div>
            ) : (
              <div className="text-center py-8">
                <IconClock size={32} className="text-slate-300 mx-auto mb-3" />
                <p className="text-sm text-slate-400">
                  点击时间轴节点<br />查看详细说明
                </p>
              </div>
            )}
          </div>

          {/* 摘要区块 — 可折叠 */}
          {archive.summary && (
            <div className="pt-4 border-t border-slate-200">
              <button
                onClick={() => setSummaryCollapsed(c => !c)}
                className="w-full flex items-center justify-between mb-2"
              >
                <h3 className="text-sm font-semibold text-slate-700">本期摘要</h3>
                {summaryCollapsed
                  ? <IconChevronRight size={14} className="text-slate-400" />
                  : <IconChevronDown size={14} className="text-slate-400" />
                }
              </button>
              {!summaryCollapsed && (
                <p className="text-xs text-slate-500 leading-relaxed whitespace-pre-wrap">
                  {archive.summary}
                </p>
              )}
            </div>
          )}
        </div>

      </div>
    </div>
  );
}
