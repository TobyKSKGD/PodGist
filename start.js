#!/usr/bin/env node
/**
 * PodGist 跨平台启动脚本
 * 自动检测操作系统，使用对应的命令启动前后端
 */

import { spawn, execSync } from 'child_process';
import { platform, arch } from 'os';
import { createRequire } from 'module';

const require = createRequire(import.meta.url);
const pkg = require('./package.json');

const isWindows = platform() === 'win32';
const isMac = platform() === 'darwin';
const EOL = isWindows ? '\r\n' : '\n';

// ANSI colors
const colors = {
  backend: isWindows ? '' : '\x1b[34m',   // blue
  frontend: isWindows ? '' : '\x1b[36m',  // cyan
  reset: isWindows ? '' : '\x1b[0m',
};

function log(color, prefix, msg) {
  console.log(`${color}[${prefix}]${msg ? ' ' + msg : ''}${colors.reset}`);
}

function killPort(port) {
  if (isWindows) {
    try {
      execSync(`netstat -ano | findstr :${port} | findstr LISTENING`, { stdio: 'ignore' });
      const output = execSync(`netstat -ano | findstr :${port}`, { encoding: 'utf8' });
      const lines = output.trim().split(EOL);
      for (const line of lines) {
        const parts = line.trim().split(/\s+/);
        const pidIndex = parts.length - 1;
        const pid = parts[pidIndex];
        if (pid && /\d+/.test(pid)) {
          execSync(`taskkill /PID ${pid} /F`, { stdio: 'ignore' });
        }
      }
    } catch {}
  } else {
    try {
      execSync(`lsof -ti:${port} | xargs kill -9 2>/dev/null || true`, { shell: '/bin/sh' });
    } catch {}
  }
}

function getVenvPython() {
  if (isWindows) {
    return 'env\\Scripts\\python.exe';
  }
  return 'env/bin/python3';
}

function getVenvPip() {
  if (isWindows) {
    return 'env\\Scripts\\pip.exe';
  }
  return 'env/bin/pip';
}

function checkDeps() {
  log(colors.backend, 'CHECK', '检查 Python 环境...');
  try {
    execSync(`"${getVenvPython()}" --version`, { stdio: 'pipe' });
  } catch {
    log(colors.backend, 'ERROR', `未找到 Python 虚拟环境。请先创建：${isWindows ? 'python -m venv env' : 'python3 -m venv env'}`);
    log(colors.backend, 'ERROR', '然后激活环境：' + (isWindows ? 'env\\Scripts\\activate' : 'source env/bin/activate'));
    log(colors.backend, 'ERROR', '最后安装依赖：pip install -r requirements.txt');
    process.exit(1);
  }

  log(colors.backend, 'CHECK', '检查 pip 依赖...');
  try {
    execSync(`"${getVenvPip()}" show fastapi >/dev/null 2>&1`);
  } catch {
    log(colors.backend, 'ERROR', '缺少 Python 依赖。请运行：pip install -r requirements.txt');
    process.exit(1);
  }

  log(colors.backend, 'CHECK', '检查 Node.js...');
  try {
    execSync('npm --version', { stdio: 'pipe' });
  } catch {
    log(colors.frontend, 'ERROR', '未找到 Node.js。请安装 Node.js 18+：https://nodejs.org');
    process.exit(1);
  }
}

async function main() {
  console.log('========================================');
  console.log('  PodGist 启动脚本');
  console.log(`  平台: ${platform()} ${arch()}`);
  console.log('========================================' + EOL);

  // Step 1: Kill existing processes
  log(colors.backend, 'CLEAN', '清理旧进程 (端口 8000, 5173)...');
  killPort(8000);
  killPort(5173);

  // Step 2: Check environment
  checkDeps();

  // Step 3: Start backend
  const pythonCmd = getVenvPython();
  const backendCmd = isWindows ? 'uvicorn' : 'uvicorn';

  log(colors.backend, 'START', '启动后端 (FastAPI :8000)...');
  const backend = spawn(pythonCmd, [
    '-m', 'uvicorn', 'api:app',
    '--reload', '--port', '8000', '--app-dir', '..'
  ], {
    cwd: '..',
    shell: false,
    stdio: ['ignore', 'pipe', 'pipe'],
  });

  backend.stdout.on('data', (data) => {
    process.stdout.write(`${colors.backend}[backend]${colors.reset} ${data}`);
  });
  backend.stderr.on('data', (data) => {
    process.stderr.write(`${colors.backend}[backend]${colors.reset} ${data}`);
  });
  backend.on('error', (err) => {
    log(colors.backend, 'ERROR', err.message);
  });

  // Wait for backend to start
  await new Promise(r => setTimeout(r, 3000));

  // Step 4: Start frontend
  log(colors.frontend, 'START', '启动前端 (Vite :5173)...');
  const frontend = spawn('npm', ['run', 'dev', '--', '--host'], {
    cwd: 'frontend',
    shell: true,
    stdio: ['ignore', 'pipe', 'pipe'],
  });

  frontend.stdout.on('data', (data) => {
    process.stdout.write(`${colors.frontend}[frontend]${colors.reset} ${data}`);
  });
  frontend.stderr.on('data', (data) => {
    process.stderr.write(`${colors.frontend}[frontend]${colors.reset} ${data}`);
  });
  frontend.on('error', (err) => {
    log(colors.frontend, 'ERROR', err.message);
  });

  console.log(EOL + '========================================');
  console.log(`  后端: ${colors.backend}http://localhost:8000${colors.reset}`);
  console.log(`  前端: ${colors.frontend}http://localhost:5173${colors.reset}`);
  console.log('========================================' + EOL);
  console.log('按 Ctrl+C 停止所有服务' + EOL);

  // Cleanup on exit
  process.on('SIGINT', () => {
    log('', 'SHUTDOWN', '正在停止服务...');
    backend.kill();
    frontend.kill();
    process.exit(0);
  });
}

main().catch(console.error);
