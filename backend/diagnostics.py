"""
系统诊断模块 - 测试所有组件是否正常工作（远程 ASR 版）

包含以下测试：
- API Key 检查（DeepSeek）
- DashScope ASR API 连接测试
- FFmpeg 安装检查
"""

import os
import subprocess
from backend import get_ffmpeg_path


def test_api_key(api_key_file=".env"):
    """
    检查 API Key 是否已配置。

    参数:
        api_key_file (str): API Key 文件路径

    返回:
        tuple: (成功与否, 消息)
    """
    if os.path.exists(api_key_file):
        with open(api_key_file, "r", encoding="utf-8") as f:
            key = f.read().strip()
        if key:
            return True, "已配置"
        else:
            return False, "文件为空，请配置 API Key"
    else:
        return False, "未配置，请在上方输入"


def test_deepseek_api(api_key):
    """
    测试 DeepSeek API 连接是否正常。

    参数:
        api_key (str): DeepSeek API 密钥

    返回:
        tuple: (成功与否, 消息/错误信息)
    """
    if not api_key:
        return False, "API Key 未配置"

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=10
        )
        if response.choices and response.choices[0].message.content:
            return True, "连接成功"
        else:
            return False, "返回内容为空"
    except Exception as e:
        error_msg = str(e)
        if "Connection" in error_msg or "connect" in error_msg.lower():
            return False, "连接失败 - 请检查网络"
        elif "authentication" in error_msg.lower() or "api key" in error_msg.lower() or "401" in error_msg:
            return False, "API Key 错误"
        elif "403" in error_msg:
            return False, "API Key 无权限"
        else:
            return False, f"错误: {error_msg[:50]}"


def test_dashscope_asr(api_key=None):
    """
    测试 DashScope ASR API 连接是否正常。

    参数:
        api_key (str, optional): DashScope API Key，不提供则从环境变量读取

    返回:
        tuple: (成功与否, 消息/错误信息)
    """
    if api_key is None:
        api_key = os.environ.get('DASHSCOPE_API_KEY', '')

    if not api_key:
        return False, "DashScope API Key 未配置"

    try:
        from dashscope import Transcription
        os.environ['DASHSCOPE_API_KEY'] = api_key

        # 用一个简单的测试音频 URL（DashScope 官方测试样本）
        response = Transcription.call(
            model='qwen3-asr-flash-2026-02-10',
            file_urls=['https://modelscope.cn/models/modelscope/speech_nlp_s3gru_asr_nat-zh8k/raw/main/nls_ms_zh_v3.flac'],
            timestamp_alignment_enabled=True
        )

        # 注意：这个 URL 可能已失效，所以不依赖返回内容
        # 关键看 API 调用是否被接受（status_code == 200）
        if response.status_code == 200:
            return True, "连接成功"
        else:
            return False, f"API 返回错误: {response.output}"
    except Exception as e:
        error_msg = str(e)
        if "InvalidTask" in error_msg or "url error" in error_msg.lower():
            # URL 错误是预期的（测试 URL 可能失效），但说明 API Key 是有效的
            return True, "API Key 有效（音频 URL 需替换为本地文件）"
        elif "AuthenticationError" in error_msg or "401" in error_msg:
            return False, "API Key 无效"
        elif "Connection" in error_msg or "connect" in error_msg.lower():
            return False, "连接失败 - 请检查网络"
        else:
            return False, f"错误: {error_msg[:80]}"


def test_hardware():
    """
    检测硬件状态（远程 ASR 模式下不需要本地 GPU）。

    返回:
        tuple: (成功与否, 硬件状态消息)
    """
    return True, "云端 ASR，无需本地硬件"


def test_whisper_model():
    """
    Whisper 测试已移除（使用 DashScope ASR）。

    返回:
        tuple: (成功与否, 消息)
    """
    return None, "Whisper 已移除（使用 DashScope ASR）"


def test_sensevoice_model():
    """
    SenseVoice 测试已移除（使用 DashScope ASR）。

    返回:
        tuple: (成功与否, 消息)
    """
    return None, "SenseVoice 已移除（使用 DashScope ASR）"


def test_ffmpeg():
    """
    测试 FFmpeg 是否已安装。

    返回:
        tuple: (成功与否, 消息/错误信息)
    """
    try:
        result = subprocess.run(
            [get_ffmpeg_path(), "-version"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            lines = [l for l in result.stdout.split('\n') if l.strip()]
            version_short = lines[1] if len(lines) > 1 else result.stdout.split('\n')[0].split('Copyright')[0].strip()
            return True, version_short[:60]
        else:
            return False, "安装但无法运行"
    except FileNotFoundError:
        return False, "未安装"
    except Exception as e:
        return False, f"错误: {str(e)[:30]}"


def run_all_diagnostics(api_key=None, api_key_file=".env"):
    """
    运行所有诊断测试。

    参数:
        api_key (str, optional): DeepSeek API Key，如果未提供则从文件读取
        api_key_file (str): API Key 文件路径

    返回:
        list: 诊断结果列表，每项为 (名称, 成功与否, 消息) 元组
    """
    results = []

    # 读取 DeepSeek API Key
    if api_key is None:
        api_key = ""
        if os.path.exists(api_key_file):
            with open(api_key_file, "r", encoding="utf-8") as f:
                api_key = f.read().strip()

    # 1. DeepSeek API Key 检查
    if api_key:
        results.append(("DeepSeek API Key", True, "已配置"))
    else:
        results.append(("DeepSeek API Key", False, "未配置，请在设置中添加"))

    # 2. DeepSeek API 连接测试
    if api_key:
        success, msg = test_deepseek_api(api_key)
        results.append(("DeepSeek API", success, msg))
    else:
        results.append(("DeepSeek API", False, "跳过（无 API Key）"))

    # 3. DashScope ASR API 测试
    dashscope_key = os.environ.get('DASHSCOPE_API_KEY', '')
    if not dashscope_key:
        # 尝试从 .env 文件读取
        env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('DASHSCOPE_API_KEY='):
                        dashscope_key = line.split('=', 1)[1].strip().strip('"\'')
                        break

    if dashscope_key:
        success, msg = test_dashscope_asr(dashscope_key)
        results.append(("DashScope ASR", success, msg))
    else:
        results.append(("DashScope ASR", False, "未配置 DASHSCOPE_API_KEY"))

    # 4. 硬件检测（远程模式）
    success, msg = test_hardware()
    results.append(("本地硬件", success, msg))

    # 5. FFmpeg 测试
    success, msg = test_ffmpeg()
    results.append(("FFmpeg", success, msg))

    return results
