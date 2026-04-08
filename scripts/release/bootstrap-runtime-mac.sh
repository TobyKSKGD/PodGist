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
    echo "  警告: 未找到系统 FFmpeg，尝试下载..."
    # 从 John's FFmpeg builds 下载静态 FFmpeg（支持 Apple Silicon）
    FFMPEG_URL="https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-arm64.zip"
    FFPROBE_URL="https://johnvansickle.com/ffmpeg/releases/ffprobe-release-arm64.zip"

    if [ ! -f "$FFMPEG_DIR/ffmpeg" ]; then
        echo "  下载 ffmpeg from $FFMPEG_URL"
        if curl -sL "$FFMPEG_URL" -o /tmp/ffmpeg.zip; then
            unzip -o /tmp/ffmpeg.zip -d /tmp/ffmpeg_extracted
            FFmpeg_BIN=$(find /tmp/ffmpeg_extracted -name "ffmpeg" -type f | head -1)
            if [ -n "$FFmpeg_BIN" ]; then
                cp "$FFmpeg_BIN" "$FFMPEG_DIR/ffmpeg"
                chmod +x "$FFMPEG_DIR/ffmpeg"
                echo "  ffmpeg 下载成功: $FFmpeg_BIN -> $FFMPEG_DIR/ffmpeg"
            else
                echo "  错误: 解压后未找到 ffmpeg 二进制文件"
            fi
        else
            echo "  ffmpeg 下载失败"
        fi
    else
        echo "  ffmpeg 已存在，跳过"
    fi

    if [ ! -f "$FFMPEG_DIR/ffprobe" ]; then
        echo "  下载 ffprobe from $FFPROBE_URL"
        if curl -sL "$FFPROBE_URL" -o /tmp/ffprobe.zip; then
            unzip -o /tmp/ffprobe.zip -d /tmp/ffprobe_extracted
            FFprobe_BIN=$(find /tmp/ffprobe_extracted -name "ffprobe" -type f | head -1)
            if [ -n "$FFprobe_BIN" ]; then
                cp "$FFprobe_BIN" "$FFMPEG_DIR/ffprobe"
                chmod +x "$FFMPEG_DIR/ffprobe"
                echo "  ffprobe 下载成功: $FFprobe_BIN -> $FFMPEG_DIR/ffprobe"
            else
                echo "  错误: 解压后未找到 ffprobe 二进制文件"
            fi
        else
            echo "  ffprobe 下载失败"
        fi
    else
        echo "  ffprobe 已存在，跳过"
    fi
fi

# 列出最终 ffmpeg 目录内容
echo ""
echo "=== $FFMPEG_DIR 内容 ==="
ls -la "$FFMPEG_DIR/"

echo ""
echo "=== Bootstrap 完成 ==="
