/**
 * 打包版媒体资源 URL 归一化工具
 *
 * 问题背景：
 * - 后端返回 /api/archives/... 等相对路径
 * - 开发环境页面 origin 是 http://localhost:5173，相对 URL 能正确解析
 * - 打包后 Electron 页面 origin 是 file://，相对 URL 解析到 file:///api/... 完全失效
 *
 * 解决：所有媒体资源走绝对后端地址 http://localhost:8000
 */

const API_BASE = 'http://localhost:8000';

/**
 * 将后端返回的相对或绝对 URL 归一化为绝对后端地址。
 * - 空值 → 空字符串
 * - http:// / https:// → 原样返回
 * - /api/... → 拼接 API_BASE
 */
export function resolveApiAssetUrl(rawUrl?: string | null): string {
  if (!rawUrl) return '';
  if (rawUrl.startsWith('http://') || rawUrl.startsWith('https://')) {
    return rawUrl;
  }
  if (rawUrl.startsWith('/')) {
    return `${API_BASE}${rawUrl}`;
  }
  return `${API_BASE}/${rawUrl}`;
}

/**
 * 构造 entity media 图片的绝对 URL。
 * archiveId 和 filename 都做 encodeURIComponent 防止中文/特殊字符破坏路径。
 */
export function resolveMediaUrl(archiveId: string, filename: string): string {
  return `${API_BASE}/api/archives/${encodeURIComponent(archiveId)}/media/${encodeURIComponent(filename)}`;
}

/**
 * 构造归档音频的绝对 URL。
 */
export function resolveAudioUrl(archiveId: string): string {
  return `${API_BASE}/api/archives/${encodeURIComponent(archiveId)}/audio`;
}

/**
 * 构造归档封面的绝对 URL。
 */
export function resolveCoverUrl(archiveId: string): string {
  return `${API_BASE}/api/archives/${encodeURIComponent(archiveId)}/cover`;
}
