import { useState } from 'react';
import { IconPlus, IconLoader2, IconAlertCircle } from '@tabler/icons-react';
import axios from 'axios';
import { useToast } from './Toast';

interface BatchProcessProps {
  settings: {
    engine: string;
    whisper_model: string;
    device: string;
    max_timeline_items: number;
  };
}

const api = axios.create({ baseURL: 'http://localhost:8000' });

export default function BatchProcess({ settings }: BatchProcessProps) {
  const { showToast } = useToast();
  const [input, setInput] = useState('');
  const [isProcessing, setIsProcessing] = useState(false);

  const handleAddToQueue = async () => {
    if (!input.trim()) {
      showToast('info', '请输入链接或本地音频路径');
      return;
    }

    setIsProcessing(true);

    try {
      const lines = input.trim().split('\n').filter(line => line.trim());
      const tasks: { source: string; task_type: string; name: string }[] = [];

      for (const line of lines) {
        const lineLower = line.toLowerCase().trim();
        let task_type = '';
        let name = '';

        if (lineLower.includes('xiaoyuzhoufm.com')) {
          task_type = 'xiaoyuzhou';
          name = '小宇宙播客';
        } else if (lineLower.includes('bilibili.com')) {
          task_type = 'bilibili';
          name = 'B站视频';
        } else if (lineLower.includes('163cn.tv') || lineLower.includes('music.163.com')) {
          task_type = 'netease';
          name = '网易云播客';
        } else if (lineLower.includes('xima.tv') || lineLower.includes('ximalaya.com')) {
          task_type = 'ximalaya';
          name = '喜马拉雅播客';
        } else if (lineLower.includes('podcasts.apple.com')) {
          task_type = 'applepodcasts';
          name = '苹果播客';
        } else if (
          lineLower.endsWith('.mp3') ||
          lineLower.endsWith('.m4a') ||
          lineLower.endsWith('.wav') ||
          lineLower.endsWith('.flac') ||
          lineLower.endsWith('.aac') ||
          lineLower.startsWith('/') ||
          lineLower.match(/^[A-Za-z]:\\/)
        ) {
          task_type = 'local';
          name = line.split('/').pop()?.split('\\').pop() || '本地音频';
        } else {
          continue;
        }

        tasks.push({ source: line.trim(), task_type, name });
      }

      if (tasks.length === 0) {
        showToast('info', '未识别到有效的链接或本地音频路径');
        setIsProcessing(false);
        return;
      }

      let addedCount = 0;
      for (const task of tasks) {
        try {
          const formData = new FormData();
          formData.append('source', task.source);
          formData.append('task_type', task.task_type);
          formData.append('engine', settings.engine);
          formData.append('max_timeline_items', String(settings.max_timeline_items));
          formData.append('name', task.name);
          await api.post('/api/tasks', formData);
          addedCount++;
        } catch (err) {
          console.error('添加任务失败:', err);
        }
      }

      if (addedCount > 0) {
        showToast('success', `已添加 ${addedCount} 个任务到队列`);
        setInput('');
      } else {
        showToast('error', '添加失败');
      }
    } catch (error) {
      showToast('error', '批量添加失败');
    } finally {
      setIsProcessing(false);
    }
  };

  return (
    <div className="flex flex-col h-full">
      {/* 大文本框 */}
      <div className="flex-1 min-h-0 flex flex-col mb-6">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={`粘贴多个链接或本地音频路径，每行一个：\n\nhttps://xiaoyuzhoufm.com/episode/xxx\nhttps://www.bilibili.com/video/BVxxx\nhttps://163cn.tv/xxx\n/Users/xxx/audio.mp3`}
          className="flex-1 min-h-[200px] w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#00ADA6]/50 focus:border-[#00ADA6] transition-all resize-none text-sm text-slate-700 placeholder:text-slate-400"
          disabled={isProcessing}
        />
      </div>

      {/* 加入队列按钮 */}
      <div className="flex-shrink-0">
        <button
          onClick={handleAddToQueue}
          disabled={isProcessing || !input.trim()}
          className="w-full flex items-center justify-center gap-2 px-4 py-3 bg-[#00ADA6] text-white rounded-lg font-medium hover:bg-[#009A94] disabled:bg-slate-300 disabled:cursor-not-allowed transition-colors shadow-sm"
        >
          {isProcessing ? (
            <>
              <IconLoader2 size={18} className="animate-spin" />
              添加中...
            </>
          ) : (
            <>
              <IconPlus size={18} />
              加入任务队列
            </>
          )}
        </button>

        {/* 顶部提示 */}
        <div className="flex items-start gap-2 p-3 bg-[#EFF6FF] border border-[#3B82F6] rounded-lg mt-3">
          <IconAlertCircle size={16} className="text-[#3B82F6] shrink-0 mt-0.5" />
          <p className="text-xs text-[#64748B] leading-relaxed">
            每行一个，支持：小宇宙、网易云音乐、喜马拉雅、Apple Podcasts、Bilibili 链接，
            <br />
            或本地音频文件的绝对路径（如 /Users/xxx/audio.mp3）
          </p>
        </div>
      </div>
    </div>
  );
}
