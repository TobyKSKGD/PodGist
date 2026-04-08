#!/bin/bash
# PodGist macOS Runtime Bootstrap 脚本
#
# 在 CI 环境中准备 macOS 运行时依赖：
# - 创建 python_venv
# - 安装 requirements.txt 依赖
# - 安装 yt-dlp
# - 准备 ffmpeg/ffprobe
#
# 用法: bash scripts/release/bootstrap-runtime-mac.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="${SCRIPT_DIR%/scripts/release}"
ELECTRON_DIR="$PROJECT_ROOT/electron"
VENV_DIR="$ELECTRON_DIR/resources/python_venv"
FFMPEG_DIR="$ELECTRON_DIR/resources/ffmpeg"

echo "=== PodGist macOS Runtime Bootstrap ==="
echo "项目目录: $PROJECT_ROOT"

# ===== 创建 python_venv =====
echo ""
echo "[1/4] 创建 Python 虚拟环境..."
if [ -d "$VENV_DIR" ]; then
    echo "  python_venv 已存在，跳过创建"
else
    python3 -m venv "$VENV_DIR"
    echo "  创建成功: $VENV_DIR"
fi

# ===== 安装依赖 =====
echo ""
echo "[2/4] 安装 Python 依赖..."
# 使用绝对路径 + 不升级 pip（venv 自带 pip）
"$VENV_DIR/bin/pip" install -r "$PROJECT_ROOT/requirements.txt"
echo "  依赖安装完成"

# ===== 安装 yt-dlp =====
echo ""
echo "[3/4] 安装 yt-dlp..."
"$VENV_DIR/bin/pip" install yt-dlp
echo "  yt-dlp 安装完成"

# ===== 准备 FFmpeg =====
echo ""
echo "[4/4] 准备 FFmpeg..."

# 创建 ffmpeg 目录
mkdir -p "$FFMPEG_DIR"

# 查找系统 ffmpeg/ffprobe
FFMPEG_BIN=""
FFPROBE_BIN=""

# Homebrew on Apple Silicon
if [ -f "/opt/homebrew/bin/ffmpeg" ]; then
    FFMPEG_BIN="/opt/homebrew/bin/ffmpeg"
    FFPROBE_BIN="/opt/homebrew/bin/ffprobe"
# Homebrew on Intel
elif [ -f "/usr/local/bin/ffmpeg" ]; then
    FFMPEG_BIN="/usr/local/bin/ffmpeg"
    FFPROBE_BIN="/usr/local/bin/ffprobe"
# System
elif [ -f "/usr/bin/ffmpeg" ]; then
    FFMPEG_BIN="/usr/bin/ffmpeg"
    FFPROBE_BIN="/usr/bin/ffprobe"
fi

if [ -n "$FFMPEG_BIN" ]; then
    echo "  找到系统 FFmpeg: $FFMPEG_BIN"

    # 复制 ffmpeg
    if [ ! -f "$FFMPEG_DIR/ffmpeg" ]; then
        cp "$FFMPEG_BIN" "$FFMPEG_DIR/ffmpeg"
        chmod +x "$FFMPEG_DIR/ffmpeg"
        echo "  ffmpeg -> $FFMPEG_DIR/ffmpeg"
    else
        echo "  ffmpeg 已存在，跳过"
    fi

    # 复制 ffprobe
    if [ ! -f "$FFMPEG_DIR/ffprobe" ]; then
        cp "$FFPROBE_BIN" "$FFMPEG_DIR/ffprobe"
        chmod +x "$FFMPEG_DIR/ffprobe"
        echo "  ffprobe -> $FFMPEG_DIR/ffprobe"
    else
        echo "  ffprobe 已存在，跳过"
    fi
else
    echo "  警告: 未找到系统 FFmpeg，尝试用 brew 安装..."
    # macOS CI 环境用 brew 安装
    if command -v brew &> /dev/null; then
        echo "  使用 brew install ffmpeg..."
        # brew 安装到 Cellar，我们从 Cellar 复制（使用 find 避免 glob 在引号内失效）
        BREW_FFMPEG=$(find $(brew --prefix)/Cellar/ffmpeg -name "ffmpeg" -type f 2>/dev/null | head -1) || true
        BREW_FFPROBE=$(find $(brew --prefix)/Cellar/ffmpeg -name "ffprobe" -type f 2>/dev/null | head -1) || true

        if [ -n "$BREW_FFMPEG" ] && [ -f "$BREW_FFMPEG" ]; then
            if [ ! -f "$FFMPEG_DIR/ffmpeg" ]; then
                cp "$BREW_FFMPEG" "$FFMPEG_DIR/ffmpeg"
                chmod +x "$FFMPEG_DIR/ffmpeg"
                echo "  ffmpeg (brew) -> $FFMPEG_DIR/ffmpeg"
            fi
            if [ -n "$BREW_FFPROBE" ] && [ -f "$BREW_FFPROBE" ] && [ ! -f "$FFMPEG_DIR/ffprobe" ]; then
                cp "$BREW_FFPROBE" "$FFMPEG_DIR/ffprobe"
                chmod +x "$FFMPEG_DIR/ffprobe"
                echo "  ffprobe (brew) -> $FFMPEG_DIR/ffprobe"
            fi
        else
            # 直接 brew install（如果 Cellar 里没有）
            echo "  Cellar 中未找到，尝试直接 brew install..."
            brew install ffmpeg
            BREW_FFMPEG=$(find $(brew --prefix)/Cellar/ffmpeg -name "ffmpeg" -type f | head -1)
            BREW_FFPROBE=$(find $(brew --prefix)/Cellar/ffmpeg -name "ffprobe" -type f | head -1)
            if [ -f "$BREW_FFMPEG" ] && [ ! -f "$FFMPEG_DIR/ffmpeg" ]; then
                cp "$BREW_FFMPEG" "$FFMPEG_DIR/ffmpeg"
                chmod +x "$FFMPEG_DIR/ffmpeg"
            fi
            if [ -f "$BREW_FFPROBE" ] && [ ! -f "$FFMPEG_DIR/ffprobe" ]; then
                cp "$BREW_FFPROBE" "$FFMPEG_DIR/ffprobe"
                chmod +x "$FFMPEG_DIR/ffprobe"
            fi
        fi
    else
        echo "  错误: brew 不可用，且未找到系统 FFmpeg"
        echo "  FFmpeg 将不可用（播客解析等功能可能受影响）"
    fi
fi

# 列出最终 ffmpeg 目录内容
echo ""
echo "=== $FFMPEG_DIR 内容 ==="
ls -la "$FFMPEG_DIR/"

echo ""
echo "=== Bootstrap 完成 ==="
