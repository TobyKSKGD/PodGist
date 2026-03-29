import { useState } from 'react';
import { IconLink, IconLoader2, IconGlobe, IconRadio, IconVideo, IconMusic, IconChevronDown, IconChevronUp, IconHelpCircle } from '@tabler/icons-react';
import axios from 'axios';
import DinoLoader from './DinoLoader';

interface PodcastDownloadFormProps {
  settings: {
    engine: string;
    whisper_model: string;
    device: string;
    max_timeline_items: number;
  };
  downloadType: 'podcast' | 'bilibili';
  onSuccess: (archiveId: string) => void;
}

const api = axios.create({ baseURL: 'http://localhost:8000' });

// 平台检测函数
function detectPlatform(url: string): { platform: string; name: string; icon: React.ReactNode } {
  const lowerUrl = url.toLowerCase();
  if (!lowerUrl) return { platform: 'unknown', name: '输入链接', icon: <IconGlobe size={18} /> };
  if (lowerUrl.includes('xiaoyuzhoufm.com')) return { platform: 'xiaoyuzhou', name: '小宇宙', icon: <IconRadio size={18} /> };
  if (lowerUrl.includes('bilibili.com')) return { platform: 'bilibili', name: 'Bilibili', icon: <IconVideo size={18} /> };
  if (lowerUrl.includes('163cn.tv') || lowerUrl.includes('music.163.com')) return { platform: 'netease', name: '网易云音乐', icon: <IconMusic size={18} /> };
  if (lowerUrl.includes('xima.tv') || lowerUrl.includes('ximalaya.com')) return { platform: 'ximalaya', name: '喜马拉雅', icon: <IconRadio size={18} /> };
  if (lowerUrl.includes('podcasts.apple.com')) return { platform: 'apple', name: 'Apple Podcasts', icon: <IconRadio size={18} /> };
  return { platform: 'unknown', name: '未知平台', icon: <IconGlobe size={18} /> };
}

export default function PodcastDownloadForm({ settings, downloadType, onSuccess }: PodcastDownloadFormProps) {
  const [url, setUrl] = useState('');
  const [isProcessing, setIsProcessing] = useState(false);
  const [status, setStatus] = useState('');
  const [showGuide, setShowGuide] = useState(false);
  const [guideTab, setGuideTab] = useState(0);

  const platform = detectPlatform(url);
  const isBilibili = downloadType === 'bilibili';

  // Bilibili 专用检测
  const isValidBilibiliUrl = url.toLowerCase().includes('bilibili.com');
  // 播客专用检测
  const isValidPodcastUrl = ['xiaoyuzhou', 'netease', 'ximalaya', 'apple'].includes(platform.platform);

  const handleSubmit = async () => {
    if (!url.trim()) {
      setStatus('请输入有效的链接');
      return;
    }

    // 平台验证
    if (isBilibili && !isValidBilibiliUrl) {
      setStatus('请输入有效的 Bilibili 视频链接');
      return;
    }
    if (!isBilibili && !isValidPodcastUrl) {
      setStatus('请输入有效的播客链接（小宇宙、网易云、喜马拉雅、苹果播客）');
      return;
    }

    setIsProcessing(true);
    setStatus('正在加入任务队列...');

    try {
      // 通过任务队列异步处理，避免同步请求超时
      const taskType = isBilibili ? 'bilibili' : platform.platform;
      const taskName = isBilibili ? 'Bilibili视频' : (platform.name + '播客');

      // 使用 FormData 发送表单数据（FastAPI Form() 需要 form-urlencoded）
      const formData = new FormData();
      formData.append('source', url.trim());
      formData.append('task_type', taskType);
      formData.append('engine', settings.engine);
      formData.append('max_timeline_items', String(settings.max_timeline_items));
      formData.append('name', taskName);

      const taskRes = await api.post('/api/tasks', formData);

      if (taskRes.data.status === 'success') {
        setStatus('已加入任务队列，请前往"任务队列"查看进度');
        onSuccess('');
        setUrl('');
      } else {
        setStatus(taskRes.data.message || '添加任务失败');
      }
    } catch (error: any) {
      console.error(error);
      const errorDetail = error.response?.data?.detail;
      let errorMessage = '处理失败';
      if (typeof errorDetail === 'string') {
        errorMessage = errorDetail;
      } else if (Array.isArray(errorDetail)) {
        // Pydantic 验证错误数组，提取所有 msg
        errorMessage = errorDetail.map((e: any) => e.msg || JSON.stringify(e)).join('; ');
      } else if (error.message) {
        errorMessage = error.message;
      }
      setStatus(errorMessage);
    } finally {
      setIsProcessing(false);
    }
  };

  // Bilibili 专用 UI
  if (isBilibili) {
    return (
      <div className="space-y-6">
        {/* URL 输入区 */}
        <div className="space-y-3">
          <label className="text-sm font-medium text-slate-700 flex items-center gap-2">
            <IconVideo size={16} />
            粘贴 B站视频链接
          </label>
          <div className="relative">
            <input
              type="text"
              placeholder="https://www.bilibili.com/video/BV..."
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              disabled={isProcessing}
              className="w-full px-4 py-3 pl-11 bg-slate-50 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#00ADA6]/50 focus:border-[#00ADA6] transition-all disabled:opacity-50"
            />
            <div className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400">
              <IconVideo size={18} />
            </div>
            {url && (
              <div className="absolute right-3 top-1/2 -translate-y-1/2">
                <span className={`text-xs px-2 py-1 rounded-full ${
                  isValidBilibiliUrl
                    ? 'bg-[#EFF6FF] text-[#64748B]'
                    : 'bg-slate-100 text-slate-500'
                }`}>
                  {isValidBilibiliUrl ? 'Bilibili' : '未知'}
                </span>
              </div>
            )}
          </div>
          <p className="text-xs text-slate-400">
            支持 Bilibili 视频链接，自动提取音频并生成摘要
          </p>
        </div>

        {/* 状态显示 */}
        {isProcessing ? (
          <DinoLoader message={isBilibili ? "B站视频下载中，请稍候..." : "播客音频下载中，请稍候..."} />
        ) : status && (
          <div className={`p-3 rounded-lg text-sm ${
            status.includes('完成')
              ? 'bg-[#D1FAF5] text-[#10B981] border border-[#10B981]'
              : status.includes('失败') || status.includes('请输入')
              ? 'bg-[#FFF1F3] text-[#E11D48] border border-[#E11D48]'
              : 'bg-[#EFF6FF] text-[#64748B] border border-[#3B82F6]'
          }`}>
            <div className="flex items-center gap-2">
              {status}
            </div>
          </div>
        )}

        {/* 提交按钮 */}
        <button
          onClick={handleSubmit}
          disabled={isProcessing || !url.trim()}
          className="w-full bg-[#00ADA6] hover:bg-[#009A94] disabled:bg-slate-300 disabled:cursor-not-allowed text-white py-3 px-4 rounded-lg font-medium transition-all shadow-sm flex items-center justify-center gap-2"
        >
          {isProcessing ? (
            <>
              <IconLoader2 className="animate-spin" size={18} />
              提取中...
            </>
          ) : (
            <>
              <IconVideo size={18} />
              解析并提取音频
            </>
          )}
        </button>
      </div>
    );
  }

  // 播客专用 UI
  return (
    <div className="space-y-6">
      {/* URL 输入区 */}
      <div className="space-y-3">
        <label className="text-sm font-medium text-slate-700 flex items-center gap-2">
          <IconLink size={16} />
          粘贴播客单集链接
        </label>
        <div className="relative">
          <input
            type="text"
            placeholder="小宇宙/网易云/喜马拉雅/苹果播客 (手机App分享链接)"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            disabled={isProcessing}
            className="w-full px-4 py-3 pl-11 bg-slate-50 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#00ADA6]/50 focus:border-[#00ADA6] transition-all disabled:opacity-50"
          />
          <div className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400">
            {platform.icon}
          </div>
          {url && (
            <div className="absolute right-3 top-1/2 -translate-y-1/2">
              <span className={`text-xs px-2 py-1 rounded-full ${
                platform.platform !== 'unknown'
                  ? 'bg-[#EFF6FF] text-[#64748B]'
                  : 'bg-slate-100 text-slate-500'
              }`}>
                {platform.name}
              </span>
            </div>
          )}
        </div>
        <p className="text-xs text-slate-400">
          支持各平台手机 App 分享链接
        </p>
      </div>

      {/* 状态显示 */}
      {isProcessing ? (
        <DinoLoader message={isBilibili ? "B站视频下载中，请稍候..." : "播客音频下载中，请稍候..."} />
      ) : status && (
        <div className={`p-3 rounded-lg text-sm ${
          status.includes('完成')
            ? 'bg-[#D1FAF5] text-[#10B981] border border-[#10B981]'
            : status.includes('失败') || status.includes('请输入')
            ? 'bg-[#FFF1F3] text-[#E11D48] border border-[#E11D48]'
            : 'bg-[#EFF6FF] text-[#64748B] border border-[#3B82F6]'
        }`}>
          <div className="flex items-center gap-2">
            {status}
          </div>
        </div>
      )}

      {/* 提交按钮 */}
      <button
        onClick={handleSubmit}
        disabled={isProcessing || !url.trim()}
        className="w-full bg-[#00ADA6] hover:bg-[#009A94] disabled:bg-slate-300 disabled:cursor-not-allowed text-white py-3 px-4 rounded-lg font-medium transition-all shadow-sm flex items-center justify-center gap-2"
      >
        {isProcessing ? (
          <>
            <IconLoader2 className="animate-spin" size={18} />
            提取中...
          </>
        ) : (
          <>
            <IconRadio size={18} />
            解析并提取音频
          </>
        )}
      </button>

      {/* 平台支持状态 */}
      <div className="p-3 bg-[#EFF6FF] border border-[#3B82F6] rounded-lg">
        <p className="text-sm text-[#64748B] flex items-center gap-2">
          <span className="w-2 h-2 bg-[#3B82F6] rounded-full"></span>
          已支持：小宇宙、网易云音乐、喜马拉雅、苹果播客
        </p>
      </div>

      {/* 平台链接获取指南 - 可折叠 */}
      <div className="border border-slate-200 rounded-lg overflow-hidden">
        <button
          onClick={() => setShowGuide(!showGuide)}
          className="w-full px-4 py-3 flex items-center justify-between text-sm text-slate-600 hover:bg-slate-50 transition-colors"
        >
          <span className="flex items-center gap-2">
            <IconHelpCircle size={16} />
            平台链接获取指南
          </span>
          {showGuide ? <IconChevronUp size={16} /> : <IconChevronDown size={16} />}
        </button>

        {showGuide && (
          <div className="border-t border-slate-100">
            {/* Tab 切换 */}
            <div className="flex border-b border-slate-100">
              {['小宇宙', '网易云音乐', '喜马拉雅', '苹果播客'].map((tab, i) => (
                <button
                  key={tab}
                  onClick={() => setGuideTab(i)}
                  className={`flex-1 py-2.5 text-xs font-medium border-b-2 transition-colors ${
                    guideTab === i
                      ? 'border-[#00ADA6] text-[#00ADA6]'
                      : 'border-transparent text-slate-500 hover:text-slate-700'
                  }`}
                >
                  {tab}
                </button>
              ))}
            </div>

            {/* Tab 内容 */}
            <div className="p-4">
              {guideTab === 0 && (
                <div className="space-y-2 text-sm text-slate-600">
                  <p className="font-medium text-slate-800">小宇宙</p>
                  <ol className="list-decimal list-inside space-y-1.5 text-xs">
                    <li>打开手机 <strong>小宇宙 App</strong> 并选择单集</li>
                    <li>点击右上角或底部的「分享」按钮</li>
                    <li>选择「复制链接」并粘贴到上方输入框</li>
                  </ol>
                  <p className="text-xs text-slate-400 mt-2">链接格式示例：xiaoyuzhoufm.com/episode/...</p>
                </div>
              )}

              {guideTab === 1 && (
                <div className="space-y-3 text-xs text-slate-600">
                  <div>
                    <p className="font-medium text-slate-800 mb-1.5">手机 App 分享（推荐）</p>
                    <ol className="list-decimal list-inside space-y-1">
                      <li>打开 <strong>网易云音乐 App</strong>，进入播客单集</li>
                      <li>点击右上角「分享」→「复制链接」</li>
                    </ol>
                    <p className="text-xs text-slate-400 mt-1">支持带文案分享，如：分享#xxx#...https://163cn.tv/xxx</p>
                  </div>
                  <div>
                    <p className="font-medium text-slate-800 mb-1.5">PC/网页端</p>
                    <p>直接复制地址栏链接（如：music.163.com/#/program?id=...）</p>
                    <a
                      href="https://music.163.com/#/discover/djradio"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 mt-2 text-xs text-[#00ADA6] hover:text-[#009A94] underline"
                    >
                      前往网易云音乐网页版 →
                    </a>
                  </div>
                </div>
              )}

              {guideTab === 2 && (
                <div className="space-y-3 text-xs text-slate-600">
                  <div>
                    <p className="font-medium text-slate-800 mb-1.5">手机 App 分享（推荐）</p>
                    <ol className="list-decimal list-inside space-y-1">
                      <li>打开 <strong>喜马拉雅 App</strong>，进入单集页面</li>
                      <li>点击右上角「分享」→「复制链接」</li>
                    </ol>
                  </div>
                  <div>
                    <p className="font-medium text-slate-800 mb-1.5">网页端</p>
                    <p>直接复制地址栏链接（如：m.ximalaya.com/sound/xxxxx）</p>
                    <a
                      href="https://www.ximalaya.com"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 mt-2 text-xs text-[#00ADA6] hover:text-[#009A94] underline"
                    >
                      前往喜马拉雅网页版 →
                    </a>
                    <p className="text-xs text-slate-400 mt-1">注：不支持 PC 客户端直接复制专辑链接</p>
                  </div>
                </div>
              )}

              {guideTab === 3 && (
                <div className="space-y-3 text-xs text-slate-600">
                  <div>
                    <p className="font-medium text-slate-800 mb-1.5">苹果播客</p>
                    <ol className="list-decimal list-inside space-y-1.5">
                      <li>打开 <strong>Apple Podcasts App</strong></li>
                      <li>进入播客单集页面，点击「分享」→「复制链接」</li>
                    </ol>
                    <p className="text-xs text-slate-400 mt-2">链接格式示例：podcasts.apple.com/cn/podcast/...</p>
                  </div>
                  <a
                    href="https://podcasts.apple.com"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 text-xs text-[#00ADA6] hover:text-[#009A94] underline"
                  >
                    前往 Apple Podcasts 网页版 →
                  </a>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
