import re
import streamlit as st
from PIL import Image
import pandas as pd
import io
import os

# --- [新功能] Google Cloud Vision API 集成 ---
from google.cloud import vision

# --- !!! 重要设置 !!! ---
# 在运行前，你需要设置 Google Cloud 的认证密钥。
# 1. 前往 Google Cloud Platform, 创建一个项目并启用 Vision API。
# 2. 创建一个服务账号 (Service Account) 并下载 JSON 密钥文件。
# 3. 将下载的 JSON 文件的完整路径替换下面的字符串。
# 示例 (Windows): "C:\\Users\\YourUser\\Documents\\my-google-cloud-key.json"
# 示例 (macOS/Linux): "/home/user/my-google-cloud-key.json"

GOOGLE_API_KEY_PATH = "请在这里粘贴你的Google Cloud API密钥JSON文件的完整路径"

# 检查密钥路径是否已设置
if not os.path.exists(GOOGLE_API_KEY_PATH):
    st.error("Google Cloud API 密钥路径无效！请在代码中设置正确的 GOOGLE_API_KEY_PATH。")
    st.stop()
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = GOOGLE_API_KEY_PATH
# --- 设置结束 ---


# --- Configuration (这部分逻辑不变) ---
TEAM_TYPE_MAP = {
    "CON": "会议团",
    "FIT": "散客团",
    "WA": "婚宴团",
}
DEFAULT_TEAM_TYPE = "旅游团"

JINLING_ROOM_CODES = [
    "DETN", "DKN", "DQN", "DSKN", "DSTN", "DTN", "EKN", "EKS", "ESN", "ESS",
    "ETN", "ETS", "FSN", "FSB", "FSC", "OTN", "PSA", "PSB", "RSN", "SKN",
    "SQN", "SQS", "SSN", "SSS", "STN", "STS"
]
APAC_ROOM_CODES = [
    "JDEN", "JDKN", "JDKS", "JEKN", "JESN", "JESS", "JETN", "JETS", "JKN",
    "JLKN", "JTN", "JTS", "PSC", "PSD", "VCKN", "VCKD", "SITN", "JEN", "JIS", "JTIN"
]
ALL_ROOM_CODES = JINLING_ROOM_CODES + APAC_ROOM_CODES
ROOM_CODES_REGEX_PATTERN = r'\b(' + '|'.join(ALL_ROOM_CODES) + r')\b'


def perform_google_vision_ocr(image_bytes: bytes) -> str:
    """
    使用 Google Cloud Vision API 对给定的图片字节进行 OCR。
    """
    client = vision.ImageAnnotatorClient()
    image = vision.Image(content=image_bytes)
    
    response = client.text_detection(image=image)
    if response.error.message:
        raise Exception(f"Google Vision API 错误: {response.error.message}")
        
    return response.full_text_annotation.text


def extract_booking_info(ocr_text: str):
    """
    从 OCR 文本中提取预订信息。(此函数逻辑不变)
    """
    lines = [line.strip() for line in ocr_text.split('\n') if line.strip()]
    if not lines:
        return "错误：OCR 文本为空。"

    team_name, arrival_date, departure_date = "", "", ""
    room_details = []

    team_name_pattern = re.compile(r'(CON|FIT|WA)\d+/[^\s]+', re.IGNORECASE) # [修改] 增加 re.IGNORECASE 忽略大小写
    date_pattern = re.compile(r'(\d{2}/\d{2})')
    room_pattern = re.compile(ROOM_CODES_REGEX_PATTERN + r'\s*(\S+)')
    price_pattern = re.compile(r'(\d+\.\d{2})')
    
    for line in lines:
        if not team_name:
            match = team_name_pattern.search(line)
            if match:
                team_name = match.group(0)
    if not team_name:
        return "错误：无法识别出团队名称。"

    all_dates = []
    for line in lines:
        all_dates.extend(date_pattern.findall(line))
    
    unique_dates = sorted(list(set(all_dates)))
    if len(unique_dates) >= 2:
        arrival_date, departure_date = unique_dates[0], unique_dates[1]
    elif len(unique_dates) == 1:
        arrival_date = departure_date = unique_dates[0]
    if not arrival_date:
        return "错误：无法识别出有效的日期。"

    for i, line in enumerate(lines):
        match_room = room_pattern.search(line)
        if not match_room:
            continue
        try:
            room_type = match_room.group(1)
            num_rooms = int(match_room.group(2))
        except (ValueError, IndexError):
            continue
        
        price = None
        price_match = price_pattern.search(line)
        if price_match:
            try: price = float(price_match.group(1))
            except (ValueError, IndexError): price = None
        
        if price is None:
            for j in range(i + 1, len(lines)):
                next_line = lines[j]
                if team_name_pattern.search(next_line) or re.search(r'自己|团体', next_line): break
                price_match = price_pattern.search(next_line)
                if price_match:
                    try:
                        price = float(price_match.group(1))
                        break
                    except (ValueError, IndexError): continue
        
        if num_rooms > 0 and price is not None:
            room_details.append((room_type, num_rooms, int(price)))

    if not room_details:
        return f"提示：找到了团队 {team_name}，但未能识别出任何有效的房型和价格信息。"

    team_prefix = team_name[:3]
    team_type = TEAM_TYPE_MAP.get(team_prefix, DEFAULT_TEAM_TYPE)
    room_details.sort(key=lambda x: x[1])

    formatted_arrival = f"{int(arrival_date.split('/')[0])}月{int(arrival_date.split('/')[1])}日"
    formatted_departure = f"{int(departure_date.split('/')[0])}月{int(departure_date.split('/')[1])}日"
    
    df = pd.DataFrame(room_details, columns=['房型', '房数', '定价'])
    
    return {
        "team_name": team_name, "team_type": team_type,
        "arrival_date": formatted_arrival, "departure_date": formatted_departure,
        "room_dataframe": df
    }

def format_notification_speech(team_name, team_type, arrival_date, departure_date, room_df):
    """
    根据最终确认的信息生成销售话术。(此函数逻辑不变)
    """
    date_range_string = f"{arrival_date}至{departure_date}"
    
    room_details = room_df.to_dict('records')
    formatted_rooms = [f"{item['房数']} {item['房型']} ({item['定价']})" for item in room_details]
    
    if len(formatted_rooms) > 1:
        room_string = "，".join(formatted_rooms[:-1]) + "，以及" + formatted_rooms[-1]
    elif formatted_rooms:
        room_string = formatted_rooms[0]
    else:
        room_string = "无房间详情"

    return f"新增{team_type} {team_name} {date_range_string} {room_string}。销售通知"

# --- Streamlit Application ---
st.set_page_config(layout="wide")
st.title("📑 OCR 销售通知生成器 (Google Vision API 版)")
st.markdown("""
**两步走工作流**：
1.  **提取信息**：上传图片，程序将调用 **Google Vision API** 识别并填充下面的表格。
2.  **审核并生成**：检查并**直接在表格中修改**信息，确认无误后点击“生成最终话术”。
""")

uploaded_file = st.file_uploader("上传图片文件", type=["png", "jpg", "jpeg"])

if uploaded_file is not None:
    image = Image.open(uploaded_file)
    st.image(image, caption="上传的图片", width=300)
    
    # 将图片转换为字节流以供 API 使用
    img_byte_arr = io.BytesIO()
    image.save(img_byte_arr, format='PNG')
    image_bytes = img_byte_arr.getvalue()
    
    if st.button("1. 从图片提取信息 (Google Vision)"):
        with st.spinner('正在调用 Google Vision API 识别中...'):
            try:
                ocr_text = perform_google_vision_ocr(image_bytes)
                result = extract_booking_info(ocr_text)
                
                if isinstance(result, str):
                    st.error(result)
                    st.session_state.clear()
                else:
                    st.session_state['booking_info'] = result
                    st.success("信息提取成功！请在下方核对并编辑。")
            except Exception as e:
                st.error(f"调用 API 时发生错误: {e}")
                st.session_state.clear()


if 'booking_info' in st.session_state:
    info = st.session_state['booking_info']
    st.markdown("---")
    st.subheader("2. 核对与编辑信息")

    col1, col2, col3 = st.columns(3)
    with col1:
        info['team_name'] = st.text_input("团队名称", value=info['team_name'])
    with col2:
        info['team_type'] = st.selectbox("团队类型", options=list(TEAM_TYPE_MAP.values()) + [DEFAULT_TEAM_TYPE], index=(list(TEAM_TYPE_MAP.values()) + [DEFAULT_TEAM_TYPE]).index(info['team_type']))
    with col3:
        arrival = st.text_input("到达日期", value=info['arrival_date'])
        departure = st.text_input("离开日期", value=info['departure_date'])

    st.markdown("##### 房间详情 (可直接在表格中编辑)")
    edited_df = st.data_editor(info['room_dataframe'], num_rows="dynamic", use_container_width=True)

    if st.button("✅ 生成最终话术"):
        final_speech = format_notification_speech(
            info['team_name'], info['team_type'], arrival, departure, edited_df
        )
        st.subheader("🎉 生成成功！")
        st.success(final_speech)
        st.code(final_speech, language=None)


