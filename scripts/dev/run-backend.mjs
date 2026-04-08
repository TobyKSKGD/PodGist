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
import { createRequire } from 'module';
import path from 'node:path';
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
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

function findPython() {
  const projectRoot = path.dirname(path.dirname(fileURLToPath(import.meta.url)));

  // 按顺序尝试的 Python 解释器路径
  const candidates = isWindows
    ? [
        path.join(projectRoot, 'env', 'Scripts', 'python.exe'),
        path.join(projectRoot, '.venv', 'Scripts', 'python.exe'),
        'py -3',
        'python',
      ]
    : [
        path.join(projectRoot, 'env', 'bin', 'python3'),
        path.join(projectRoot, '.venv', 'bin', 'python3'),
        path.join(projectRoot, 'env', 'bin', 'python'),
        path.join(projectRoot, '.venv', 'bin', 'python'),
        'python3',
        'python',
      ];

  for (const candidate of candidates) {
    try {
      if (typeof candidate === 'string' && candidate.includes(' ')) {
        // For commands like "py -3" or "python3"
        const [cmd, ...args] = candidate.split(' ');
        const result = spawn(cmd, ['--version'], { stdio: 'pipe' });
        // Wait briefly
        result.on('close', (code) => {
          if (code === 0) log(`使用 Python: ${candidate}`);
        });
        // Return the command string for use with spawn
        return candidate;
      } else if (fs.existsSync(candidate)) {
        const result = spawn(candidate, ['--version'], { stdio: 'pipe' });
        result.on('close', (code) => {
          if (code === 0) log(`使用 Python: ${candidate}`);
        });
        return candidate;
      }
    } catch {
      // continue
    }
  }

  return null;
}

function getPythonCmd(projectRoot) {
  if (isWindows) {
    const venvPython = path.join(projectRoot, 'env', 'Scripts', 'python.exe');
    if (fs.existsSync(venvPython)) return venvPython;
    const venvPython2 = path.join(projectRoot, '.venv', 'Scripts', 'python.exe');
    if (fs.existsSync(venvPython2)) return venvPython2;
    return 'py'; // fallback to py launcher
  } else {
    const venvPython = path.join(projectRoot, 'env', 'bin', 'python3');
    if (fs.existsSync(venvPython)) return venvPython;
    const venvPython2 = path.join(projectRoot, '.venv', 'bin', 'python3');
    if (fs.existsSync(venvPython2)) return venvPython2;
    return 'python3';
  }
}

function checkPythonEnv(pythonCmd, projectRoot) {
  return new Promise((resolve) => {
    const check = spawn(pythonCmd, ['-c', 'import fastapi'], {
      cwd: projectRoot,
      stdio: 'pipe',
    });
    check.on('close', (code) => {
      resolve(code === 0);
    });
    check.on('error', () => resolve(false));
  });
}

async function main() {
  // 使用 cwd 作为项目根目录（start.js 启动时 cwd 就是项目根目录）
  const projectRoot = process.cwd();
  const pythonCmd = getPythonCmd(projectRoot);

  log(`项目目录: ${projectRoot}`);
  log(`平台: ${platform()}`);

  // Check Python exists
  try {
    const versionCheck = spawn(pythonCmd, ['--version'], { stdio: 'pipe' });
    await new Promise((resolve) => {
      versionCheck.on('close', (code) => {
        if (code !== 0) {
          logError(`Python 不可用: ${pythonCmd}`);
          process.exit(1);
        }
        resolve();
      });
    });
  } catch (e) {
    logError(`启动 Python 失败: ${e.message}`);
    process.exit(1);
  }

  // Check fastapi installed
  const hasFastAPI = await checkPythonEnv(pythonCmd, projectRoot);
  if (!hasFastAPI) {
    logError('未安装 fastapi 依赖。请运行: pip install -r requirements.txt');
    process.exit(1);
  }

  // Spawn uvicorn
  log('启动 uvicorn api:app --reload --host 127.0.0.1 --port 8000...');

  const uvicorn = spawn(pythonCmd, ['-m', 'uvicorn', 'api:app', '--reload', '--host', '127.0.0.1', '--port', '8000'], {
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
