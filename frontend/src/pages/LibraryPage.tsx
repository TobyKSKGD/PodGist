import { useNavigate } from 'react-router-dom';
import {
  IconPlus, IconClock, IconMessageCircle,
  IconUpload, IconRadio, IconLayersLinked,
  IconPlayerPlay, IconBrandBilibili
} from '@tabler/icons-react';

// ===== Mock 数据 =====

interface ContinueListeningItem {
  id: string;
  title: string;
  source: string;
  duration: string;
  progress: number; // 0~1
  coverColor: string;
}

interface RecentArchiveItem {
  id: string;
  title: string;
  source: string;
  createTime: string;
  tag?: string;
}

const CONTINUE_LISTENING: ContinueListeningItem[] = [
  {
    id: 'ep-001',
    title: '深度学习与认知科学',
    source: '小宇宙',
    duration: '58:23',
    progress: 0.35,
    coverColor: '#E0F2FE',
  },
  {
    id: 'ep-002',
    title: '产品认知与用户研究方法论',
    source: '喜马拉雅',
    duration: '42:10',
    progress: 0.72,
    coverColor: '#FEF3C7',
  },
  {
    id: 'ep-003',
    title: 'AI 时代的编程教育',
    source: 'Bilibili',
    duration: '1:15:33',
    progress: 0.08,
    coverColor: '#D1FAF5',
  },
];

const RECENT_ARCHIVES: RecentArchiveItem[] = [
  {
    id: 'arch-001',
    title: '认知科学与 AI 的未来',
    source: '小宇宙',
    createTime: '2 天前',
    tag: '科技',
  },
  {
    id: 'arch-002',
    title: '产品思维 30 讲（节选）',
    source: '喜马拉雅',
    createTime: '3 天前',
    tag: '商业',
  },
  {
    id: 'arch-003',
    title: 'Python 设计模式深入讲解',
    source: '本地文件',
    createTime: '5 天前',
    tag: '技术',
  },
  {
    id: 'arch-004',
    title: '吴恩达访谈：大模型的下一步',
    source: 'Bilibili',
    createTime: '1 周前',
    tag: 'AI',
  },
];

// ===== 导入类型定义 =====
type ImportType = 'local' | 'podcast' | 'bilibili' | 'batch';

interface ImportEntry {
  type: ImportType;
  label: string;
  description: string;
  icon: React.ReactNode;
  color: string;
  bgColor: string;
}

const IMPORT_ENTRIES: ImportEntry[] = [
  {
    type: 'local',
    label: '本地音频',
    description: 'MP3、WAV、M4A',
    icon: <IconUpload size={22} />,
    color: 'text-[#00ADA6]',
    bgColor: 'bg-[#D1FAF5]',
  },
  {
    type: 'podcast',
    label: '播客链接',
    description: '小宇宙 · 喜马拉雅 · Apple',
    icon: <IconRadio size={22} />,
    color: 'text-[#8B5CF6]',
    bgColor: 'bg-[#EDE9FE]',
  },
  {
    type: 'bilibili',
    label: '视频音频',
    description: 'Bilibili 视频剥离',
    icon: <IconBrandBilibili size={22} />,
    color: 'text-[#EF4444]',
    bgColor: 'bg-[#FEE2E2]',
  },
  {
    type: 'batch',
    label: '批量处理',
    description: '多个文件一次处理',
    icon: <IconLayersLinked size={22} />,
    color: 'text-[#F59E0B]',
    bgColor: 'bg-[#FEF3C7]',
  },
];

// ===== 组件 =====

export default function LibraryPage() {
  const navigate = useNavigate();

  const handleImportClick = (type: ImportType) => {
    navigate(`/import?tab=${type}`);
  };

  const handleContinueListen = (id: string) => {
    navigate(`/episode/${id}`);
  };

  const handleArchiveClick = (id: string) => {
    navigate(`/episode/${id}`);
  };

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-5xl w-full mx-auto p-8 pb-16">

        {/* ===== A. 顶部欢迎区 ===== */}
        <div className="mb-10">
          <h1 className="text-2xl font-bold text-slate-800 mb-2">
            导入音频，生成可跳转时间轴
          </h1>
          <p className="text-slate-500 text-sm leading-relaxed">
            支持本地文件、播客链接、Bilibili 视频，让长音频变得可听、可找、可回看。
          </p>
        </div>

        {/* ===== B. 继续收听 ===== */}
        {CONTINUE_LISTENING.length > 0 && (
          <section className="mb-10">
            <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-4 flex items-center gap-2">
              <IconPlayerPlay size={14} className="text-[#00ADA6]" />
              继续收听
            </h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {CONTINUE_LISTENING.map((item) => (
                <button
                  key={item.id}
                  onClick={() => handleContinueListen(item.id)}
                  className="text-left bg-white border border-slate-200 rounded-xl p-4 hover:border-[#00ADA6] hover:shadow-sm transition-all group"
                >
                  {/* 封面色块 + 进度条 */}
                  <div className="flex items-start gap-3 mb-3">
                    <div
                      className="w-12 h-12 rounded-lg shrink-0 flex items-center justify-center"
                      style={{ backgroundColor: item.coverColor }}
                    >
                      <IconMessageCircle size={20} className="text-slate-500" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-slate-800 truncate group-hover:text-[#00ADA6] transition-colors">
                        {item.title}
                      </p>
                      <p className="text-xs text-slate-400 mt-0.5">{item.source} · {item.duration}</p>
                    </div>
                  </div>
                  {/* 进度条 */}
                  <div className="w-full bg-slate-100 rounded-full h-1">
                    <div
                      className="bg-[#00ADA6] h-1 rounded-full transition-all"
                      style={{ width: `${item.progress * 100}%` }}
                    />
                  </div>
                  <p className="text-xs text-slate-400 mt-1.5">
                    {Math.round(item.progress * 100)}% 已听完
                  </p>
                </button>
              ))}
            </div>
          </section>
        )}

        {/* ===== C. 最近归档 ===== */}
        <section className="mb-10">
          <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-4 flex items-center gap-2">
            <IconClock size={14} className="text-[#00ADA6]" />
            最近归档
          </h2>
          <div className="bg-white border border-slate-200 rounded-xl divide-y divide-slate-100 overflow-hidden">
            {RECENT_ARCHIVES.map((item) => (
              <button
                key={item.id}
                onClick={() => handleArchiveClick(item.id)}
                className="w-full text-left px-4 py-3.5 hover:bg-slate-50 transition-colors flex items-center justify-between group"
              >
                <div className="flex items-center gap-3 flex-1 min-w-0">
                  <IconMessageCircle size={16} className="text-slate-300 shrink-0" />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-slate-700 truncate group-hover:text-[#00ADA6] transition-colors">
                      {item.title}
                    </p>
                    <p className="text-xs text-slate-400 mt-0.5">
                      {item.source} · {item.createTime}
                    </p>
                  </div>
                </div>
                {item.tag && (
                  <span className="ml-3 text-xs px-2 py-0.5 bg-slate-100 text-slate-500 rounded shrink-0">
                    {item.tag}
                  </span>
                )}
              </button>
            ))}
          </div>
        </section>

        {/* ===== D. 导入入口 ===== */}
        <section>
          <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-4 flex items-center gap-2">
            <IconPlus size={14} className="text-[#00ADA6]" />
            导入内容
          </h2>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {IMPORT_ENTRIES.map((entry) => (
              <button
                key={entry.type}
                onClick={() => handleImportClick(entry.type)}
                className="flex flex-col items-center gap-2 p-5 bg-white border border-slate-200 rounded-xl hover:border-[#00ADA6] hover:shadow-sm transition-all text-center group"
              >
                <div className={`w-10 h-10 rounded-lg ${entry.bgColor} flex items-center justify-center ${entry.color}`}>
                  {entry.icon}
                </div>
                <div>
                  <p className="text-sm font-medium text-slate-700 group-hover:text-[#00ADA6] transition-colors">
                    {entry.label}
                  </p>
                  <p className="text-xs text-slate-400 mt-0.5">{entry.description}</p>
                </div>
              </button>
            ))}
          </div>
        </section>

      </div>
    </div>
  );
}
