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

  // ===== 从 localStorage 恢复播放进度（仅一次，首次 audio 加载完成后）=====
  const progressRestoredRef = useRef(false);
  useEffect(() => {
    if (!archive || !audioRef.current || progressRestoredRef.current) return;
    if (duration <= 0) return;
    progressRestoredRef.current = true;
    try {
      const raw = localStorage.getItem('podgist_play_progress');
      if (!raw) return;
      const all = JSON.parse(raw);
      const saved = all[id];
      if (saved && saved.lastPositionSeconds > 0 && saved.lastPositionSeconds < saved.duration - 5) {
        audioRef.current.currentTime = saved.lastPositionSeconds;
        audioRef.current.pause();
        setIsPlaying(false);
        setCurrentTime(saved.lastPositionSeconds);
      }
    } catch { /* ignore */ }
  }, [archive, duration]);

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
      const clamped = Math.max(0, Math.min(seconds, duration));
      audioRef.current.currentTime = clamped;
      setCurrentTime(clamped);
    }
  };

  const skipForward30 = () => seekTo(currentTime + 30);
  const skipBackward15 = () => seekTo(currentTime - 15);

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
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [currentTime, duration]);

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

    // 节点类型 → 配色
    const nodeTypeConfig: Record<string, { bg: string; text: string; label: string }> = {
      company_news: { bg: 'bg-orange-50', text: 'text-orange-600', label: '公司动态' },
      product:      { bg: 'bg-blue-50',   text: 'text-blue-600',   label: '产品' },
      person:       { bg: 'bg-purple-50', text: 'text-purple-600', label: '人物' },
      topic_change: { bg: 'bg-slate-50',  text: 'text-slate-500',  label: '话题切换' },
      quote:        { bg: 'bg-green-50',  text: 'text-green-600',  label: '金句' },
      background:   { bg: 'bg-slate-50',  text: 'text-slate-400',  label: '背景' },
      fun_moment:   { bg: 'bg-yellow-50', text: 'text-yellow-600', label: '趣味时刻' },
      other:        { bg: 'bg-slate-50',  text: 'text-slate-400',  label: '其他' },
    };
    const tc = activeNode?.node_type
      ? (nodeTypeConfig[activeNode.node_type] ?? nodeTypeConfig['other'])
      : null;

    // 实体类型 → 配色
    const entityTypeColors: Record<string, string> = {
      company:  'bg-blue-50 text-blue-600 border-blue-100',
      product:  'bg-indigo-50 text-indigo-600 border-indigo-100',
      person:   'bg-purple-50 text-purple-600 border-purple-100',
      location: 'bg-green-50 text-green-600 border-green-100',
      concept:  'bg-orange-50 text-orange-600 border-orange-100',
      media:    'bg-red-50 text-red-600 border-red-100',
      other:    'bg-slate-50 text-slate-500 border-slate-100',
    };

    return (
      <>
        {/* ===== 主内容：中间大卡片 + 右侧目录 ===== */}
        <div className="flex-1 flex overflow-hidden">

          {/* ===== 中间：当前节点阅读面板（主角） ===== */}
          <div className="flex-1 overflow-y-auto" style={{ background: '#FAFAF8' }}>
            {activeNode ? (
              <div className="max-w-2xl mx-auto px-10 py-8">

                {/* ——— 头部：时间 + 类型 ——— */}
                <div className="flex items-center gap-2 mb-5">
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

                {/* ——— 为什么重要（重点提示块） ——— */}
                {activeNode.why_it_matters && (
                  <div className="relative pl-4 mb-6 before:content-[''] before:absolute before:left-0 before:top-0 before:bottom-0 before:w-0.5 before:bg-amber-400 before:rounded-full">
                    <p className="text-sm text-amber-700 leading-relaxed">
                      <span className="font-semibold text-amber-800">重要原因 · </span>
                      {activeNode.why_it_matters}
                    </p>
                  </div>
                )}

                {/* ——— 相关实体（信息卡片） ——— */}
                {activeNode.entities && activeNode.entities.length > 0 && (
                  <div className="mb-6">
                    <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-3">相关实体</p>
                    <div className="space-y-2">
                      {activeNode.entities.map((entity, i) => {
                        const ec = entityTypeColors[entity.type] ?? entityTypeColors['other'];
                        return (
                          <div key={i} className={`flex items-start gap-3 p-3 rounded-xl border ${ec} bg-white/60`}>
                            <div className="min-w-0 flex-1">
                              <div className="flex items-center gap-2 mb-1">
                                <span className="text-sm font-semibold text-slate-800">{entity.name}</span>
                                <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${ec}`}>
                                  {entity.type}
                                </span>
                              </div>
                              {entity.description && (
                                <p className="text-xs text-slate-500 leading-relaxed">{entity.description}</p>
                              )}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}

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

                {/* ——— 空状态 ——— */}
                {!activeNode.summary && !activeNode.why_it_matters
                  && !activeNode.entities?.length && !activeNode.facts?.length
                  && !activeNode.quote_or_joke_explainer && (
                    <div className="py-16 text-center">
                      <p className="text-sm text-slate-400">暂无详细解读内容</p>
                    </div>
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
                        onClick={(e) => handleNodeClick(node, e)}
                        className={`w-full text-left rounded-lg px-3 py-2.5 transition-all duration-150 group ${
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

            {/* 快退 15 秒 */}
            <button
              onClick={skipBackward15}
              disabled={!hasAudio}
              className="text-slate-400 hover:text-[#00ADA6] transition-colors disabled:opacity-30 shrink-0"
              title="快退 15 秒"
            >
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                <path d="M8 3a5 5 0 1 0 4.783 3.9l-1.3-.75A3.5 3.5 0 1 1 8 5.5v1.4l2.6-1.5-2.6-1.5v1.4A5 5 0 0 0 8 3z" fill="currentColor"/>
                <text x="8" y="14" textAnchor="middle" fontSize="5" fill="currentColor" fontWeight="bold">15</text>
              </svg>
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
              className="text-slate-400 hover:text-[#00ADA6] transition-colors disabled:opacity-30 shrink-0"
              title="快进 30 秒"
            >
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                <path d="M8 3a5 5 0 1 1-4.783 3.9l1.3-.75A3.5 3.5 0 1 0 8 5.5v1.4l-2.6-1.5 2.6-1.5v1.4A5 5 0 0 1 8 3z" fill="currentColor"/>
                <text x="8" y="14" textAnchor="middle" fontSize="5" fill="currentColor" fontWeight="bold">30</text>
              </svg>
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
              {/* 快退 15 秒 */}
              <button
                onClick={skipBackward15}
                disabled={!hasAudio}
                className="text-slate-400 hover:text-[#00ADA6] transition-colors disabled:opacity-30 shrink-0"
                title="快退 15 秒"
              >
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                  <path d="M8 3a5 5 0 1 0 4.783 3.9l-1.3-.75A3.5 3.5 0 1 1 8 5.5v1.4l2.6-1.5-2.6-1.5v1.4A5 5 0 0 0 8 3z" fill="currentColor"/>
                  <text x="8" y="14" textAnchor="middle" fontSize="5" fill="currentColor" fontWeight="bold">15</text>
                </svg>
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
                className="text-slate-400 hover:text-[#00ADA6] transition-colors disabled:opacity-30 shrink-0"
                title="快进 30 秒"
              >
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                  <path d="M8 3a5 5 0 1 1-4.783 3.9l1.3-.75A3.5 3.5 0 1 0 8 5.5v1.4l-2.6-1.5 2.6-1.5v1.4A5 5 0 0 1 8 3z" fill="currentColor"/>
                  <text x="8" y="14" textAnchor="middle" fontSize="5" fill="currentColor" fontWeight="bold">30</text>
                </svg>
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
