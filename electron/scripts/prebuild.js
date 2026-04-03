#!/usr/bin/env node
/**
 * 预构建脚本 - 在 electron-builder 之前复制必要文件并安装依赖
 * 跨平台兼容：支持 macOS/Linux (cp) 和 Windows (xcopy/copy)
 */

const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const os = require('os');

const electronDir = path.dirname(__dirname);  // electron/ 目录
const projectRoot = path.dirname(electronDir);  // PodGist/ 目录

function copyDir(src, dest) {
  // 先删除目标如果存在
  if (fs.existsSync(dest)) {
    if (fs.statSync(dest).isDirectory()) {
      fs.rmSync(dest, { recursive: true });
    } else {
      fs.unlinkSync(dest);
    }
  }

  fs.mkdirSync(dest, { recursive: true });

  const entries = fs.readdirSync(src, { withFileTypes: true });

  for (const entry of entries) {
    const srcPath = path.join(src, entry.name);
    const destPath = path.join(dest, entry.name);

    if (entry.isDirectory()) {
      copyDir(srcPath, destPath);
    } else {
      fs.copyFileSync(srcPath, destPath);
    }
  }
}

function copyFile(src, dest) {
  const destDir = path.dirname(dest);
  if (!fs.existsSync(destDir)) {
    fs.mkdirSync(destDir, { recursive: true });
  }
  // 先移除已存在的目标文件（处理只读/权限问题）
  if (fs.existsSync(dest)) {
    fs.unlinkSync(dest);
  }
  fs.copyFileSync(src, dest);
}

console.log('[prebuild] 准备构建文件...');

// 复制 frontend/dist -> electron/frontend-dist
const frontendDistSrc = path.join(projectRoot, 'frontend', 'dist');
const frontendDistDest = path.join(electronDir, 'frontend-dist');
if (fs.existsSync(frontendDistSrc)) {
  console.log('[prebuild] 复制 frontend/dist -> frontend-dist');
  copyDir(frontendDistSrc, frontendDistDest);
} else {
  console.warn('[prebuild] 警告: frontend/dist 不存在，请先运行 npm run build (在前端目录)');
}

// 复制 api.py
const apiSrc = path.join(projectRoot, 'api.py');
const apiDest = path.join(electronDir, 'api.py');
if (fs.existsSync(apiSrc)) {
  console.log('[prebuild] 复制 api.py');
  copyFile(apiSrc, apiDest);
}

// 复制 requirements.txt
const reqSrc = path.join(projectRoot, 'requirements.txt');
const reqDest = path.join(electronDir, 'requirements.txt');
if (fs.existsSync(reqSrc)) {
  console.log('[prebuild] 复制 requirements.txt');
  copyFile(reqSrc, reqDest);
}

// 复制 backend/
const backendSrc = path.join(projectRoot, 'backend');
const backendDest = path.join(electronDir, 'backend');
if (fs.existsSync(backendSrc)) {
  console.log('[prebuild] 复制 backend/');
  copyDir(backendSrc, backendDest);
}

// 复制 ffprobe 到 resources/ffmpeg/ 目录
const ffmpegDir = path.join(electronDir, 'resources', 'ffmpeg');
const platform = os.platform();
if (platform === 'darwin' || platform === 'linux') {
  // macOS/Linux: 从 Homebrew 或系统路径复制 ffprobe
  const possibleFfprobePaths = [
    '/opt/homebrew/bin/ffprobe',    // Homebrew on Apple Silicon
    '/usr/local/bin/ffprobe',        // Homebrew on Intel
    '/usr/bin/ffprobe'               // System
  ];
  let ffprobeSrc = null;
  for (const p of possibleFfprobePaths) {
    if (fs.existsSync(p)) {
      ffprobeSrc = p;
      break;
    }
  }
  if (ffprobeSrc) {
    console.log(`[prebuild] 复制 ffprobe from ${ffprobeSrc}`);
    copyFile(ffprobeSrc, path.join(ffmpegDir, 'ffprobe'));
  } else {
    console.warn('[prebuild] 警告: 未找到 ffprobe，跳过复制');
  }
} else if (platform === 'win32') {
  // Windows: ffprobe 通常在 PATH 或同目录
  const ffprobeSrc = 'ffprobe.exe';
  const ffprobeDest = path.join(ffmpegDir, 'ffprobe.exe');
  if (fs.existsSync(ffprobeSrc)) {
    console.log('[prebuild] 复制 ffprobe.exe');
    copyFile(ffprobeSrc, ffprobeDest);
  }
}

// 在 python_venv 中安装 yt-dlp 和 ffmpeg-python
const venvPython = path.join(electronDir, 'resources', 'python_venv', 'bin', 'python3');
const venvPip = path.join(electronDir, 'resources', 'python_venv', 'bin', 'pip3');
if (fs.existsSync(venvPip)) {
  console.log('[prebuild] 在 python_venv 中安装 yt-dlp...');
  try {
    execSync(`${venvPip} install yt-dlp`, { stdio: 'inherit' });
  } catch (e) {
    console.warn('[prebuild] yt-dlp 安装失败，继续...');
  }
} else {
  console.warn('[prebuild] python_venv 不存在，跳过 yt-dlp 安装');
}

console.log('[prebuild] 完成');
