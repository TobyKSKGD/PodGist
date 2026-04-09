#!/usr/bin/env node
/**
 * 预构建脚本 - 在 electron-builder 之前复制必要文件
 *
 * 仅负责确定性文件复制，不做任何动态安装。
 *
 * 跨平台兼容：支持 macOS/Linux (cp) 和 Windows (xcopy/copy)
 */

const fs = require('fs');
const path = require('path');
const os = require('os');

const electronDir = path.dirname(__dirname);  // electron/ 目录
const projectRoot = path.dirname(electronDir);  // PodGist/ 目录

function copyDir(src, dest, excludeDirs = []) {
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
    // 跳过排除的目录
    if (excludeDirs.includes(entry.name)) {
      continue;
    }

    const srcPath = path.join(src, entry.name);
    const destPath = path.join(dest, entry.name);

    if (entry.isDirectory()) {
      copyDir(srcPath, destPath, excludeDirs);
    } else {
      try {
        fs.copyFileSync(srcPath, destPath);
      } catch (err) {
        // 跳过不支持的文件类型（如 macOS framework sockets）
        if (err.code === 'ENOTSUP' || err.code === 'ENOENT') {
          console.warn(`[prebuild] 跳过不支持的文件: ${srcPath} (${err.code})`);
        } else {
          throw err;
        }
      }
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
  console.warn('[prebuild] 警告: frontend/dist 不存在，请先运行 npm run build (在项目根目录)');
}

// 复制 api.py（根目录为唯一真源）
const apiSrc = path.join(projectRoot, 'api.py');
const apiDest = path.join(electronDir, 'api.py');
if (fs.existsSync(apiSrc)) {
  console.log('[prebuild] 复制 api.py');
  copyFile(apiSrc, apiDest);
} else {
  console.error('[prebuild] 错误: api.py 不存在');
}

// 复制 requirements.txt（根目录为唯一真源）
const reqSrc = path.join(projectRoot, 'requirements.txt');
const reqDest = path.join(electronDir, 'requirements.txt');
if (fs.existsSync(reqSrc)) {
  console.log('[prebuild] 复制 requirements.txt');
  copyFile(reqSrc, reqDest);
} else {
  console.error('[prebuild] 错误: requirements.txt 不存在');
}

// 复制 backend/（根目录为唯一真源 -> electron/backend/）
// 排除 dist/ 目录（PyInstaller 产物由单独的后端构建脚本处理）
const backendSrc = path.join(projectRoot, 'backend');
const backendDest = path.join(electronDir, 'backend');
if (fs.existsSync(backendSrc)) {
  console.log('[prebuild] 复制 backend/ -> electron/backend/ (排除 dist/)');
  copyDir(backendSrc, backendDest, ['dist']);
} else {
  console.error('[prebuild] 错误: backend/ 目录不存在');
}

// 复制 ffprobe 到 resources/ffmpeg/ 目录（仅当目标不存在时）
const ffmpegDir = path.join(electronDir, 'resources', 'ffmpeg');
const platform = os.platform();

function ensureFfprobe(src, destFile) {
  const dest = path.join(ffmpegDir, destFile);
  if (!fs.existsSync(ffmpegDir)) {
    fs.mkdirSync(ffmpegDir, { recursive: true });
  }
  if (fs.existsSync(dest)) {
    console.log(`[prebuild] ffprobe 已存在，跳过: ${dest}`);
    return;
  }
  if (fs.existsSync(src)) {
    console.log(`[prebuild] 复制 ffprobe: ${src} -> ${dest}`);
    copyFile(src, dest);
  } else {
    console.warn(`[prebuild] 警告: 未找到 ffprobe: ${src}`);
  }
}

if (platform === 'darwin' || platform === 'linux') {
  const possibleFfprobePaths = [
    '/opt/homebrew/bin/ffprobe',    // Homebrew on Apple Silicon
    '/usr/local/bin/ffprobe',        // Homebrew on Intel
    '/usr/bin/ffprobe'               // System
  ];
  for (const p of possibleFfprobePaths) {
    if (fs.existsSync(p)) {
      ensureFfprobe(p, 'ffprobe');
      break;
    }
  }
} else if (platform === 'win32') {
  const ffprobeSrc = 'ffprobe.exe';
  ensureFfprobe(ffprobeSrc, 'ffprobe.exe');
}

console.log('[prebuild] 完成');
