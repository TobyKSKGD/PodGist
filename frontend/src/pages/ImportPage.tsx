/**
 * ImportPage — 导入内容页面
 *
 * 保留旧 upload 视图的完整逻辑，只是把它包装成独立页面。
 * 通过 URL 参数 ?tab= 支持预选标签页（local/podcast/bilibili/batch）。
 */
import { useSearchParams } from 'react-router-dom';
import { useState, useRef } from 'react';
import { IconCloudUpload, IconLoader2, IconUpload, IconRadio, IconVideo, IconLayersLinked } from '@tabler/icons-react';
import PodcastDownloadForm from '../components/PodcastDownloadForm';
import BatchProcess from '../components/BatchProcess';
import axios from 'axios';

const api = axios.create({ baseURL: 'http://localhost:8000' });

export default function ImportPage() {
  const [searchParams] = useSearchParams();
  const initialTab = (searchParams.get('tab') || 'local') as 'local' | 'podcast' | 'bilibili' | 'batch';
  const [activeInputTab, setActiveInputTab] = useState<'local' | 'podcast' | 'bilibili' | 'batch'>(initialTab);
  const [isUploading, setIsUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFileUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    setIsUploading(true);
    const formData = new FormData();
    formData.append('file', file);
    formData.append('engine', 'SenseVoice');
    formData.append('whisper_model', 'small');
    formData.append('device', 'auto');

    try {
      await api.post('/api/transcribe/local', formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      });
    } catch (error) {
      console.error(error);
    } finally {
      setIsUploading(false);
    }
  };

  return (
    <div className="flex-1 overflow-y-auto bg-white">
      <div className="max-w-4xl w-full mx-auto p-8 pb-16">

        <div className="mb-8">
          <h1 className="text-xl font-bold text-slate-800 mb-1">导入内容</h1>
          <p className="text-sm text-slate-500">选择音频来源，添加到资料库</p>
        </div>

        <div className="flex border-b border-slate-200 mb-8">
          {([
            { key: 'local', label: '本地提炼', icon: <IconUpload size={16} /> },
            { key: 'podcast', label: '播客直连', icon: <IconRadio size={16} /> },
            { key: 'bilibili', label: '视频剥离', icon: <IconVideo size={16} /> },
            { key: 'batch', label: '批量处理', icon: <IconLayersLinked size={16} /> },
          ] as const).map(({ key, label, icon }) => (
            <button
              key={key}
              onClick={() => setActiveInputTab(key)}
              className={`px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
                activeInputTab === key
                  ? 'border-[#00ADA6] text-[#00ADA6]'
                  : 'border-transparent text-slate-500 hover:text-slate-700'
              }`}
            >
              <span className="flex items-center gap-1.5">
                {icon}
                {label}
              </span>
            </button>
          ))}
        </div>

        {activeInputTab === 'local' ? (
          <div>
            <input
              type="file"
              accept=".mp3,.wav,.m4a"
              className="hidden"
              ref={fileInputRef}
              onChange={handleFileUpload}
              disabled={isUploading}
            />
            <div
              onClick={() => !isUploading && fileInputRef.current?.click()}
              className={`border-2 border-dashed rounded-xl flex flex-col items-center justify-center p-14 transition-all ${
                isUploading
                  ? 'border-slate-300 bg-slate-50 cursor-not-allowed'
                  : 'border-slate-300 hover:border-[#00ADA6] hover:bg-[#D1FAF5] cursor-pointer bg-slate-50'
              }`}
            >
              {isUploading ? (
                <div className="flex flex-col items-center gap-3 py-8">
                  <IconLoader2 className="animate-spin text-[#00ADA6]" size={32} />
                  <span className="text-sm text-slate-500">音频转录中，请稍候...</span>
                </div>
              ) : (
                <>
                  <IconCloudUpload className="text-slate-400 mb-4" size={48} strokeWidth={1.5} />
                  <p className="text-lg font-medium text-slate-700 mb-1">
                    点击或拖拽音频文件到此处
                  </p>
                  <p className="text-sm text-slate-400">
                    支持 MP3, WAV, M4A (最大 200MB)
                  </p>
                </>
              )}
            </div>
          </div>
        ) : activeInputTab === 'podcast' ? (
          <PodcastDownloadForm
            settings={{ engine: 'SenseVoice', whisper_model: 'small', device: 'auto' }}
            downloadType="podcast"
            onSuccess={() => {}}
          />
        ) : activeInputTab === 'bilibili' ? (
          <PodcastDownloadForm
            settings={{ engine: 'SenseVoice', whisper_model: 'small', device: 'auto' }}
            downloadType="bilibili"
            onSuccess={() => {}}
          />
        ) : (
          <BatchProcess settings={{ engine: 'SenseVoice', whisper_model: 'small', device: 'auto' }} />
        )}

      </div>
    </div>
  );
}
