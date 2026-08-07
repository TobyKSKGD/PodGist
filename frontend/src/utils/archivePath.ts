/** 从后端任务结果目录中提取归档 ID，兼容 Windows 与 POSIX 路径。 */
export function archiveIdFromResultPath(resultPath: string | null | undefined): string | undefined {
  if (!resultPath) return undefined;
  return resultPath.split(/[\\/]/).filter(Boolean).at(-1);
}
