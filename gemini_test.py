import requests
import datetime
import time
import json
import os
import re  # For sanitizing filenames
import mimetypes  # For guessing MIME types

# Gemini AI Specific Imports as provided by user
from google import genai
from google.genai import types as genai_types

# Pillow for GIF processing
try:
    from PIL import Image as PILImage

    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False
    # This warning will be printed when the script starts if Pillow is missing.

# --- 用户配置 ---
LLONEBOT_API_URL = "http://127.0.0.1:3000"
TARGET_GROUP_ID = 1021625002
REQUEST_TIMEOUT = 10
DELAY_BETWEEN_REQUESTS = 0.1
MAX_FETCH_LOOPS = 20
IMAGE_DOWNLOAD_DIR = "downloaded_qq_images_for_gemini"
GEMINI_MODEL_NAME = "gemini-2.5-flash-preview-05-20"  # Matching user example

# 新增：统计的小时数
FETCH_HOURS_AGO = 24  # 例如: 24 代表过去24小时, 12 代表过去12小时

# 新增：最大处理消息数量限制
MAX_MESSAGES_TO_PROCESS = 1500  # 设置一个上限，防止处理过多消息

# Moved prompt prefix to configuration
# The {fetch_hours} placeholder will be replaced by the value of FETCH_HOURS_AGO
GEMINI_PROMPT_PREFIX = (
    f"这是过去{FETCH_HOURS_AGO}小时的部分QQ群聊记录。其中《图片N》代表按顺序提供的第N张图（部分图片可能来自GIF等）。\n"
    "请用中文结合所有文本和图片信息进行分析和回应。请按照以下指示和结构进行回复：\n\n"
    "1.  **主要讨论方向概述**：\n"
    f"    简要总结过去{FETCH_HOURS_AGO}小时内群聊的整体讨论方向或最核心的主题,同一个方向的不同事件应该分别说明。如果无明显核心，请说明情况。\n\n"
    "2.  **详细主题分析**：\n"
    "    请分条列举各个具体讨论主题。对于每个主题：\n"
    "    a.  首先，给出该主题的**总结**，这部分内容不要超过50字。\n"
    "    b.  然后，在总结之后，紧接着给出相关的**原始聊天记录片段**。这部分请严格使用大括号 {} 包围，并且括号内部的每一条相关原始消息都以 `<<时间,用户名,用户id,发言>>` 的格式独立成行。注意每一个部分给出的聊天记录片段不要超过80行\n"
    "    例如一个主题的格式：\n"
    "游戏讨论总结：昨晚大家主要讨论了新发布的游戏A，特别是其画面和玩法。\n"
    "{<<22:30:05,玩家小明,10001,游戏A的风景太美了《图片5》>>\n"
    "<<22:31:00,玩家小红,10002,是啊，操作手感也不错，就是有点肝。>>\n"
    "<<22:35:10,群主,10000,我还没买，看你们聊得挺热闹《图片6》。>>}\n\n"
    "    请确保每个主题的总结和对应的原始记录块清晰配对。引用图片时继续使用《图片N》。注意识别群友的反语与调侃。\n"
    "    如果没有识别出任何明确的讨论主题，请在“详细主题分析”部分说明“未能识别出明确的独立讨论主题”。\n\n"
    "群聊记录开始：\n"
)

# --- API密钥配置 (移至顶部) ---
GEMINI_API_KEY_VALUE = "YOUR_GEMINI_API_KEY_HERE"


# --- 用户配置结束 ---

# --- Helper Functions ---
def ensure_dir_exists(dir_path):
    if not os.path.exists(dir_path):
        try:
            os.makedirs(dir_path)
        except OSError as e:
            print(f"    [错误] 创建目录 {dir_path} 失败: {e}")
            return False
    return True


def sanitize_filename(filename):
    s = re.sub(r'[\\/*?:"<>|]', "", filename)
    return s[:200].strip()


def get_mime_type(file_path):
    mime_type, _ = mimetypes.guess_type(file_path)
    if mime_type is None:
        ext = os.path.splitext(file_path)[1].lower()
        if ext == '.jpg' or ext == '.jpeg':
            mime_type = 'image/jpeg'
        elif ext == '.png':
            mime_type = 'image/png'
        elif ext == '.gif':
            mime_type = 'image/gif'
        elif ext == '.webp':
            mime_type = 'image/webp'
        else:
            mime_type = 'application/octet-stream'
    return mime_type


def download_and_process_image_for_gemini(image_url, group_id, image_name_from_qq, message_id_context):
    if not image_url: return None, ""
    group_image_folder = os.path.join(IMAGE_DOWNLOAD_DIR, f"group_{group_id}")
    if not ensure_dir_exists(group_image_folder): return None, ""

    base_name_from_qq = os.path.basename(image_name_from_qq if image_name_from_qq else "")
    original_safe_basename = ""
    if not base_name_from_qq or base_name_from_qq == "image" or "." not in base_name_from_qq:
        _, ext_from_url = os.path.splitext(image_url.split('?')[0])
        if not ext_from_url or len(ext_from_url) > 5 or len(ext_from_url) < 2: ext_from_url = ".jpg"
        original_safe_basename = sanitize_filename(f"msg_{message_id_context}_{int(time.time() * 1000)}{ext_from_url}")
    else:
        original_safe_basename = sanitize_filename(base_name_from_qq)

    original_download_path = os.path.join(group_image_folder, original_safe_basename)

    if not (os.path.exists(original_download_path) and os.path.getsize(original_download_path) > 0):
        try:
            img_response = requests.get(image_url, timeout=REQUEST_TIMEOUT, stream=True)
            img_response.raise_for_status()
            with open(original_download_path, "wb") as f_img:
                for chunk in img_response.iter_content(chunk_size=8192): f_img.write(chunk)
        except Exception as e:
            print(f"    [图片] 原始文件下载失败: {original_safe_basename} (URL: {image_url[:60]}...), 错误: {e}")
            if os.path.exists(original_download_path):
                try:
                    os.remove(original_download_path)
                except:
                    pass
            return None, f" (下载失败: {original_safe_basename})"

    final_image_path_to_send = original_download_path
    media_info_for_log = ""
    file_ext = os.path.splitext(original_safe_basename)[1].lower()

    if file_ext == '.gif':
        if not PILLOW_AVAILABLE:
            print(f"    [GIF处理] Pillow库未安装，无法提取 {original_safe_basename} 的第一帧。此GIF不会作为图片发送。")
            return None, " (来自GIF - Pillow缺失)"
        try:
            pil_im = PILImage.open(original_download_path)
            pil_im.seek(0)
            frame_filename_base = os.path.splitext(original_safe_basename)[0]
            frame_save_filename = sanitize_filename(f"{frame_filename_base}_frame0.png")
            frame_full_path = os.path.join(group_image_folder, frame_save_filename)
            if pil_im.mode == 'P' or pil_im.mode == 'RGBA':
                converted_frame = pil_im.convert('RGBA') if pil_im.mode == 'P' else pil_im
            elif pil_im.mode != 'RGB':
                converted_frame = pil_im.convert('RGB')
            else:
                converted_frame = pil_im
            converted_frame.save(frame_full_path, "PNG")
            final_image_path_to_send = frame_full_path
            media_info_for_log = " (来自GIF)"
        except Exception as e_gif:
            print(f"    [GIF处理] 提取GIF第一帧失败 ({original_safe_basename}): {e_gif}. 此图片将不被发送。")
            return None, f" (来自GIF - 处理失败)"
    elif file_ext in ['.mp4', '.mov', '.avi', '.mkv', '.webm']:
        print(
            f"    [视频处理] 检测到视频: {original_safe_basename}. 提取视频第一帧的功能需要额外库 (如OpenCV) 且未在此版本实现。此视频将不被作为图片发送。")
        return None, f" (来自视频 - 不支持提取)"

    if not os.path.exists(final_image_path_to_send) or os.path.getsize(final_image_path_to_send) == 0:
        print(f"    [错误] 最终图片文件不存在或为空: {final_image_path_to_send}")
        return None, " (文件错误)"
    return final_image_path_to_send, media_info_for_log


# --- End Helper Functions ---

# --- Gemini API Call Function (Moved to Top) ---
def send_to_gemini(text_prompt, image_paths):
    if not genai or not genai_types:
        print("Gemini AI library (genai or genai.types) not available. Cannot send.")
        return

    gemini_api_key_to_use = GEMINI_API_KEY_VALUE

    if not gemini_api_key_to_use:
        print("错误：GEMINI_API_KEY_VALUE 未在脚本顶部配置。请设置该变量后再运行。")
        return
    if "YOUR_GEMINI_API_KEY_HERE" in gemini_api_key_to_use:
        print("=" * 70)
        print("错误：检测到占位符或示例API密钥。")
        print("请在脚本顶部的 GEMINI_API_KEY_VALUE 处填入您真实的Gemini API Key。")
        print("=" * 70)
        return

    try:
        client = genai.Client(api_key=gemini_api_key_to_use)
    except Exception as e:
        print(f"初始化Gemini Client失败: {e}")
        return

    model_to_call = GEMINI_MODEL_NAME
    print(f"\n--- 向 Gemini ({model_to_call}) 发送内容 ---")
    print(f"图片数量: {len(image_paths)}")

    api_parts = []
    for image_path in image_paths:
        try:
            mime = get_mime_type(image_path)
            with open(image_path, 'rb') as f:
                image_bytes = f.read()
            api_parts.append(genai_types.Part.from_bytes(mime_type=mime, data=image_bytes))
        except AttributeError:
            print("  [严重错误] `google.genai.types.Part.from_bytes` 不存在。您的 SDK 版本可能与示例代码不兼容。")
            print("  请检查 google-generativeai SDK 版本。当前 SDK 通常使用 `Part.from_data`。")
            return
        except Exception as e:
            print(f"  [错误] 读取或处理图片 {os.path.basename(image_path)} 失败: {e}")
            print("  由于图片处理错误，取消发送。")
            return

    api_parts.append(genai_types.Part.from_text(text=text_prompt))

    if not text_prompt and not image_paths:
        print("没有文本或图片可以发送给Gemini。")
        return

    contents_for_api_call = [
        genai_types.Content(
            role="user",
            parts=api_parts
        )
    ]

    generate_content_config = genai_types.GenerateContentConfig(
        response_mime_type="text/plain",
    )

    print("\n--- Gemini AI 回复 (流式) ---")
    last_chunk = None  # Initialize variable to store the last chunk
    try:
        response_stream = client.models.generate_content_stream(
            model=model_to_call,
            contents=contents_for_api_call,
            config=generate_content_config,
        )
        for chunk in response_stream:
            if hasattr(chunk, 'text') and chunk.text:
                print(chunk.text, end="", flush=True)
            last_chunk = chunk  # Update last_chunk with the current chunk

        print("\n--- Gemini AI 回复结束 ---")

        # After the stream is consumed, the last_chunk should have usage_metadata
        if last_chunk and hasattr(last_chunk, 'usage_metadata') and last_chunk.usage_metadata:
            print("\n\n--- Token Usage ---")  # Added extra newline for separation
            print(last_chunk.usage_metadata)
        else:
            print("\n\n[信息] 未能从API响应中获取到 usage_metadata。")

    except Exception as e:
        print(f"\n[错误] 调用Gemini API失败: {e}")
        import traceback
        traceback.print_exc()
        # Also print if usage_metadata was available on an erroring last_chunk, if applicable
        if last_chunk and hasattr(last_chunk, 'usage_metadata') and last_chunk.usage_metadata:
            print("\n--- Token Usage (注意: 错误发生前可能已收到部分数据) ---")
            print(last_chunk.usage_metadata)


# --- End Gemini API Call Function ---

# --- QQ Message Fetching and Formatting Logic ---
def get_target_time_range_timestamps():
    now_moment = datetime.datetime.now()
    start_datetime_obj = now_moment - datetime.timedelta(hours=FETCH_HOURS_AGO)
    start_ts = int(start_datetime_obj.timestamp())
    end_ts = int(now_moment.timestamp())
    print(
        f"目标时间范围: 从 {start_datetime_obj.strftime('%Y-%m-%d %H:%M:%S')} (Unix: {start_ts}) (即过去 {FETCH_HOURS_AGO} 小时)")
    print(f"              至 {now_moment.strftime('%Y-%m-%d %H:%M:%S')} (Unix: {end_ts})")
    return start_ts, end_ts


def format_message_content_for_gemini(message_segments, group_id, message_id_context,
                                      image_paths_collector_list, current_image_placeholder_counter):
    text_parts_for_this_message = []
    updated_counter = current_image_placeholder_counter
    if not isinstance(message_segments, list): return "[消息格式错误]", updated_counter

    for segment in message_segments:
        seg_type = segment.get("type")
        seg_data = segment.get("data", {})
        if seg_type == "text":
            text_parts_for_this_message.append(seg_data.get("text", ""))
        elif seg_type == "image":
            image_url = seg_data.get('url')
            qq_file_name = seg_data.get('file', '')
            if image_url:
                processed_image_path, media_info = download_and_process_image_for_gemini(
                    image_url, group_id, qq_file_name, message_id_context
                )
                if processed_image_path:
                    image_paths_collector_list.append(processed_image_path)
                    text_parts_for_this_message.append(f"《图片{updated_counter}{media_info}》")
                    updated_counter += 1
                else:
                    text_parts_for_this_message.append(
                        f"[图片: {qq_file_name if qq_file_name else '未知'}{media_info} (处理失败或不支持)]")
            else:
                text_parts_for_this_message.append(f"[图片: {qq_file_name if qq_file_name else '未知'} (无URL)]")
        elif seg_type == "video":
            qq_file_name = seg_data.get('file', '')
            text_parts_for_this_message.append(f"[视频: {qq_file_name if qq_file_name else '未知'} (帧提取未实现)]")
        elif seg_type == "at":
            text_parts_for_this_message.append(f"@{str(seg_data.get('qq', 'all'))}")
        elif seg_type == "face":
            text_parts_for_this_message.append(f"[表情ID:{seg_data.get('id', '')}]")
        elif seg_type == "reply":
            text_parts_for_this_message.append(f"[回复消息ID:{seg_data.get('id', '')}]")
    return "".join(text_parts_for_this_message), updated_counter


def format_display_message_for_gemini(msg_obj, group_id, image_paths_collector_list, current_image_placeholder_counter):
    msg_time_unix = msg_obj.get("time", 0)
    dt_object = datetime.datetime.fromtimestamp(msg_time_unix)
    time_str = dt_object.strftime("%H:%M:%S")
    sender_info = msg_obj.get("sender", {})
    sender_display = sender_info.get("card", "") or sender_info.get("nickname", "未知用户")
    user_id = msg_obj.get("user_id", "")
    message_id = msg_obj.get("message_id", f"msgid_{msg_obj.get('message_seq', int(time.time() * 1000))}")

    text_content, updated_counter = format_message_content_for_gemini(
        msg_obj.get("message", []), group_id, message_id,
        image_paths_collector_list, current_image_placeholder_counter
    )
    formatted_line = f"{time_str} {sender_display}({user_id}): {text_content}"
    return formatted_line, updated_counter


def fetch_and_prepare_for_gemini(group_id):
    if not genai or not genai_types:
        print("Gemini AI library (genai or genai.types) not available. Exiting.")
        return None, None
    if not PILLOW_AVAILABLE:
        print(
            "警告: Pillow (PIL) 库未安装。GIF图片将无法提取第一帧，相关图片可能不会被发送。请运行 'pip install Pillow' 来启用此功能。")

    start_ts, end_ts = get_target_time_range_timestamps()
    ensure_dir_exists(IMAGE_DOWNLOAD_DIR)
    print(f"正在为Gemini准备群 {group_id} 的消息 (最多 {MAX_MESSAGES_TO_PROCESS} 条)...")

    all_text_parts_for_gemini_prompt = []
    ordered_image_paths_for_gemini = []
    current_image_placeholder_counter = 1
    raw_messages_to_process = []
    collected_message_ids_for_fetch = set()

    current_message_seq_for_api_call = None
    loop_count = 0
    print("  开始从API拉取消息...")
    while True:
        loop_count += 1
        if loop_count > MAX_FETCH_LOOPS:
            print(f"  [警告] 已达到最大API调用次数 ({MAX_FETCH_LOOPS})。停止拉取。");
            break

        if len(raw_messages_to_process) >= MAX_MESSAGES_TO_PROCESS:
            print(
                f"  [信息] 已收集到 {len(raw_messages_to_process)} 条消息，达到 MAX_MESSAGES_TO_PROCESS ({MAX_MESSAGES_TO_PROCESS}) 限制。停止拉取。")
            break

        params = {"group_id": int(group_id)}
        if current_message_seq_for_api_call is not None: params["message_seq"] = int(current_message_seq_for_api_call)
        params["reverseOrder"]='true'
        params["count"]=100
        try:
            response = requests.post(f"{LLONEBOT_API_URL}/get_group_msg_history", json=params, timeout=REQUEST_TIMEOUT)
            print(response.text)
            response.raise_for_status()
            api_data = response.json()
        except Exception as e:
            print(f"  [错误] API请求失败: {e}")
            break

        if not (api_data and api_data.get("status") == "ok" and api_data.get("retcode") == 0):
            print(f"  [错误] API返回不成功: {api_data.get('msg', '未知错误') if api_data else '无响应'}")
            break

        messages_batch = api_data.get("data", {}).get("messages")
        if not messages_batch: print("  [信息] API未返回更多消息。"); break

        batch_added_count = 0
        for msg_obj in messages_batch:
            if len(raw_messages_to_process) >= MAX_MESSAGES_TO_PROCESS:
                break

            msg_id = msg_obj.get("message_id")
            msg_time_unix = msg_obj.get("time", 0)

            if msg_id not in collected_message_ids_for_fetch and start_ts <= msg_time_unix <= end_ts:
                raw_messages_to_process.append(msg_obj)
                collected_message_ids_for_fetch.add(msg_id)
                batch_added_count += 1

        if len(raw_messages_to_process) >= MAX_MESSAGES_TO_PROCESS:
            print(f"  [信息] 在处理批次时达到 MAX_MESSAGES_TO_PROCESS ({MAX_MESSAGES_TO_PROCESS}) 限制。停止拉取。")
            break

        oldest_msg_in_batch = messages_batch[0]
        oldest_msg_in_batch_time = oldest_msg_in_batch.get("time", 0)
        oldest_msg_in_batch_seq = oldest_msg_in_batch.get("message_seq")

        if oldest_msg_in_batch_seq is None:
            print("  [错误] 批次中的第一条消息缺少 'message_seq'。停止拉取。");
            break

        current_message_seq_for_api_call = int(oldest_msg_in_batch_seq)

        if oldest_msg_in_batch_time < start_ts and batch_added_count == 0:
            print(
                f"  [信息] 当前批次最旧消息 ({datetime.datetime.fromtimestamp(oldest_msg_in_batch_time).strftime('%Y-%m-%d %H:%M:%S')}) 早于目标开始时间，且此批次无新相关消息加入。停止拉取。")
            break

        if current_message_seq_for_api_call == 0:
            print("  [信息] API报告 message_seq 已为0，无更早消息。");
            break

        time.sleep(DELAY_BETWEEN_REQUESTS)

    print(
        f"  API拉取完成，共获得 {len(raw_messages_to_process)} 条原始消息进行处理 (设定上限为 {MAX_MESSAGES_TO_PROCESS})。")
    if not raw_messages_to_process:
        print("没有收集到任何在时间范围内的唯一消息。")
        return None, None

    raw_messages_to_process.sort(key=lambda m: (m.get("time", 0), m.get("message_seq", 0)))

    print(f"  消息排序完成。开始格式化 ({len(raw_messages_to_process)} 条) 并下载/处理图片...")

    for msg_obj in raw_messages_to_process:
        formatted_line, current_image_placeholder_counter = format_display_message_for_gemini(
            msg_obj, group_id, ordered_image_paths_for_gemini, current_image_placeholder_counter
        )
        all_text_parts_for_gemini_prompt.append(formatted_line)

    final_text_prompt = GEMINI_PROMPT_PREFIX + "\n".join(
        all_text_parts_for_gemini_prompt)

    return final_text_prompt, ordered_image_paths_for_gemini


# --- End QQ Message Fetching and Formatting Logic ---

# --- Main Execution Block ---
if __name__ == "__main__":
    if not PILLOW_AVAILABLE:
        print("\n警告: Pillow 库未安装，GIF图片的第一帧提取功能将不可用。相关图片可能不会被发送。")
        print("请运行 'pip install Pillow' 来安装。\n")

    if not genai or not genai_types:
        print("错误: google-generativeai 库导入失败。请确保已正确安装。脚本无法继续。")
        exit(1)

    if "YOUR_GEMINI_API_KEY_HERE" in GEMINI_API_KEY_VALUE or \
            not GEMINI_API_KEY_VALUE:
        print("=" * 70)
        print("错误：Gemini API Key 未配置或仍为占位符。")
        print("请在脚本顶部的 GEMINI_API_KEY_VALUE 处填入您真实的Gemini API Key。")
        print("如果您希望通过环境变量设置，请修改脚本对应行为。")
        print("=" * 70)
        exit(1)

    if TARGET_GROUP_ID == 738484049:
        print("=" * 50)
        print(f"提示：您可能正在使用示例群号: {TARGET_GROUP_ID}")
        print(f"将从过去 {FETCH_HOURS_AGO} 小时拉取消息，最多处理 {MAX_MESSAGES_TO_PROCESS} 条。")
        print(f"图片将临时下载到 '{IMAGE_DOWNLOAD_DIR}/group_{TARGET_GROUP_ID}' 目录。")
        print(f"确保 GEMINI_API_KEY_VALUE 已在脚本中正确设置，并且已安装 google-generativeai 和 Pillow。")
        print(f"将使用模型: {GEMINI_MODEL_NAME}")
        print("!!! 安全警告: API密钥当前配置在脚本中。请确保此脚本文件的安全，或改用环境变量。 !!!")
        print("=" * 50)

    aggregated_text, ordered_image_paths = fetch_and_prepare_for_gemini(TARGET_GROUP_ID)
    # print(aggregated_text)
    if aggregated_text is not None and ordered_image_paths is not None:
        send_to_gemini(aggregated_text, ordered_image_paths)
        print(f"\n提示: 处理完成。临时图片位于 '{IMAGE_DOWNLOAD_DIR}' 目录，您可能需要手动清理。")
    else:
        print("未能准备好发送给Gemini的内容或准备过程中出错。")
# --- End Main Execution Block ---