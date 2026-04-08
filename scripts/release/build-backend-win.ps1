#!/usr/bin/env pwsh
# PodGist Windows 后端 PyInstaller 构建脚本
#
# 从根目录 backend/ 构建 Windows 可执行文件
# 产物：backend/dist/api/api-engine.exe
#
# 用法：powershell -ExecutionPolicy Bypass -File scripts/release/build-backend-win.ps1

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)

Write-Host "=== PodGist Windows 后端构建 ===" -ForegroundColor Cyan
Write-Host "项目目录: $projectRoot"

# 切换到项目根目录
Set-Location $projectRoot

# ===== 语法检查 =====
Write-Host "`n[1/5] 运行后端语法检查..." -ForegroundColor Yellow
python scripts/check_backend.py
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: 后端语法检查失败" -ForegroundColor Red
    exit 1
}
Write-Host "语法检查通过" -ForegroundColor Green

# ===== 验证必需文件存在 =====
Write-Host "`n[2/5] 验证后端文件..." -ForegroundColor Yellow
$required = @(
    "backend/start_electron.py",
    "backend/__init__.py",
    "backend/downloader.py",
    "backend/transcriber.py",
    "backend/worker.py",
    "backend/llm_agent.py",
    "backend/rag_retriever.py",
    "backend/diagnostics.py",
    "backend/rag_db.py",
    "backend/task_queue.py",
    "backend/api.spec",
    "api.py"
)
foreach ($f in $required) {
    $fullPath = Join-Path $projectRoot $f
    if (Test-Path $fullPath) {
        Write-Host "  OK: $f"
    } else {
        Write-Host "  MISSING: $f" -ForegroundColor Red
        exit 1
    }
}
Write-Host "文件验证通过" -ForegroundColor Green

# ===== PyInstaller 构建 =====
Write-Host "`n[3/5] 运行 PyInstaller..." -ForegroundColor Yellow
$env:PYTHONOPTIMIZE = "1"
# 清理旧输出（绝对路径确保在 repo root 执行）
$absProjectRoot = (Resolve-Path $projectRoot).Path
Remove-Item "$absProjectRoot/backend/dist" -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item "$absProjectRoot/backend/build" -Recurse -Force -ErrorAction SilentlyContinue
# 使用绝对路径运行 pyinstaller，确保路径解析正确
$specFile = Join-Path $absProjectRoot "backend/api.spec"
Push-Location (Join-Path $absProjectRoot "backend")
try {
    pyinstaller --clean --noconfirm $specFile
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: PyInstaller 失败，exit code=$LASTEXITCODE" -ForegroundColor Red
        exit 1
    }
} finally {
    Pop-Location
}

# ===== 定位输出目录 =====
Write-Host "`n[4/5] 定位输出目录..." -ForegroundColor Yellow
$apiDist = $null
if (Test-Path "backend/dist/api") {
    $apiDist = "backend/dist/api"
} elseif (Test-Path "dist/api") {
    $apiDist = "dist/api"
} else {
    Write-Host "ERROR: api dist not found" -ForegroundColor Red
    Get-ChildItem . -Recurse -Filter "*.exe" -ErrorAction SilentlyContinue | Select-Object -First 10 FullName
    exit 1
}
Write-Host "输出目录: $apiDist" -ForegroundColor Green

# ===== 验证 PyInstaller 产物 =====
Write-Host "`n[5/5] 验证构建产物..." -ForegroundColor Yellow
$requiredDlls = @(
    "api-engine.exe",
    "_internal\python311.dll",
    "_internal\vcruntime140.dll",
    "_internal\vcruntime140_1.dll",
    "_internal\msvcp140.dll"
)
$allOk = $true
foreach ($dll in $requiredDlls) {
    $fullPath = Join-Path $apiDist $dll
    if (Test-Path $fullPath) {
        Write-Host "  OK: $dll"
    } else {
        Write-Host "  MISSING: $dll" -ForegroundColor Red
        $allOk = $false
    }
}

if (-not $allOk) {
    Write-Host "ERROR: PyInstaller 产物不完整" -ForegroundColor Red
    exit 1
}

# ===== 复制到 electron/dist/api =====
Write-Host "`n复制到 electron/dist/api..." -ForegroundColor Yellow
# 使用绝对路径
$srcDir = Join-Path $absProjectRoot $apiDist
$destDir = Join-Path $absProjectRoot "electron/dist/api"
Write-Host "  源: $srcDir"
Write-Host "  目标: $destDir"
# 用 robocopy 镜像复制（更可靠，支持嵌套目录）
$robocopyResult = robocopy $srcDir $destDir /MIR /NFL /NDL /NJH /NJS /NC /NS /NP
$robocopyExit = $LASTEXITCODE
Write-Host "  robocopy exit code: $robocopyExit"
if ($robocopyExit -ge 8) {
    Write-Host "ERROR: robocopy 复制失败，exit code=$robocopyExit" -ForegroundColor Red
    exit 1
}

if (-not (Test-Path (Join-Path $destDir "api-engine.exe"))) {
    Write-Host "ERROR: $destDir\api-engine.exe not found after copy" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "=== Windows 后端构建成功 ===" -ForegroundColor Green
Write-Host "产物: electron/dist/api/api-engine.exe"
exit 0
