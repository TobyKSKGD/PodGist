import { useState, useEffect } from 'react';
import { IconFileDescription, IconClock, IconChevronLeft, IconDownload, IconCopy, IconCheck, IconSearch, IconLoader2, IconMessageCircle } from '@tabler/icons-react';
import TagManager from './TagManager';
import axios from 'axios';

interface ResultViewProps {
  archiveId: string;
  onBack: () => void;
  onJumpToChat: (sessionId: string) => void;
}

interface ArchiveContent {
  id: string;
  name: string;
  summary: string;
  rawText: string;
  createTime: string;
}

const api = axios.create({ baseURL: 'http://localhost:8000' });

export default function ResultView({ archiveId, onBack, onJumpToChat }: ResultViewProps) {
  const [content, setContent] = useState<ArchiveContent | null>(null);
  const [activeTab, setActiveTab] = useState<'summary' | 'transcript'>('summary');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [copied, setCopied] = useState(false);

  // AI IconSearch state
  const [searchQuery, setIconSearchQuery] = useState('');
  const [searchResult, setIconSearchResult] = useState('');
  const [isIconSearching, setIsIconSearching] = useState(false);
  const [showIconSearch, setShowIconSearch] = useState(false);

  // Backlinks
  const [backlinks, setBacklinks] = useState<{id: string; title: string; updated_at: string}[]>([]);

  useEffect(() => {
    fetchArchiveContent();
    fetchBacklinks();
  }, [archiveId]);

  const fetchArchiveContent = async () => {
    try {
      setLoading(true);
      const res = await api.get(`/api/archives/${archiveId}`);
      if (res.data.status === 'success') {
        setContent(res.data.data);
      }
    } catch (err) {
      setError('加载归档内容失败');
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const fetchBacklinks = async () => {
    try {
      const res = await api.get(`/api/chat/archives/${archiveId}/references`);
      if (res.data.status === 'success') setBacklinks(res.data.data);
    } catch {}
  };

  const handleIconCopy = async () => {
    if (!content) return;
    const textToIconCopy = activeTab === 'summary' ? content.summary : content.rawText;
    try {
      await navigator.clipboard.writeText(textToIconCopy);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error('复制失败:', err);
    }
  };

  const handleIconDownload = () => {
    if (!content) return;
    // IconDownload the markdown summary as PodGist_Report.md
    const blob = new Blob([content.summary], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'PodGist_Report.md';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const handleIconSearch = async () => {
    if (!searchQuery.trim() || !content) return;

    setIsIconSearching(true);
    setIconSearchResult('');

    try {
      const res = await api.post('/api/search', {
        archive_id: archiveId,
        query: searchQuery.trim()
      }, {
        headers: { 'Content-Type': 'application/json' }
      });

      if (res.data.status === 'success') {
        setIconSearchResult(res.data.result);
      }
    } catch (err: any) {
      console.error('搜索失败:', err);
      const errorDetail = err.response?.data?.detail;
      const errorMessage = typeof errorDetail === 'string' ? errorDetail : JSON.stringify(errorDetail);
      setIconSearchResult(`搜索失败: ${errorMessage || err.message}`);
    } finally {
      setIsIconSearching(false);
    }
  };

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center h-full">
        <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-[#00ADA6]"></div>
      </div>
    );
  }

  if (error || !content) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center h-full text-slate-500">
        <p>{error || '无法加载内容'}</p>
        <button onClick={onBack} className="mt-4 text-[#00ADA6] hover:underline">
          返回首页
        </button>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden bg-white">
      {/* Header */}
      <div className="border-b border-slate-200 px-8 py-4 flex items-center justify-between bg-white">
        <div className="flex items-center gap-4">
          <button
            onClick={onBack}
            className="flex items-center gap-1 text-slate-500 hover:text-slate-700 transition-colors"
          >
            <IconChevronLeft size={20} />
            <span className="text-sm">返回</span>
          </button>
          <div className="h-6 w-px bg-slate-200"></div>
          <div>
            <h1 className="text-lg font-semibold text-slate-800 truncate max-w-md">
              {content.name}
            </h1>
            <p className="text-xs text-slate-400 flex items-center gap-1">
              <IconClock size={12} />
              {content.createTime}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowIconSearch(!showIconSearch)}
            className={`flex items-center gap-2 px-3 py-2 text-sm rounded-lg transition-colors ${
              showIconSearch ? 'bg-[#00ADA6] text-white' : 'text-slate-600 hover:bg-slate-100'
            }`}
          >
            <IconSearch size={16} />
            AI 定位
          </button>
          <TagManager archiveId={archiveId} />
          <button
            onClick={handleIconCopy}
            className="flex items-center gap-2 px-3 py-2 text-sm text-slate-600 hover:bg-slate-100 rounded-lg transition-colors"
          >
            {copied ? <IconCheck size={16} className="text-[#10B981]" /> : <IconCopy size={16} />}
            {copied ? '已复制' : '复制'}
          </button>
          <button
            onClick={handleIconDownload}
            className="flex items-center gap-2 px-3 py-2 text-sm bg-[#00ADA6] text-white hover:bg-[#009A94] rounded-lg transition-colors"
          >
            <IconDownload size={16} />
            下载报告
          </button>
        </div>
      </div>

      {/* AI IconSearch Bar */}
      {showIconSearch && (
        <div className="border-b border-slate-200 px-8 py-4 bg-slate-50">
          <div className="max-w-4xl mx-auto">
            <label className="text-sm font-medium text-slate-700 mb-2 flex items-center gap-2">
              <IconMessageCircle size={16} />
              AI 模糊定位器 (当前音频)
            </label>
            <div className="flex gap-2 mt-2">
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setIconSearchQuery(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleIconSearch()}
                placeholder="向本期音频提问，如：这段音频主要讨论了什么话题？"
                className="flex-1 px-4 py-2.5 bg-white border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#00ADA6]/50 focus:border-[#00ADA6] transition-all"
              />
              <button
                onClick={handleIconSearch}
                disabled={isIconSearching || !searchQuery.trim()}
                className="px-5 py-2.5 bg-[#00ADA6] text-white rounded-lg font-medium hover:bg-[#009A94] disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2 transition-colors"
              >
                {isIconSearching ? (
                  <>
                    <IconLoader2 size={16} className="animate-spin" />
                    搜索中...
                  </>
                ) : (
                  <>
                    <IconSearch size={16} />
                    精准搜索
                  </>
                )}
              </button>
            </div>
            {searchResult && (
              <div className="mt-4 p-4 bg-white rounded-lg border border-slate-200">
                <p className="text-sm text-slate-700 whitespace-pre-wrap">{searchResult}</p>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Tab Navigation */}
      <div className="border-b border-slate-200 px-8">
        <div className="flex gap-6">
          <button
            onClick={() => setActiveTab('summary')}
            className={`py-3 text-sm font-medium border-b-2 transition-colors ${
              activeTab === 'summary'
                ? 'border-[#00ADA6] text-[#00ADA6]'
                : 'border-transparent text-slate-500 hover:text-slate-700'
            }`}
          >
            <div className="flex items-center gap-2">
              <IconFileDescription size={16} />
              AI 摘要
            </div>
          </button>
          <button
            onClick={() => setActiveTab('transcript')}
            className={`py-3 text-sm font-medium border-b-2 transition-colors ${
              activeTab === 'transcript'
                ? 'border-[#00ADA6] text-[#00ADA6]'
                : 'border-transparent text-slate-500 hover:text-slate-700'
            }`}
          >
            <div className="flex items-center gap-2">
              <IconClock size={16} />
              原始转录
            </div>
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto">
        <div className="max-w-4xl mx-auto p-8">
          {activeTab === 'summary' ? (
            <div className="prose prose-slate max-w-none">
              <div
                className="markdown-content"
                dangerouslySetInnerHTML={{
                  __html: renderMarkdown(content.summary),
                }}
              />
            </div>
          ) : (
            <div className="bg-slate-50 rounded-lg p-6">
              <pre className="whitespace-pre-wrap font-mono text-sm text-slate-700 leading-relaxed">
                {content.rawText}
              </pre>
            </div>
          )}
        </div>

        {/* Backlinks 关联对话 */}
        {backlinks.length > 0 && (
          <div className="border-t border-slate-200 bg-slate-50 px-8 py-5">
            <div className="max-w-4xl mx-auto">
              <h3 className="text-sm font-semibold text-slate-700 mb-3 flex items-center gap-2">
                <IconMessageCircle size={14} className="text-[#00ADA6]" />
                在这些对话中被引用
              </h3>
              <div className="flex flex-wrap gap-2">
                {backlinks.map(ref => (
                  <button
                    key={ref.id}
                    onClick={() => onJumpToChat(ref.id)}
                    className="flex items-center gap-2 px-3 py-1.5 bg-white border border-slate-200 rounded-lg text-sm text-slate-600 hover:border-[#00ADA6] hover:text-[#00ADA6] transition-colors"
                  >
                    <IconMessageCircle size={12} />
                    {ref.title || '无标题对话'}
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// Simple markdown renderer
function renderMarkdown(md: string): string {
  return (
    md
      // Timestamps [MM:SS] or [MM:SS.SS] or [H:MM:SS] etc. - green badges
      .replace(/\[(\d+:\d{2}(?:\.\d+)?)\]/g, '<span class="inline-flex items-center px-1.5 py-0.5 rounded bg-[#D1FAF5] text-[#10B981] text-xs font-mono font-medium">$1</span>')
      // Headers
      .replace(/^### (.*$)/gim, '<h3 class="text-lg font-semibold text-slate-800 mt-6 mb-3">$1</h3>')
      .replace(/^## (.*$)/gim, '<h2 class="text-xl font-bold text-slate-800 mt-8 mb-4">$1</h2>')
      .replace(/^# (.*$)/gim, '<h1 class="text-2xl font-bold text-slate-800 mt-8 mb-4">$1</h1>')
      // Bold
      .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
      // Blockquote
      .replace(/^> (.*$)/gim, '<blockquote class="border-l-4 border-[#00ADA6] pl-4 py-2 my-4 bg-slate-50 text-slate-600">$1</blockquote>')
      // List items
      .replace(/^- (.*$)/gim, '<li class="ml-4 py-1 text-slate-700">$1</li>')
      // Paragraphs
      .replace(/\n\n/g, '</p><p class="my-4 text-slate-700 leading-relaxed">')
      // Wrap in paragraph if not already wrapped
      .replace(/^(.+)$/gim, (match) => {
        if (match.startsWith('<')) return match;
        return `<p class="my-4 text-slate-700 leading-relaxed">${match}</p>`;
      })
      // Fix double paragraph wrapping
      .replace(/<p class="my-4[^"]*"><(h[123]|blockquote|li)/g, '<$1')
      .replace(/<\/(h[123]|blockquote|li)><\/p>/g, '</$1>')
  );
}
