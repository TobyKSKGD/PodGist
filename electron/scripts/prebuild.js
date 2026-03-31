#!/usr/bin/env node
/**
 * 预构建脚本 - 在 electron-builder 之前复制必要文件
 * 跨平台兼容：支持 macOS/Linux (cp) 和 Windows (xcopy/copy)
 */

const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const electronDir = __dirname;
const projectRoot = path.dirname(electronDir);

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

console.log('[prebuild] 完成');
