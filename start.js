#!/usr/bin/env node
/**
 * PodGist 跨平台启动脚本
 *
 * 同时启动前后端服务：
 * - 后端：node scripts/dev/run-backend.mjs
 * - 前端：vite（通过 npm run dev --prefix frontend）
 *
 * Ctrl+C / SIGINT / SIGTERM 时正确关闭两个子进程。
 */

import { spawn, execSync } from 'child_process';
import { platform, arch } from 'os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const isWindows = platform() === 'win32';
const EOL = isWindows ? '\r\n' : '\n';

// ANSI colors
const RESET = isWindows ? '' : '\x1b[0m';
const BLUE = isWindows ? '' : '\x1b[34m';
const CYAN = isWindows ? '' : '\x1b[36m';

function log(color, prefix, msg) {
  console.log(`${color}[${prefix}]${msg ? ' ' + msg : ''}${RESET}`);
}

function killPort(port) {
  if (isWindows) {
    try {
      const output = execSync(`netstat -ano | findstr :${port} | findstr LISTENING`, {
        encoding: 'utf8',
        stdio: ['pipe', 'pipe', 'pipe'],
      });
      const lines = (output || '').trim().split(EOL);
      for (const line of lines) {
        const parts = line.trim().split(/\s+/);
        const pid = parts[parts.length - 1];
        if (pid && /^\d+$/.test(pid)) {
          try {
            execSync(`taskkill /PID ${pid} /F`, { stdio: 'ignore' });
          } catch {}
        }
      }
    } catch {}
  } else {
    try {
      execSync(`lsof -ti:${port} | xargs kill -9 2>/dev/null || true`, {
        shell: '/bin/sh',
        stdio: ['pipe', 'pipe', 'pipe'],
      });
    } catch {}
  }
}

async function main() {
  const isMac = platform() === 'darwin';

  console.log('========================================');
  console.log('  PodGist 启动脚本');
  console.log(`  平台: ${platform()} ${arch()}`);
  console.log('========================================' + EOL);

  // Step 1: Kill existing processes on ports 8000 and 5173
  log(BLUE, 'CLEAN', '清理旧进程 (端口 8000, 5173)...');
  killPort(8000);
  killPort(5173);
  await new Promise((r) => setTimeout(r, 500));

  // Step 2: Start backend
  log(BLUE, 'START', '启动后端...');
  const __dirname = path.dirname(fileURLToPath(import.meta.url));
  const backendScript = path.join(__dirname, 'scripts', 'dev', 'run-backend.mjs');

  const backend = spawn('node', [backendScript], {
    stdio: ['ignore', 'pipe', 'pipe'],
    detached: false,
  });

  backend.stdout.on('data', (data) => {
    process.stdout.write(`${BLUE}[backend]${RESET} ${data}`);
  });

  backend.stderr.on('data', (data) => {
    process.stderr.write(`${BLUE}[backend]${RESET} ${data}`);
  });

  backend.on('error', (err) => {
    log(BLUE, 'ERROR', `后端启动失败: ${err.message}`);
  });

  // Step 3: Start frontend
  log(CYAN, 'START', '启动前端...');
  // Windows 不能在所有 Node 版本中直接 spawn .cmd 文件；通过系统命令解释器启动。
  // macOS/Linux 继续直接执行 npm，避免改变原有开发体验。
  const npmCmd = isWindows ? (process.env.ComSpec || 'cmd.exe') : 'npm';
  const npmArgs = isWindows
    ? ['/d', '/s', '/c', 'npm.cmd run dev --prefix frontend']
    : ['run', 'dev', '--prefix', 'frontend'];
  const frontend = spawn(
    npmCmd,
    npmArgs,
    {
      stdio: ['ignore', 'pipe', 'pipe'],
      detached: false,
    }
  );

  frontend.stdout.on('data', (data) => {
    process.stdout.write(`${CYAN}[frontend]${RESET} ${data}`);
  });

  frontend.stderr.on('data', (data) => {
    process.stderr.write(`${CYAN}[frontend]${RESET} ${data}`);
  });

  frontend.on('error', (err) => {
    log(CYAN, 'ERROR', `前端启动失败: ${err.message}`);
  });

  console.log(EOL + '========================================');
  console.log(`  后端: ${BLUE}http://localhost:8000${RESET}`);
  console.log(`  前端: ${CYAN}http://localhost:5173${RESET}`);
  console.log('========================================' + EOL);
  console.log('按 Ctrl+C 停止所有服务' + EOL);

  // Collect child processes for cleanup
  const children = [backend, frontend];

  // Cleanup on exit
  const shutdown = (signal) => {
    log(RESET, 'SHUTDOWN', `收到 ${signal}，正在停止服务...`);
    for (const child of children) {
      if (child && !child.killed) {
        try {
          if (isWindows) {
            execSync(`taskkill /PID ${child.pid} /T /F`, { stdio: 'ignore' });
          } else {
            child.kill('SIGTERM');
          }
        } catch {}
      }
    }
    // Force kill after timeout
    setTimeout(() => {
      for (const child of children) {
        if (child && !child.killed) {
          try {
            child.kill('SIGKILL');
          } catch {}
        }
      }
      process.exit(0);
    }, 3000);
  };

  process.on('SIGINT', shutdown);
  process.on('SIGTERM', shutdown);

  // Monitor children
  backend.on('close', (code) => {
    if (code !== 0 && code !== null) {
      log(BLUE, 'BACKEND', `后端进程退出，code=${code}`);
    }
  });

  frontend.on('close', (code) => {
    if (code !== 0 && code !== null) {
      log(CYAN, 'FRONTEND', `前端进程退出，code=${code}`);
    }
    // Frontend exiting usually means user stopped, exit too
    shutdown('child-exit');
  });
}

main().catch(console.error);
