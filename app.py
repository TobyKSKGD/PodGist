import streamlit as st
import os
import base64
import time
import shutil
import re
from backend.transcriber import get_available_devices, get_whisper_model, transcribe_audio_to_timestamped_text
from backend.llm_agent import get_podcast_summary, search_in_podcast
from backend.downloader import AudioDownloader

# ================= 1. 页面配置 =================
st.set_page_config(page_title="PodGist | 播客提炼器", page_icon="🎙️", layout="wide")

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

def sanitize_filename(name):
    """
    清理文件名，移除无效字符。

    参数:
        name (str): 原始文件名

    返回:
        str: 清理后的安全文件名
    """
    return re.sub(r'[\\/*?:"<>|]', "", name).strip()

def archive_task(podcast_text, summary):
    """
    将播客转录文本和摘要归档到本地目录。

    参数:
        podcast_text (str): 带时间戳的播客转录文本
        summary (str): AI 生成的播客摘要

    说明:
        创建按时间戳命名的归档目录，保存原始文本和 Markdown 格式摘要。
    """
    lines = summary.strip().split('\n')
    ai_title = sanitize_filename(lines[0])
    if not ai_title: ai_title = "未命名播客摘要"

    timestamp = time.strftime("%Y%m%d_%H%M")
    folder_name = f"{timestamp}_{ai_title}"
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


def process_audio_file(audio_file_path, raw_text_file, api_key, selected_model, selected_device_key, selected_device_name, progress_start=0, cleanup_after=False):
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
        raw_summary = get_podcast_summary(api_key, st.session_state.podcast_text)
        archive_task(st.session_state.podcast_text, raw_summary)

        archive_folders = get_archive_list()
        latest_archive_path = os.path.join(ARCHIVE_DIR, archive_folders[0])
        with open(os.path.join(latest_archive_path, "summary.md"), "r", encoding="utf-8") as f:
            st.session_state.summary = f.read()

        # 如果是下载的音频，处理完成后删除
        if cleanup_after and os.path.exists(audio_file_path):
            try:
                os.remove(audio_file_path)
            except Exception:
                pass

        progress_bar.progress(100)
        status_text.success("🎉 处理完成！数据已智能命名并安全归档。")

    except Exception as e:
        status_text.error(f"❌ 大模型调用失败: {e}")


# ================= 3. 会话状态管理 =================
if "podcast_text" not in st.session_state: st.session_state.podcast_text = ""
if "summary" not in st.session_state: st.session_state.summary = ""

# ================= 4. 侧边栏界面 =================
st.markdown("<h1 style='text-align: center;'>🎙️ PodGist 播客知识库</h1>", unsafe_allow_html=True)
st.markdown("<p style='text-align: center;'>上传播客提取精华，或从左侧历史归档中唤醒记忆，支持 AI 精准定位。</p>", unsafe_allow_html=True)
st.divider()

with st.sidebar:
    st.header("⚙️ 核心设置")
    api_key = st.text_input("DeepSeek API Key", value=load_api_key(), type="password")
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

        根据用户选择的归档目录，加载对应的播客转录文本和摘要到会话状态。
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

    selected_archive = st.selectbox("选择往期播客查看", archive_list, key="history_selector", on_change=on_history_change)
    
    if selected_archive != "-- 新建提炼任务 --":
        if st.button("🗑️ 删除此归档", type="primary", use_container_width=True):
            shutil.rmtree(os.path.join(ARCHIVE_DIR, selected_archive))
            st.session_state.podcast_text = ""
            st.session_state.summary = ""
            st.rerun()

    st.divider()

    st.subheader("🛠️ 转录引擎设置")
    available_devices = get_available_devices()
    device_options = list(available_devices.values())
    device_keys = list(available_devices.keys())

    best_device_index = 0
    if "cuda" in device_keys: best_device_index = device_keys.index("cuda")
    elif "mps" in device_keys: best_device_index = device_keys.index("mps")

    selected_model = st.selectbox("1. 模型规模", ["tiny", "base", "small", "medium", "large-v3"], index=2)
    selected_device_name = st.selectbox("2. 算力硬件", device_options, index=best_device_index)
    selected_device_key = device_keys[device_options.index(selected_device_name)]

# ================= 5. 文件处理逻辑 =================
if selected_archive == "-- 新建提炼任务 --":
    # 创建标签页：本地文件 vs 在线链接
    tab_local, tab_online = st.tabs(["📂 本地文件上传", "🌐 在线链接解析（Bilibili）"])

    with tab_local:
        uploaded_file = st.file_uploader("请拖拽一个 .mp3 播客文件", type=['mp3'], key="local_uploader")

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
                    progress_start=0
                )
        elif uploaded_file is None:
            st.info("请拖拽上传音频文件")

    with tab_online:
        st.markdown("支持 Bilibili 视频链接，自动提取音频并生成摘要")
        bilibili_url = st.text_input("粘贴 Bilibili 视频链接", placeholder="https://www.bilibili.com/video/BV...", key="bilibili_url")

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
                                cleanup_after=True
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
    st.subheader("🔍 AI 模糊定位器 (当前播客)")
    search_query = st.text_input("向本期播客提问：")
    
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