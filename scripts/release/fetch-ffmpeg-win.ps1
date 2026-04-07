#!/usr/bin/env pwsh
# PodGist Windows FFmpeg 下载脚本
#
# 下载 FFmpeg 并放置到 electron/resources/ffmpeg/
#
# 用法：powershell -ExecutionPolicy Bypass -File scripts/release/fetch-ffmpeg-win.ps1

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot

Write-Host "=== 下载 FFmpeg for Windows ===" -ForegroundColor Cyan
Write-Host "项目目录: $projectRoot"

Set-Location $projectRoot

$ffmpegDir = Join-Path $projectRoot "electron\resources\ffmpeg"
New-Item -ItemType Directory -Force -Path $ffmpegDir | Out-Null

$url = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
$zipPath = "$env:TEMP\podgist_ffmpeg.zip"
$extractDir = "$env:TEMP\ffmpeg_extracted"

Write-Host "下载 FFmpeg from $url" -ForegroundColor Yellow
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Invoke-WebRequest -Uri $url -OutFile $zipPath

Write-Host "解压..." -ForegroundColor Yellow
Expand-Archive -Path $zipPath -DestinationPath $extractDir -Force

# 查找 ffmpeg.exe
$ffmpegExe = Get-ChildItem -Path $extractDir -Recurse -Filter "ffmpeg.exe" | Select-Object -First 1
if (-not $ffmpegExe) {
    Write-Host "ERROR: ffmpeg.exe not found in archive" -ForegroundColor Red
    Remove-Item $zipPath -Force -ErrorAction SilentlyContinue
    exit 1
}

$ffprobeExe = Get-ChildItem -Path $extractDir -Recurse -Filter "ffprobe.exe" | Select-Object -First 1
if (-not $ffprobeExe) {
    Write-Host "ERROR: ffprobe.exe not found in archive" -ForegroundColor Red
    Remove-Item $zipPath -Force -ErrorAction SilentlyContinue
    exit 1
}

# 复制到目标目录
Copy-Item $ffmpegExe.FullName -Destination $ffmpegDir -Force
Copy-Item $ffprobeExe.FullName -Destination $ffmpegDir -Force

# 清理
Remove-Item $zipPath -Force -ErrorAction SilentlyContinue
Remove-Item $extractDir -Recurse -Force -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "=== FFmpeg 准备完成 ===" -ForegroundColor Green
Write-Host "ffmpeg.exe -> $ffmpegDir"
Write-Host "ffprobe.exe -> $ffmpegDir"

# 列出最终文件
Get-ChildItem $ffmpegDir | ForEach-Object { Write-Host "  $($_.Name)" }

exit 0
