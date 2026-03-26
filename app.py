import streamlit as st
from PIL import Image
import os
import base64
import time
import shutil
import re
from backend.transcriber import get_available_devices, get_whisper_model, transcribe_audio_to_timestamped_text
from backend.llm_agent import get_podcast_summary_robust, get_podcast_summary, search_in_podcast
from backend.diagnostics import run_all_diagnostics
from backend.downloader import AudioDownloader
from backend import task_queue
from backend import worker

# 加载 Favicon 图片
favicon_path = os.path.join(os.path.dirname(__file__), "assets", "favicon.png")
if os.path.exists(favicon_path):
    fav_image = Image.open(favicon_path)
else:
    fav_image = "🎙️"  # 备用方案

# 极简成功 Checkmark (极光深色)
svg_icon_check = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="18px" height="18px" style="vertical-align: middle; margin-right: 6px;"><path d="M 9 16.17 L 4.83 12 L 3.41 13.41 L 9 19 L 21 7 L 19.59 5.59 Z" fill="#008080"/></svg>"""

# 极简失败/错误 Cross (极光亮色)
svg_icon_cross = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="18px" height="18px" style="vertical-align: middle; margin-right: 6px;"><path d="M 19 6.41 L 17.59 5 L 12 10.59 L 6.41 5 L 5 6.41 L 10.59 12 L 5 17.59 L 6.41 19 L 12 13.41 L 17.59 19 L 19 17.59 L 13.41 12 Z" fill="#00E5FF"/></svg>"""

# 极简提示 Info 图标 (高级石板灰)
svg_icon_info = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="18px" height="18px" style="vertical-align: middle; margin-right: 6px;"><path d="M 11 7 L 13 7 L 13 9 L 11 9 Z M 11 11 L 13 11 L 13 17 L 11 17 Z M 12 2 C 6.48 2 2 6.48 2 12 C 2 17.52 6.48 22 12 22 C 17.52 22 22 17.52 22 12 C 22 6.48 17.52 2 Z" fill="#64748B"/></svg>"""

# 辅助函数：渲染自定义成功/失败/提示消息
def render_success(msg):
    st.markdown(f'<div style="display: flex; align-items: center; border-radius: 6px; padding: 10px 15px; background-color: #F0FDFD; border: 1px solid #C4F1F1;">{svg_icon_check} <span style="color: #008080; font-weight: 500;">{msg}</span></div>', unsafe_allow_html=True)
    st.markdown("")

def render_error(msg):
    st.markdown(f'<div style="display: flex; align-items: center; border-radius: 6px; padding: 10px 15px; background-color: #ECFEFF; border: 1px solid #A5F3FC;">{svg_icon_cross} <span style="color: #0891B2; font-weight: 500;">{msg}</span></div>', unsafe_allow_html=True)
    st.markdown("")

def render_info(msg):
    st.markdown(f'<div style="display: flex; align-items: center; border-radius: 6px; padding: 10px 15px; background-color: #F8FAFC; border: 1px solid #E2E8F0; margin-bottom: 1rem;">{svg_icon_info} <span style="color: #475569; font-weight: 500;">{msg}</span></div>', unsafe_allow_html=True)

# ================= 1. 页面配置 =================
st.set_page_config(page_title="PodGist", page_icon=fav_image, layout="wide")

# ================= 启动时初始化 =================
# 初始化任务队列数据库
task_queue.init_db()
# 恢复僵尸任务（PROCESSING -> PENDING）
reset_count = task_queue.reset_processing_to_pending()
if reset_count > 0:
    print(f"[Init] 已恢复 {reset_count} 个僵尸任务")

# ================= 核心 UI 重构：细节修复版 (Notion 风格 + API Key对齐) =================
ui_refactor_css = """
<style>
    /* 1. 隐藏多余组件 (Deploy按钮、汉堡菜单、底部水印) */
    header {visibility: hidden;}
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    .stAppDeployButton {display: none !important;}

    /* 2. 压平侧边栏和 Expander 边框 */
    [data-testid="stSidebar"], [data-testid="stExpander"] {
        padding-top: 1rem;
        border: none !important; /* 彻底去掉 expander 的外描边 */
        box-shadow: none !important;
    }
    [data-testid="stSidebar"] {
        border-right: 1px solid #E2E8F0 !important;
    }

    /* 让 Expander 内部看起来更 flat */
    [data-testid="stExpander"] div[aria-expanded="true"] {
        background-color: transparent !important;
        padding-left: 0.5rem !important;
    }

    /* 3. 统一全局按钮极简扁平化 */
    .stButton>button {
        border-radius: 6px !important;
        border: 1px solid #E2E8F0 !important;
        background-color: #FFFFFF !important;
        color: #475569 !important;
        transition: all 0.2s ease;
        font-weight: 500;
        box-shadow: 0 1px 2px rgba(0,0,0,0.02);
    }
    .stButton>button:hover {
        border-color: #008080 !important;
        color: #008080 !important;
        background-color: #F0FDFD !important;
    }
    /* 主按钮样式 */
    .stButton>button[kind="primary"] {
        background-color: #008080 !important;
        border: none !important;
        color: white !important;
        box-shadow: 0 2px 4px rgba(0, 128, 128, 0.2);
    }

    /* 4. 【核心修复】：解决 API Key 输入框和眼睛对齐/描边问题 */
    /* Target: Password Input Container */
    [data-testid="stTextInputPassword"]>div>div {
        border-radius: 6px !important;
        border: 1px solid #CBD5E1 !important;
        background-color: #FFFFFF !important;
        overflow: hidden; /* 保证圆角 */
    }

    /* 让输入框本身无边框，高度占满 */
    [data-testid="stTextInputPassword"]>div>div>input {
        border: none !important;
        height: 100% !important;
        box-shadow: none !important;
    }

    /* 统一设置"眼睛"按钮的样式，确保和框对齐且长度一致 */
    [data-testid="stTextInputPassword"]>div>div>button {
        background-color: #F8FAFC !important;
        border-left: 1px solid #CBD5E1 !important; /* 加一条分割线把眼睛和框拉开 */
        border-right: none !important;
        border-top: none !important;
        border-bottom: none !important;
        border-radius: 0 !important;
        color: #475569 !important;
        padding: 0 12px !important;
        transition: all 0.2s ease;
    }
    [data-testid="stTextInputPassword"]>div>div>button:hover {
        color: #008080 !important;
        background-color: #F1F5F9 !important;
    }

    /* 弱化分割线颜色 */
    hr {
        margin: 1.5em 0;
        border-color: #F1F5F9 !important;
    }
</style>
"""
st.markdown(ui_refactor_css, unsafe_allow_html=True)

# ================= 2. 持久化存储 =================
API_KEY_FILE = ".env"
ARCHIVE_DIR = "archives"
TEMP_DIR = "temp_audio"
os.makedirs(ARCHIVE_DIR, exist_ok=True)
os.makedirs(TEMP_DIR, exist_ok=True)


# ================= 任务监控大屏（自动刷新） =================
@st.fragment(run_every=3)
def render_task_monitor():
    """
    任务监控大屏 - 每3秒自动刷新
    """
    st.divider()
    st.markdown("### 队列监控大屏")
    st.caption("已完成任务请到侧边栏「历史归档」查看")

    # 获取统计信息
    stats = task_queue.get_queue_stats()

    # 显示统计 (使用自定义 SVG 图标)
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        pending_count = stats.get("PENDING", 0)
        st.markdown(f'<div style="text-align: center; padding: 10px 0;"><div style="color: #94A3B8; font-size: 14px; margin-bottom: 4px;">等待</div><div style="color: #1E293B; font-size: 28px; font-weight: 600;">{pending_count}</div></div>', unsafe_allow_html=True)
    with col2:
        processing_count = stats.get("PROCESSING", 0)
        st.markdown(f'<div style="text-align: center; padding: 10px 0;"><div style="color: #008080; font-size: 14px; margin-bottom: 4px;">处理中</div><div style="color: #008080; font-size: 28px; font-weight: 600;">{processing_count}</div></div>', unsafe_allow_html=True)
    with col3:
        completed_count = stats.get("COMPLETED", 0)
        st.markdown(f'<div style="text-align: center; padding: 10px 0;"><div style="color: #008080; font-size: 14px; margin-bottom: 4px;">{svg_icon_check} 完成</div><div style="color: #008080; font-size: 28px; font-weight: 600;">{completed_count}</div></div>', unsafe_allow_html=True)
    with col4:
        failed_count = stats.get("FAILED", 0)
        st.markdown(f'<div style="text-align: center; padding: 10px 0;"><div style="color: #0891B2; font-size: 14px; margin-bottom: 4px;">{svg_icon_cross} 失败</div><div style="color: #0891B2; font-size: 28px; font-weight: 600;">{failed_count}</div></div>', unsafe_allow_html=True)

    # 获取所有任务
    all_tasks = task_queue.get_all_tasks()

    if not all_tasks:
        render_info("队列为空，请先添加任务")
        return

    # 显示任务列表
    st.markdown("#### 任务列表")

    if not all_tasks:
        st.info("队列为空")

    # 按状态排序：处理中 > 等待 > 失败 > 完成
    status_order = {"PROCESSING": 0, "PENDING": 1, "FAILED": 2, "COMPLETED": 3}
    sorted_tasks = sorted(all_tasks, key=lambda x: (status_order.get(x["status"], 99), x["create_time"]))

    for task in sorted_tasks:
        task_id = task["id"]
        source = task["source"]
        task_type = task["type"]
        status = task["status"]
        error_msg = task.get("error_msg", "")
        result_path = task.get("result_path", "")

        # 状态图标和颜色 (替换掉原来的空字符串)
        if status == "COMPLETED":
            icon = svg_icon_check
            color = "green"
        elif status == "PROCESSING":
            icon = """<span style="color:#008080; font-weight:900;">· 运行中</span>"""
            color = "blue"
        elif status == "FAILED":
            icon = svg_icon_cross
            color = "red"
        else:
            icon = """<span style="color:#CBD5E1; font-weight:500;">- 等待</span>"""
            color = "gray"

        # 任务类型图标
        if task_type == "xiaoyuzhou":
            type_icon = "播客"
        elif task_type == "bilibili":
            type_icon = "视频"
        elif task_type == "netease":
            type_icon = "网易云音乐"
        elif task_type == "ximalaya":
            type_icon = "喜马拉雅"
        elif task_type == "applepodcasts":
            type_icon = "苹果播客"
        elif task_type == "local":
            type_icon = "本地"
        else:
            type_icon = "未知"

        # 使用任务自带的名称
        name = task.get("name") or source
        if len(name) > 40:
            name = name[:40] + "..."

        # 获取进度状态
        progress_status = task.get("progress_status", "")

        # 显示任务行
        with st.container():
            col_icon, col_name, col_type, col_action = st.columns([1, 4, 1, 2])

            with col_icon:
                st.markdown(f"{icon}", unsafe_allow_html=True)

            with col_name:
                st.markdown(f"{name}")
                if progress_status:
                    st.caption(f"{progress_status}")
                if status == "FAILED" and error_msg:
                    st.caption(f"错误: {error_msg[:50]}...")

            with col_type:
                st.markdown(f"{type_icon}")

            with col_action:
                if status == "COMPLETED" and result_path:
                    # 归档名称
                    archive_name = os.path.basename(result_path)
                    if st.button("查看报告", key=f"view_{task_id}", use_container_width=True):
                        # 跳转到历史归档
                        st.session_state.just_finished_archive = archive_name
                        # 加载归档内容
                        folder_path = os.path.join(ARCHIVE_DIR, archive_name)
                        try:
                            with open(os.path.join(folder_path, "raw.txt"), "r", encoding="utf-8") as f:
                                st.session_state.podcast_text = f.read()
                            with open(os.path.join(folder_path, "summary.md"), "r", encoding="utf-8") as f:
                                st.session_state.summary = f.read()
                        except:
                            pass
                        st.rerun()

                elif status == "PENDING":
                    if st.button("删除", key=f"del_{task_id}", use_container_width=True):
                        task_queue.delete_task(task_id)
                        st.rerun()

                elif status == "FAILED":
                    if st.button("重试", key=f"retry_{task_id}", use_container_width=True):
                        # 重置为 PENDING
                        task_queue.update_task_status(task_id, "PENDING")
                        st.rerun()

    # ================= 已完成任务快速查看（循环外）====================
    completed_tasks = [t for t in task_queue.get_all_tasks() if t["status"] == "COMPLETED"]

    if completed_tasks:
        st.divider()
        st.markdown("#### 已完成任务快速查看")
        st.caption(f"共 {len(completed_tasks)} 个任务已完成")

        # 直接显示所有已完成任务
        for task in completed_tasks:
            task_name = task.get('name', '未命名')
            result_path = task.get("result_path", "")

            if result_path:
                summary_file = os.path.join(result_path, "summary.md")
                if os.path.exists(summary_file):
                    with open(summary_file, "r", encoding="utf-8") as f:
                        summary_content = f.read()

                    with st.expander(f"{task_name} (点击展开)"):
                        styled_summary = re.sub(
                            r'(\[\d+:\d{2}\])',
                            r'<span style="color: #2e7d32; background-color: #e8f5e9; font-weight: 700; padding: 2px 6px; border-radius: 5px; margin-right: 5px; box-shadow: 0px 1px 2px rgba(0,0,0,0.1);">\1</span>',
                            summary_content
                        )
                        st.markdown(styled_summary, unsafe_allow_html=True)

    st.divider()


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
        f.write(f"# {ai_title}\n\n{clean_summary}")

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
        status_text.info(f"发现本地暂存，瞬间读取中...")
        progress_bar.progress(50)
        with open(raw_text_file, "r", encoding="utf-8") as f:
            st.session_state.podcast_text = f.read()
    else:
        if use_sensevoice:
            # SenseVoice 转录模式
            status_text.warning(f"正在加载 SenseVoice 模型...")

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
                loading_gif.info("SenseVoice 转录中...")

            try:
                st.session_state.podcast_text = transcribe_with_sensevoice(
                    audio_file_path, selected_device_key
                )
                loading_gif.empty()

                with open(raw_text_file, "w", encoding="utf-8") as f:
                    f.write(st.session_state.podcast_text)
                progress_bar.progress(50 + progress_start)
            except Exception as e:
                render_error(f"SenseVoice 转录失败！报错: {e}")
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
                status_text.warning(f"转录引擎轰鸣中！算力节点: 【{selected_device_name}】")

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
                render_error(f"转录失败！报错: {e}")
                st.stop()

    status_text.info("正在呼叫 DeepSeek 提炼高光时间轴并智能命名...")
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
        render_success("处理完成！数据已智能命名并安全归档。")

        # 记录刚完成的归档名称，用于侧边栏自动选中
        if archive_folders:
            st.session_state.just_finished_archive = archive_folders[0]
            # 读取刚生成的摘要到 session_state（用于直接展示）
            latest_archive_path = os.path.join(ARCHIVE_DIR, archive_folders[0])
            with open(os.path.join(latest_archive_path, "summary.md"), "r", encoding="utf-8") as f:
                st.session_state.summary = f.read()

        # 清理临时文件
        if os.path.exists(audio_file_path):
            try:
                os.remove(audio_file_path)
            except Exception:
                pass
        if os.path.exists(raw_text_file):
            try:
                os.remove(raw_text_file)
            except Exception:
                pass

        # 刷新页面以显示新归档
        st.rerun()

    except Exception as e:
        render_error(f"大模型调用失败: {e}")
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
if "current_view_task" not in st.session_state: st.session_state.current_view_task = None

# ================= 补充引擎相关的会话状态 =================
if "transcription_engine" not in st.session_state: st.session_state.transcription_engine = "SenseVoice (极速模式)"
if "selected_model" not in st.session_state: st.session_state.selected_model = "small"
if "max_timeline_items" not in st.session_state: st.session_state.max_timeline_items = 15
if "selected_device_name" not in st.session_state:
    available_devices = get_available_devices()
    device_keys = list(available_devices.keys())
    if "cuda" in device_keys: st.session_state.selected_device_name = available_devices["cuda"]
    elif "mps" in device_keys: st.session_state.selected_device_name = available_devices["mps"]
    else: st.session_state.selected_device_name = available_devices["cpu"]

# ================= 大模型重试处理（会话状态初始化后立即检查） =================
# 检查是否有持久化的失败状态（页面刷新后也能恢复）
saved_state = load_llm_failed_state()
if saved_state:
    st.session_state.llm_failed = True
    st.session_state.llm_failed_original_name = saved_state.get("original_name", "未命名")
    st.session_state.llm_failed_raw_file = saved_state.get("raw_file_path", "")

# ================= 主页头部与侧边栏渲染 (防 Markdown 缩进 Bug 版) =================

# 1. 主页的水平并排 Logo + 标题
hero_section = """<div style="display: flex; justify-content: center; align-items: center; gap: 15px; margin-bottom: 10px; margin-top: -10px;">
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 250" width="60px">
<defs>
<linearGradient id="gradP3" x1="0%" y1="100%" x2="100%" y2="0%">
<stop offset="0%" stop-color="#001A9C" />
<stop offset="100%" stop-color="#008080" />
</linearGradient>
<linearGradient id="gradG3" x1="0%" y1="0%" x2="100%" y2="100%">
<stop offset="0%" stop-color="#00E5FF" />
<stop offset="100%" stop-color="#B2FF59" />
</linearGradient>
</defs>
<g transform="translate(0, -10)">
<path d="M 120 190 L 120 60 L 160 60 A 50 50 0 0 1 160 160 L 120 160" fill="none" stroke="url(#gradP3)" stroke-width="32" stroke-linecap="round" stroke-linejoin="round"/>
<path d="M 230 110 L 280 110 A 50 50 0 1 1 260 70" fill="none" stroke="url(#gradG3)" stroke-width="32" stroke-linecap="round" stroke-linejoin="round"/>
<circle cx="260" cy="70" r="14" fill="#FFFFFF"/>
</g>
</svg>
<h1 style="margin: 0; padding: 0; font-size: 2.8rem;">PodGist</h1>
</div>"""

st.markdown(hero_section, unsafe_allow_html=True)
st.markdown("<p style='text-align: center; color: #888;'>上传音频提取精华，或从左侧历史归档中唤醒记忆，支持 AI 精准定位。</p>", unsafe_allow_html=True)
st.divider()

with st.sidebar:
    st.header("核心设置")
    api_key = st.text_input(
        "DeepSeek API Key",
        value=load_api_key(),
        type="password",
        help="DeepSeek API Key，用于调用大模型生成摘要。可在 https://platform.deepseek.com 获取。"
    )
    if st.button("保存 Key", use_container_width=True):
        if api_key:
            save_api_key(api_key)
            render_success("已保存")
        else:
            st.warning("请输入 Key")

    st.divider()

    st.header("历史归档")
    archive_list = ["-- 新建提炼任务 --"] + get_archive_list()

    # 检查是否有刚完成的归档需要自动选中
    if "just_finished_archive" in st.session_state:
        just_finished = st.session_state.just_finished_archive
        if just_finished in archive_list:
            st.session_state.history_selector = just_finished
        st.session_state.pop("just_finished_archive", None)

    def on_history_change():
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
        if st.button("删除此归档", type="primary", use_container_width=True):
            shutil.rmtree(os.path.join(ARCHIVE_DIR, selected_archive))
            st.session_state.podcast_text = ""
            st.session_state.summary = ""
            st.rerun()

    st.divider()

    st.subheader("转录引擎设置")

    # 选择转录引擎
    transcription_engine = st.radio(
        "选择转录引擎",
        ["SenseVoice (极速模式)", "Whisper (高精度时间戳)"],
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
    if "max_timeline_items" in st.session_state and st.session_state.max_timeline_items in timeline_options:
        default_index = timeline_options.index(st.session_state.max_timeline_items)

    max_timeline_items = st.selectbox(
        "3. 时间轴上限",
        timeline_options,
        index=default_index,
        help="AI 生成的时间轴最多不超过此条数。数量越少，生成速度越快、越稳定。"
    )
    st.session_state.max_timeline_items = max_timeline_items

    # ================= 诊断区域（侧边栏底部） =================
    st.divider()
    st.header("系统诊断")

    # 初始化诊断结果存储
    if "diagnostic_results" not in st.session_state:
        st.session_state.diagnostic_results = None

    # 诊断按钮
    if st.button("一键诊断所有组件", use_container_width=True):
        with st.spinner("正在诊断..."):
            api_key = load_api_key()
            results = run_all_diagnostics(api_key)
            st.session_state.diagnostic_results = results

    # 显示诊断结果
    if st.session_state.diagnostic_results is not None:
        results = st.session_state.diagnostic_results

        all_passed = all(r[1] for r in results)

        if all_passed:
            render_success("全部通过！可以开始处理音频。")
        else:
            st.error("部分组件存在问题，请检查以下项目：")

        for name, success, msg in results:
            if success:
                st.markdown(f'<div style="display: flex; align-items: center; border-radius: 6px; padding: 8px 12px; background-color: #F0FDFD; border: 1px solid #C4F1F1; margin-bottom: 4px;">{svg_icon_check} <span style="color: #008080; font-weight: 500;">{name}: {msg}</span></div>', unsafe_allow_html=True)
            else:
                st.markdown(f'<div style="display: flex; align-items: center; border-radius: 6px; padding: 8px 12px; background-color: #ECFEFF; border: 1px solid #A5F3FC; margin-bottom: 4px;">{svg_icon_cross} <span style="color: #0891B2; font-weight: 500;">{name}: {msg}</span></div>', unsafe_allow_html=True)

        # 添加重新诊断按钮
        if st.button("重新诊断", use_container_width=True):
            st.session_state.diagnostic_results = None
            st.rerun()
    else:
        st.caption("点击上方按钮测试所有组件是否正常")

# ================= 提取底层参数供核心业务使用 =================
# 使用侧边栏中的参数
use_sensevoice = "SenseVoice" in transcription_engine

available_devices = get_available_devices()
device_keys = list(available_devices.keys())
device_options = list(available_devices.values())
selected_device_key = device_keys[device_options.index(selected_device_name)]

# 用于兼容后续代码中的 selected_archive 变量
selected_archive = st.session_state.history_selector

# 加载 API Key 供主程序使用
api_key = load_api_key()

# ================= 5. 文件处理逻辑 =================
# 如果有摘要内容（刚完成的任务），显示归档查看而不是新建任务
show_new_task = (selected_archive == "-- 新建提炼任务 --") and not st.session_state.summary

if show_new_task:
    # 创建标签页：本地文件 vs 播客直连 vs 视频剥离
    tab_local, tab_podcast, tab_video, tab_batch = st.tabs(["本地提炼", "播客直连", "视频剥离", "批量处理"])

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

            if st.button("开始提炼并打上时间戳", use_container_width=True, key="local_process"):
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
            render_info("请拖拽上传音频文件")

    # ================= 批量处理 Tab =================
    with tab_batch:
        st.markdown("### 批量任务输入区")

        # 初始化 session state
        if "batch_input" not in st.session_state:
            st.session_state.batch_input = ""

        # 批量输入文本域 - 使用 key 来控制
        batch_input = st.text_area(
            "批量粘贴链接（每行一个）",
            key="batch_input_key",
            height=200,
            placeholder="示例：\nhttps://xiaoyuzhoufm.com/episode/xxx\nhttps://www.bilibili.com/video/xxx\nhttps://163cn.tv/3Kc5VwN"
        )

        # 本地文件上传
        st.markdown("**或上传本地音频文件：**")
        uploaded_files = st.file_uploader(
            "拖拽音频文件到此处（支持多选）",
            type=['mp3', 'm4a', 'wav', 'flac', 'aac'],
            accept_multiple_files=True,
            key="batch_file_uploader"
        )

        # 转录引擎设置
        col_engine, col_timeline = st.columns(2)
        with col_engine:
            batch_engine = st.selectbox(
                "转录引擎",
                ["sensevoice", "whisper"],
                index=0,
                key="batch_engine",
                help="选择转录引擎：SenseVoice 更快，Whisper 更准确"
            )
        with col_timeline:
            batch_timeline = st.select_slider(
                "时间轴上限",
                options=[8, 10, 15, 20, 25],
                value=15,
                key="batch_timeline",
                help="AI 生成的时间轴最多不超过此条数"
            )

        # 按钮说明
        with st.expander("批量处理按钮说明"):
            st.markdown("""
            - **一键开始批处理**：将输入的链接/文件加入队列，并开始处理
            - **加入队列**：将新的链接/文件加入到当前队列（队列必须有任务）
            - **暂停/继续批处理**：暂停或继续当前队列的处理（不删除任务）
            - **删除当前队列**：清空队列中的所有任务记录
            """)

        # 按钮行 - 三个按钮
        col_start, col_add, col_stop = st.columns(3)

        # 检查队列中是否有任务
        all_tasks = task_queue.get_all_tasks()
        has_tasks = len(all_tasks) > 0

        with col_start:
            # 一键开始批处理：有任务时禁用
            if has_tasks:
                st.button("一键开始批处理", disabled=True, use_container_width=True)
            else:
                # 一键开始批处理：入队并开始
                def start_batch_and_clear():
                    """一键开始批处理的回调函数"""
                    # 读取 text_area 的内容
                    current_input = st.session_state.get("batch_input_key", "")
                    added_count = 0

                    # 处理文本域中的链接
                    if current_input.strip():
                        lines = current_input.strip().split("\n")
                        for line in lines:
                            line = line.strip()
                            if line:
                                # 检查文本中是否包含 URL（在任意位置，不仅仅是开头）
                                line_lower = line.lower()
                                has_url = "http" in line_lower

                                if has_url:
                                    if "xiaoyuzhoufm.com" in line_lower:
                                        task_type = "xiaoyuzhou"
                                    elif "bilibili.com" in line_lower:
                                        task_type = "bilibili"
                                    elif "163cn.tv" in line_lower or "music.163.com" in line_lower:
                                        task_type = "netease"
                                    elif "xima.tv" in line_lower or "ximalaya.com" in line_lower:
                                        task_type = "ximalaya"
                                    elif "podcasts.apple.com" in line_lower:
                                        task_type = "applepodcasts"
                                    else:
                                        task_type = "unknown"
                                    print(f"[DEBUG] 添加任务: source={line}, task_type={task_type}")
                                else:
                                    task_type = "local"

                                if task_type != "unknown":
                                    task_queue.add_task(
                                        source=line,
                                        task_type=task_type,
                                        engine=st.session_state.batch_engine,
                                        max_timeline_items=st.session_state.batch_timeline
                                    )
                                    added_count += 1

                    # 处理上传的本地文件
                    files = st.session_state.get("batch_file_uploader", [])
                    if files:
                        for uploaded_file in files:
                            file_path = os.path.join(TEMP_DIR, f"batch_{uploaded_file.name}")
                            with open(file_path, "wb") as f:
                                f.write(uploaded_file.getbuffer())

                            task_queue.add_task(
                                source=file_path,
                                task_type="local",
                                engine=st.session_state.batch_engine,
                                max_timeline_items=st.session_state.batch_timeline
                            )
                            added_count += 1

                    # 清空输入框
                    st.session_state.batch_input_key = ""

                    # 启动 Worker
                    if added_count > 0:
                        try:
                            worker.start_worker(force_restart=True)
                        except:
                            pass
                        # 设置刷新标志
                        st.session_state.batch_need_rerun = True
                        # 设置 Toast 消息（用新变量避免冲突）
                        st.session_state.batch_show_toast = f"已添加 {added_count} 个任务并开始处理"
                        st.session_state.batch_toast_type = "success"
                    else:
                        st.session_state.batch_show_toast = "请输入链接或上传音频文件"
                        st.session_state.batch_toast_type = "warning"

                # 使用 on_click 回调
                st.button(
                    "一键开始批处理",
                    type="primary",
                    use_container_width=True,
                    key="start_batch",
                    on_click=start_batch_and_clear
                )

                # 显示添加结果（Toast 会在几秒后自动消失）
                # 注意：这里用 session_state 传递消息，只有在本次点击后才会有值
                if st.session_state.get("batch_show_toast"):
                    toast_msg = st.session_state.batch_show_toast
                    toast_type = st.session_state.get("batch_toast_type", "info")
                    del st.session_state.batch_show_toast
                    if "batch_toast_type" in st.session_state:
                        del st.session_state.batch_toast_type
                    if toast_type == "success":
                        st.toast(toast_msg)
                    else:
                        st.toast(toast_msg)

        with col_add:
            # 加入队列：队列有任务时才可用
            if has_tasks:
                # 加入队列的回调函数
                def add_to_queue():
                    current_input = st.session_state.get("batch_input_key", "")
                    added_count = 0

                    # 处理文本域中的链接
                    if current_input.strip():
                        lines = current_input.strip().split("\n")
                        for line in lines:
                            line = line.strip()
                            if line:
                                # 检查文本中是否包含 URL（在任意位置，不仅仅是开头）
                                line_lower = line.lower()
                                has_url = "http" in line_lower

                                if has_url:
                                    if "xiaoyuzhoufm.com" in line_lower:
                                        task_type = "xiaoyuzhou"
                                    elif "bilibili.com" in line_lower:
                                        task_type = "bilibili"
                                    elif "163cn.tv" in line_lower or "music.163.com" in line_lower:
                                        task_type = "netease"
                                    elif "xima.tv" in line_lower or "ximalaya.com" in line_lower:
                                        task_type = "ximalaya"
                                    elif "podcasts.apple.com" in line_lower:
                                        task_type = "applepodcasts"
                                    else:
                                        task_type = "unknown"
                                    print(f"[DEBUG] 添加任务: source={line}, task_type={task_type}")
                                else:
                                    task_type = "local"

                                if task_type != "unknown":
                                    task_queue.add_task(
                                        source=line,
                                        task_type=task_type,
                                        engine=st.session_state.batch_engine,
                                        max_timeline_items=st.session_state.batch_timeline
                                    )
                                    added_count += 1

                    # 处理上传的本地文件
                    files = st.session_state.get("batch_file_uploader", [])
                    if files:
                        for uploaded_file in files:
                            file_path = os.path.join(TEMP_DIR, f"batch_{uploaded_file.name}")
                            with open(file_path, "wb") as f:
                                f.write(uploaded_file.getbuffer())

                            task_queue.add_task(
                                source=file_path,
                                task_type="local",
                                engine=st.session_state.batch_engine,
                                max_timeline_items=st.session_state.batch_timeline
                            )
                            added_count += 1

                    # 清空输入框
                    st.session_state.batch_input_key = ""

                    return added_count

                # 使用 on_click 回调
                def on_add_click():
                    result = add_to_queue()
                    if result > 0:
                        # 检查 Worker 是否在运行，如果没有则启动
                        if not worker.is_worker_running():
                            try:
                                worker.start_worker(force_restart=True)
                            except Exception as e:
                                print(f"启动 Worker 失败: {e}")
                        # 设置刷新标志
                        st.session_state.batch_need_rerun = True
                        # 设置 Toast 消息
                        st.session_state.batch_show_toast = f"已添加 {result} 个任务到队列"
                        st.session_state.batch_toast_type = "success"
                    else:
                        st.session_state.batch_show_toast = "请输入链接或上传音频文件"
                        st.session_state.batch_toast_type = "warning"

                st.button("加入队列", use_container_width=True, key="add_to_queue", on_click=on_add_click)

                # 点击后自动刷新页面
                if st.session_state.get("batch_need_rerun", False):
                    st.session_state.batch_need_rerun = False
                    st.rerun()

                # 显示消息（使用统一的变量）
                if st.session_state.get("batch_show_toast"):
                    toast_msg = st.session_state.batch_show_toast
                    toast_type = st.session_state.get("batch_toast_type", "info")
                    del st.session_state.batch_show_toast
                    if "batch_toast_type" in st.session_state:
                        del st.session_state.batch_toast_type
                    if toast_type == "success":
                        st.toast(toast_msg)
                    else:
                        st.toast(toast_msg)
            else:
                st.button("加入队列", disabled=True, use_container_width=True)

        with col_stop:
            # 暂停/继续批处理：有任务时可以按下
            if has_tasks:
                # 检查是否暂停
                is_paused = worker.is_paused()
                if is_paused:
                    # 显示继续按钮
                    if st.button("继续批处理", type="secondary", use_container_width=True, key="resume_batch"):
                        worker.resume_worker()
                        st.toast("批处理已继续")
                        st.rerun()
                else:
                    # 显示暂停按钮
                    if st.button("暂停批处理", type="secondary", use_container_width=True, key="pause_batch"):
                        worker.pause_worker()
                        st.warning("批处理已暂停")
                        st.rerun()
            else:
                st.button("暂停批处理", disabled=True, use_container_width=True)

        # 删除队列按钮（在 fragment 外面）
        if st.button("删除当前队列", key="clear_queue_button", use_container_width=True):
            # 删除所有任务（不包括归档）
            all_tasks = task_queue.get_all_tasks()
            for task in all_tasks:
                task_queue.delete_task(task["id"])
            # 清除所有可能存在的消息状态
            for key in ["batch_added_count", "batch_show_msg", "batch_show_toast", "batch_toast_type"]:
                if key in st.session_state:
                    del st.session_state[key]
            success_html = f'<div style="background-color: #F0FDFD; border: 1px solid #C4F1F1; border-radius: 6px; padding: 12px 16px; color: #008080; font-weight: 500; display: flex; align-items: center;">{svg_icon_check} 队列已清空</div>'
            st.markdown(success_html, unsafe_allow_html=True)
            st.rerun()

        # 任务监控大屏（包含已完成任务查看器）
        render_task_monitor()

        # 刷新按钮（放在 fragment 外面）
        if st.button("刷新任务状态", key="refresh_task_status"):
            st.rerun()

        st.divider()

    with tab_podcast:
        # 平台支持状态
        st.markdown("**平台支持状态：**")
        col1, col2 = st.columns(2)
        with col1:
            success_html = f'<div style="background-color: #F0FDFD; border: 1px solid #C4F1F1; border-radius: 6px; padding: 12px 16px; color: #008080; font-weight: 500; display: flex; align-items: center;">{svg_icon_check} 已支持：小宇宙、网易云音乐、喜马拉雅、苹果播客</div>'
            st.markdown(success_html, unsafe_allow_html=True)
        with col2:
            render_info("规划中：荔枝FM、Spotify")

        # 输入框
        podcast_url = st.text_input("请粘贴播客单集链接", placeholder="小宇宙/网易云/喜马拉雅/苹果播客 (手机App分享链接)", key="podcast_url")

        if podcast_url and api_key:
            if st.button("解析并提取音频", use_container_width=True, key="podcast_process"):
                # 先清理 temp_audio 目录
                cleanup_temp_files()

                # 检测平台
                from backend.downloader import detect_platform
                platform = detect_platform(podcast_url)

                # 根据平台选择下载函数
                if platform == "netease":
                    from backend.downloader import download_netease_audio
                    download_func = download_netease_audio
                    spinner_text = "正在连接网易云音乐服务器提取音频..."
                    success_msg = "音频提取成功"
                elif platform == "ximalaya":
                    from backend.downloader import download_ximalaya_audio
                    download_func = download_ximalaya_audio
                    spinner_text = "正在连接喜马拉雅服务器提取音频..."
                    success_msg = "音频提取成功"
                elif platform == "xiaoyuzhou":
                    from backend.downloader import download_xiaoyuzhou_audio
                    download_func = download_xiaoyuzhou_audio
                    spinner_text = "正在连接小宇宙服务器提取音频..."
                    success_msg = "音频提取成功"
                elif platform == "applepodcasts":
                    from backend.downloader import download_applepodcasts_audio
                    download_func = download_applepodcasts_audio
                    spinner_text = "正在连接苹果播客服务器提取音频..."
                    success_msg = "音频提取成功"
                else:
                    render_error(f"不支持的平台: {platform}")
                    st.stop()

                with st.spinner(spinner_text):
                    try:
                        download_result = download_func(podcast_url, TEMP_DIR)

                        if download_result['success']:
                            audio_file_path = download_result['file_path']
                            podcast_title = download_result['title']
                            st.success(f"{success_msg}: {podcast_title}")

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
                            render_error(f"下载失败: {download_result['error']}")
                    except Exception as e:
                        render_error(f"解析失败: {str(e)}")
        elif podcast_url and not api_key:
            st.warning("请先在左侧填写 API Key")
        else:
            render_info("请粘贴小宇宙或网易云音乐播客链接")

        # 操作引导 - 统一收纳为单一下拉框 + 内部 Tabs
        with st.expander("平台链接获取指南", expanded=False):
            tab_xyz, tab_wyy, tab_xml, tab_apple = st.tabs(["小宇宙", "网易云音乐", "喜马拉雅", "苹果播客"])

            with tab_xyz:
                st.markdown("""
                1. 打开手机 **小宇宙 App** 并选择单集
                2. 点击右上角或底部的「分享」按钮
                3. 选择「复制链接」并粘贴到上方输入框
                *链接格式示例：xiaoyuzhoufm.com/episode/...*
                """)

            with tab_wyy:
                st.markdown("""
                **手机 App 分享：**
                1. 打开 **网易云音乐 App**，进入播客单集
                2. 点击右上角「分享」→「复制链接」
                *支持带文案分享，如：分享#xxx#...https://163cn.tv/xxx*

                **PC/网页端复制：**
                直接复制地址栏链接（如：music.163.com/#/program?id=...）
                """)

            with tab_xml:
                st.markdown("""
                **手机 App 分享（推荐）：**
                1. 打开 **喜马拉雅 App**，进入单集页面
                2. 点击右上角「分享」→「复制链接」

                **网页端分享：**
                直接复制地址栏链接（如：m.ximalaya.com/sound/xxxxx）
                *注：不支持 PC 客户端直接复制专辑链接*
                """)

            with tab_apple:
                st.markdown("""
                **手机 App / 电脑端分享：**
                1. 打开 **Apple Podcasts App**
                2. 进入播客单集页面，点击「分享」→「复制链接」
                *链接格式示例：podcasts.apple.com/cn/podcast/...*
                """)

    with tab_video:
        st.markdown("支持 Bilibili 视频链接，自动提取音频并生成摘要")
        bilibili_url = st.text_input("请粘贴 B站视频链接", placeholder="https://www.bilibili.com/video/BV...", key="bilibili_url")

        if bilibili_url and api_key:
            if st.button("解析并提取音频", use_container_width=True, key="bilibili_process"):
                # 先清理 temp_audio 目录
                cleanup_temp_files()

                with st.spinner("正在连接 B 站服务器提取音频..."):
                    try:
                        # 初始化下载器
                        downloader = AudioDownloader(save_dir=TEMP_DIR)

                        # 下载音频
                        download_result = downloader.download_bilibili_audio(bilibili_url)

                        if download_result['success']:
                            audio_file_path = download_result['file_path']
                            video_title = download_result['title']
                            render_success(f"音频提取成功: {video_title}")

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
                            render_error(f"下载失败: {download_result['error']}")
                    except Exception as e:
                        render_error(f"解析失败: {str(e)}")
        elif bilibili_url and not api_key:
            st.warning("请先在左侧填写 API Key")
        else:
            render_info("请粘贴 Bilibili 视频链接")

    # 如果用户没有填写 API Key，给出提示
    if not api_key:
        st.warning("请在左侧填写 DeepSeek API Key 后再操作")

if "llm_failed" in st.session_state and st.session_state.get("llm_failed"):
    st.divider()
    st.error("大模型调用失败，您可以点击下方按钮重试（使用已有的转录稿，无需重新转录）")

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

    selected_file = st.selectbox("选择转录稿文件", temp_files if temp_files else [raw_text_file], key="retry_file_select")

    col_retry1, col_retry2 = st.columns(2)
    with col_retry1:
        if st.button("重试调用大模型", type="primary", key="retry_llm", use_container_width=True):
            if selected_file:
                # 读取文字稿
                retry_file_path = os.path.join(TEMP_DIR, selected_file)
                if os.path.exists(retry_file_path):
                    with open(retry_file_path, "r", encoding="utf-8") as f:
                        podcast_text = f.read()

                    with st.spinner("正在重新调用大模型..."):
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

                            st.success("重试成功！")
                            st.rerun()
                        except Exception as retry_error:
                            render_error(f"重试仍然失败: {retry_error}")
                else:
                    st.warning("文件不存在")
            else:
                st.warning("没有可用的转录稿文件")

    with col_retry2:
        if st.button("放弃重试，重新开始", key="giveup_retry", use_container_width=True):
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
    # 查看历史归档或刚完成的任务（有 summary 时自动显示最新归档）
    if st.session_state.summary:
        # 获取最新归档名称
        archive_folders = get_archive_list()
        if archive_folders:
            display_name = archive_folders[0]
        else:
            display_name = "最新任务"
    else:
        display_name = selected_archive

    # 如果在批量处理 Tab 且没有任务，不显示"正在查看"
    in_batch_tab = (selected_archive == "-- 新建提炼任务 --")
    has_any_tasks = len(task_queue.get_all_tasks()) > 0

    if not in_batch_tab or has_any_tasks:
        render_info(f"正在查看：{display_name}")


# ================= 6. 结果展示与搜索 =================
if st.session_state.summary:
    st.divider()

    # 使用正则表达式将 [MM:SS] 格式时间戳替换为带样式的 HTML 元素
    # 支持任意位数分钟（如 [99:59] 或 [100:00]）
    styled_summary = re.sub(
        r'(\[\d+:\d{2}\])',
        r'<span style="color: #2e7d32; background-color: #e8f5e9; font-weight: 700; padding: 2px 6px; border-radius: 5px; margin-right: 5px; box-shadow: 0px 1px 2px rgba(0,0,0,0.1);">\1</span>',
        st.session_state.summary
    )

    st.markdown(styled_summary, unsafe_allow_html=True)

    st.download_button(
        label="下载当前 Markdown 报告",
        data=st.session_state.summary,  # 注：下载的文件为原始 Markdown 内容，不含 HTML 样式
        file_name="PodGist_Report.md",
        mime="text/markdown",
        use_container_width=True
    )
    
    st.divider()
    st.subheader("AI 模糊定位器 (当前音频)")
    search_query = st.text_input("向本期音频提问：")
    
    if st.button("精准搜索"):
        if search_query and api_key:
            with st.spinner("正在检索相关片段..."):
                try:
                    ans = search_in_podcast(api_key, search_query, st.session_state.podcast_text)
                    st.info(ans)
                except Exception as e:
                    st.error(f"搜索失败: {e}")
        else:
            st.warning("请确保输入了问题，并且已填写 API Key！")

