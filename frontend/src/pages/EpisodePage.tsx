/**
 * EpisodePage — 新的播放器详情页骨架
 *
 * 架构：
 * - 顶部信息区（封面、标题、来源、时长、创建时间）
 * - 播放器区（真实 <audio> 标签）
 * - 时间轴区（chapters / highlights / terms 三个 tab）
 * - 节点说明区（选中时间轴节点后的说明卡片）
 * - 转录区（简化版）
 *
 * 数据策略：
 * - 真实 archive 数据从 /api/archives/:id 获取
 * - 时间轴结构暂时用 mock 数据填充骨架
 * - audio URL：优先尝试 /api/archives/:id/audio，无则显示占位
 */
import { useState, useEffect, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import axios from 'axios';
import {
  IconChevronLeft, IconPlayerPlay, IconClock,
  IconMessageCircle, IconPlayerSkipForward, IconCheck
} from '@tabler/icons-react';

const api = axios.create({ baseURL: 'http://localhost:8000' });

// ===== Mock 时间轴数据结构 =====

interface TimelineItem {
  id: string;
  title: string;
  time: string;       // MM:SS 格式
  timeSeconds: number; // 秒数（用于 audio.currentTime 跳转）
  description?: string;
}

interface TimelineSection {
  chapters: TimelineItem[];
  highlights: TimelineItem[];
  terms: TimelineItem[];
}

const MOCK_TIMELINE: TimelineSection = {
  chapters: [
    { id: 'ch1', title: '开场与背景介绍', time: '00:00', timeSeconds: 0, description: '介绍本期话题的背景和目的' },
    { id: 'ch2', title: '核心概念解析', time: '08:23', timeSeconds: 503, description: '深入讲解本期的核心概念和理论' },
    { id: 'ch3', title: '案例分析', time: '22:15', timeSeconds: 1335, description: '通过实际案例说明概念的应用' },
    { id: 'ch4', title: '总结与行动建议', time: '45:30', timeSeconds: 2730, description: '回顾要点并给出具体建议' },
  ],
  highlights: [
    { id: 'hl1', title: '认知科学的关键发现', time: '05:12', timeSeconds: 312, description: '关于大脑可塑性的一项重要研究结论' },
    { id: 'hl2', title: '产品设计的核心原则', time: '18:45', timeSeconds: 1125, description: '用户研究方法的三个核心原则' },
    { id: 'hl3', title: 'AI 辅助编程实践', time: '35:20', timeSeconds: 2120, description: '如何在实际工作中使用 AI 工具' },
  ],
  terms: [
    { id: 'tm1', title: '神经可塑性', time: '06:30', timeSeconds: 390, description: '大脑神经元连接持续改变的能力' },
    { id: 'tm2', title: 'RAG', time: '28:10', timeSeconds: 1690, description: 'Retrieval-Augmented Generation，检索增强生成' },
    { id: 'tm3', title: '影子风格设计', time: '40:55', timeSeconds: 2455, description: '一种模仿特定产品体验的设计方法' },
  ],
};

// ===== 组件 =====

type TimelineTab = 'chapters' | 'highlights' | 'terms';

export default function EpisodePage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  // 归档数据
  const [archiveName, setArchiveName] = useState('');
  const [summary, setSummary] = useState('');
  const [rawText, setRawText] = useState('');
  const [createTime, setCreateTime] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // 播放器状态
  const audioRef = useRef<HTMLAudioElement>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);

  // 时间轴状态
  const [activeTab, setActiveTab] = useState<TimelineTab>('chapters');
  const [selectedItem, setSelectedItem] = useState<TimelineItem | null>(null);

  // 获取 archive 数据
  useEffect(() => {
    if (!id) return;

    setLoading(true);
    api.get(`/api/archives/${id}`)
      .then(res => {
        if (res.data.status === 'success') {
          const d = res.data.data;
          setArchiveName(d.name);
          setSummary(d.summary);
          setRawText(d.raw_text || '');
          setCreateTime(d.createTime || '');
        }
      })
      .catch(() => {
        setError('加载归档失败');
      })
      .finally(() => {
        setLoading(false);
      });
  }, [id]);

  // 音频时间更新
  const handleTimeUpdate = () => {
    if (audioRef.current) {
      setCurrentTime(audioRef.current.currentTime);
    }
  };

  const handleLoadedMetadata = () => {
    if (audioRef.current) {
      setDuration(audioRef.current.duration);
    }
  };

  const togglePlay = () => {
    if (!audioRef.current) return;
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
    setSelectedItem(null);
  };

  const handleItemClick = (item: TimelineItem) => {
    setSelectedItem(item);
    if (audioRef.current && duration > 0) {
      audioRef.current.currentTime = item.timeSeconds;
    }
  };

  const formatTime = (seconds: number) => {
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${s.toString().padStart(2, '0')}`;
  };

  const currentItems = MOCK_TIMELINE[activeTab];

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center h-full">
        <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-[#00ADA6]" />
      </div>
    );
  }

  if (error || !id) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center h-full text-slate-500">
        <p>{error || '无效的归档 ID'}</p>
        <button onClick={() => navigate('/')} className="mt-4 text-[#00ADA6] hover:underline">
          返回首页
        </button>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden bg-white">

      {/* ===== A. 顶部信息区 ===== */}
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
          <div className="w-10 h-10 rounded-lg bg-[#D1FAF5] flex items-center justify-center">
            <IconMessageCircle size={18} className="text-[#00ADA6]" />
          </div>
          <div>
            <h1 className="text-base font-semibold text-slate-800">{archiveName || id}</h1>
            <p className="text-xs text-slate-400 flex items-center gap-1">
              {createTime && <><IconClock size={12} />{createTime}</>}
              {duration > 0 && <span className="ml-2">· {formatTime(duration)}</span>}
            </p>
          </div>
        </div>
      </div>

      {/* ===== 主内容区：播放器 + 时间轴 ===== */}
      <div className="flex-1 flex overflow-hidden">

        {/* 左侧：播放器 + 时间轴 + 转录 */}
        <div className="flex-1 flex flex-col overflow-y-auto">

          {/* ===== B. 播放器区 ===== */}
          <div className="px-8 py-6 border-b border-slate-100">
            <div className="flex items-center gap-4">
              <audio
                ref={audioRef}
                // 注意：这里使用一个假的音频 URL 演示。真实场景下需要后端提供 /api/archives/:id/audio 端点
                src={`/api/archives/${id}/audio`}
                onTimeUpdate={handleTimeUpdate}
                onLoadedMetadata={handleLoadedMetadata}
                onPlay={() => setIsPlaying(true)}
                onPause={() => setIsPlaying(false)}
                onEnded={() => setIsPlaying(false)}
              />
              <button
                onClick={togglePlay}
                className="w-12 h-12 rounded-full bg-[#00ADA6] hover:bg-[#009A94] text-white flex items-center justify-center transition-colors shrink-0"
              >
                {isPlaying
                  ? <IconPlayerSkipForward size={20} className="ml-0.5" />
                  : <IconPlayerPlay size={20} className="ml-0.5" />
                }
              </button>
              <div className="flex-1 min-w-0">
                {/* 进度条 */}
                <div className="flex items-center gap-3">
                  <span className="text-xs text-slate-400 font-mono w-10">{formatTime(currentTime)}</span>
                  <div className="flex-1 h-1.5 bg-slate-100 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-[#00ADA6] rounded-full transition-all"
                      style={{ width: duration > 0 ? `${(currentTime / duration) * 100}%` : '0%' }}
                    />
                  </div>
                  <span className="text-xs text-slate-400 font-mono w-10">{formatTime(duration)}</span>
                </div>
              </div>
            </div>
          </div>

          {/* ===== C. 时间轴区 ===== */}
          <div className="px-8 py-5 border-b border-slate-100">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-sm font-semibold text-slate-700">时间轴</h2>
              {/* Tab 切换 */}
              <div className="flex gap-1 bg-slate-100 rounded-lg p-1">
                {(['chapters', 'highlights', 'terms'] as TimelineTab[]).map(tab => (
                  <button
                    key={tab}
                    onClick={() => setActiveTab(tab)}
                    className={`px-3 py-1 text-xs rounded-md transition-colors ${
                      activeTab === tab
                        ? 'bg-white text-[#00ADA6] shadow-sm font-medium'
                        : 'text-slate-500 hover:text-slate-700'
                    }`}
                  >
                    {tab === 'chapters' ? '章节' : tab === 'highlights' ? '高光' : '术语'}
                  </button>
                ))}
              </div>
            </div>

            {/* 时间轴列表 */}
            <div className="space-y-1">
              {currentItems.map((item) => (
                <button
                  key={item.id}
                  onClick={() => handleItemClick(item)}
                  className={`w-full text-left px-3 py-2.5 rounded-lg transition-all flex items-center gap-3 ${
                    selectedItem?.id === item.id
                      ? 'bg-[#D1FAF5] border border-[#00ADA6]/30'
                      : 'hover:bg-slate-50'
                  }`}
                >
                  <span className="text-sm font-mono font-medium text-[#00ADA6] w-12 shrink-0">
                    {item.time}
                  </span>
                  <span className={`text-sm flex-1 ${
                    selectedItem?.id === item.id ? 'text-[#00ADA6] font-medium' : 'text-slate-700'
                  }`}>
                    {item.title}
                  </span>
                  {selectedItem?.id === item.id && (
                    <IconCheck size={14} className="text-[#00ADA6] shrink-0" />
                  )}
                </button>
              ))}
            </div>
          </div>

          {/* ===== E. 转录区（简化版） ===== */}
          {rawText && (
            <div className="px-8 py-5">
              <h2 className="text-sm font-semibold text-slate-700 mb-3">转录文本</h2>
              <div className="bg-slate-50 rounded-lg p-4 max-h-60 overflow-y-auto">
                <pre className="whitespace-pre-wrap font-mono text-xs text-slate-600 leading-relaxed">
                  {rawText.slice(0, 2000)}{rawText.length > 2000 ? '\n...(已截断)' : ''}
                </pre>
              </div>
            </div>
          )}
        </div>

        {/* ===== D. 右侧节点说明区 ===== */}
        <div className="w-80 border-l border-slate-200 overflow-y-auto p-6 bg-slate-50">
          <h2 className="text-sm font-semibold text-slate-700 mb-4">节点说明</h2>

          {selectedItem ? (
            <div className="space-y-4">
              {/* 封装时间戳 */}
              <div className="inline-flex items-center px-2.5 py-1 bg-[#D1FAF5] text-[#00ADA6] text-sm font-mono font-medium rounded">
                {selectedItem.time}
              </div>

              {/* 标题 */}
              <h3 className="text-base font-semibold text-slate-800">{selectedItem.title}</h3>

              {/* 说明 */}
              {selectedItem.description && (
                <p className="text-sm text-slate-600 leading-relaxed">
                  {selectedItem.description}
                </p>
              )}

              {/* 跳转播放按钮 */}
              <button
                onClick={() => seekTo(selectedItem.timeSeconds)}
                className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-[#00ADA6] hover:bg-[#009A94] text-white text-sm font-medium rounded-lg transition-colors"
              >
                <IconPlayerPlay size={16} />
                跳转到此处播放
              </button>
            </div>
          ) : (
            <div className="text-center py-8">
              <IconClock size={32} className="text-slate-300 mx-auto mb-3" />
              <p className="text-sm text-slate-400">
                点击时间轴节点<br />查看详细说明
              </p>
            </div>
          )}

          {/* 摘要区块（如果选中了节点也显示摘要） */}
          {summary && (
            <div className="mt-6 pt-6 border-t border-slate-200">
              <h3 className="text-sm font-semibold text-slate-700 mb-2">本期摘要</h3>
              <p className="text-xs text-slate-500 leading-relaxed line-clamp-6">
                {summary.slice(0, 300)}{summary.length > 300 ? '...' : ''}
              </p>
            </div>
          )}
        </div>

      </div>
    </div>
  );
}
