#!/usr/bin/env node
/**
 * PodGist 后端启动脚本
 *
 * 在项目根目录启动 uvicorn FastAPI 后端。
 * 自动寻找 Python 解释器，不依赖 bash/source 激活虚拟环境。
 *
 * 用法: node scripts/dev/run-backend.mjs
 */

import { spawn } from 'child_process';
import { platform } from 'os';
import path from 'node:path';
import fs from 'node:fs';

const isWindows = platform() === 'win32';

// ANSI colors
const RESET = isWindows ? '' : '\x1b[0m';
const BLUE = isWindows ? '' : '\x1b[34m';

function log(msg) {
  console.log(`${BLUE}[backend]${RESET} ${msg}`);
}

function logError(msg) {
  console.error(`${BLUE}[backend]${RESET} ${msg}`);
}

function probePython(candidate, projectRoot) {
  return new Promise((resolve) => {
    const check = spawn(candidate.command, [
      ...candidate.prefixArgs,
      '-c',
      'import sys, fastapi, uvicorn; print(sys.executable); print(sys.version.split()[0])',
    ], {
      cwd: projectRoot,
      stdio: 'pipe',
    });
    let stdout = '';
    check.stdout.on('data', (data) => { stdout += data.toString(); });
    check.on('close', (code) => {
      const lines = stdout.trim().split(/\r?\n/);
      resolve(code === 0 ? {
        ...candidate,
        executable: lines[0] || candidate.label,
        version: lines[1] || 'unknown',
      } : null);
    });
    check.on('error', () => resolve(null));
  });
}

async function findPython(projectRoot) {
  const candidates = isWindows
    ? [
        { label: 'env', command: path.join(projectRoot, 'env', 'Scripts', 'python.exe'), prefixArgs: [], local: true },
        { label: '.venv', command: path.join(projectRoot, '.venv', 'Scripts', 'python.exe'), prefixArgs: [], local: true },
        { label: 'python', command: 'python', prefixArgs: [], local: false },
        { label: 'py -3', command: 'py', prefixArgs: ['-3'], local: false },
        { label: 'py', command: 'py', prefixArgs: [], local: false },
      ]
    : [
        { label: 'env/bin/python3', command: path.join(projectRoot, 'env', 'bin', 'python3'), prefixArgs: [], local: true },
        { label: '.venv/bin/python3', command: path.join(projectRoot, '.venv', 'bin', 'python3'), prefixArgs: [], local: true },
        { label: 'env/bin/python', command: path.join(projectRoot, 'env', 'bin', 'python'), prefixArgs: [], local: true },
        { label: '.venv/bin/python', command: path.join(projectRoot, '.venv', 'bin', 'python'), prefixArgs: [], local: true },
        { label: 'python3', command: 'python3', prefixArgs: [], local: false },
        { label: 'python', command: 'python', prefixArgs: [], local: false },
      ];

  for (const candidate of candidates) {
    if (candidate.local && !fs.existsSync(candidate.command)) continue;
    const available = await probePython(candidate, projectRoot);
    if (available) return available;
  }
  return null;
}

async function main() {
  // 使用 cwd 作为项目根目录（start.js 启动时 cwd 就是项目根目录）
  const projectRoot = process.cwd();
  log(`项目目录: ${projectRoot}`);
  log(`平台: ${platform()}`);

  const python = await findPython(projectRoot);
  if (!python) {
    logError('未找到同时安装了 fastapi 和 uvicorn 的 Python。');
    logError('请创建项目虚拟环境并运行: python -m pip install -r requirements.txt');
    process.exit(1);
  }
  log(`使用 Python ${python.version}: ${python.executable}`);

  // Spawn uvicorn
  log('启动 uvicorn api:app --reload --host 127.0.0.1 --port 8000...');

  const uvicorn = spawn(python.command, [
    ...python.prefixArgs,
    '-m', 'uvicorn', 'api:app', '--reload', '--host', '127.0.0.1', '--port', '8000',
  ], {
    cwd: projectRoot,
    stdio: ['ignore', 'pipe', 'pipe'],
    env: { ...process.env, PODGIST_DATA_DIR: projectRoot },
  });

  uvicorn.stdout.on('data', (data) => {
    process.stdout.write(`${BLUE}[backend]${RESET} ${data}`);
  });

  uvicorn.stderr.on('data', (data) => {
    process.stderr.write(`${BLUE}[backend]${RESET} ${data}`);
  });

  uvicorn.on('error', (err) => {
    logError(`启动失败: ${err.message}`);
    process.exit(1);
  });

  uvicorn.on('close', (code) => {
    if (code !== 0) {
      logError(`后端进程退出，code=${code}`);
    }
  });

  // Graceful shutdown
  const shutdown = (signal) => {
    log(`收到 ${signal}，正在停止后端...`);
    uvicorn.kill('SIGTERM');
    setTimeout(() => {
      uvicorn.kill('SIGKILL');
    }, 3000);
  };

  process.on('SIGINT', shutdown);
  process.on('SIGTERM', shutdown);

  log('后端已启动');
}

main().catch((e) => {
  logError(`致命错误: ${e.message}`);
  process.exit(1);
});
