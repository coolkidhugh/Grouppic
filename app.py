import re
import streamlit as st
from PIL import Image
import pandas as pd
import io

# --- SDK 依赖 ---
# 在部署时，Streamlit 会自动根据 requirements.txt 安装这些库
# pip install google-cloud-vision google-auth-oauthlib
try:
    from google.cloud import vision
    from google.oauth2 import service_account
    SDK_AVAILABLE = True
except ImportError:
    SDK_AVAILABLE = False


# --- 配置信息 ---
TEAM_TYPE_MAP = { "CON": "会议团", "FIT": "散客团", "WA": "婚宴团" }
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


def get_ocr_text_from_google(image: Image.Image) -> str:
    """
    调用 Google Cloud Vision API 从图片中识别文本。
    此版本使用 Streamlit Secrets 进行安全凭证管理。
    """
    if not SDK_AVAILABLE:
        st.error("错误：Google SDK 未安装。请确保 requirements.txt 文件包含了 'google-cloud-vision' 和 'google-auth-oauthlib'。")
        return ""
    
    # 检查 Streamlit secrets 是否已配置
    if "google_credentials" not in st.secrets:
        st.error("错误：Google API 凭证未在 Streamlit Cloud 的 Secrets 中配置。")
        st.info("请在部署设置的 'Advanced settings' -> 'Secrets' 区域粘贴你的 Google JSON 密钥内容。")
        return ""

    try:
        # 从 Streamlit secrets 加载凭证
        creds_dict = st.secrets["google_credentials"]
        credentials = service_account.Credentials.from_service_account_info(creds_dict)
        client = vision.ImageAnnotatorClient(credentials=credentials)

        # 将 PIL Image 对象转换为字节流
        buffered = io.BytesIO()
        image.save(buffered, format="PNG")
        content = buffered.getvalue()

        image_for_api = vision.Image(content=content)
        
        # 调用文本检测 API
        response = client.text_detection(image=image_for_api)
        if response.error.message:
            raise Exception(
                f"{response.error.message}\nFor more info, check: "
                "https://cloud.google.com/apis/design/errors"
            )
        
        return response.full_text_annotation.text
    except Exception as e:
        st.error(f"调用 Google Cloud Vision API 失败: {e}")
        return ""


def extract_booking_info(ocr_text: str):
    """
    从 OCR 文本中提取预订信息。
    """
    lines = [line.strip() for line in ocr_text.split('\n') if line.strip()]
    if not lines: return "错误：OCR 文本为空。"

    team_name, arrival_date, departure_date = "", "", ""
    room_details = []

    team_name_pattern = re.compile(r'(CON|FIT|WA)\d+/[^\s]+', re.IGNORECASE)
    date_pattern = re.compile(r'(\d{1,2}/\d{1,2})')
    spaced_room_codes = [r'\s*'.join(list(code)) for code in ALL_ROOM_CODES]
    room_pattern = re.compile(r'(' + '|'.join(spaced_room_codes) + r')\s*(\d+)', re.IGNORECASE)
    price_pattern = re.compile(r'(\d+\s*\.\s*\d{2})')

    for line in lines:
        if not team_name:
            match = team_name_pattern.search(line)
            if match: team_name = match.group(0)
    if not team_name: return "错误：无法识别出团队名称。"

    all_dates = [d for line in lines for d in date_pattern.findall(line)]
    unique_dates = sorted(list(set(all_dates)))
    if len(unique_dates) >= 2: arrival_date, departure_date = unique_dates[0], unique_dates[1]
    elif len(unique_dates) == 1: arrival_date = departure_date = unique_dates[0]
    if not arrival_date: return "错误：无法识别出有效的日期。"

    for i, line in enumerate(lines):
        match_room = room_pattern.search(line)
        if not match_room: continue
        try:
            room_type = re.sub(r'\s+', '', match_room.group(1)).upper()
            num_rooms = int(match_room.group(2))
        except (ValueError, IndexError): continue
        
        price = None
        price_match = price_pattern.search(line)
        if price_match:
            try: price = float(re.sub(r'\s+', '', price_match.group(1)))
            except (ValueError, IndexError): price = None
        
        if price is None:
            for j in range(i + 1, len(lines)):
                next_line = lines[j]
                if team_name_pattern.search(next_line) or re.search(r'自己|团体', next_line, re.IGNORECASE): break
                price_match = price_pattern.search(next_line)
                if price_match:
                    try:
                        price = float(re.sub(r'\s+', '', price_match.group(1)))
                        break
                    except (ValueError, IndexError): continue
        
        if num_rooms > 0 and price is not None:
            room_details.append((room_type, num_rooms, int(price)))

    if not room_details: return f"提示：找到了团队 {team_name}，但未能识别出任何有效的房型和价格信息。"

    team_prefix = team_name[:3].upper()
    team_type = TEAM_TYPE_MAP.get(team_prefix, DEFAULT_TEAM_TYPE)
    room_details.sort(key=lambda x: x[1])
    
    # 格式化日期
    try:
        arr_month, arr_day = map(int, arrival_date.split('/'))
        dep_month, dep_day = map(int, departure_date.split('/'))
        formatted_arrival = f"{arr_month}月{arr_day}日"
        formatted_departure = f"{dep_month}月{dep_day}日"
    except ValueError:
        return "错误：日期格式无法解析。"

    df = pd.DataFrame(room_details, columns=['房型', '房数', '定价'])
    return {
        "team_name": team_name, "team_type": team_type,
        "arrival_date": formatted_arrival, "departure_date": formatted_departure,
        "room_dataframe": df
    }

def format_notification_speech(team_name, team_type, arrival_date, departure_date, room_df):
    date_range_string = f"{arrival_date}至{departure_date}"
    room_details = room_df.to_dict('records')
    formatted_rooms = [f"{item['房数']}间{item['房型']}({item['定价']}元)" for item in room_details]
    room_string = ("，".join(formatted_rooms[:-1]) + "，以及" + formatted_rooms[-1]) if len(formatted_rooms) > 1 else (formatted_rooms[0] if formatted_rooms else "无房间详情")
    return f"新增{team_type} {team_name} {date_range_string} {room_string}。销售通知"

# --- Streamlit Application ---
st.set_page_config(layout="wide")
st.title("📑 OCR 销售通知生成器 (Google Cloud Vision 版)")
st.markdown("""
**两步走工作流**：
1.  **提取信息**：上传图片，程序将调用 **Google Cloud Vision API** 识别并填充表格。
2.  **审核并生成**：检查并**直接在表格中修改**信息，确认无误后点击“生成最终话术”。
""")

uploaded_file = st.file_uploader("上传图片文件", type=["png", "jpg", "jpeg"])

if uploaded_file is not None:
    image = Image.open(uploaded_file)
    st.image(image, caption="上传的图片", width=300)
    
    if st.button("1. 从图片提取信息 (Google Cloud OCR)"):
        with st.spinner('正在调用 Google Cloud Vision API 识别中...'):
            ocr_text = get_ocr_text_from_google(image)
            if ocr_text:
                result = extract_booking_info(ocr_text)
                if isinstance(result, str):
                    st.error(result)
                    st.session_state.clear()
                else:
                    st.session_state['booking_info'] = result
                    st.success("信息提取成功！请在下方核对并编辑。")

if 'booking_info' in st.session_state:
    info = st.session_state['booking_info']
    st.markdown("---")
    st.subheader("2. 核对与编辑信息")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        info['team_name'] = st.text_input("团队名称", value=info['team_name'])
    with col2:
        info['team_type'] = st.selectbox("团队类型", options=list(TEAM_TYPE_MAP.values()) + [DEFAULT_TEAM_TYPE], index=(list(TEAM_TYPE_MAP.values()) + [DEFAULT_TEAM_TYPE]).index(info['team_type']))
    with col3:
        arrival = st.text_input("到达日期", value=info['arrival_date'])
    with col4:
        departure = st.text_input("离开日期", value=info['departure_date'])

    st.markdown("##### 房间详情 (可直接在表格中编辑)")
    edited_df = st.data_editor(info['room_dataframe'], num_rows="dynamic", use_container_width=True)

    if st.button("✅ 生成最终话术"):
        final_speech = format_notification_speech(info['team_name'], info['team_type'], arrival, departure, edited_df)
        st.subheader("🎉 生成成功！")
        st.success(final_speech)
        st.code(final_speech, language=None)

