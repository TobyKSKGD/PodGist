import { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import ReactMarkdown from 'react-markdown';
import {
  IconMessageCircle, IconPlus, IconTrash, IconChevronDown,
  IconChevronLeft, IconChevronRight,
  IconSearch, IconLoader2,
  IconBook, IconTag, IconBrain
} from '@tabler/icons-react';

interface ChatReference {
  archive_id: string;
  archive_name: string;
  timestamp: string;
}

interface ChatSourceLink {
  archiveId: string;
  timestamp: string;
}

function findArchiveId(
  archiveName: string,
  references: ChatReference[] | undefined,
  archives: { id: string; name: string }[],
  timestamps: string[] = [],
): string | undefined {
  const normalize = (value: string) => value
    .replace(/\s/g, '')
    .replaceAll('《', '')
    .replaceAll('》', '')
    .replaceAll('「', '')
    .replaceAll('」', '')
    .replaceAll('【', '')
    .replaceAll('】', '')
    .replaceAll('[', '')
    .replaceAll(']', '')
    .replaceAll('（', '')
    .replaceAll('）', '')
    .replaceAll('(', '')
    .replaceAll(')', '')
    .toLowerCase();
  const normalizedName = normalize(archiveName);
  const isPlaceholderName = /^(?:\.{2,}|…+|⋯+)$/.test(archiveName.trim());
  const matches = (candidate: string) => {
    const normalizedCandidate = normalize(candidate);
    return !isPlaceholderName && (normalizedCandidate === normalizedName
      || normalizedName.includes(normalizedCandidate)
      || normalizedCandidate.includes(normalizedName));
  };

  return references?.find((reference) => matches(reference.archive_name))?.archive_id
    || references?.find((reference) => timestamps.includes(reference.timestamp))?.archive_id
    || archives.find((archive) => matches(archive.name))?.id;
}

function getArchiveDisplayName(
  archiveId: string | undefined,
  fallbackName: string,
  references: ChatReference[] | undefined,
  archives: { id: string; name: string }[],
): string {
  if (!archiveId) return fallbackName;
  return references?.find((reference) => reference.archive_id === archiveId)?.archive_name
    || archives.find((archive) => archive.id === archiveId)?.name
    || fallbackName;
}

function getExplicitArchiveName(rawArchiveName: string): string {
  // 模型偶尔会在正文作品名之后才输出真正来源，例如：
  // 《作品名》相关说明……「来源：《完整归档标题》[00:16]」。
  // 宽松引用正则会从前一个书名号开始匹配；此时应采用最后一个明确的来源标题。
  const explicitSourceMarker = /(?:参考)?来源\s*[:：]?\s*《/g;
  const markers = [...rawArchiveName.matchAll(explicitSourceMarker)];
  const lastMarker = markers.at(-1);
  if (!lastMarker || lastMarker.index === undefined) return rawArchiveName.trim();

  return rawArchiveName
    .slice(lastMarker.index + lastMarker[0].length)
    .trim();
}

/** 把纯文本内容按引用格式拆成片段，引用部分可点击 */
function renderContentWithCitations(
  content: string,
  references: ChatReference[] | undefined,
  archives: { id: string; name: string }[],
  onJump: ((source: ChatSourceLink) => void) | undefined
): React.ReactNode[] {
  // 兼容模型生成的「来源：…」、来源：…，以及兜底回复里的“参考来源：\n- …”。
  // 整个来源标记都会被消费，避免把「、」或列表符号遗留在正文中单独换行。
  // 标题本身可能包含书名号，例如《天下第一？《女神异闻录5皇家版》到底有没有被过誉？》。
  // 用紧邻时间戳的外层 `》` 作为标题终点，不能在内部第一个 `》` 提前截断。
  // 正文中的引用必须带“来源：”；不带前缀的兜底来源只允许出现在独立行首。
  // 这样不会把正文里的普通作品名误当成引用起点并一直吞到后面的时间戳。
  const pattern = /(?:[「『[]\s*)?(?:(?:(?:参考)?来源\s*[:：]?\s*)(?:[-•·]\s*)?|(?:^|\n)\s*(?:[-•·]\s*)?)《(.+?)》((?:\s*\[\d{1,2}:\d{2}(?::\d{2})?\])+)(?:\s*[」』\]])?(?:\s*[。.]?(?=\s|$))?/gm;
  const parts: React.ReactNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  let key = 0;
  let lastResolvedArchiveId: string | undefined;

  const pushMarkdown = (raw: string) => {
    // 模型常把引用末尾的句号、列表符或额外时间戳拆成单独一行；这些不属于正文。
    const cleaned = raw
      .replace(/^\s*(?:[-•·]\s*)?(?:[。.]\s*)+(?=\S|$)/, '')
      .replace(/\n\s*(?:[-•·]\s*)?(?:[。.]\s*)+(?=\n|$)/g, '\n')
      .replace(/^(?:\s*\[\d{1,2}:\d{2}(?::\d{2})?\])+\s*[。.]?\s*/g, '')
      .replace(/\n{3,}/g, '\n\n');
    if (cleaned.trim()) parts.push(<ReactMarkdown key={key++}>{cleaned}</ReactMarkdown>);
  };

  while ((match = pattern.exec(content)) !== null) {
    if (match.index > lastIndex) {
      pushMarkdown(content.slice(lastIndex, match.index));
    }
    const archiveName = getExplicitArchiveName(match[1]);
    const timestamps = [...match[2].matchAll(/\[(\d{1,2}:\d{2}(?::\d{2})?)\]/g)].map(item => item[1]);
    const timestamp = timestamps[0] || '';
    const placeholderName = /^(?:\.{2,}|…+|⋯+)$/.test(archiveName.trim());
    const targetId = findArchiveId(archiveName, references, archives, timestamps)
      || (placeholderName ? lastResolvedArchiveId : undefined);
    if (targetId) lastResolvedArchiveId = targetId;
    const displayName = getArchiveDisplayName(targetId, archiveName, references, archives);
    const onClick = () => {
      if (targetId && onJump) onJump({ archiveId: targetId, timestamp });
    };
    parts.push(
      <div key={key++} className="my-2 flex max-w-full">
        <button
          type="button"
          onClick={onClick}
          disabled={!targetId}
          className="inline-flex min-w-0 max-w-full items-center gap-1.5 rounded-md text-left text-xs italic text-slate-400 transition-colors hover:text-[#00ADA6] hover:underline disabled:cursor-default disabled:hover:no-underline"
          title={targetId ? `打开《${displayName}》的 ${timestamp} 时间轴` : displayName}
        >
          <span className="shrink-0">来源 · 《</span>
          <span className="min-w-0 overflow-hidden text-ellipsis whitespace-nowrap">{displayName}</span>
          <span className="shrink-0">》[{timestamp}]</span>
        </button>
      </div>
    );
    lastIndex = match.index + match[0].length;
  }

  // 剩余文本
  if (lastIndex < content.length) {
    pushMarkdown(content.slice(lastIndex));
  }

  return parts;
}

const api = axios.create({ baseURL: 'http://localhost:8000' });

interface Tag { id: string; name: string; created_at: string; }
interface Session { id: string; title: string; updated_at: string; }
interface Message {
  id: string;
  role: string;
  content: string;
  created_at: string;
  references?: ChatReference[];
}

interface ScopeOption {
  type: 'global' | 'tag' | 'archive';
  label: string;
  id?: string;
}

interface ChatViewProps {
  onJumpToArchive?: (source: ChatSourceLink) => void;
}

export default function ChatView({ onJumpToArchive }: ChatViewProps) {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [tags, setTags] = useState<Tag[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [scopeOpen, setScopeOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [scope, setScope] = useState<ScopeOption>({ type: 'global', label: '全库检索' });
  const [archives, setArchives] = useState<{id: string; name: string}[]>([]);
  const bottomRef = useRef<HTMLDivElement>(null);
  const scopeRef = useRef<HTMLDivElement>(null);

  // 加载标签和归档
  useEffect(() => {
    loadTags();
    loadArchives();
    loadSessions();

    // 检查是否从归档 Backlink 跳转而来
    const jumpSessionId = sessionStorage.getItem('jump_to_session');
    if (jumpSessionId) {
      sessionStorage.removeItem('jump_to_session');
      setActiveSessionId(jumpSessionId);
    }
  }, []);

  // 加载会话消息
  useEffect(() => {
    if (activeSessionId) {
      loadSession(activeSessionId);
    } else {
      setMessages([]);
    }
  }, [activeSessionId]);

  // 滚动到底部
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // 点击外部关闭范围选择器
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (scopeRef.current && !scopeRef.current.contains(e.target as Node)) {
        setScopeOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  async function loadTags() {
    try {
      const res = await api.get('/api/chat/tags');
      if (res.data.status === 'success') setTags(res.data.data);
    } catch { /* ignore */ }
  }

  async function loadArchives() {
    try {
      const res = await api.get('/api/archives');
      if (res.data.status === 'success') setArchives(res.data.archives);
    } catch { /* ignore */ }
  }

  async function loadSessions() {
    try {
      const res = await api.get('/api/chat/sessions');
      if (res.data.status === 'success') setSessions(res.data.data);
    } catch { /* ignore */ }
  }

  async function loadSession(sessionId: string) {
    try {
      const res = await api.get(`/api/chat/sessions/${sessionId}`);
      if (res.data.status === 'success') {
        setMessages(res.data.data.messages || []);
      }
    } catch { setMessages([]); }
  }

  async function createSession() {
    try {
      const res = await api.post('/api/chat/sessions', { title: '新对话' });
      if (res.data.status === 'success') {
        setActiveSessionId(res.data.session_id);
        setMessages([]);
        loadSessions();
      }
    } catch { /* ignore */ }
  }

  async function deleteSession(sessionId: string, e: React.MouseEvent) {
    e.stopPropagation();
    try {
      await api.delete(`/api/chat/sessions/${sessionId}`);
      if (activeSessionId === sessionId) {
        setActiveSessionId(null);
        setMessages([]);
      }
      loadSessions();
    } catch { /* ignore */ }
  }

  async function selectScope(option: ScopeOption) {
    setScope(option);
    setScopeOpen(false);
  }

  async function sendMessage() {
    if (!input.trim() || isLoading) return;

    // 如果没有会话，先创建一个
    let sessionId = activeSessionId;
    if (!sessionId) {
      try {
        const res = await api.post('/api/chat/sessions', { title: '新对话' });
        if (res.data.status === 'success') {
          sessionId = res.data.session_id;
          setActiveSessionId(sessionId);
          loadSessions();
        } else {
          setIsLoading(false);
          return;
        }
      } catch {
        setIsLoading(false);
        return;
      }
    }

    const userMessage: Message = {
      id: `temp-${Date.now()}`,
      role: 'user',
      content: input.trim(),
      created_at: new Date().toISOString()
    };
    setMessages(prev => [...prev, userMessage]);
    setInput('');
    setIsLoading(true);

    try {
      const body: Record<string, unknown> = { query: userMessage.content };
      if (scope.type === 'archive' && scope.id) {
        body.archive_ids = [scope.id];
      } else if (scope.type === 'tag' && scope.id) {
        body.tag_ids = [scope.id];
      }

      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 120000);

      const response = await fetch(
        `http://localhost:8000/api/chat/sessions/${sessionId}/stream`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
          signal: controller.signal
        }
      );
      clearTimeout(timeoutId);

      if (!response.ok) {
        throw new Error(`请求失败: ${response.status}`);
      }

      const reader = response.body?.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let fullContent = '';
      let receivedRefs: ChatReference[] = [];

      setMessages(prev => [...prev, {
        id: `assistant-streaming`,
        role: 'assistant',
        content: '',
        created_at: new Date().toISOString()
      }]);

      // 【核心修复】：将事件解析状态提升到循环外部
      // 即使 TCP chunk 边界把一个 SSE 事件切成多段，解析器也不会失忆
      let eventData: Record<string, string> = { event: '', data: '' };
      let isStreamEnded = false;

      while (!isStreamEnded) {
        let value: Uint8Array | undefined;
        let done = false;
        if (!reader) break;
        try {
          const result = await reader.read();
          value = result.value;
          done = result.done;
        } catch {
          done = true;
        }

        if (value) {
          buffer += decoder.decode(value, { stream: true });
        }

        // 内层循环：只负责把 buffer 里的数据一行行吃掉
        while (true) {
          if (!buffer) break;

          const lfIdx = buffer.indexOf('\n');
          if (lfIdx === -1) break; // 数据不够一行，等下一个 TCP Chunk

          const line = buffer.slice(0, lfIdx).replace(/\r$/, '');
          buffer = buffer.slice(lfIdx + 1);

          // 遇到空行，代表一个完整的 SSE 事件结束，开始处理
          if (line === '') {
            if (eventData['event'] === 'token' && eventData['data']) {
              fullContent += eventData['data'];
              setMessages(prev =>
                prev.map(m =>
                  m.id === 'assistant-streaming' ? { ...m, content: fullContent } : m
                )
              );
            } else if (eventData['event'] === 'done') {
              const dataStr = eventData['data'] || '';
              const nlIdx = dataStr.indexOf('\n');
              if (nlIdx !== -1) {
                try {
                  receivedRefs = JSON.parse(dataStr.slice(0, nlIdx));
                } catch {
                  // 兼容服务端没有附带引用信息的历史响应。
                }
                fullContent = dataStr.slice(nlIdx + 1);
              } else if (dataStr) {
                fullContent = dataStr;
              }
            } else if (eventData['event'] === 'error') {
              fullContent = eventData['data'] || '智能对话暂时无法生成回复，请稍后重试。';
            } else if (eventData['event'] === 'end') {
              isStreamEnded = true;
            }

            // 处理完毕，清空大脑，准备接收下一个事件
            eventData = { event: '', data: '' };
            continue;
          }

          // 非空行，解析 SSE 的 field: value
          const colonIdx = line.indexOf(':');
          if (colonIdx === -1) continue;

          const field = line.slice(0, colonIdx).trim();
          // SSE 标准：冒号后的第一个空格要保留（是 fieldValue 的一部分）
          const fieldValue = line.slice(colonIdx + 1).replace(/^ /, '');

          if (field === 'event') {
            eventData['event'] = fieldValue;
          } else if (field === 'data') {
            if (eventData['data']) eventData['data'] += '\n' + fieldValue;
            else eventData['data'] = fieldValue;
          }
        }

        if (done || isStreamEnded) break;
      }

      // 统一在 finally 前替换流式消息（无论成功结束还是 reader 出错）
      // 如果 streamEnded=false（reader 出错），fullContent 可能为空
      setMessages(prev =>
        prev.map(m => {
          if (m.id === 'assistant-streaming') {
            return {
              id: `assistant-${Date.now()}`,
              role: 'assistant',
              content: fullContent || '（未能获取回复）',
              created_at: new Date().toISOString(),
              references: receivedRefs
            };
          }
          return m;
        })
      );
      loadSessions();
    } catch (err) {
      console.error('[ChatView] sendMessage error:', err);
      // 移除失败的流式占位
      setMessages(prev => prev.filter(m => m.id !== 'assistant-streaming'));
      if (err instanceof Error && err.name === 'AbortError') {
        setMessages(prev => [...prev, {
          id: `error-${Date.now()}`,
          role: 'assistant',
          content: '（请求超时，请检查网络或 API 配置）',
          created_at: new Date().toISOString()
        }]);
      } else {
        const errMsg = err instanceof Error ? `${err.name}: ${err.message}` : String(err);
        setMessages(prev => [...prev, {
          id: `error-${Date.now()}`,
          role: 'assistant',
          content: `（发送失败: ${errMsg}）`,
          created_at: new Date().toISOString()
        }]);
      }
    } finally {
      setIsLoading(false);
    }
  }

  function formatTime(iso: string) {
    try {
      return new Date(iso).toLocaleString('zh-CN', {
        month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit'
      });
    } catch { return ''; }
  }

  return (
    <div className="flex h-full">
      {/* ================= 左侧会话列表（可折叠）================= */}
      <div className={`flex flex-col bg-[#F9F9F9] border-r border-slate-200 transition-all duration-300 ${sidebarCollapsed ? 'w-16' : 'w-64'}`}>
        {/* Header */}
        <div className="flex items-center justify-between h-12 px-3">
          {!sidebarCollapsed && (
            <span className="text-sm font-bold text-slate-700 flex items-center gap-1.5">
              <IconBrain size={16} className="text-[#00ADA6]" />
              智能对话
            </span>
          )}
          <div className="flex items-center gap-1">
            {!sidebarCollapsed && (
              <button
                onClick={createSession}
                className="p-1.5 hover:bg-slate-200 rounded-md transition-colors"
                title="新建对话"
              >
                <IconPlus size={16} className="text-slate-500" />
              </button>
            )}
            <button
              onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
              className="p-1.5 hover:bg-slate-200 rounded-md transition-colors text-slate-500 hover:text-slate-700"
              title={sidebarCollapsed ? '展开侧栏' : '收起侧栏'}
            >
              {sidebarCollapsed ? <IconChevronRight size={16} /> : <IconChevronLeft size={16} />}
            </button>
          </div>
        </div>

        {/* 会话列表 */}
        {!sidebarCollapsed && (
          <div className="flex-1 overflow-y-auto">
            {sessions.length === 0 ? (
              <div className="px-4 py-8 text-center text-xs text-slate-400">
                <IconMessageCircle size={24} className="mx-auto mb-2 opacity-40" />
                暂无对话记录
              </div>
            ) : (
              sessions.map(s => (
                <div
                  key={s.id}
                  onClick={() => setActiveSessionId(s.id)}
                  className={`group flex items-center gap-2 px-3 py-2.5 mx-2 my-0.5 text-sm rounded-lg cursor-pointer transition-colors ${
                    activeSessionId === s.id
                      ? 'bg-slate-200 text-[#00ADA6]'
                      : 'text-slate-600 hover:bg-slate-200'
                  }`}
                >
                  <IconMessageCircle size={14} className="shrink-0" />
                  <span className="truncate flex-1">{s.title || '新对话'}</span>
                  <button
                    onClick={(e) => deleteSession(s.id, e)}
                    className="opacity-0 group-hover:opacity-100 p-1 hover:bg-[#FFF1F3] hover:text-[#E11D48] rounded transition-all shrink-0"
                  >
                    <IconTrash size={12} />
                  </button>
                </div>
              ))
            )}
          </div>
        )}

        {/* 折叠时显示的图标 */}
        {sidebarCollapsed && (
          <div className="flex-1 flex flex-col items-center pt-3 gap-1">
            {sessions.map(s => (
              <button
                key={s.id}
                onClick={() => setActiveSessionId(s.id)}
                className={`p-2 rounded-lg transition-colors ${
                  activeSessionId === s.id
                    ? 'bg-slate-200 text-[#00ADA6]'
                    : 'text-slate-500 hover:bg-slate-200'
                }`}
                title={s.title || '新对话'}
              >
                <IconMessageCircle size={16} />
              </button>
            ))}
          </div>
        )}
      </div>

      {/* ================= 右侧对话区 ================= */}
      <div className="flex-1 flex flex-col min-h-0">
        {/* 上下文范围选择器 */}
        <div className="px-4 py-3 border-b border-slate-200 flex items-center gap-3 bg-white">
          <span className="text-xs text-slate-500">检索范围：</span>

          <div ref={scopeRef} className="relative">
            <button
              onClick={() => setScopeOpen(!scopeOpen)}
              className="flex items-center gap-1.5 px-3 py-1.5 text-sm border border-slate-200 rounded-lg hover:bg-slate-50 transition-colors bg-white"
            >
              {scope.type === 'global' && <IconSearch size={14} className="text-[#00ADA6]" />}
              {scope.type === 'tag' && <IconTag size={14} className="text-purple-500" />}
              {scope.type === 'archive' && <IconBook size={14} className="text-blue-500" />}
              <span>{scope.label}</span>
              <IconChevronDown size={12} className="text-slate-400" />
            </button>

            {scopeOpen && (
              <div className="absolute top-full left-0 mt-1 w-72 bg-white border border-slate-200 rounded-xl shadow-lg z-50 overflow-hidden">
                {/* 全库 */}
                <button
                  onClick={() => selectScope({ type: 'global', label: '全库检索' })}
                  className="w-full flex items-center gap-2.5 px-3 py-2 text-sm hover:bg-slate-50 transition-colors"
                >
                  <IconSearch size={14} className="text-[#00ADA6] shrink-0" />
                  <span>全库检索</span>
                  <span className="ml-auto text-xs text-slate-400">所有归档</span>
                </button>

                <div className="border-t border-slate-100" />

                {/* 标签分组 */}
                {tags.length > 0 && (
                  <>
                    <div className="px-3 py-1.5 text-xs font-bold text-slate-400">标签</div>
                    {tags.map(tag => (
                      <button
                        key={tag.id}
                        onClick={() => selectScope({ type: 'tag', label: `🏷 ${tag.name}`, id: tag.id })}
                        className="w-full flex items-center gap-2.5 px-3 py-2 text-sm hover:bg-slate-50 transition-colors"
                      >
                        <IconTag size={14} className="text-purple-500 shrink-0" />
                        <span>{tag.name}</span>
                      </button>
                    ))}
                    <div className="border-t border-slate-100" />
                  </>
                )}

                {/* 归档列表（可滚动） */}
                <div className="border-t border-slate-100">
                  <div className="px-3 py-1.5 text-xs font-bold text-slate-400">归档</div>
                  <div className="max-h-48 overflow-y-auto">
                    {archives.length === 0 ? (
                      <div className="px-3 py-2 text-xs text-slate-400">暂无归档</div>
                    ) : (
                      archives.map(arch => (
                        <button
                          key={arch.id}
                          onClick={() => selectScope({ type: 'archive', label: `📄 ${arch.name}`, id: arch.id })}
                          className="w-full flex items-center gap-2.5 px-3 py-2 text-sm hover:bg-slate-50 transition-colors"
                        >
                          <IconBook size={14} className="text-blue-500 shrink-0" />
                          <span className="truncate">{arch.name}</span>
                        </button>
                      ))
                    )}
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* 消息列表 */}
        <div className="flex-1 overflow-y-auto bg-white px-6 py-4">
          {messages.length === 0 && !isLoading && (
            <div className="h-full flex flex-col items-center justify-center text-center">
              <IconBrain size={48} className="text-slate-200 mb-4" strokeWidth={1} />
              <p className="text-slate-400 text-sm mb-1">选择会话或开始新对话</p>
              <p className="text-slate-300 text-xs">AI 将基于归档内容回答您的问题</p>
            </div>
          )}

          {messages.map(msg => {
            // 流式占位（id=assistant-streaming）且内容为空时，跳过不渲染
            // 此时思考中图标会单独显示，不会产生双气泡
            if (msg.id === 'assistant-streaming' && !msg.content) return null;
            return (
              <div key={msg.id} className={`flex gap-3 mb-4 ${msg.role === 'user' ? 'flex-row-reverse' : ''}`}>
                <div className={`shrink-0 w-8 h-8 rounded-full flex items-center justify-center text-xs font-medium ${
                  msg.role === 'user'
                    ? 'bg-[#00ADA6] text-white'
                    : 'bg-slate-100 text-slate-500'
                }`}>
                  {msg.role === 'user' ? '我' : 'AI'}
                </div>
                <div className={`max-w-[75%] ${msg.role === 'user' ? 'text-right' : ''}`}>
                  <div className={`inline-block px-4 py-2.5 rounded-2xl text-sm leading-relaxed ${
                    msg.role === 'user'
                      ? 'bg-[#00ADA6] text-white rounded-tr-sm text-left'
                      : 'bg-slate-100 text-slate-700 rounded-tl-sm'
                  }`}>
                    {msg.role === 'assistant' ? (
                      <div className="prose prose-sm max-w-none">
                        {renderContentWithCitations(msg.content, msg.references, archives, onJumpToArchive)}
                      </div>
                    ) : (
                      msg.content
                    )}
                  </div>
                  {msg.created_at && (
                    <div className="text-xs text-slate-300 mt-1 px-1">
                      {formatTime(msg.created_at)}
                    </div>
                  )}
                </div>
              </div>
            );
          })}

          {isLoading && (
            <div className="flex gap-3 mb-4">
              <div className="shrink-0 w-8 h-8 rounded-full bg-slate-100 flex items-center justify-center text-xs text-slate-500">
                AI
              </div>
              <div className="bg-slate-100 px-4 py-3 rounded-2xl rounded-tl-sm flex items-center gap-2">
                <IconLoader2 size={16} className="text-slate-400 animate-spin" />
                <span className="text-sm text-slate-400">正在思考中...</span>
              </div>
            </div>
          )}

          <div ref={bottomRef} />
        </div>

        {/* 输入框 */}
        <div className="p-4 border-t border-slate-200 bg-white">
          <div className="flex gap-2 items-end">
            <textarea
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  sendMessage();
                }
              }}
              placeholder="输入问题，按 Enter 发送..."
              rows={1}
              className="flex-1 resize-none border border-slate-200 rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-[#00ADA6] focus:ring-1 focus:ring-[#00ADA6] max-h-32 overflow-y-auto"
              style={{ minHeight: '48px' }}
            />
            <button
              onClick={sendMessage}
              disabled={!input.trim() || isLoading}
              className="shrink-0 px-4 py-2.5 bg-[#00ADA6] hover:bg-[#009A94] disabled:bg-slate-200 disabled:cursor-not-allowed text-white rounded-xl text-sm font-medium transition-colors"
            >
              发送
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
