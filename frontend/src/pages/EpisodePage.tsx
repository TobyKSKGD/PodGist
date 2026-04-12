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

interface TimelineNode {
  id: string;
  start: number;
  end: number;
  time: string;
  title: string;
  node_type: string;
  summary: string;
  why_it_matters: string;
  entities: Array<{ name: string; type: string; description: string }>;
  facts: Array<{ label: string; value: string }>;
  quote_or_joke_explainer: string;
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
  timeline: Timeline;
  transcriptSegments: TimelineItem[];
  mode?: string;
  metadata?: Record<string, unknown>;
  timelineData?: TimelineData;
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

          // timeline 模式默认选中第一个节点
          if (data.timelineData?.nodes?.length) {
            setCurrentNode(data.timelineData.nodes[0]);
            setSelectedNode(data.timelineData.nodes[0]);
          }
        }
      })
      .catch(() => setError('加载归档失败'))
      .finally(() => setLoading(false));
  }, [id]);

  // ===== 播放进度本地存储 =====

  const PROGRESS_KEY = 'podgist_play_progress';

  const lastSaveRef = useRef(0);
  const saveProgress = (seconds: number, dur: number) => {
    if (!id || !dur || dur <= 0) return;
    const now = Date.now();
    if (now - lastSaveRef.current < 10000) return;
    lastSaveRef.current = now;
    try {
      const raw = localStorage.getItem(PROGRESS_KEY);
      const all: Record<string, { archiveId: string; lastPositionSeconds: number; duration: number; updatedAt: number }> = raw ? JSON.parse(raw) : {};
      all[id] = { archiveId: id, lastPositionSeconds: seconds, duration: dur, updatedAt: now };
      localStorage.setItem(PROGRESS_KEY, JSON.stringify(all));
    } catch { /* ignore */ }
  };

  // ===== 音频事件 =====

  const rafRef = useRef<number | null>(null);
  const lastUpdateRef = useRef<number>(0);

  const handleTimeUpdate = useCallback(() => {
    if (!audioRef.current) return;
    const now = performance.now();
    if (now - lastUpdateRef.current < 200) return;
    lastUpdateRef.current = now;
    const t = audioRef.current.currentTime;
    setCurrentTime(t);
    saveProgress(t, audioRef.current.duration || 0);
  }, []);

  const handleLoadedMetadata = () => {
    if (!audioRef.current) return;
    const dur = audioRef.current.duration;
    setDuration(dur);
    if (id && dur > 0) {
      try {
        const raw = localStorage.getItem('podgist_play_progress');
        if (raw) {
          const all = JSON.parse(raw);
          const saved = all[id];
          if (saved && saved.lastPositionSeconds > 0 && saved.lastPositionSeconds < dur - 5) {
            audioRef.current.currentTime = saved.lastPositionSeconds;
          }
        }
      } catch { /* ignore */ }
    }
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

  // ===== 时间轴自动高亮（summary 模式）=====

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

  useEffect(() => {
    if (!archive) return;
    if (activeTab !== 'chapters' && activeTab !== 'terms') return;
    if (selectedItem) {
      setAutoHighlightItem(selectedItem);
    }
  }, [activeTab, archive]);

  // ===== 时间轴自动高亮（timeline 模式）=====

  useEffect(() => {
    if (!archive?.timelineData?.nodes) return;
    const node = findActiveNode(archive.timelineData.nodes, currentTime);
    if (node && node.id !== currentNode?.id) {
      setCurrentNode(node);
    }
  }, [currentTime, archive]);

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

  const handleNodeClick = (node: TimelineNode) => {
    setSelectedNode(node);
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
    const activeNode = currentNode ?? selectedNode;

    // 节点类型配色映射
    const nodeTypeColors: Record<string, string> = {
      company_news: 'bg-orange-100 text-orange-600',
      product: 'bg-blue-100 text-blue-600',
      person: 'bg-purple-100 text-purple-600',
      topic_change: 'bg-slate-100 text-slate-500',
      quote: 'bg-green-100 text-green-600',
      background: 'bg-slate-100 text-slate-400',
      fun_moment: 'bg-yellow-100 text-yellow-600',
      other: 'bg-slate-100 text-slate-400',
    };
    const nodeTypeBg = activeNode?.node_type ? (nodeTypeColors[activeNode.node_type] ?? nodeTypeColors['other']) : '';

    return (
      <>
        {/* ===== 主内容区 ===== */}
        <div className="flex-1 flex overflow-hidden">

          {/* 中间：当前节点大卡片（主角） */}
          <div className="flex-1 overflow-y-auto px-8 py-6 bg-white">
            {activeNode ? (
              <div className="max-w-2xl mx-auto space-y-5">

                {/* 时间范围 + 类型标签 */}
                <div className="flex items-center gap-2 flex-wrap">
                  <div className="inline-flex items-center px-3 py-1 bg-[#D1FAF5] text-[#00ADA6] text-sm font-mono font-medium rounded-lg">
                    {activeNode.time} — {formatTime(activeNode.end)}
                  </div>
                  {activeNode.node_type && (
                    <div className={`inline-flex items-center px-2.5 py-1 text-xs font-medium rounded ${nodeTypeBg}`}>
                      {activeNode.node_type}
                    </div>
                  )}
                </div>

                {/* 标题 */}
                <h2 className="text-xl font-bold text-slate-800 leading-snug">
                  {activeNode.title}
                </h2>

                {/* 摘要 */}
                {activeNode.summary && (
                  <p className="text-base text-slate-600 leading-relaxed">{activeNode.summary}</p>
                )}

                {/* 为什么重要 */}
                {activeNode.why_it_matters && (
                  <div className="bg-amber-50 border border-amber-200 rounded-xl px-4 py-3">
                    <p className="text-sm text-amber-700 leading-relaxed">
                      <span className="font-semibold">重要原因：</span>
                      {activeNode.why_it_matters}
                    </p>
                  </div>
                )}

                {/* 实体列表 */}
                {activeNode.entities && activeNode.entities.length > 0 && (
                  <div className="space-y-2">
                    <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider">相关实体</p>
                    <div className="grid grid-cols-1 gap-2">
                      {activeNode.entities.map((entity, i) => (
                        <div key={i} className="flex items-start gap-3 p-3 bg-slate-50 rounded-lg border border-slate-100">
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center gap-2 mb-0.5">
                              <span className="text-xs font-semibold text-slate-700">{entity.name}</span>
                              <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${
                                entity.type === 'company' ? 'bg-blue-50 text-blue-500' :
                                entity.type === 'product' ? 'bg-indigo-50 text-indigo-500' :
                                entity.type === 'person' ? 'bg-purple-50 text-purple-500' :
                                entity.type === 'location' ? 'bg-green-50 text-green-500' :
                                entity.type === 'media' ? 'bg-red-50 text-red-500' :
                                'bg-slate-100 text-slate-500'
                              }`}>{entity.type}</span>
                            </div>
                            {entity.description && (
                              <p className="text-xs text-slate-500 leading-relaxed">{entity.description}</p>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* 关键事实 */}
                {activeNode.facts && activeNode.facts.length > 0 && (
                  <div className="space-y-2">
                    <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider">关键事实</p>
                    <div className="space-y-1.5">
                      {activeNode.facts.map((fact, i) => (
                        <div key={i} className="flex items-start gap-2">
                          <span className="text-xs bg-slate-100 text-slate-500 px-2 py-0.5 rounded font-medium shrink-0 mt-0.5">{fact.label}</span>
                          <p className="text-sm text-slate-600 leading-relaxed">{fact.value}</p>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* 解读 / 梗解释 */}
                {activeNode.quote_or_joke_explainer && (
                  <div className="bg-purple-50 border border-purple-200 rounded-xl px-4 py-3">
                    <p className="text-sm text-purple-700 leading-relaxed italic">
                      {activeNode.quote_or_joke_explainer}
                    </p>
                  </div>
                )}

                {/* 空状态占位 */}
                {!activeNode.summary && !activeNode.why_it_matters && !activeNode.entities?.length && !activeNode.facts?.length && !activeNode.quote_or_joke_explainer && (
                  <p className="text-sm text-slate-400 text-center py-8">暂无节点详情</p>
                )}
              </div>
            ) : (
              <div className="h-full flex flex-col items-center justify-center text-center">
                <div className="w-16 h-16 rounded-full bg-slate-100 flex items-center justify-center mb-4">
                  <IconPlayerPlay size={24} className="text-slate-300" />
                </div>
                <p className="text-sm text-slate-400 leading-relaxed">
                  播放音频<br />系统将自动高亮当前节点
                </p>
              </div>
            )}
          </div>

          {/* 右侧：节点目录（独立滚动） */}
          <div className="w-72 border-l border-slate-100 flex flex-col overflow-hidden bg-slate-50/50">
            <div className="px-4 py-3 border-b border-slate-100 shrink-0">
              <div className="flex items-center justify-between">
                <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-wider">目录</h2>
                <span className="text-xs text-slate-400">{nodes.length} 个节点</span>
              </div>
            </div>

            <div ref={nodeListRef} className="flex-1 overflow-y-auto px-3 py-2">
              {nodes.length === 0 ? (
                <p className="text-xs text-slate-400 py-8 text-center">暂无节点</p>
              ) : (
                <div className="space-y-0.5">
                  {nodes.map(node => {
                    const isActive = activeNode?.id === node.id;
                    return (
                      <button
                        key={node.id}
                        onClick={() => handleNodeClick(node)}
                        className={`w-full text-left px-3 py-2 rounded-lg transition-all flex items-start gap-2.5 ${
                          isActive
                            ? 'bg-white border border-[#00ADA6]/30 shadow-sm'
                            : 'hover:bg-white/60'
                        }`}
                      >
                        <span className={`text-xs font-mono font-medium w-10 shrink-0 mt-0.5 ${
                          isActive ? 'text-[#00ADA6]' : 'text-slate-400'
                        }`}>
                          {node.time}
                        </span>
                        <span className={`text-xs flex-1 leading-relaxed ${
                          isActive ? 'text-[#00ADA6] font-semibold' : 'text-slate-500'
                        }`}>
                          {node.title}
                        </span>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* ===== 底部播放器 ===== */}
        <div className="border-t border-slate-100 px-6 py-3 bg-white shrink-0">
          <div className="flex items-center gap-3">
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
            <div className="flex-1 min-w-0 flex items-center gap-2.5">
              <span className="text-xs text-slate-400 font-mono w-10 shrink-0 text-right">{formatTime(currentTime)}</span>
              <div
                className="flex-1 h-1.5 bg-slate-100 rounded-full overflow-hidden cursor-pointer"
                onClick={(e) => {
                  if (!hasAudio || !audioRef.current) return;
                  const rect = e.currentTarget.getBoundingClientRect();
                  const ratio = (e.clientX - rect.left) / rect.width;
                  audioRef.current.currentTime = ratio * duration;
                }}
              >
                <div
                  className="h-full bg-[#00ADA6] rounded-full transition-all duration-200"
                  style={{ width: duration > 0 ? `${(currentTime / duration) * 100}%` : '0%' }}
                />
              </div>
              <span className="text-xs text-slate-400 font-mono w-10 shrink-0">{formatTime(duration)}</span>
            </div>
            {/* 当前节点标签（播放器右侧提示） */}
            {activeNode && (
              <div className="hidden md:flex items-center gap-1.5 ml-2 px-2 py-1 bg-slate-50 rounded-lg border border-slate-100 max-w-[200px] shrink-0">
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
              <div className="flex-1 min-w-0 flex items-center gap-2.5">
                <span className="text-xs text-slate-400 font-mono w-9 shrink-0 text-right">{formatTime(currentTime)}</span>
                <div className="flex-1 h-1 bg-slate-100 rounded-full overflow-hidden">
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
                      ? archive.transcriptSegments.length
                      : archive.timeline[tab].length;
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

          {archive.summary && (
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
                  {archive.summary}
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
            <div className="inline-flex items-center px-2 py-0.5 bg-purple-100 text-purple-600 text-xs font-medium rounded">
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
