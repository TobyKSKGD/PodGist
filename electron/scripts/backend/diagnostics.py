"""
系统诊断模块 - 测试所有组件是否正常工作

包含以下测试：
- API Key 检查
- DeepSeek API 连接测试
- PyTorch/硬件检测
- Whisper 模型加载测试
- SenseVoice 模型加载测试
- FFmpeg 安装检查
"""

import os
import subprocess
import torch


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
        # 发送最简单的测试消息
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


def test_hardware():
    """
    检测 PyTorch 硬件可用性。

    返回:
        tuple: (成功与否, 硬件状态消息)
    """
    hw_status = []
    if torch.cuda.is_available():
        hw_status.append("CUDA 可用")
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        hw_status.append("MPS 可用")
    if not hw_status:
        hw_status.append("仅 CPU")

    return True, ", ".join(hw_status)


def test_whisper_model():
    """
    测试 Whisper 模型加载是否正常。

    返回:
        tuple: (成功与否, 消息/错误信息)
    """
    try:
        import whisper
        # 使用最小模型测试加载
        model = whisper.load_model("tiny", device="cpu")
        return True, "tiny 模型加载成功"
    except Exception as e:
        return False, f"加载失败: {str(e)[:50]}"


def test_sensevoice_model():
    """
    测试 SenseVoice 模型加载是否正常。

    返回:
        tuple: (成功与否, 消息/错误信息)
    """
    try:
        from modelscope.pipelines import pipeline
        from modelscope.utils.constant import Tasks
        # 只测试 pipeline 创建，不实际处理音频
        pipeline(
            Tasks.auto_speech_recognition,
            model="iic/SenseVoiceSmall",
            device="cpu"
        )
        return True, "pipeline 初始化成功"
    except ImportError as e:
        return False, f"缺少依赖: {str(e)[:50]}"
    except Exception as e:
        return False, f"加载失败: {str(e)[:50]}"


def test_ffmpeg():
    """
    测试 FFmpeg 是否已安装。

    返回:
        tuple: (成功与否, 消息/错误信息)
    """
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            # 提取版本号
            version_line = result.stdout.split("\n")[0]
            return True, version_line
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
        api_key (str, optional): API Key，如果未提供则从文件读取
        api_key_file (str): API Key 文件路径

    返回:
        list: 诊断结果列表，每项为 (名称, 成功与否, 消息) 元组
    """
    results = []

    # 1. API Key 检查
    if api_key is None:
        api_key = ""
        if os.path.exists(api_key_file):
            with open(api_key_file, "r", encoding="utf-8") as f:
                api_key = f.read().strip()

    if api_key:
        results.append(("API Key", True, "已配置"))
    else:
        results.append(("API Key", False, "未配置，请在上方输入"))

    # 2. DeepSeek API 测试
    if api_key:
        success, msg = test_deepseek_api(api_key)
        results.append(("DeepSeek API", success, msg))
    else:
        results.append(("DeepSeek API", False, "跳过（无 API Key）"))

    # 3. PyTorch/硬件检测
    success, msg = test_hardware()
    results.append(("硬件", success, msg))

    # 4. Whisper 测试
    success, msg = test_whisper_model()
    results.append(("Whisper", success, msg))

    # 5. SenseVoice 测试
    success, msg = test_sensevoice_model()
    results.append(("SenseVoice", success, msg))

    # 6. FFmpeg 测试
    success, msg = test_ffmpeg()
    results.append(("FFmpeg", success, msg))

    return results
