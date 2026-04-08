#!/usr/bin/env pwsh
# PodGist Windows 后端 PyInstaller 构建脚本
#
# 用法：powershell -ExecutionPolicy Bypass -File scripts/release/build-backend-win.ps1

$ErrorActionPreference = "Stop"

# 解析项目根目录（脚本在 scripts/release/，项目根是其父的父）
$scriptRoot = Split-Path -Parent $PSScriptRoot
$projectRoot = Split-Path -Parent $scriptRoot

# 使用绝对路径，后续所有路径操作基于此
$absProjectRoot = (Resolve-Path $projectRoot).Path
$absBackendDir = Join-Path $absProjectRoot "backend"
$absApiSpec = Join-Path $absBackendDir "api.spec"
$absApiDist = Join-Path $absBackendDir "dist"
$absApiOutput = Join-Path $absApiDist "api"
$absElectronDist = Join-Path $absProjectRoot "electron/dist"
$absElectronApi = Join-Path $absElectronDist "api"

Write-Host "=== PodGist Windows 后端构建 ===" -ForegroundColor Cyan
Write-Host "项目目录: $absProjectRoot"

# ===== 语法检查 =====
Write-Host "`n[1/5] 运行后端语法检查..." -ForegroundColor Yellow
$checkScript = Join-Path $absProjectRoot "scripts/check_backend.py"
python $checkScript
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: 后端语法检查失败" -ForegroundColor Red
    exit 1
}
Write-Host "语法检查通过" -ForegroundColor Green

# ===== 验证必需文件存在 =====
Write-Host "`n[2/5] 验证后端文件..." -ForegroundColor Yellow
$required = @(
    (Join-Path $absBackendDir "start_electron.py"),
    (Join-Path $absBackendDir "__init__.py"),
    (Join-Path $absBackendDir "downloader.py"),
    (Join-Path $absBackendDir "transcriber.py"),
    (Join-Path $absBackendDir "worker.py"),
    (Join-Path $absBackendDir "llm_agent.py"),
    (Join-Path $absBackendDir "rag_retriever.py"),
    (Join-Path $absBackendDir "diagnostics.py"),
    (Join-Path $absBackendDir "rag_db.py"),
    (Join-Path $absBackendDir "task_queue.py"),
    $absApiSpec,
    (Join-Path $absProjectRoot "api.py")
)
foreach ($f in $required) {
    if (Test-Path $f) {
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

# 清理旧输出
Write-Host "  清理旧输出..."
if (Test-Path $absApiDist) {
    Remove-Item $absApiDist -Recurse -Force -ErrorAction SilentlyContinue
}
$absBuildDir = Join-Path $absBackendDir "build"
if (Test-Path $absBuildDir) {
    Remove-Item $absBuildDir -Recurse -Force -ErrorAction SilentlyContinue
}

# 在 backend/ 目录下运行 pyinstaller
Write-Host "  运行 pyinstaller --onedir --specpath $absBackendDir $absApiSpec ..."
Push-Location $absBackendDir
try {
    pyinstaller --clean --onedir --specpath $absBackendDir $absApiSpec 2>&1 | ForEach-Object {
        Write-Host "    $_"
    }
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: PyInstaller 失败，exit code=$LASTEXITCODE" -ForegroundColor Red
        exit 1
    }
} finally {
    Pop-Location
}

# ===== 定位输出目录 =====
Write-Host "`n[4/5] 定位输出目录..." -ForegroundColor Yellow
if (Test-Path $absApiOutput) {
    Write-Host "输出目录: $absApiOutput" -ForegroundColor Green
} else {
    Write-Host "ERROR: api dist 目录不存在: $absApiOutput" -ForegroundColor Red
    # 列出 backend/dist 内容用于调试
    if (Test-Path $absApiDist) {
        Get-ChildItem $absApiDist -Recurse | Select-Object -First 20 FullName
    }
    exit 1
}

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
    $fullPath = Join-Path $absApiOutput $dll
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
Write-Host "  源: $absApiOutput"
Write-Host "  目标: $absElectronApi"

# 创建目标目录
New-Item -ItemType Directory -Force -Path $absElectronApi | Out-Null

# 用 robocopy 镜像复制（确保所有嵌套文件正确复制）
Write-Host "  执行 robocopy..."
$robocopyResult = robocopy $absApiOutput $absElectronApi /MIR /NFL /NDL /NJH /NJS /NC /NS /NP
$robocopyExit = $LASTEXITCODE
Write-Host "  robocopy exit code: $robocopyExit"
if ($robocopyExit -ge 8) {
    Write-Host "ERROR: robocopy 复制失败，exit code=$robocopyExit" -ForegroundColor Red
    exit 1
}

# 验证复制结果
$destApiEngine = Join-Path $absElectronApi "api-engine.exe"
if (-not (Test-Path $destApiEngine)) {
    Write-Host "ERROR: 复制后 api-engine.exe 不存在: $destApiEngine" -ForegroundColor Red
    # 列出目标目录内容
    if (Test-Path $absElectronApi) {
        Write-Host "  $absElectronApi 内容:"
        Get-ChildItem $absElectronApi -Recurse | Select-Object -First 20 FullName
    }
    exit 1
}

# 列出复制后的内容（用于调试）
Write-Host "  复制后 $absElectronApi 内容:"
Get-ChildItem $absElectronApi | ForEach-Object {
    if ($_.PSIsContainer) {
        Write-Host "    $($_.Name)/"
    } else {
        Write-Host "    $($_.Name)"
    }
}

Write-Host ""
Write-Host "=== Windows 后端构建成功 ===" -ForegroundColor Green
Write-Host "产物: $destApiEngine"
exit 0
