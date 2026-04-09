#!/usr/bin/env pwsh
# PodGist Windows backend build script
$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $PSScriptRoot
$projectRoot = Split-Path -Parent $scriptRoot
$absProjectRoot = (Resolve-Path $projectRoot).Path
$absBackendDir = Join-Path $absProjectRoot "backend"
$absApiSpec = Join-Path $absBackendDir "api.spec"
$absApiDist = Join-Path $absBackendDir "dist"
$absApiOutput = Join-Path $absApiDist "api"
$absBuildDir = Join-Path $absBackendDir "build"
$absElectronApi = Join-Path $absProjectRoot "electron/dist/api"

Write-Host "=== PodGist Windows Backend Build ===" -ForegroundColor Cyan
Write-Host "Project: ${absProjectRoot}"

# Step 1: Syntax check
Write-Host "`n[1/5] Running syntax check..." -ForegroundColor Yellow
$checkScript = Join-Path $absProjectRoot "scripts/check_backend.py"
python $checkScript
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Syntax check failed" -ForegroundColor Red
    exit 1
}
Write-Host "Syntax check OK" -ForegroundColor Green

# Step 2: Verify required files
Write-Host "`n[2/5] Verifying files..." -ForegroundColor Yellow
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
Write-Host "File verification OK" -ForegroundColor Green

# Step 3: PyInstaller build
Write-Host "`n[3/5] Running PyInstaller..." -ForegroundColor Yellow
$env:PYTHONOPTIMIZE = "1"

Write-Host "  Cleaning old output..."
if (Test-Path $absApiDist) {
    Remove-Item $absApiDist -Recurse -Force -ErrorAction SilentlyContinue
}
if (Test-Path $absBuildDir) {
    Remove-Item $absBuildDir -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host "  Running PyInstaller..."
Write-Host "    Spec: ${absApiSpec}"
Write-Host "    distpath: ${absApiDist}"
Write-Host "    workpath: ${absBuildDir}"

# 不加 --onedir/--onefile，spec 文件已包含此配置
# 不使用 cmd /c | ForEach-Object，直接运行
python -m PyInstaller --clean --noconfirm --distpath $absApiDist --workpath $absBuildDir $absApiSpec
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: PyInstaller failed with exit code $LASTEXITCODE" -ForegroundColor Red
    exit 1
}
Write-Host "  PyInstaller done" -ForegroundColor Green

# Step 4: Locate output
Write-Host "`n[4/5] Locating output..." -ForegroundColor Yellow
if (-not (Test-Path $absApiDist)) {
    Write-Host "ERROR: dist dir not found: ${absApiDist}" -ForegroundColor Red
    exit 1
}
if (-not (Test-Path $absApiOutput)) {
    Write-Host "ERROR: api output dir not found: ${absApiOutput}" -ForegroundColor Red
    exit 1
}
Write-Host "Output: ${absApiOutput}" -ForegroundColor Green

# Step 5: Verify PyInstaller output
Write-Host "`n[5/5] Verifying build artifacts..." -ForegroundColor Yellow
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
    Write-Host "ERROR: PyInstaller artifacts incomplete" -ForegroundColor Red
    exit 1
}
Write-Host "All artifacts verified" -ForegroundColor Green

# Copy to electron/dist/api
Write-Host "`nCopying to electron/dist/api..." -ForegroundColor Yellow
Write-Host "  Source: ${absApiOutput}"
Write-Host "  Dest: ${absElectronApi}"

New-Item -ItemType Directory -Force -Path $absElectronApi | Out-Null

# robocopy /MIR 镜像复制，/S 复制子目录
# robocopy exit 0-7 都是成功
robocopy $absApiOutput $absElectronApi /MIR /S /NFL /NDL /NJH /NJS /NC /NS /NP
$robocopyExit = $LASTEXITCODE
Write-Host "  robocopy exit code: $robocopyExit"
if ($robocopyExit -ge 8) {
    Write-Host "ERROR: robocopy failed with exit code $robocopyExit" -ForegroundColor Red
    exit 1
}

# 严格检查复制结果
$destApiEngine = Join-Path $absElectronApi "api-engine.exe"
if (-not (Test-Path $destApiEngine)) {
    Write-Host "ERROR: api-engine.exe not found after copy: ${destApiEngine}" -ForegroundColor Red
    exit 1
}
Write-Host "  Copy verified: ${destApiEngine}" -ForegroundColor Green

Write-Host ""
Write-Host "=== Windows Backend Build SUCCESS ===" -ForegroundColor Green
Write-Host "Output: ${destApiEngine}"
exit 0
