#!/bin/bash
# PodGist macOS backend build script
# Uses PyInstaller to bundle backend into a standalone executable (like api-engine on Windows)
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ELECTRON_DIR="$PROJECT_ROOT/electron"
BACKEND_DIR="$PROJECT_ROOT/backend"
API_SPEC="$BACKEND_DIR/api.spec"
API_DIST="$BACKEND_DIR/dist"
API_OUTPUT="$API_DIST/api"
BUILD_DIR="$BACKEND_DIR/build"
ELECTRON_API="$PROJECT_ROOT/electron/dist/api"

echo "=== PodGist macOS Backend Build ==="
echo "Project: ${PROJECT_ROOT}"

# Step 1: Syntax check
echo ""
echo "[1/5] Running syntax check..."
CHECK_SCRIPT="$PROJECT_ROOT/scripts/check_backend.py"
python "$CHECK_SCRIPT"
if [ $? -ne 0 ]; then
    echo "ERROR: Syntax check failed"
    exit 1
fi
echo "Syntax check OK"

# Step 2: Verify required files
echo ""
echo "[2/5] Verifying files..."
REQUIRED_FILES=(
    "$BACKEND_DIR/start_electron.py"
    "$BACKEND_DIR/__init__.py"
    "$BACKEND_DIR/downloader.py"
    "$BACKEND_DIR/transcriber.py"
    "$BACKEND_DIR/worker.py"
    "$BACKEND_DIR/llm_agent.py"
    "$BACKEND_DIR/rag_retriever.py"
    "$BACKEND_DIR/diagnostics.py"
    "$BACKEND_DIR/rag_db.py"
    "$BACKEND_DIR/task_queue.py"
    "$API_SPEC"
    "$PROJECT_ROOT/api.py"
)
for f in "${REQUIRED_FILES[@]}"; do
    if [ -f "$f" ]; then
        echo "  OK: $f"
    else
        echo "  MISSING: $f"
        exit 1
    fi
done
echo "File verification OK"

# Step 3: PyInstaller build
echo ""
echo "[3/5] Running PyInstaller..."
export PYTHONOPTIMIZE="1"

# IMPORTANT: Use the bootstrapped python_venv's Python, not the system/setup-python's Python.
# The bootstrapped venv has all required packages (fastapi, uvicorn, etc.) installed via pip.
# Without this, PyInstaller runs with a different Python that lacks these packages.
PYTHON_VENV="$ELECTRON_DIR/resources/python_venv"
PYTHON_BIN="$PYTHON_VENV/bin/python3"

echo "  Using Python from venv: $PYTHON_BIN"
if [ ! -f "$PYTHON_BIN" ]; then
    echo "ERROR: python_venv Python not found: $PYTHON_BIN"
    echo "  Run bootstrap-runtime-mac.sh first!"
    exit 1
fi

echo "  Cleaning old output..."
if [ -d "$API_DIST" ]; then
    rm -rf "$API_DIST"
fi
if [ -d "$BUILD_DIR" ]; then
    rm -rf "$BUILD_DIR"
fi

echo "  Running PyInstaller..."
echo "    Spec: ${API_SPEC}"
echo "    distpath: ${API_DIST}"
echo "    workpath: ${BUILD_DIR}"
echo "    Python: $PYTHON_BIN"

# Use api.spec - do NOT pass --onedir/--onefile when spec file is given
# Run from project root so COLLECT output goes to backend/dist/api/
cd "$PROJECT_ROOT"
"$PYTHON_BIN" -m PyInstaller --clean --noconfirm --distpath "$API_DIST" --workpath "$BUILD_DIR" "$API_SPEC"
PYINSTALLER_EXIT=$?

# PyInstaller returns exit code 1 for hidden import warnings but build still succeeds
if [ $PYINSTALLER_EXIT -ne 0 ] && [ $PYINSTALLER_EXIT -ne 1 ]; then
    echo "ERROR: PyInstaller failed with exit code $PYINSTALLER_EXIT"
    exit 1
fi
echo "  PyInstaller done"

# Step 4: Locate output
echo ""
echo "[4/5] Locating output..."
if [ ! -d "$API_DIST" ]; then
    echo "ERROR: dist dir not found: ${API_DIST}"
    exit 1
fi
if [ ! -d "$API_OUTPUT" ]; then
    echo "ERROR: api output dir not found: ${API_OUTPUT}"
    exit 1
fi
echo "Output: ${API_OUTPUT}"

# Step 5: Verify PyInstaller output
echo ""
echo "[5/5] Verifying build artifacts..."
ALL_OK=true

# Verify the main executable exists
if [ -f "$API_OUTPUT/api-engine" ]; then
    SIZE=$(stat -f%z "$API_OUTPUT/api-engine" 2>/dev/null || stat -c%s "$API_OUTPUT/api-engine" 2>/dev/null || echo "unknown")
    echo "  OK: api-engine ($SIZE bytes)"
else
    echo "  MISSING: api-engine executable"
    ALL_OK=false
fi

# Verify _internal directory exists (contains Python runtime and dependencies)
if [ -d "$API_OUTPUT/_internal" ]; then
    INTERNAL_COUNT=$(ls "$API_OUTPUT/_internal" 2>/dev/null | wc -l | tr -d ' ')
    echo "  OK: _internal/ directory ($INTERNAL_COUNT entries)"
else
    echo "  MISSING: _internal/ directory"
    ALL_OK=false
fi

# Verify Python framework (macOS) or python shared lib
if [ -f "$API_OUTPUT/_internal/Python" ] || [ -f "$API_OUTPUT/_internal/libpython"*".dylib" ] 2>/dev/null; then
    echo "  OK: Python runtime found in _internal"
else
    echo "  WARNING: Python runtime not found in _internal (may still work)"
fi

if [ "$ALL_OK" = false ]; then
    echo "ERROR: PyInstaller artifacts incomplete"
    exit 1
fi
echo "All artifacts verified"

# Copy to electron/dist/api
echo ""
echo "Copying to electron/dist/api..."
echo "  Source: ${API_OUTPUT}"
echo "  Dest: ${ELECTRON_API}"

mkdir -p "$ELECTRON_API"

# Use rsync or cp -R to copy the entire directory
if command -v rsync &> /dev/null; then
    rsync -a "$API_OUTPUT/" "$ELECTRON_API/"
else
    cp -R "$API_OUTPUT/"* "$ELECTRON_API/"
fi

# Strict verification
DEST_API_ENGINE="$ELECTRON_API/api-engine"
if [ ! -f "$DEST_API_ENGINE" ]; then
    echo "ERROR: api-engine not found after copy: ${DEST_API_ENGINE}"
    exit 1
fi
echo "  Copy verified: ${DEST_API_ENGINE}"

# Make executable
chmod +x "$DEST_API_ENGINE"

echo ""
echo "=== macOS Backend Build SUCCESS ==="
echo "Output: ${DEST_API_ENGINE}"
exit 0
