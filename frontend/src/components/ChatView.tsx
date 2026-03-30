import { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import {
  IconMessageCircle, IconPlus, IconTrash, IconChevronDown,
  IconSearch, IconLoader2,
  IconBook, IconTag, IconBrain
} from '@tabler/icons-react';

const api = axios.create({ baseURL: 'http://localhost:8000' });

interface Tag { id: string; name: string; created_at: string; }
interface Session { id: string; title: string; updated_at: string; }
interface Message {
  id: string;
  role: string;
  content: string;
  created_at: string;
  references?: { archive_id: string; archive_name: string; timestamp: string }[];
}

interface ScopeOption {
  type: 'global' | 'tag' | 'archive';
  label: string;
  id?: string;
}

interface ChatViewProps {
  onJumpToArchive?: (archiveId: string) => void;
}

export default function ChatView({ onJumpToArchive }: ChatViewProps) {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [tags, setTags] = useState<Tag[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [scopeOpen, setScopeOpen] = useState(false);
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

    // 添加一个占位的消息
    const assistantTempId = `temp-assistant-${Date.now()}`;
    setMessages(prev => [...prev, {
      id: assistantTempId,
      role: 'assistant',
      content: '',
      created_at: new Date().toISOString()
    }]);

    try {
      const body: Record<string, unknown> = { query: userMessage.content };
      if (scope.type === 'archive' && scope.id) {
        body.archive_ids = [scope.id];
      } else if (scope.type === 'tag' && scope.id) {
        body.tag_ids = [scope.id];
      }

      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 60000);

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
      let done = false;
      let streamDone = false;
      let fullContent = '';
      let receivedRefs: { archive_id: string; archive_name: string; timestamp: string }[] = [];

      while (!streamDone && reader) {
        const { value, done: d } = await reader.read();
        done = d;
        if (value) {
          const text = decoder.decode(value, { stream: !done });
          // SSE 解析：按空行分隔事件，每行内部按冒号分割
          const rawEvents = text.split(/\n\n/);
          for (const rawEvent of rawEvents) {
            if (!rawEvent.trim()) continue;
            const eventData: Record<string, string> = {};
            for (const line of rawEvent.split('\n')) {
              const colonIdx = line.indexOf(':');
              if (colonIdx === -1) continue;
              const key = line.slice(0, colonIdx).trim();
              const val = line.slice(colonIdx + 1).trim();
              if (key === 'event') eventData['event'] = val;
              else if (key === 'data') eventData['data'] = val;
              else if (key === 'extra_data') eventData['extra_data'] = val;
            }

            if (eventData['event'] === 'token' && eventData['data']) {
              fullContent += eventData['data'];
              setMessages(prev =>
                prev.map(m =>
                  m.id === assistantTempId ? { ...m, content: fullContent } : m
                )
              );
            } else if (eventData['event'] === 'done') {
              // data 字段就是完整内容（来自后端 done 事件的 full_content）
              if (eventData['data']) fullContent = eventData['data'];
              if (eventData['extra_data']) {
                try {
                  receivedRefs = JSON.parse(eventData['extra_data']);
                } catch {}
              }
            } else if (eventData['event'] === 'end') {
              // SSE 流结束信号
              streamDone = true;
            }
          }
        }
        // 当 done=true（reader 返回的最后一条数据）时，处理完当前数据后退出
        if (done) streamDone = true;
      }

      // 用真实消息替换临时占位
      setMessages(prev =>
        prev.map(m => {
          if (m.id === assistantTempId) {
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
      // 移除失败的占位，显示错误消息
      setMessages(prev => prev.filter(m => m.id !== assistantTempId));
      if (err instanceof Error && err.name === 'AbortError') {
        setMessages(prev => [...prev, {
          id: `error-${Date.now()}`,
          role: 'assistant',
          content: '（请求超时，请检查网络或 API 配置）',
          created_at: new Date().toISOString()
        }]);
      } else {
        setMessages(prev => [...prev, {
          id: `error-${Date.now()}`,
          role: 'assistant',
          content: '（发送失败，请重试）',
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
      {/* ================= 左侧会话列表 ================= */}
      <div className="w-64 border-r border-slate-200 flex flex-col bg-[#F9F9F9]">
        <div className="p-3 border-b border-slate-200 flex items-center justify-between">
          <span className="text-sm font-bold text-slate-700 flex items-center gap-1.5">
            <IconBrain size={16} className="text-[#00ADA6]" />
            智能对话
          </span>
          <button
            onClick={createSession}
            className="p-1.5 hover:bg-slate-200 rounded-md transition-colors"
            title="新建对话"
          >
            <IconPlus size={16} className="text-slate-500" />
          </button>
        </div>

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
                  className="w-full flex items-center gap-2.5 px-3 py-2.5 text-sm hover:bg-slate-50 transition-colors"
                >
                  <IconSearch size={14} className="text-[#00ADA6]" />
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
                        <IconTag size={14} className="text-purple-500" />
                        <span>{tag.name}</span>
                      </button>
                    ))}
                    <div className="border-t border-slate-100" />
                  </>
                )}

                {/* 归档列表 */}
                <div className="px-3 py-1.5 text-xs font-bold text-slate-400">归档</div>
                {archives.length === 0 ? (
                  <div className="px-3 py-2 text-xs text-slate-400">暂无归档</div>
                ) : (
                  archives.map(arch => (
                    <button
                      key={arch.id}
                      onClick={() => selectScope({ type: 'archive', label: `📄 ${arch.name}`, id: arch.id })}
                      className="w-full flex items-center gap-2.5 px-3 py-2 text-sm hover:bg-slate-50 transition-colors"
                    >
                      <IconBook size={14} className="text-blue-500" />
                      <span className="truncate">{arch.name}</span>
                    </button>
                  ))
                )}
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

          {messages.map(msg => (
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
                    ? 'bg-[#00ADA6] text-white rounded-tr-sm'
                    : 'bg-slate-100 text-slate-700 rounded-tl-sm'
                }`}>
                  {msg.content}
                </div>
                {msg.created_at && (
                  <div className="text-xs text-slate-300 mt-1 px-1">
                    {formatTime(msg.created_at)}
                  </div>
                )}
                {/* 引用来源 chips（仅助手消息） */}
                {msg.role === 'assistant' && msg.references && msg.references.length > 0 && (
                  <div className="flex flex-wrap gap-1.5 mt-2">
                    <span className="text-xs text-slate-400 self-center">参考：</span>
                    {msg.references.map((ref, i) => (
                      <button
                        key={i}
                        onClick={() => onJumpToArchive?.(ref.archive_id)}
                        className="flex items-center gap-1 px-2 py-0.5 bg-white border border-slate-200 rounded-full text-xs text-slate-500 hover:border-[#00ADA6] hover:text-[#00ADA6] transition-colors"
                        title={`跳转到 ${ref.archive_name}`}
                      >
                        <IconBook size={10} />
                        <span>{ref.archive_name}</span>
                        {ref.timestamp && <span className="text-slate-400">[{ref.timestamp}]</span>}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))}

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
