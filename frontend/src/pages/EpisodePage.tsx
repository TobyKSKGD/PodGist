/**
 * EpisodePage — 播放器详情页
 *
 * 数据来源：/api/archives/:id
 *  - name, summary, rawText, createTime, audioUrl, timeline
 *
 * 时间轴：
 *  - highlights：从 summary.md 中解析真实时间戳条目
 *  - chapters / terms：后端当前返回空数组，待后续扩展
 *
 * 音频：
 *  - audioUrl 为 null（音频文件处理后已删除）
 *  - 播放器 UI 保留，但不实际播放
 */
import { useState, useEffect, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import axios from 'axios';
import {
  IconChevronLeft, IconPlayerPlay, IconClock,
  IconMessageCircle, IconPlayerSkipForward, IconCheck
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
}

type TimelineTab = 'chapters' | 'highlights' | 'terms';

export default function EpisodePage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  // 数据
  const [archive, setArchive] = useState<ArchiveDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // 播放器状态（audioUrl 为 null 时不实际播放）
  const audioRef = useRef<HTMLAudioElement>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);

  // 时间轴状态
  const [activeTab, setActiveTab] = useState<TimelineTab>('highlights');
  const [selectedItem, setSelectedItem] = useState<TimelineItem | null>(null);

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
          }
        }
      })
      .catch(() => setError('加载归档失败'))
      .finally(() => setLoading(false));
  }, [id]);

  // 音频事件
  const handleTimeUpdate = () => {
    if (audioRef.current) setCurrentTime(audioRef.current.currentTime);
  };
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

  const handleItemClick = (item: TimelineItem) => {
    setSelectedItem(item);
    if (archive?.audioUrl && audioRef.current) {
      audioRef.current.currentTime = item.seconds;
    }
  };

  const formatTime = (seconds: number) => {
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${s.toString().padStart(2, '0')}`;
  };

  // 当前 tab 的列表
  const currentItems = archive?.timeline[activeTab] ?? [];

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
          <div className="w-10 h-10 rounded-lg bg-[#D1FAF5] flex items-center justify-center">
            <IconMessageCircle size={18} className="text-[#00ADA6]" />
          </div>
          <div>
            <h1 className="text-base font-semibold text-slate-800">{archive.name}</h1>
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

        {/* 左侧：播放器 + 时间轴 + 转录 */}
        <div className="flex-1 flex flex-col overflow-y-auto">

          {/* ===== 播放器区 ===== */}
          <div className="px-8 py-6 border-b border-slate-100">
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

          {/* ===== 时间轴区 ===== */}
          <div className="px-8 py-5 border-b border-slate-100">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-sm font-semibold text-slate-700">时间轴</h2>
              <div className="flex gap-1 bg-slate-100 rounded-lg p-1">
                {(['chapters', 'highlights', 'terms'] as TimelineTab[]).map(tab => {
                  const count = archive.timeline[tab].length;
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
                      {tab === 'chapters' ? '章节' : tab === 'highlights' ? '高光' : '术语'}
                      {count > 0 && <span className="ml-1 text-[10px] opacity-60">({count})</span>}
                    </button>
                  );
                })}
              </div>
            </div>

            {currentItems.length === 0 ? (
              <p className="text-sm text-slate-400 py-4 text-center">
                {activeTab === 'chapters' ? '暂无章节信息' :
                 activeTab === 'highlights' ? '暂无高光时间轴' : '暂无术语解释'}
              </p>
            ) : (
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
            )}
          </div>

          {/* ===== 转录区 ===== */}
          {archive.rawText && (
            <div className="px-8 py-5">
              <h2 className="text-sm font-semibold text-slate-700 mb-3">转录文本</h2>
              <div className="bg-slate-50 rounded-lg p-4 max-h-60 overflow-y-auto">
                <pre className="whitespace-pre-wrap font-mono text-xs text-slate-600 leading-relaxed">
                  {archive.rawText.slice(0, 2000)}{archive.rawText.length > 2000 ? '\n...(已截断)' : ''}
                </pre>
              </div>
            </div>
          )}
        </div>

        {/* ===== 右侧节点说明区 ===== */}
        <div className="w-80 border-l border-slate-200 overflow-y-auto p-6 bg-slate-50">
          <h2 className="text-sm font-semibold text-slate-700 mb-4">节点说明</h2>

          {selectedItem ? (
            <div className="space-y-4">
              <div className="inline-flex items-center px-2.5 py-1 bg-[#D1FAF5] text-[#00ADA6] text-sm font-mono font-medium rounded">
                {selectedItem.time}
              </div>
              <h3 className="text-base font-semibold text-slate-800">{selectedItem.title}</h3>
              {selectedItem.description && (
                <p className="text-sm text-slate-600 leading-relaxed">{selectedItem.description}</p>
              )}
              {hasAudio && (
                <button
                  onClick={() => seekTo(selectedItem.seconds)}
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

          {/* 摘要区块 */}
          {archive.summary && (
            <div className="mt-6 pt-6 border-t border-slate-200">
              <h3 className="text-sm font-semibold text-slate-700 mb-2">本期摘要</h3>
              <p className="text-xs text-slate-500 leading-relaxed line-clamp-6">
                {archive.summary.slice(0, 300)}{archive.summary.length > 300 ? '...' : ''}
              </p>
            </div>
          )}
        </div>

      </div>
    </div>
  );
}
