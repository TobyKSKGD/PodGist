import { useState, useEffect, useRef } from 'react';
import { IconTag, IconPlus, IconX, IconCheck } from '@tabler/icons-react';
import axios from 'axios';

const api = axios.create({ baseURL: 'http://localhost:8000' });

interface Tag { id: string; name: string; created_at: string; }

interface TagManagerProps {
  archiveId: string;
}

export default function TagManager({ archiveId }: TagManagerProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [allTags, setAllTags] = useState<Tag[]>([]);
  const [archiveTags, setArchiveTags] = useState<Tag[]>([]);
  const [newTagName, setNewTagName] = useState('');
  const [isCreating, setIsCreating] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (isOpen) {
      loadTags();
      loadArchiveTags();
    }
  }, [isOpen, archiveId]);

  // 点击外部关闭
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (
        panelRef.current && !panelRef.current.contains(e.target as Node) &&
        triggerRef.current && !triggerRef.current.contains(e.target as Node)
      ) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  async function loadTags() {
    try {
      const res = await api.get('/api/chat/tags');
      if (res.data.status === 'success') setAllTags(res.data.data);
    } catch {}
  }

  async function loadArchiveTags() {
    try {
      const res = await api.get(`/api/chat/archives/${archiveId}/tags`);
      if (res.data.status === 'success') setArchiveTags(res.data.data);
    } catch {}
  }

  async function createTag() {
    if (!newTagName.trim()) return;
    setIsCreating(true);
    try {
      await api.post('/api/chat/tags', { name: newTagName.trim() });
      setNewTagName('');
      await loadTags();
    } catch {}
    setIsCreating(false);
  }

  async function deleteTag(tagId: string) {
    try {
      await api.delete(`/api/chat/tags/${tagId}`);
      await loadTags();
      await loadArchiveTags();
    } catch {}
  }

  async function toggleTag(tag: Tag) {
    const isActive = archiveTags.some(t => t.id === tag.id);
    const newTagIds = isActive
      ? archiveTags.filter(t => t.id !== tag.id).map(t => t.id)
      : [...archiveTags.map(t => t.id), tag.id];

    try {
      await api.post(`/api/chat/archives/${archiveId}/tags`, { tag_ids: newTagIds });
      await loadArchiveTags();
    } catch {}
  }

  const activeTagIds = new Set(archiveTags.map(t => t.id));

  return (
    <div className="relative">
      <button
        ref={triggerRef}
        onClick={() => setIsOpen(!isOpen)}
        className={`flex items-center gap-2 px-3 py-2 text-sm rounded-lg transition-colors ${
          isOpen || archiveTags.length > 0
            ? 'bg-purple-50 text-purple-600 border border-purple-200'
            : 'text-slate-600 hover:bg-slate-100'
        }`}
      >
        <IconTag size={16} />
        {archiveTags.length > 0 ? (
          <span className="font-medium">{archiveTags.length} 个标签</span>
        ) : (
          <span>标签管理</span>
        )}
      </button>

      {isOpen && (
        <div
          ref={panelRef}
          className="absolute top-full right-0 mt-2 w-72 bg-white border border-slate-200 rounded-xl shadow-lg z-50 overflow-hidden"
        >
          {/* Header */}
          <div className="px-4 py-3 border-b border-slate-100 flex items-center justify-between">
            <span className="text-sm font-semibold text-slate-700">标签管理</span>
            <button onClick={() => setIsOpen(false)} className="p-1 hover:bg-slate-100 rounded">
              <IconX size={14} className="text-slate-400" />
            </button>
          </div>

          {/* 新建标签 */}
          <div className="px-4 py-3 border-b border-slate-100">
            <div className="flex gap-2">
              <input
                value={newTagName}
                onChange={e => setNewTagName(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && createTag()}
                placeholder="新建标签名..."
                className="flex-1 px-3 py-1.5 text-sm border border-slate-200 rounded-lg focus:outline-none focus:border-purple-400"
              />
              <button
                onClick={createTag}
                disabled={!newTagName.trim() || isCreating}
                className="px-3 py-1.5 bg-purple-500 text-white text-sm rounded-lg hover:bg-purple-600 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1"
              >
                {isCreating ? <IconX size={12} /> : <IconPlus size={12} />}
              </button>
            </div>
          </div>

          {/* 已有标签列表 */}
          <div className="max-h-64 overflow-y-auto py-1">
            {allTags.length === 0 ? (
              <div className="px-4 py-6 text-center text-xs text-slate-400">
                暂无标签，点击上方创建
              </div>
            ) : (
              allTags.map(tag => {
                const isActive = activeTagIds.has(tag.id);
                return (
                  <div
                    key={tag.id}
                    className="flex items-center gap-2 px-4 py-2 hover:bg-slate-50 group"
                  >
                    <button
                      onClick={() => toggleTag(tag)}
                      className={`flex-1 flex items-center gap-2 text-sm text-left transition-colors ${
                        isActive ? 'text-purple-700 font-medium' : 'text-slate-600'
                      }`}
                    >
                      <span className={`w-4 h-4 rounded border flex items-center justify-center shrink-0 ${
                        isActive ? 'bg-purple-500 border-purple-500' : 'border-slate-300'
                      }`}>
                        {isActive && <IconCheck size={10} className="text-white" />}
                      </span>
                      {tag.name}
                    </button>
                    <button
                      onClick={() => deleteTag(tag.id)}
                      className="opacity-0 group-hover:opacity-100 p-1 text-slate-400 hover:text-red-500 transition-opacity"
                    >
                      <IconX size={12} />
                    </button>
                  </div>
                );
              })
            )}
          </div>
        </div>
      )}
    </div>
  );
}
