/**
 * EpisodePage — 播放器详情页
 *
 * 数据来源：/api/archives/:id
 *  - name, summary, rawText, createTime, audioUrl, timeline, transcriptSegments
 *  - mode, metadata, timelineData (timeline 模式才有)
 *
 * 三种联动模式：
 *  - summary 模式：<audio> 当前播放时间 ↔ highlights 高亮 ↔ transcript segments 高亮
 *  - timeline 模式：<audio> 当前播放时间 → 自动高亮当前节点（center card） ↔ 右侧节点列表
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import axios from 'axios';
import {
  IconChevronLeft, IconPlayerPlay, IconClock,
  IconMessageCircle, IconPlayerSkipForward, IconRewindBackward15,
  IconRewindForward30,
  IconChevronDown, IconExternalLink
} from '@tabler/icons-react';
import { resolveApiAssetUrl, resolveMediaUrl } from '../utils/apiAsset';

const api = axios.create({ baseURL: 'http://localhost:8000' });
const PROGRESS_KEY = 'podgist_play_progress';

// ===== 类型 =====

interface TimelineItem {
  id: string;
  title: string;
  time: string;        // "MM:SS"
  seconds: number;     // 总秒数
  description?: string;
  text?: string;       // transcript segment text (segments tab)
}

interface Timeline {
  chapters: TimelineItem[];
  highlights: TimelineItem[];
  terms: TimelineItem[];
}

interface Reference {
  title: string;
  url: string;
  source: string;
  kind: string;
  confidence: number;
  note: string;
}

interface TimelineNode {
  id: string;
  start: number;
  end: number;
  time: string;
  title: string;
  node_type: string;
  summary: string;
  why_it_matters: string;
  entities: Array<{
    name: string;
    type: string;
    description: string;
    refUrl?: string;
    refTitle?: string;
    sourceTier?: string;
    media?: { filename?: string; source_url?: string; remote_url?: string };
  }>;
  facts: Array<{ label: string; value: string }>;
  quote_or_joke_explainer: string;
  references: Reference[];
  media: unknown[];
}

interface TimelineData {
  mode: string;
  version: number;
  title: string;
  nodes: TimelineNode[];
}

interface ArchiveDetail {
  id: string;
  name: string;
  summary: string;
  rawText: string;
  createTime: string;
  audioUrl: string | null;
  coverUrl?: string | null;
  timeline: Timeline;
  transcriptSegments: TimelineItem[];
  mode?: string;
  metadata?: Record<string, unknown>;
  timelineData?: TimelineData;
  enrichmentStatus?: 'PENDING' | 'PROCESSING' | 'COMPLETED' | 'FAILED' | null;
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

/** 根据当前秒数，从 timeline nodes 中找出当前节点（node.start <= currentTime < node.end） */
function findActiveNode(nodes: TimelineNode[], currentTime: number): TimelineNode | null {
  if (!nodes || nodes.length === 0) return null;
  let active: TimelineNode | null = null;
  for (const node of nodes) {
    if (node.start <= currentTime) {
      active = node;
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

  // ===== summary 模式状态 =====
  const [activeTab, setActiveTab] = useState<TimelineTab>('chapters');
  const [selectedItem, setSelectedItem] = useState<TimelineItem | null>(null);
  const [autoHighlightItem, setAutoHighlightItem] = useState<TimelineItem | null>(null);

  // ===== timeline 模式状态 =====
  const [currentNode, setCurrentNode] = useState<TimelineNode | null>(null);
  const [selectedNode, setSelectedNode] = useState<TimelineNode | null>(null);

  // 摘要折叠
  const [summaryCollapsed, setSummaryCollapsed] = useState(true);

  // 列表滚动容器的 ref
  const listScrollRef = useRef<HTMLDivElement>(null);
  const nodeListRef = useRef<HTMLDivElement>(null);
  const lastPrioritizedNodeId = useRef<string | null>(null);

  // 最后一次滚动处理的时间戳（用于防抖）
  const lastScrollTime = useRef(0);

  // 获取 archive 详情
  useEffect(() => {
    if (!id) return;
    queueMicrotask(() => setLoading(true));
    api.get<{ status: string; data: ArchiveDetail }>(`/api/archives/${id}`)
      .then(res => {
        if (res.data.status === 'success') {
          setArchive(res.data.data);
          const data = res.data.data;
          const chapters = data.timeline.chapters;
          const highlights = data.timeline.highlights;
          const segments = data.transcriptSegments;

          // summary 模式默认选中
          if (chapters.length > 0) {
            setSelectedItem(chapters[0]);
            setAutoHighlightItem(chapters[0]);
          } else if (highlights.length > 0) {
            setSelectedItem(highlights[0]);
            setAutoHighlightItem(highlights[0]);
          } else if (segments.length > 0) {
            setSelectedItem(segments[0]);
            setAutoHighlightItem(segments[0]);
          }

          // timeline 模式默认跟随播放进度。selectedNode 只表示用户手动点选的节点。
          if (data.timelineData?.nodes?.length) {
            setCurrentNode(data.timelineData.nodes[0]);
            setSelectedNode(null);
          }
        }
      })
      .catch(() => setError('加载归档失败'))
      .finally(() => setLoading(false));
  }, [id]);

  // 外部实体资料在后台补充完成后，仅刷新时间轴数据；不重置播放状态或用户选择。
  useEffect(() => {
    if (!id || !archive?.timelineData) return;
    if (archive.enrichmentStatus !== 'PENDING' && archive.enrichmentStatus !== 'PROCESSING') return;

    const interval = window.setInterval(() => {
      api.get<{ status: string; data: ArchiveDetail }>(`/api/archives/${id}`)
        .then(res => {
          if (res.data.status !== 'success') return;
          setArchive(previous => previous ? {
            ...previous,
            timelineData: res.data.data.timelineData,
            enrichmentStatus: res.data.data.enrichmentStatus,
          } : previous);
        })
        .catch(() => { /* 后台富化失败不影响当前节目使用 */ });
    }, 4000);

    return () => window.clearInterval(interval);
  }, [id, archive?.enrichmentStatus, archive?.timelineData]);

  // ===== 从 localStorage 恢复播放进度（仅一次，首次 audio 加载完成后）=====
  const progressRestoredRef = useRef(false);
  useEffect(() => {
    if (!archive || !audioRef.current || progressRestoredRef.current) return;
    if (duration <= 0) return;
    progressRestoredRef.current = true;
    try {
      const raw = localStorage.getItem('podgist_play_progress');
      if (!raw) return;
      const all: Record<string, { archiveId: string; lastPositionSeconds: number; duration: number; updatedAt: number }> = JSON.parse(raw);
      const saved = id ? all[id] : null;
      if (saved && saved.lastPositionSeconds > 0 && saved.lastPositionSeconds < saved.duration - 5) {
        audioRef.current.currentTime = saved.lastPositionSeconds;
        audioRef.current.pause();
        queueMicrotask(() => {
          setIsPlaying(false);
          setCurrentTime(saved.lastPositionSeconds);
        });
      }
    } catch { /* 忽略损坏或过期的本地播放进度 */ }
  }, [archive, duration, id]);

  // ===== 播放进度本地存储 =====

  const lastSaveRef = useRef(0);
  const saveProgress = useCallback((seconds: number, dur: number) => {
    if (!id || !dur || dur <= 0) return;
    const now = Date.now();
    if (now - lastSaveRef.current < 10000) return;
    lastSaveRef.current = now;
    try {
      const raw = localStorage.getItem(PROGRESS_KEY);
      const all: Record<string, { archiveId: string; lastPositionSeconds: number; duration: number; updatedAt: number }> = raw ? JSON.parse(raw) : {};
      all[id] = { archiveId: id, lastPositionSeconds: seconds, duration: dur, updatedAt: now };
      localStorage.setItem(PROGRESS_KEY, JSON.stringify(all));
    } catch { /* localStorage 不可用时不影响播放 */ }
  }, [id]);

  // ===== 音频事件 =====

  const lastUpdateRef = useRef<number>(0);

  const handleTimeUpdate = useCallback(() => {
    if (!audioRef.current) return;
    const now = performance.now();
    if (now - lastUpdateRef.current < 200) return;
    lastUpdateRef.current = now;
    const t = audioRef.current.currentTime;
    setCurrentTime(t);
    saveProgress(t, audioRef.current.duration || 0);
  }, [saveProgress]);

  const handleLoadedMetadata = () => {
    if (!audioRef.current) return;
    const dur = audioRef.current.duration;
    setDuration(dur);
  };

  const togglePlay = useCallback(() => {
    if (!audioRef.current || !archive?.audioUrl) return;
    if (audioRef.current.paused) {
      audioRef.current.play();
    } else {
      audioRef.current.pause();
    }
  }, [archive?.audioUrl]);

  const seekTo = useCallback((seconds: number) => {
    if (!audioRef.current) return;
    const clamped = Math.max(0, Math.min(seconds, duration));
    audioRef.current.currentTime = clamped;
    // 注意：不在这里调用 setCurrentTime，由 onTimeUpdate 自然同步
  }, [duration]);

  // 读取音频真实当前位置，避免闭包捕获旧 state 值
  const skipForward30 = useCallback(() => {
    if (!audioRef.current) return;
    seekTo(audioRef.current.currentTime + 30);
  }, [seekTo]);
  const skipBackward15 = useCallback(() => {
    if (!audioRef.current) return;
    seekTo(audioRef.current.currentTime - 15);
  }, [seekTo]);

  // ===== 时间轴自动高亮（summary 模式）=====

  useEffect(() => {
    if (!archive) return;

    if (activeTab === 'segments') {
      const seg = findActiveItem(archive.transcriptSegments, currentTime);
      if (seg && seg.id !== autoHighlightItem?.id) {
        queueMicrotask(() => setAutoHighlightItem(seg));
      }
    } else if (activeTab === 'highlights') {
      const hl = findActiveItem(archive.timeline.highlights, currentTime);
      if (hl && hl.id !== autoHighlightItem?.id) {
        queueMicrotask(() => setAutoHighlightItem(hl));
      }
    }
  }, [activeTab, archive, autoHighlightItem?.id, currentTime]);

  useEffect(() => {
    if (!archive) return;
    if (activeTab !== 'chapters' && activeTab !== 'terms') return;
    if (selectedItem) {
      queueMicrotask(() => setAutoHighlightItem(selectedItem));
    }
  }, [activeTab, archive, selectedItem]);

  // ===== 时间轴自动高亮（timeline 模式）=====

  useEffect(() => {
    if (!archive?.timelineData?.nodes) return;
    const node = findActiveNode(archive.timelineData.nodes, currentTime);
    if (!node) return;

    queueMicrotask(() => {
      setCurrentNode(prev => (prev?.id === node.id ? prev : node));
      setSelectedNode(prev => (prev && prev.id !== node.id ? null : prev));
    });
  }, [currentTime, archive]);

  // 流媒体式资料富化：当前节点优先，后端同时预加载相邻节点。
  // 只在切换节点或用户手动跳转时触发，不随每秒播放进度重复请求。
  useEffect(() => {
    if (!id || !archive?.timelineData?.nodes?.length) return;
    if (archive.enrichmentStatus === 'COMPLETED') return;
    const focusedNode = selectedNode ?? currentNode ?? archive.timelineData.nodes[0];
    if (!focusedNode || focusedNode.id === lastPrioritizedNodeId.current) return;

    const timeout = window.setTimeout(() => {
      api.post(`/api/archives/${encodeURIComponent(id)}/enrichment/priority`, {
        node_id: focusedNode.id,
      })
        .then(() => {
          lastPrioritizedNodeId.current = focusedNode.id;
        })
        .catch(() => { /* 富化网络异常不影响播放和时间轴阅读 */ });
    }, 350);

    return () => window.clearTimeout(timeout);
  }, [id, archive?.enrichmentStatus, archive?.timelineData, currentNode, selectedNode]);

  useEffect(() => {
    const activeNode = selectedNode ?? currentNode;
    const container = nodeListRef.current;
    if (!activeNode || !container) return;

    const activeButton = container.querySelector(
      `[data-node-id="${CSS.escape(activeNode.id)}"]`
    ) as HTMLElement | null;
    if (!activeButton) return;

    const targetTop =
      activeButton.offsetTop -
      (container.clientHeight / 2) +
      (activeButton.offsetHeight / 2);
    const maxScrollTop = Math.max(0, container.scrollHeight - container.clientHeight);
    const nextScrollTop = Math.max(0, Math.min(targetTop, maxScrollTop));

    container.scrollTo({ top: nextScrollTop, behavior: 'smooth' });
  }, [currentNode, selectedNode]);

  // ===== 键盘快捷键 =====
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // 忽略在 input/textarea/contenteditable 中的按键
      const target = e.target as HTMLElement;
      if (
        target.tagName === 'INPUT' ||
        target.tagName === 'TEXTAREA' ||
        target.isContentEditable
      ) {
        return;
      }

      if (e.key === 'ArrowLeft') {
        e.preventDefault();
        skipBackward15();
      } else if (e.key === 'ArrowRight') {
        e.preventDefault();
        skipForward30();
      } else if (e.key === ' ') {
        e.preventDefault();
        togglePlay();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [skipBackward15, skipForward30, togglePlay]);

  // ===== 双向联动逻辑（summary 模式）=====

  const scrollToItem = useCallback((item: TimelineItem | null) => {
    if (!item) return;
    const now = Date.now();
    if (now - lastScrollTime.current < 300) return;
    lastScrollTime.current = now;

    const container = listScrollRef.current;
    if (!container) return;

    const buttons = container.querySelectorAll('[data-item-id]');
    for (const btn of buttons) {
      if (btn.getAttribute('data-item-id') === item.id) {
        (btn as HTMLButtonElement).scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        break;
      }
    }
  }, []);

  const handleItemClick = (item: TimelineItem) => {
    setSelectedItem(item);
    if (archive?.audioUrl && audioRef.current) {
      audioRef.current.currentTime = item.seconds;
    }
    if (archive) {
      const hl = findActiveItem(archive.timeline.highlights, item.seconds);
      if (hl) {
        setAutoHighlightItem(hl);
      }
    }
    if (activeTab === 'highlights' && archive) {
      const seg = findActiveItem(archive.transcriptSegments, item.seconds);
      if (seg) {
        setAutoHighlightItem(seg);
        setActiveTab('segments');
        setTimeout(() => scrollToItem(seg), 50);
      }
    } else if (activeTab === 'segments') {
      scrollToItem(item);
    }
  };

  const handleSegmentClick = (seg: TimelineItem) => {
    setSelectedItem(seg);
    if (archive?.audioUrl && audioRef.current) {
      audioRef.current.currentTime = seg.seconds;
    }
    if (archive) {
      const hl = findActiveItem(archive.timeline.highlights, seg.seconds);
      if (hl) {
        setSelectedItem(hl);
        setAutoHighlightItem(hl);
      }
      scrollToItem(seg);
    }
  };

  // ===== timeline 模式：节点点击 → seek =====

  const handleNodeClick = (node: TimelineNode, e: React.MouseEvent) => {
    e.stopPropagation();
    setSelectedNode(node);
    // 直接跳转到节点起始时间（新协议：span 边界由程序确定，start 即话题开始）
    seekTo(node.start);
  };

  // ===== 渲染辅助（summary 模式）=====

  const currentItems = activeTab === 'segments'
    ? (archive?.transcriptSegments ?? [])
    : (archive?.timeline[activeTab] ?? []);

  const highlightedItem = autoHighlightItem ?? selectedItem;

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
        className={`w-full text-left px-2.5 py-2 rounded-lg transition-all flex items-center gap-2.5 ${
          isHighlighted
            ? 'bg-[#D1FAF5] border border-[#00ADA6]/30'
            : isSelected
              ? 'bg-[#D1FAF5] border border-[#00ADA6]/30'
              : 'hover:bg-slate-50'
        }`}
      >
        <span className={`text-xs font-mono font-medium w-11 shrink-0 ${
          isHighlighted ? 'text-[#00ADA6]' : 'text-slate-400'
        }`}>
          {item.time}
        </span>
        <span className={`text-xs flex-1 leading-relaxed ${
          isHighlighted ? 'text-[#00ADA6] font-medium' : 'text-slate-600'
        }`}>
          {activeTab === 'segments' ? item.text : item.title}
        </span>
        {isHighlighted && (
          <span className="w-1 h-1 rounded-full bg-[#00ADA6] shrink-0" />
        )}
      </button>
    );
  };

  // ===== Timeline 模式视图 =====

  const renderTimelineMode = () => {
    const nodes = archive?.timelineData?.nodes ?? [];
    const activeNode = selectedNode ?? currentNode;

    // 节点类型 → 配色（品牌色系深浅变化，避免彩虹化）
    const nodeTypeConfig: Record<string, { bg: string; text: string; label: string }> = {
      // 公司动态 / 产品 / 人物 — 同一品牌色系，用深浅区分
      company_news: { bg: 'bg-[#00ADA6]/10', text: 'text-[#00ADA6]', label: '公司动态' },
      product:      { bg: 'bg-[#00ADA6]/8',  text: 'text-[#007A75]', label: '产品' },
      person:       { bg: 'bg-[#0891B2]/10', text: 'text-[#0891B2]', label: '人物' },
      // 背景/话题切换 — 用中性 slate 深浅
      topic_change: { bg: 'bg-slate-100',    text: 'text-slate-500',  label: '话题切换' },
      background:   { bg: 'bg-slate-50',     text: 'text-slate-400',  label: '背景' },
      // 趣味/金句 — 改用主题青蓝色调
      fun_moment:   { bg: 'bg-[#00ADA6]/10', text: 'text-[#00ADA6]', label: '趣味时刻' },
      // 合并 quote → fun_moment
      quote:        { bg: 'bg-[#00ADA6]/10', text: 'text-[#00ADA6]', label: '趣味时刻' },
      other:        { bg: 'bg-slate-50',     text: 'text-slate-400',  label: '其他' },
    };
    const tc = activeNode?.node_type
      ? (nodeTypeConfig[activeNode.node_type] ?? nodeTypeConfig['other'])
      : null;

    // 实体类型 → 配色（品牌色系，避免彩虹化）
    const entityTypeColors: Record<string, string> = {
      company:  'bg-[#00ADA6]/10 text-[#00ADA6] border-[#00ADA6]/20',
      product:  'bg-[#0891B2]/10 text-[#0891B2] border-[#0891B2]/20',
      person:   'bg-[#00ADA6]/8 text-[#007A75] border-[#00ADA6]/15',
      location: 'bg-slate-100 text-slate-500 border-slate-200',
      concept:  'bg-slate-100 text-slate-500 border-slate-200',
      media:    'bg-[#0891B2]/10 text-[#0891B2] border-[#0891B2]/20',
      other:    'bg-slate-50 text-slate-400 border-slate-200',
    };

    return (
      <>
        {/* ===== 主内容：中间大卡片 + 右侧目录 ===== */}
        <div className="flex-1 flex overflow-hidden">

          {/* ===== 中间：当前节点阅读面板（主角） ===== */}
          <div className="flex-1 overflow-y-auto" style={{ background: '#FAFAF8' }}>
            {activeNode ? (
              <div className="max-w-2xl mx-auto px-10 py-8">

                {/* ——— 头部：封面缩略图 + 时间 + 类型 ——— */}
                <div className="flex items-center gap-2.5 mb-5">
                  {archive?.coverUrl && (
                    <img
                      src={resolveApiAssetUrl(archive.coverUrl)}
                      alt="封面"
                      className="w-11 h-11 rounded-lg object-cover shrink-0 border border-slate-100"
                    />
                  )}
                  <div className="inline-flex items-center px-3 py-1 bg-white border border-[#00ADA6]/20 text-[#00ADA6] text-sm font-mono font-semibold rounded-lg shadow-sm">
                    {activeNode.time} → {formatTime(activeNode.end)}
                  </div>
                  {tc && (
                    <div className={`inline-flex items-center px-2.5 py-1 text-xs font-medium rounded border ${tc.bg} ${tc.text} border-current/10`}>
                      {tc.label}
                    </div>
                  )}
                </div>

                {/* ——— 标题（最突出） ——— */}
                <h2 className="text-2xl font-bold text-slate-800 leading-tight mb-6">
                  {activeNode.title}
                </h2>

                {/* ——— 摘要（正文段落感） ——— */}
                {activeNode.summary && (
                  <p className="text-base text-slate-600 leading-7 mb-6 whitespace-pre-wrap">
                    {activeNode.summary}
                  </p>
                )}

                {/* ——— 为什么重要（重点提示块）—— 品牌辅助色柔和提示，不使用过亮的 amber ——— */}
                {activeNode.why_it_matters && (
                  <div className="relative pl-4 mb-6 before:content-[''] before:absolute before:left-0 before:top-0 before:bottom-0 before:w-0.5 before:bg-[#00ADA6] before:rounded-full">
                    <p className="text-sm text-slate-600 leading-relaxed">
                      <span className="font-semibold text-[#00ADA6]">重要原因 · </span>
                      {activeNode.why_it_matters}
                    </p>
                  </div>
                )}

                {/* ——— 相关实体（信息卡片） ——— */}
                {(() => {
                  const sourceTierBadge: Record<string, string> = {
                    official: 'bg-[#EFF6FF] text-[#3B82F6] border-[#BFDBFE]',
                    encyclopedia: 'bg-[#F0FDF4] text-[#16A34A] border-[#BBF7D0]',
                    media: 'bg-[#FFF7ED] text-[#EA580C] border-[#FED7AA]',
                    community: 'bg-slate-100 text-slate-500 border-slate-200',
                  };
                  const tierLabel: Record<string, string> = {
                    official: '官方', encyclopedia: '百科', media: '媒体', community: '社区',
                  };
                  const refLabel: Record<string, string> = {
                    official: '官网', encyclopedia: '百度百科', media: '媒体', community: '链接',
                  };

                  // 统一归一化：过滤无标题实体，计算派生字段
                  interface DisplayEntity {
                    key: string;
                    displayName: string;
                    displayType: string;
                    displayDescription: string;
                    ec: string;
                    sl: string;
                    hasRef: boolean;
                    hasMedia: boolean;
                    mediaUrl: string;
                    refUrl: string;
                    refTitle: string;
                    tier: string;
                    tierLabel: string;
                    refLabel: string;
                  }
                  const displayEntities: DisplayEntity[] = (activeNode.entities ?? [])
                    .map((entity, i) => {
                      const displayName = entity.name || entity.refTitle || '';
                      if (!displayName) return null;
                      const ec = entityTypeColors[entity.type ?? ''] ?? entityTypeColors['other'];
                      const sl = sourceTierBadge[entity.sourceTier ?? ''] ?? '';
                      const tier = entity.sourceTier ?? '';
                      const hasRef = !!(entity.refUrl && !entity.refUrl.includes('github.com'));
                      const mediaFilename = entity.media?.filename ?? '';
                      const remoteMediaUrl = entity.media?.remote_url ?? '';
                      const mediaUrl = mediaFilename
                        ? resolveMediaUrl(archive!.id, mediaFilename)
                        : resolveApiAssetUrl(remoteMediaUrl);
                      const hasMedia = !!mediaUrl;
                      return {
                        key: `${activeNode.id}-${displayName}-${i}`,
                        displayName,
                        displayType: entity.type ?? 'other',
                        displayDescription: entity.description ?? '',
                        ec,
                        sl,
                        hasRef,
                        hasMedia,
                        mediaUrl,
                        refUrl: entity.refUrl ?? '',
                        refTitle: entity.refTitle ?? '',
                        tier,
                        tierLabel: tierLabel[tier] ?? tier,
                        refLabel: refLabel[tier] ?? '链接',
                      };
                    })
                    .filter((e): e is DisplayEntity => e !== null);

                  if (!displayEntities.length) return null;
                  return (
                    <div className="mb-6">
                      <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-3">相关实体</p>
                      <div className="space-y-2">
                        {displayEntities.map((de) => (
                          <div
                            key={de.key}
                            className={`rounded-xl border ${de.ec} bg-white/60 overflow-hidden ${de.hasRef ? 'hover:shadow-sm transition-shadow cursor-default' : ''}`}
                          >
                            {de.hasMedia ? (
                              <div className="flex gap-0">
                                <div className="shrink-0 entity-card-media">
                                  <img
                                    src={de.mediaUrl}
                                    alt={de.displayName}
                                    referrerPolicy="no-referrer"
                                    className="w-24 h-24 object-cover"
                                    onError={(e) => {
                                      ((e.target as HTMLImageElement).closest('.entity-card-media') as HTMLElement | null)!.style.display = 'none';
                                    }}
                                  />
                                </div>
                                <div className="flex-1 min-w-0 p-3 flex flex-col gap-1.5">
                                  <div className="flex items-center gap-2 flex-wrap">
                                    <span className="text-sm font-semibold text-slate-800">{de.displayName}</span>
                                    <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${de.ec}`}>{de.displayType}</span>
                                    {de.hasRef && de.tier && (
                                      <span className={`text-xs px-1.5 py-0.5 rounded border font-medium ${de.sl}`}>{de.tierLabel}</span>
                                    )}
                                  </div>
                                  {de.displayDescription && (
                                    <p className="text-xs text-slate-500 leading-relaxed line-clamp-2">{de.displayDescription}</p>
                                  )}
                                  {de.hasRef && de.refUrl && (
                                    <a
                                      href={de.refUrl}
                                      target="_blank"
                                      rel="noopener noreferrer"
                                      className="text-xs text-[#00ADA6] hover:text-[#009A94] flex items-center gap-1 mt-0.5"
                                    >
                                      参考：{de.refTitle || de.refLabel}<IconExternalLink size={11} />
                                    </a>
                                  )}
                                </div>
                              </div>
                            ) : (
                              <div className="p-3 flex flex-col gap-1.5">
                                <div className="flex items-center gap-2 flex-wrap">
                                  <span className="text-sm font-semibold text-slate-800">{de.displayName}</span>
                                  <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${de.ec}`}>{de.displayType}</span>
                                  {de.hasRef && de.tier && (
                                    <span className={`text-xs px-1.5 py-0.5 rounded border font-medium ${de.sl}`}>{de.tierLabel}</span>
                                  )}
                                </div>
                                {de.displayDescription && (
                                  <p className="text-xs text-slate-500 leading-relaxed">{de.displayDescription}</p>
                                )}
                                {de.hasRef && de.refUrl && (
                                  <a
                                    href={de.refUrl}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="text-xs text-[#00ADA6] hover:text-[#009A94] flex items-center gap-1 mt-0.5"
                                  >
                                    参考：{de.refTitle || de.refLabel}<IconExternalLink size={11} />
                                  </a>
                                )}
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  );
                })()}

                {/* ——— 关键事实（结构化事实卡） ——— */}
                {activeNode.facts && activeNode.facts.length > 0 && (
                  <div className="mb-6">
                    <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-3">关键事实</p>
                    <div className="bg-white border border-slate-100 rounded-xl divide-y divide-slate-100">
                      {activeNode.facts.map((fact, i) => (
                        <div key={i} className="flex items-start gap-3 px-4 py-2.5">
                          <span className="text-xs font-medium text-slate-400 w-20 shrink-0 pt-0.5">{fact.label}</span>
                          <span className="text-sm text-slate-700 leading-relaxed">{fact.value}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* ——— 解读 / 梗解释（补充说明块） ——— */}
                {activeNode.quote_or_joke_explainer && (
                  <div className="bg-slate-50 border border-slate-200 rounded-xl px-5 py-4 mb-6">
                    <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-2">解读</p>
                    <p className="text-sm text-slate-600 leading-relaxed italic">
                      {activeNode.quote_or_joke_explainer}
                    </p>
                  </div>
                )}

                {/* ——— 参考链接（references 区块） ——— */}
                {(() => {
                  const entityUrls = new Set(
                    (activeNode.entities || [])
                      .filter(e => e.refUrl && !e.refUrl.includes('github.com'))
                      .map(e => e.refUrl)
                  );
                  const filteredRefs = (activeNode.references || []).filter(ref => {
                    if (ref.source === 'github' || ref.kind === 'repo') return false;
                    if (entityUrls.has(ref.url)) return false;
                    return true;
                  });
                  if (!filteredRefs.length) return null;
                  return (
                    <div className="mb-6">
                      <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-3">参考链接</p>
                      <div className="space-y-2">
                        {filteredRefs.map((ref, i) => {
                          const sourceLabel: Record<string, string> = {
                            wikipedia: '维基百科',
                            official: '官网',
                            article: '文章',
                            webpage: '网页',
                          };
                          const kindLabel: Record<string, string> = {
                            tool: '工具',
                            company: '公司',
                            product: '产品',
                            game: '游戏',
                            film: '影视',
                            document: '文档',
                            article: '文章',
                            webpage: '网页',
                            person: '人物',
                            location: '地点',
                          };
                          const sl = sourceLabel[ref.source] ?? ref.source;
                          const kl = kindLabel[ref.kind] ?? ref.kind;
                          return (
                            <a
                              key={i}
                              href={ref.url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="flex items-center gap-3 p-3 bg-white border border-slate-100 rounded-xl hover:border-[#00ADA6]/30 hover:shadow-sm transition-all group"
                            >
                              <div className="w-8 h-8 rounded-lg bg-[#EFF6FF] flex items-center justify-center shrink-0">
                                <IconExternalLink size={14} className="text-[#3B82F6]" />
                              </div>
                              <div className="min-w-0 flex-1">
                                <div className="flex items-center gap-2 mb-0.5">
                                  <span className="text-sm font-medium text-slate-700 group-hover:text-[#00ADA6] transition-colors truncate">
                                    {ref.title}
                                  </span>
                                  <span className="text-xs px-1.5 py-0.5 rounded bg-[#EFF6FF] text-[#64748B] shrink-0">
                                    {sl}
                                  </span>
                                  {kl && kl !== sl && (
                                    <span className="text-xs px-1.5 py-0.5 rounded bg-slate-100 text-slate-400 shrink-0">
                                      {kl}
                                    </span>
                                  )}
                                </div>
                                <p className="text-xs text-slate-400 truncate">{ref.note}</p>
                              </div>
                            </a>
                          );
                        })}
                      </div>
                      <p className="text-xs text-slate-300 mt-2">链接由 AI 辅助生成，请自行判断</p>
                    </div>
                  );
                })()}

                {/* ——— 空状态 ——— */}
                {!activeNode.summary && !activeNode.why_it_matters
                  && !activeNode.entities?.length && !activeNode.facts?.length
                  && !activeNode.quote_or_joke_explainer && !activeNode.references?.length && (
                    <div className="py-16 text-center">
                      <p className="text-sm text-slate-400">暂无详细解读内容</p>
                    </div>
                  )}

                {/* ——— 节点级统一提示（只在有内容时显示）———— */}
                {(activeNode.entities?.length || activeNode.facts?.length || activeNode.references?.length) && (
                  <p className="text-xs text-slate-300 leading-relaxed">
                    链接、图片等内容由 AI 辅助收集，请自行判断。
                  </p>
                )}

                {/* 底部留白（让滚动有呼吸感） */}
                <div className="h-8" />
              </div>
            ) : (
              /* 无当前节点时 */
              <div className="h-full flex flex-col items-center justify-center text-center px-8">
                <div className="w-20 h-20 rounded-full bg-slate-100 flex items-center justify-center mb-6">
                  <IconPlayerPlay size={28} className="text-slate-300 ml-0.5" />
                </div>
                <p className="text-sm text-slate-400 leading-relaxed">
                  播放音频<br />系统将自动高亮当前节点
                </p>
              </div>
            )}
          </div>

          {/* ===== 右侧：节目目录 ===== */}
          <div className="w-72 shrink-0 flex flex-col overflow-hidden border-l border-slate-200" style={{ background: '#F7F7F5' }}>
            {/* 目录头部 */}
            <div className="px-5 py-4 border-b border-slate-200 shrink-0">
              <div className="flex items-center justify-between">
                <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-widest">目录</h2>
                <span className="text-xs text-slate-400 tabular-nums">{nodes.length} 节</span>
              </div>
            </div>

            {/* 目录列表 */}
            <div
              ref={nodeListRef}
              className="flex-1 overflow-y-auto"
              style={{ scrollBehavior: 'smooth' }}
            >
              {nodes.length === 0 ? (
                <div className="py-12 text-center">
                  <p className="text-xs text-slate-400">暂无节点</p>
                </div>
              ) : (
                <div className="px-3 py-2 space-y-0.5">
                  {nodes.map((node, idx) => {
                    const isActive = activeNode?.id === node.id;
                    const tc = nodeTypeConfig[node.node_type] ?? nodeTypeConfig['other'];
                    return (
                      <button
                        key={node.id}
                        data-node-id={node.id}
                        onClick={(e) => handleNodeClick(node, e)}
                        className={`relative w-full text-left rounded-lg px-3 py-2.5 transition-all duration-150 group ${
                          isActive
                            ? 'bg-white shadow-sm border border-[#00ADA6]/20'
                            : 'hover:bg-white/70'
                        }`}
                      >
                        <div className="flex items-start gap-2.5">
                          {/* 节号 */}
                          <span className={`text-xs font-mono font-medium w-6 shrink-0 mt-0.5 ${
                            isActive ? 'text-[#00ADA6]' : 'text-slate-300 group-hover:text-slate-400'
                          }`}>
                            {String(idx + 1).padStart(2, '0')}
                          </span>
                          <div className="min-w-0 flex-1">
                            {/* 时间 + 类型 */}
                            <div className="flex items-center gap-1.5 mb-0.5">
                              <span className={`text-xs font-mono ${
                                isActive ? 'text-[#00ADA6]' : 'text-slate-400'
                              }`}>
                                {node.time}
                              </span>
                              {node.node_type && (
                                <span className={`text-[10px] px-1 py-0.5 rounded ${tc.bg} ${tc.text} font-medium`}>
                                  {tc.label}
                                </span>
                              )}
                            </div>
                            {/* 标题 */}
                            <p className={`text-xs leading-snug ${
                              isActive
                                ? 'text-[#00ADA6] font-semibold'
                                : 'text-slate-500 group-hover:text-slate-700'
                            }`}>
                              {node.title}
                            </p>
                            {/* 摘要预览（active 时显示） */}
                            {isActive && node.summary && (
                              <p className="text-[11px] text-slate-400 leading-relaxed mt-1 line-clamp-2">
                                {node.summary}
                              </p>
                            )}
                          </div>
                          {/* 当前节点指示条 */}
                          {isActive && (
                            <div className="w-0.5 h-full absolute left-0 top-0 bottom-0 bg-[#00ADA6] rounded-full" />
                          )}
                        </div>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* ===== 底部播放器控制条 ===== */}
        <div
          className="border-t border-slate-200 px-6 py-3.5 shrink-0"
          style={{ background: 'linear-gradient(to top, #F9F9F8, #FFFFFF)' }}
        >
          <div className="flex items-center gap-4">

            {/* 音频源 */}
            {hasAudio && archive && (
              <audio
                ref={audioRef}
                src={resolveApiAssetUrl(archive.audioUrl!)}
                onTimeUpdate={handleTimeUpdate}
                onLoadedMetadata={handleLoadedMetadata}
                onPlay={() => setIsPlaying(true)}
                onPause={() => setIsPlaying(false)}
                onEnded={() => setIsPlaying(false)}
              />
            )}

            {/* 快退 15 秒 */}
            <button
              onClick={skipBackward15}
              disabled={!hasAudio}
              className={`w-9 h-9 rounded-full flex items-center justify-center transition-all shrink-0 ${
                hasAudio
                  ? 'bg-[#00ADA6]/10 hover:bg-[#00ADA6]/20 text-[#00ADA6]'
                  : 'bg-slate-100 text-slate-300 cursor-not-allowed'
              }`}
              title="快退 15 秒"
            >
              <IconRewindBackward15 size={17} />
            </button>

            {/* 播放/暂停按钮（更大更醒目） */}
            <button
              onClick={togglePlay}
              disabled={!hasAudio}
              className={`w-11 h-11 rounded-full flex items-center justify-center transition-all shrink-0 ${
                hasAudio
                  ? 'bg-[#00ADA6] hover:bg-[#009A94] active:scale-95 shadow-md shadow-[#00ADA6]/20'
                  : 'bg-slate-100 text-slate-300 cursor-not-allowed'
              }`}
            >
              {isPlaying
                ? <IconPlayerSkipForward size={18} className="text-white ml-0.5" />
                : <IconPlayerPlay size={18} className="text-white ml-0.5" />
              }
            </button>

            {/* 快进 30 秒 */}
            <button
              onClick={skipForward30}
              disabled={!hasAudio}
              className={`w-9 h-9 rounded-full flex items-center justify-center transition-all shrink-0 ${
                hasAudio
                  ? 'bg-[#00ADA6]/10 hover:bg-[#00ADA6]/20 text-[#00ADA6]'
                  : 'bg-slate-100 text-slate-300 cursor-not-allowed'
              }`}
              title="快进 30 秒"
            >
              <IconRewindForward30 size={17} />
            </button>

            {/* 当前时间 */}
            <span className="text-xs text-slate-400 font-mono tabular-nums w-11 text-right shrink-0">
              {formatTime(currentTime)}
            </span>

            {/* 进度条（更宽更粗，支持点击 seek） */}
            <div className="flex-1 mx-2">
              <div
                className="h-1.5 bg-slate-100 rounded-full overflow-hidden cursor-pointer group"
                onClick={(e) => {
                  if (!hasAudio || !audioRef.current) return;
                  e.stopPropagation();
                  const rect = e.currentTarget.getBoundingClientRect();
                  const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
                  seekTo(ratio * duration);
                }}
              >
                <div
                  className="h-full bg-[#00ADA6] rounded-full transition-all duration-150 group-hover:bg-[#009A94]"
                  style={{ width: duration > 0 ? `${(currentTime / duration) * 100}%` : '0%' }}
                />
              </div>
            </div>

            {/* 总时长 */}
            <span className="text-xs text-slate-400 font-mono tabular-nums w-11 shrink-0">
              {formatTime(duration)}
            </span>

            {/* 当前节点标签（播放器右侧提示） */}
            {activeNode && (
              <div className="hidden lg:flex items-center gap-2 px-3 py-1.5 rounded-full bg-slate-50 border border-slate-100 max-w-[220px] shrink-0">
                <div className="w-1.5 h-1.5 rounded-full bg-[#00ADA6] animate-pulse shrink-0" />
                <span className="text-xs font-mono text-[#00ADA6] shrink-0">{activeNode.time}</span>
                <span className="text-xs text-slate-500 truncate">{activeNode.title}</span>
              </div>
            )}
          </div>
        </div>
      </>
    );
  };

  // ===== Summary 模式视图 =====

  const renderSummaryMode = () => {
    return (
      <div className="flex-1 flex overflow-hidden">

        {/* 左侧：播放器 + 时间轴 */}
        <div className="flex-1 flex flex-col overflow-hidden">

          {/* 播放器区 */}
          <div className="px-6 py-3.5 border-b border-slate-100 shrink-0">
            <div className="flex items-center gap-3">
              {hasAudio && archive && (
                <audio
                  ref={audioRef}
                  src={resolveApiAssetUrl(archive.audioUrl!)}
                  onTimeUpdate={handleTimeUpdate}
                  onLoadedMetadata={handleLoadedMetadata}
                  onPlay={() => setIsPlaying(true)}
                  onPause={() => setIsPlaying(false)}
                  onEnded={() => setIsPlaying(false)}
                />
              )}
              {/* 快退 15 秒 */}
              <button
                onClick={skipBackward15}
                disabled={!hasAudio}
                className={`w-9 h-9 rounded-full flex items-center justify-center transition-all shrink-0 ${
                  hasAudio
                    ? 'bg-[#00ADA6]/10 hover:bg-[#00ADA6]/20 text-[#00ADA6]'
                    : 'bg-slate-100 text-slate-300 cursor-not-allowed'
                }`}
                title="快退 15 秒"
              >
                <IconRewindBackward15 size={17} />
              </button>
              <button
                onClick={togglePlay}
                disabled={!hasAudio}
                className={`w-10 h-10 rounded-full flex items-center justify-center transition-colors shrink-0 ${
                  hasAudio
                    ? 'bg-[#00ADA6] hover:bg-[#009A94] text-white'
                    : 'bg-slate-100 text-slate-300 cursor-not-allowed'
                }`}
              >
                {isPlaying
                  ? <IconPlayerSkipForward size={17} className="ml-0.5" />
                  : <IconPlayerPlay size={17} className="ml-0.5" />
                }
              </button>
              {/* 快进 30 秒 */}
              <button
                onClick={skipForward30}
                disabled={!hasAudio}
                className={`w-9 h-9 rounded-full flex items-center justify-center transition-all shrink-0 ${
                  hasAudio
                    ? 'bg-[#00ADA6]/10 hover:bg-[#00ADA6]/20 text-[#00ADA6]'
                    : 'bg-slate-100 text-slate-300 cursor-not-allowed'
                }`}
                title="快进 30 秒"
              >
                <IconRewindForward30 size={17} />
              </button>
              <div className="flex-1 min-w-0 flex items-center gap-2.5">
                <span className="text-xs text-slate-400 font-mono w-9 shrink-0 text-right">{formatTime(currentTime)}</span>
                <div
                  className="flex-1 h-1 bg-slate-100 rounded-full overflow-hidden cursor-pointer"
                  onClick={(e) => {
                    if (!hasAudio || !audioRef.current) return;
                    e.stopPropagation();
                    const rect = e.currentTarget.getBoundingClientRect();
                    const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
                    seekTo(ratio * duration);
                  }}
                >
                  <div
                    className="h-full bg-[#00ADA6] rounded-full transition-all duration-200"
                    style={{ width: duration > 0 ? `${(currentTime / duration) * 100}%` : '0%' }}
                  />
                </div>
                <span className="text-xs text-slate-400 font-mono w-9 shrink-0">{formatTime(duration)}</span>
              </div>
            </div>
          </div>

          {/* 时间轴区（可滚动） */}
          <div className="flex-1 overflow-hidden flex flex-col">
            <div className="px-6 py-3 border-b border-slate-100 shrink-0">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-semibold text-slate-700">时间轴</h2>
                <div className="flex gap-1 bg-slate-100 rounded-lg p-1">
                  {(['chapters', 'highlights', 'terms', 'segments'] as TimelineTab[]).map(tab => {
                    const count = tab === 'segments'
                      ? archive!.transcriptSegments.length
                      : archive!.timeline[tab].length;
                    if (tab === 'terms' && count === 0) return null;
                    return (
                      <button
                        key={tab}
                        onClick={() => setActiveTab(tab)}
                        className={`px-2.5 py-1 text-xs rounded-md transition-colors ${
                          activeTab === tab
                            ? 'bg-white text-[#00ADA6] shadow-sm font-medium border border-[#00ADA6]/20'
                            : 'text-slate-500 hover:text-slate-700'
                        }`}
                      >
                        {tab === 'chapters' ? '章节' : tab === 'highlights' ? '高光' : tab === 'terms' ? '术语' : '转录'}
                        {count > 0 && <span className="ml-0.5 text-[10px] opacity-50">({count})</span>}
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>

            <div
              ref={listScrollRef}
              className="flex-1 overflow-y-auto px-5 py-2.5"
            >
              {currentItems.length === 0 ? (
                <p className="text-xs text-slate-400 py-8 text-center">
                  {activeTab === 'chapters' ? '该归档未生成章节' :
                   activeTab === 'highlights' ? '该归档暂无高光记录' :
                   activeTab === 'terms' ? '该归档暂无术语' : '该归档暂无转录分段'}
                </p>
              ) : (
                <div className="space-y-1 pb-4">
                  {currentItems.map(renderItem)}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* 右侧节点说明区 */}
        <div className="w-72 border-l border-slate-100 overflow-y-auto px-5 py-4 bg-slate-50/80 flex flex-col gap-5">
          <div>
            <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-3">节点说明</h2>
            {highlightedItem ? (
              <div className="space-y-2.5">
                <div className="inline-flex items-center px-2 py-0.5 bg-[#D1FAF5] text-[#00ADA6] text-xs font-mono font-medium rounded">
                  {highlightedItem.time}
                </div>
                <h3 className="text-sm font-semibold text-slate-800 leading-snug">
                  {activeTab === 'segments' ? highlightedItem.text : highlightedItem.title}
                </h3>
                {highlightedItem.description && activeTab !== 'segments' && (
                  <p className="text-xs text-slate-500 leading-relaxed line-clamp-3">{highlightedItem.description}</p>
                )}
                {hasAudio && (
                  <button
                    onClick={() => seekTo(highlightedItem.seconds)}
                    className="w-full flex items-center justify-center gap-1.5 px-3 py-2 bg-[#00ADA6] hover:bg-[#009A94] text-white text-xs font-medium rounded-lg transition-colors mt-1"
                  >
                    <IconPlayerPlay size={13} />
                    跳转播放
                  </button>
                )}
              </div>
            ) : (
              <div className="py-4">
                <p className="text-xs text-slate-400 text-center leading-relaxed">
                  点击时间轴节点<br />查看详细说明
                </p>
              </div>
            )}
          </div>

          {archive && archive.summary && (
            <div className="pt-4 border-t border-slate-100">
              <button
                onClick={() => setSummaryCollapsed(c => !c)}
                className="w-full flex items-center justify-between mb-2 group"
              >
                <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wide">本期摘要</h3>
                <span className={`text-xs text-slate-400 transition-transform ${summaryCollapsed ? '' : 'rotate-180'}`}>
                  <IconChevronDown size={13} />
                </span>
              </button>
              {!summaryCollapsed && (
                <p className="text-xs text-slate-500 leading-relaxed whitespace-pre-wrap line-clamp-6">
                  {archive!.summary}
                </p>
              )}
            </div>
          )}
        </div>
      </div>
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
  const isTimeline = archive.mode === 'timeline';

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden bg-white">

      {/* 顶部信息区 */}
      <div className="border-b border-slate-100 px-6 py-3 flex items-center gap-3 bg-white">
        <button
          onClick={() => navigate('/')}
          className="flex items-center gap-1 text-slate-400 hover:text-slate-600 transition-colors"
        >
          <IconChevronLeft size={18} />
          <span className="text-xs">返回</span>
        </button>
        <div className="h-4 w-px bg-slate-200" />
        {isTimeline && (
          <>
            <div className="inline-flex items-center px-2 py-0.5 bg-[#00ADA6]/10 text-[#00ADA6] text-xs font-medium rounded">
              时间轴模式
            </div>
            <div className="h-4 w-px bg-slate-200" />
          </>
        )}
        <div className="flex items-center gap-2 min-w-0">
          <div className="w-9 h-9 rounded-lg bg-[#D1FAF5] flex items-center justify-center shrink-0">
            <IconMessageCircle size={16} className="text-[#00ADA6]" />
          </div>
          <div className="min-w-0">
            <h1 className="text-sm font-semibold text-slate-800 leading-snug truncate">{archive.name}</h1>
            <p className="text-xs text-slate-400 flex items-center gap-1.5">
              {archive.createTime && <><IconClock size={11} />{archive.createTime}</>}
              {duration > 0 && <span>{formatTime(duration)}</span>}
              {!hasAudio && (
                <span className="text-amber-500 flex items-center gap-0.5">
                  <span className="w-1 h-1 rounded-full bg-amber-400 inline-block" />
                  音频不可用
                </span>
              )}
            </p>
          </div>
        </div>
      </div>

      {/* 主内容：按 mode 路由 */}
      {isTimeline ? renderTimelineMode() : renderSummaryMode()}

    </div>
  );
}
