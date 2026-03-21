import streamlit as st
import os
import base64
import time
import shutil
import re
from backend.transcriber import get_available_devices, get_whisper_model, transcribe_audio_to_timestamped_text
from backend.llm_agent import get_podcast_summary_robust, get_podcast_summary, search_in_podcast
from backend.diagnostics import run_all_diagnostics
from backend.downloader import AudioDownloader

# ================= 1. 页面配置 =================
st.set_page_config(page_title="PodGist | 音频提炼器", page_icon="🎙️", layout="wide")

hide_st_style = """
            <style>
            #MainMenu {visibility: hidden;}
            footer {visibility: hidden;}
            .stAppDeployButton {display: none !important; visibility: hidden !important;}
            [data-testid="stAppDeployButton"] {display: none !important; visibility: hidden !important;}
            .stDeployButton {display: none !important;}
            [data-testid="stHeader"] {background: transparent !important;} 
            </style>
            """
st.markdown(hide_st_style, unsafe_allow_html=True)

# ================= 2. 持久化存储 =================
API_KEY_FILE = ".env"
ARCHIVE_DIR = "archives"
TEMP_DIR = "temp_audio"
os.makedirs(ARCHIVE_DIR, exist_ok=True)
os.makedirs(TEMP_DIR, exist_ok=True)

def load_api_key():
    """
    从本地文件加载 API 密钥。

    返回:
        str: API 密钥字符串，若文件不存在则返回空字符串
    """
    if os.path.exists(API_KEY_FILE):
        with open(API_KEY_FILE, "r", encoding="utf-8") as f: return f.read().strip()
    return ""

def save_api_key(key):
    """
    将 API 密钥保存到本地文件。

    参数:
        key (str): API 密钥字符串
    """
    with open(API_KEY_FILE, "w", encoding="utf-8") as f: f.write(key.strip())

def sanitize_filename(name, max_length=50):
    """
    清理文件名，移除无效字符，并限制长度。

    参数:
        name (str): 原始文件名
        max_length (int): 最大长度限制，默认为50

    返回:
        str: 清理后的安全文件名
    """
    # 移除无效字符
    name = re.sub(r'[\\/*?:"<>|]', "", name).strip()

    # 分离文件名和扩展名
    if '.' in name:
        # 找到最后一个点（扩展名分隔符）
        last_dot = name.rfind('.')
        base_name = name[:last_dot]
        extension = name[last_dot:]  # 包含点
    else:
        base_name = name
        extension = ""

    # 限制长度，保留扩展名
    if len(base_name) > max_length - len(extension):
        base_name = base_name[:max_length - len(extension)]

    return base_name + extension

def archive_task(podcast_text, summary, original_name):
    """
    将音频转录文本和摘要归档到本地目录。

    参数:
        podcast_text (str): 带时间戳的音频转录文本
        summary (str): AI 生成的音频摘要
        original_name (str): 原始文件名或视频标题

    说明:
        创建按时间戳命名的归档目录，保存原始文本和 Markdown 格式摘要。
    """
    lines = summary.strip().split('\n')
    ai_title = sanitize_filename(lines[0])
    if not ai_title: ai_title = "未命名音频摘要"

    # 使用原始文件名
    safe_original_name = sanitize_filename(original_name)
    if not safe_original_name: safe_original_name = "未命名音频"

    timestamp = time.strftime("%Y%m%d_%H%M")
    folder_name = f"{timestamp}_{safe_original_name}"
    folder_path = os.path.join(ARCHIVE_DIR, folder_name)

    os.makedirs(folder_path, exist_ok=True)
    clean_summary = "\n".join(lines[1:]).strip()

    with open(os.path.join(folder_path, "raw.txt"), "w", encoding="utf-8") as f:
        f.write(podcast_text)
    with open(os.path.join(folder_path, "summary.md"), "w", encoding="utf-8") as f:
        f.write(f"# 🎙️ {ai_title}\n\n{clean_summary}")

def cleanup_temp_files(keep_files=None):
    """
    清理临时音频文件目录，保留指定文件。

    参数:
        keep_files (list, optional): 需要保留的文件名列表，默认为空列表
    """
    if keep_files is None:
        keep_files = []
    for filename in os.listdir(TEMP_DIR):
        if filename in keep_files:
            continue
        file_path = os.path.join(TEMP_DIR, filename)
        try:
            if os.path.isfile(file_path):
                os.remove(file_path)
        except Exception:
            pass


# ================= 大模型失败状态持久化 =================
import json

LLM_FAILED_STATE_FILE = os.path.join(TEMP_DIR, ".llm_failed_state.json")

def save_llm_failed_state(original_name, raw_file_path):
    """保存大模型调用失败状态到文件"""
    import time
    state = {
        "original_name": original_name,
        "raw_file_path": raw_file_path,
        "timestamp": time.time()
    }
    with open(LLM_FAILED_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)

def load_llm_failed_state():
    """从文件加载大模型调用失败状态，返回 None 如果不存在或已过期"""
    import time
    if not os.path.exists(LLM_FAILED_STATE_FILE):
        return None
    try:
        with open(LLM_FAILED_STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
        # 检查是否在 24 小时内
        if time.time() - state.get("timestamp", 0) > 24 * 60 * 60:
            # 超过 24 小时，删除文件
            os.remove(LLM_FAILED_STATE_FILE)
            return None
        return state
    except Exception:
        return None

def clear_llm_failed_state():
    """清除大模型调用失败状态"""
    if os.path.exists(LLM_FAILED_STATE_FILE):
        try:
            os.remove(LLM_FAILED_STATE_FILE)
        except Exception:
            pass


def get_archive_list():
    """
    获取归档目录列表，自动过滤系统垃圾文件。

    返回:
        list: 过滤后的归档目录列表（按时间倒序）
    """
    # 系统垃圾文件过滤列表
    system_junk_files = {
        '.DS_Store',      # macOS
        'Thumbs.db',      # Windows
        'desktop.ini',    # Windows
        '.Trash',         # Linux/macOS
        '.localized',     # macOS
        '._.DS_Store',    # macOS 额外
    }

    try:
        folders = os.listdir(ARCHIVE_DIR)
        # 过滤掉系统垃圾文件和目录
        folders = [f for f in folders if f not in system_junk_files and not f.startswith('.')]
        return sorted(folders, reverse=True)
    except Exception:
        return []


def process_audio_file(audio_file_path, raw_text_file, api_key, selected_model, selected_device_key, selected_device_name, progress_start=0, cleanup_after=False, original_name="", use_sensevoice=False):
    """
    统一的音频文件处理函数。

    参数:
        audio_file_path: 音频文件路径
        raw_text_file: 缓存的原始文本文件路径
        api_key: API 密钥
        selected_model: Whisper 模型规模
        selected_device_key: 设备标识符
        selected_device_name: 设备名称
        progress_start: 进度条起始值
        cleanup_after: 处理完成后是否删除音频文件
        original_name: 原始文件名或视频标题
        use_sensevoice: 是否使用 SenseVoice
    """
    status_text = st.empty()
    progress_bar = st.progress(progress_start)

    # 检查是否有缓存的转录结果
    if os.path.exists(raw_text_file):
        status_text.info(f"📂 发现本地暂存，瞬间读取中...")
        progress_bar.progress(50)
        with open(raw_text_file, "r", encoding="utf-8") as f:
            st.session_state.podcast_text = f.read()
    else:
        if use_sensevoice:
            # SenseVoice 转录模式
            status_text.warning(f"⚡ 正在加载 SenseVoice 模型...")

            from backend.transcriber import get_sensevoice_model, transcribe_with_sensevoice

            loading_gif = st.empty()
            gif_path = os.path.join("assets", "dino.gif")
            if os.path.exists(gif_path):
                with open(gif_path, "rb") as f: gif_base64 = base64.b64encode(f.read()).decode("utf-8")
                loading_gif.markdown(
                    f"""<div style="display: flex; flex-direction: column; align-items: center; justify-content: center; margin: 20px 0;">
                        <img src="data:image/gif;base64,{gif_base64}" width="200" style="border-radius: 10px;">
                        <p style="text-align: center; color: #888; font-size: 14px; margin-top: 10px;">SenseVoice 转录中，极速处理中...</p>
                    </div>""", unsafe_allow_html=True)
            else:
                loading_gif.info("⚡ SenseVoice 转录中...")

            try:
                st.session_state.podcast_text = transcribe_with_sensevoice(
                    audio_file_path, selected_device_key
                )
                loading_gif.empty()

                with open(raw_text_file, "w", encoding="utf-8") as f:
                    f.write(st.session_state.podcast_text)
                progress_bar.progress(50 + progress_start)
            except Exception as e:
                status_text.error(f"❌ SenseVoice 转录失败！报错: {e}")
                st.stop()
        else:
            # Whisper 转录模式
            status_text.warning(f"🤖 正在准备 Whisper [{selected_model}] 模型...")
            @st.cache_resource
            def load_model_cached(model_name, device):
                """
                缓存 Whisper 模型加载结果，避免重复加载。
                """
                return get_whisper_model(model_name, device)

            try:
                model = load_model_cached(selected_model, selected_device_key)
                progress_bar.progress(20 + progress_start)
                status_text.warning(f"👂 转录引擎轰鸣中！算力节点: 【{selected_device_name}】")

                loading_gif = st.empty()
                gif_path = os.path.join("assets", "dino.gif")
                if os.path.exists(gif_path):
                    with open(gif_path, "rb") as f: gif_base64 = base64.b64encode(f.read()).decode("utf-8")
                    loading_gif.markdown(
                        f"""<div style="display: flex; flex-direction: column; align-items: center; justify-content: center; margin: 20px 0;">
                            <img src="data:image/gif;base64,{gif_base64}" width="200" style="border-radius: 10px;">
                            <p style="text-align: center; color: #888; font-size: 14px; margin-top: 10px;">底层狂奔转录中，请先喝杯水...</p>
                        </div>""", unsafe_allow_html=True)
                else:
                    loading_gif.info("🦖 引擎轰鸣转录中...")

                st.session_state.podcast_text = transcribe_audio_to_timestamped_text(
                    model, audio_file_path, selected_device_key
                )
                loading_gif.empty()

                with open(raw_text_file, "w", encoding="utf-8") as f:
                    f.write(st.session_state.podcast_text)
                progress_bar.progress(50 + progress_start)
            except Exception as e:
                status_text.error(f"❌ 转录失败！报错: {e}")
                st.stop()

    status_text.info("🧠 正在呼叫 DeepSeek 提炼高光时间轴并智能命名...")
    progress_bar.progress(70)

    try:
        raw_summary = get_podcast_summary_robust(api_key, st.session_state.podcast_text, max_timeline_items)
        archive_task(st.session_state.podcast_text, raw_summary, original_name)

        archive_folders = get_archive_list()
        latest_archive_path = os.path.join(ARCHIVE_DIR, archive_folders[0])
        with open(os.path.join(latest_archive_path, "summary.md"), "r", encoding="utf-8") as f:
            st.session_state.summary = f.read()

        # 清理临时文件
        if os.path.exists(audio_file_path):
            try:
                os.remove(audio_file_path)
            except Exception:
                pass
        # 同时清理缓存的 raw.txt 文件
        if os.path.exists(raw_text_file):
            try:
                os.remove(raw_text_file)
            except Exception:
                pass

        progress_bar.progress(100)
        status_text.success("🎉 处理完成！数据已智能命名并安全归档。")

        # 自动选中刚生成的归档
        if archive_folders:
            st.session_state.history_selector = archive_folders[0]

        # 刷新页面以显示新归档
        st.rerun()

    except Exception as e:
        status_text.error(f"❌ 大模型调用失败: {e}")
        # 保存到 session_state
        st.session_state.llm_failed = True
        st.session_state.llm_failed_original_name = original_name
        raw_file_for_state = ""
        if 'raw_text_file' in locals():
            st.session_state.llm_failed_raw_file = raw_text_file
            raw_file_for_state = raw_text_file
        # 保存当前转录文本
        st.session_state.llm_failed_podcast_text = st.session_state.podcast_text
        # 持久化保存到文件（防止刷新页面丢失）
        save_llm_failed_state(original_name, raw_file_for_state)


# ================= 3. 会话状态管理 =================
if "podcast_text" not in st.session_state: st.session_state.podcast_text = ""
if "summary" not in st.session_state: st.session_state.summary = ""
if "history_selector" not in st.session_state: st.session_state.history_selector = "-- 新建提炼任务 --"
if "llm_failed" not in st.session_state: st.session_state.llm_failed = False

# ================= 大模型重试处理（会话状态初始化后立即检查） =================
# 检查是否有持久化的失败状态（页面刷新后也能恢复）
saved_state = load_llm_failed_state()
if saved_state:
    st.session_state.llm_failed = True
    st.session_state.llm_failed_original_name = saved_state.get("original_name", "未命名")
    st.session_state.llm_failed_raw_file = saved_state.get("raw_file_path", "")

# ================= 4. 侧边栏界面 =================
st.markdown("<h1 style='text-align: center;'>🎙️ PodGist</h1>", unsafe_allow_html=True)
st.markdown("<p style='text-align: center;'>上传音频提取精华，或从左侧历史归档中唤醒记忆，支持 AI 精准定位。</p>", unsafe_allow_html=True)
st.divider()

with st.sidebar:
    st.header("⚙️ 核心设置")
    api_key = st.text_input(
        "DeepSeek API Key",
        value=load_api_key(),
        type="password",
        help="DeepSeek API Key，用于调用大模型生成摘要。可在 https://platform.deepseek.com 获取。"
    )
    if st.button("💾 保存 Key", use_container_width=True):
        if api_key:
            save_api_key(api_key)
            st.success("✅ 已保存")
        else:
            st.warning("⚠️ 请输入 Key")
    
    st.divider()

    st.header("🗂️ 历史归档")
    archive_list = ["-- 新建提炼任务 --"] + get_archive_list()

    def on_history_change():
        """
        历史归档选择变更回调函数。

        根据用户选择的归档目录，加载对应的音频转录文本和摘要到会话状态。
        """
        selected = st.session_state.history_selector
        if selected != "-- 新建提炼任务 --":
            folder_path = os.path.join(ARCHIVE_DIR, selected)
            try:
                with open(os.path.join(folder_path, "raw.txt"), "r", encoding="utf-8") as f:
                    st.session_state.podcast_text = f.read()
                with open(os.path.join(folder_path, "summary.md"), "r", encoding="utf-8") as f:
                    st.session_state.summary = f.read()
            except:
                st.session_state.podcast_text = "读取原始文本失败。"
                st.session_state.summary = "读取摘要失败。"
        else:
            st.session_state.podcast_text = ""
            st.session_state.summary = ""

    selected_archive = st.selectbox(
        "选择往期音频查看",
        archive_list,
        key="history_selector",
        on_change=on_history_change,
        help="选择已保存的音频归档查看，或选择「新建提炼任务」开始处理新音频。"
    )

    if selected_archive != "-- 新建提炼任务 --":
        if st.button("🗑️ 删除此归档", type="primary", use_container_width=True):
            shutil.rmtree(os.path.join(ARCHIVE_DIR, selected_archive))
            st.session_state.podcast_text = ""
            st.session_state.summary = ""
            st.rerun()

    st.divider()

    st.subheader("🛠️ 转录引擎设置")

    # 选择转录引擎
    transcription_engine = st.radio(
        "选择转录引擎",
        ["⚡ SenseVoice (极速模式)", "🐢 Whisper (高精度时间戳)"],
        horizontal=True,
        index=0,
        help="SenseVoice：阿里开源模型，转录速度极快，适合大多数场景。\n\nWhisper：OpenAI 模型，精度更高，但速度较慢。"
    )

    use_sensevoice = "SenseVoice" in transcription_engine

    available_devices = get_available_devices()
    device_options = list(available_devices.values())
    device_keys = list(available_devices.keys())

    best_device_index = 0
    if "cuda" in device_keys: best_device_index = device_keys.index("cuda")
    elif "mps" in device_keys: best_device_index = device_keys.index("mps")

    # Whisper 模式：显示模型规模选择；SenseVoice 模式：隐藏
    if use_sensevoice:
        st.caption("SenseVoice 使用 Small 版本，无需选择模型规模")
        selected_model = "sensevoice-small"
    else:
        selected_model = st.selectbox(
            "1. 模型规模",
            ["tiny", "base", "small", "medium", "large-v3"],
            index=2,
            help="选择 Whisper 模型规模。\n\ntiny/base：速度快，精度较低。\n\nsmall/medium：平衡选择，推荐 small。\n\nlarge-v3：精度最高，但需要更多显存。"
        )

    selected_device_name = st.selectbox(
        "2. 算力硬件",
        device_options,
        index=best_device_index,
        help="选择用于转录的计算设备。\n\nApple Silicon (MPS)：Mac M系列芯片专用加速，推荐 Mac 用户使用。\n\nGPU (CUDA)：NVIDIA 显卡加速。\n\nCPU：使用处理器计算，速度较慢。"
    )
    selected_device_key = device_keys[device_options.index(selected_device_name)]

    # 输出条数配置
    timeline_options = [8, 10, 15, 20, 25]
    default_index = 2
    # 如果之前有设置，使用之前的设置
    if "max_timeline_items" in st.session_state and st.session_state.max_timeline_items in timeline_options:
        default_index = timeline_options.index(st.session_state.max_timeline_items)

    max_timeline_items = st.selectbox(
        "3. 时间轴上限",
        timeline_options,
        index=default_index,
        help="AI 生成的时间轴最多不超过此条数。数量越少，生成速度越快、越稳定。"
    )
    # 保存用户设置到 session_state
    st.session_state.max_timeline_items = max_timeline_items

    # ================= 诊断区域（侧边栏底部） =================
    st.divider()
    st.header("🩺 系统诊断")

    # 初始化诊断结果存储
    if "diagnostic_results" not in st.session_state:
        st.session_state.diagnostic_results = None

    # 诊断按钮
    if st.button("🔍 一键诊断所有组件", use_container_width=True):
        with st.spinner("正在诊断..."):
            api_key = load_api_key()
            results = run_all_diagnostics(api_key)
            st.session_state.diagnostic_results = results

    # 显示诊断结果
    if st.session_state.diagnostic_results is not None:
        results = st.session_state.diagnostic_results

        all_passed = all(r[1] for r in results)

        if all_passed:
            st.success("✅ 全部通过！可以开始处理音频。")
        else:
            st.error("⚠️ 部分组件存在问题，请检查以下项目：")

        for name, success, msg in results:
            if success:
                st.write(f"✅ **{name}**: {msg}")
            else:
                st.write(f"❌ **{name}**: {msg}")

        # 添加重新诊断按钮
        if st.button("🔄 重新诊断", use_container_width=True):
            st.session_state.diagnostic_results = None
            st.rerun()
    else:
        st.caption("点击上方按钮测试所有组件是否正常")

# ================= 5. 文件处理逻辑 =================
if selected_archive == "-- 新建提炼任务 --":
    # 创建标签页：本地文件 vs 播客直连 vs 视频剥离
    tab_local, tab_podcast, tab_video = st.tabs(["📂 本地提炼", "🎧 播客直连", "📺 视频剥离"])

    with tab_local:
        uploaded_file = st.file_uploader("请拖拽一个 .mp3 音频文件", type=['mp3'], key="local_uploader")

        if uploaded_file is not None and api_key:
            # 先清理 temp_audio 目录
            cleanup_temp_files()

            current_audio_name = f"temp_{uploaded_file.name}"
            current_raw_name = current_audio_name.replace(".mp3", f"_{selected_model}_raw.txt")

            audio_file_path = os.path.join(TEMP_DIR, current_audio_name)
            raw_text_file = os.path.join(TEMP_DIR, current_raw_name)

            with open(audio_file_path, "wb") as f:
                f.write(uploaded_file.getbuffer())

            if st.button("🚀 开始提炼并打上时间戳", use_container_width=True, key="local_process"):
                process_audio_file(
                    audio_file_path=audio_file_path,
                    raw_text_file=raw_text_file,
                    api_key=api_key,
                    selected_model=selected_model,
                    selected_device_key=selected_device_key,
                    selected_device_name=selected_device_name,
                    progress_start=0,
                    original_name=uploaded_file.name,
                    use_sensevoice=use_sensevoice
                )
        elif uploaded_file is None:
            st.info("请拖拽上传音频文件")

    with tab_podcast:
        # 平台支持状态
        st.markdown("**平台支持状态：**")
        col1, col2 = st.columns(2)
        with col1:
            st.success("✅ 已支持：小宇宙")
        with col2:
            st.info("⏳ 规划中：苹果播客、网易云音乐、喜马拉雅")

        # 操作引导
        with st.expander("💡 如何获取小宇宙链接？", expanded=False):
            st.markdown("""
            1. 打开手机【小宇宙 App】
            2. 选择要下载的播客单集
            3. 点击右上角或底部的【分享】按钮
            4. 选择【复制链接】
            5. 发送到电脑并粘贴到下方输入框

            链接格式通常包含：`xiaoyuzhoufm.com/episode/...`
            """)

        # 输入框
        podcast_url = st.text_input("🔗 请粘贴播客单集链接", placeholder="https://xiaoyuzhoufm.com/episode/xxx", key="podcast_url")

        if podcast_url and api_key:
            if st.button("⚡ 解析并提取音频", use_container_width=True, key="podcast_process"):
                # 先清理 temp_audio 目录
                cleanup_temp_files()

                with st.spinner("🔗 正在连接小宇宙服务器提取音频..."):
                    try:
                        from backend.downloader import download_xiaoyuzhou_audio
                        download_result = download_xiaoyuzhou_audio(podcast_url, TEMP_DIR)

                        if download_result['success']:
                            audio_file_path = download_result['file_path']
                            podcast_title = download_result['title']
                            st.success(f"✅ 音频提取成功: {podcast_title}")

                            # 使用标题创建临时文件名
                            current_audio_name = f"temp_{podcast_title}.mp3"
                            current_raw_name = current_audio_name.replace(".mp3", f"_{selected_model}_raw.txt")

                            # 继续转录流程
                            process_audio_file(
                                audio_file_path=audio_file_path,
                                raw_text_file=os.path.join(TEMP_DIR, current_raw_name),
                                api_key=api_key,
                                selected_model=selected_model,
                                selected_device_key=selected_device_key,
                                selected_device_name=selected_device_name,
                                progress_start=0,
                                cleanup_after=True,
                                original_name=podcast_title,
                                use_sensevoice=use_sensevoice
                            )
                        else:
                            st.error(f"❌ 下载失败: {download_result['error']}")
                    except Exception as e:
                        st.error(f"❌ 解析失败: {str(e)}")
        elif podcast_url and not api_key:
            st.warning("请先在左侧填写 API Key")
        else:
            st.info("请粘贴小宇宙播客单集链接")

    with tab_video:
        st.markdown("支持 Bilibili 视频链接，自动提取音频并生成摘要")
        bilibili_url = st.text_input("🔗 请粘贴 B站视频链接", placeholder="https://www.bilibili.com/video/BV...", key="bilibili_url")

        if bilibili_url and api_key:
            if st.button("⚡ 解析并提取音频", use_container_width=True, key="bilibili_process"):
                # 先清理 temp_audio 目录
                cleanup_temp_files()

                with st.spinner("🔗 正在连接 B 站服务器提取音频..."):
                    try:
                        # 初始化下载器
                        downloader = AudioDownloader(save_dir=TEMP_DIR)

                        # 下载音频
                        download_result = downloader.download_bilibili_audio(bilibili_url)

                        if download_result['success']:
                            audio_file_path = download_result['file_path']
                            video_title = download_result['title']
                            st.success(f"✅ 音频提取成功: {video_title}")

                            # 使用视频标题创建临时文件名
                            current_audio_name = f"temp_{video_title}.mp3"
                            current_raw_name = current_audio_name.replace(".mp3", f"_{selected_model}_raw.txt")

                            # 继续转录流程
                            process_audio_file(
                                audio_file_path=audio_file_path,
                                raw_text_file=os.path.join(TEMP_DIR, current_raw_name),
                                api_key=api_key,
                                selected_model=selected_model,
                                selected_device_key=selected_device_key,
                                selected_device_name=selected_device_name,
                                progress_start=0,
                                cleanup_after=True,
                                original_name=video_title,
                                use_sensevoice=use_sensevoice
                            )
                        else:
                            st.error(f"❌ 下载失败: {download_result['error']}")
                    except Exception as e:
                        st.error(f"❌ 解析失败: {str(e)}")
        elif bilibili_url and not api_key:
            st.warning("请先在左侧填写 API Key")
        else:
            st.info("请粘贴 Bilibili 视频链接")

    # 如果用户没有填写 API Key，给出提示
    if not api_key:
        st.warning("👈 请在左侧填写 DeepSeek API Key 后再操作")

if "llm_failed" in st.session_state and st.session_state.get("llm_failed"):
    st.divider()
    st.error("⚠️ 大模型调用失败，您可以点击下方按钮重试（使用已有的转录稿，无需重新转录）")

    # 从 session_state 或持久化文件中获取信息
    raw_text_file = st.session_state.get("llm_failed_raw_file", "")
    original_name = st.session_state.get("llm_failed_original_name", "未命名")

    # 列出可用的 temp 文件供选择
    st.caption("📁 当前可用的转录稿文件：")
    temp_files = []
    if os.path.exists(TEMP_DIR):
        for f in os.listdir(TEMP_DIR):
            if f.endswith("_raw.txt"):
                st.write(f"  - {f}")
                temp_files.append(f)

    col1, col2 = st.columns([1, 3])
    with col1:
        selected_file = st.selectbox("选择转录稿文件", temp_files if temp_files else [raw_text_file], key="retry_file_select")

        if st.button("🔄 重试调用大模型", type="primary", key="retry_llm"):
            if selected_file:
                # 读取文字稿
                retry_file_path = os.path.join(TEMP_DIR, selected_file)
                if os.path.exists(retry_file_path):
                    with open(retry_file_path, "r", encoding="utf-8") as f:
                        podcast_text = f.read()

                    with st.spinner("🔄 正在重新调用大模型..."):
                        try:
                            # 使用默认值15，或者从 session_state 获取之前设置的值
                            retry_max_items = st.session_state.get("max_timeline_items", 15)
                            raw_summary = get_podcast_summary_robust(api_key, podcast_text, retry_max_items)
                            archive_task(podcast_text, raw_summary, original_name)

                            archive_folders = get_archive_list()
                            latest_archive_path = os.path.join(ARCHIVE_DIR, archive_folders[0])
                            with open(os.path.join(latest_archive_path, "summary.md"), "r", encoding="utf-8") as f:
                                st.session_state.summary = f.read()

                            # 清理临时文件
                            if os.path.exists(retry_file_path):
                                try:
                                    os.remove(retry_file_path)
                                except Exception:
                                    pass

                            # 清理其他 temp 文件
                            for f in os.listdir(TEMP_DIR):
                                if f.startswith("temp_"):
                                    try:
                                        os.remove(os.path.join(TEMP_DIR, f))
                                    except Exception:
                                        pass

                            # 清除失败状态（包括持久化文件）
                            clear_llm_failed_state()
                            st.session_state.llm_failed = False
                            st.session_state.pop("llm_failed_original_name", None)
                            st.session_state.pop("llm_failed_raw_file", None)
                            st.session_state.pop("llm_failed_podcast_text", None)

                            st.success("🎉 重试成功！")
                            st.rerun()
                        except Exception as retry_error:
                            st.error(f"❌ 重试仍然失败: {retry_error}")
                else:
                    st.warning("文件不存在")
            else:
                st.warning("没有可用的转录稿文件")
    with col2:
        if st.button("放弃重试，重新开始", key="giveup_retry"):
            # 清理所有临时文件
            for f in os.listdir(TEMP_DIR):
                if f.startswith("temp_"):
                    try:
                        os.remove(os.path.join(TEMP_DIR, f))
                    except Exception:
                        pass
            # 清除失败状态（包括持久化文件）
            clear_llm_failed_state()
            st.session_state.llm_failed = False
            st.session_state.pop("llm_failed_original_name", None)
            st.session_state.pop("llm_failed_raw_file", None)
            st.session_state.pop("llm_failed_podcast_text", None)
            st.rerun()

else:
    # 查看历史归档
    st.info(f"📂 正在查看历史归档：**{selected_archive}**")


# ================= 6. 结果展示与搜索 =================
if st.session_state.summary:
    st.divider()
    
    # 使用正则表达式将 [MM:SS] 格式时间戳替换为带样式的 HTML 元素
    styled_summary = re.sub(
        r'(\[\d{2}:\d{2}\])', 
        r'<span style="color: #2e7d32; background-color: #e8f5e9; font-weight: 700; padding: 2px 6px; border-radius: 5px; margin-right: 5px; box-shadow: 0px 1px 2px rgba(0,0,0,0.1);">\1</span>', 
        st.session_state.summary
    )
    
    st.markdown(styled_summary, unsafe_allow_html=True)
    
    st.download_button(
        label="⬇️ 下载当前 Markdown 报告",
        data=st.session_state.summary,  # 注：下载的文件为原始 Markdown 内容，不含 HTML 样式
        file_name="PodGist_Report.md",
        mime="text/markdown",
        use_container_width=True
    )
    
    st.divider()
    st.subheader("🔍 AI 模糊定位器 (当前音频)")
    search_query = st.text_input("向本期音频提问：")
    
    if st.button("精准搜索"):
        if search_query and api_key:
            with st.spinner("🧠 正在检索相关片段..."):
                try:
                    ans = search_in_podcast(api_key, search_query, st.session_state.podcast_text)
                    st.info(ans)
                except Exception as e:
                    st.error(f"搜索失败: {e}")
        else:
            st.warning("请确保输入了问题，并且已填写 API Key！")

