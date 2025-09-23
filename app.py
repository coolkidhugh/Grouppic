import re
import streamlit as st
from PIL import Image
import pandas as pd
import pytesseract

# --- Tesseract 设置 ---
# 如果 Tesseract 没有在你的系统路径中，请取消下面的注释并设置其可执行文件路径
# 示例 (Windows):
# pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'


# --- 配置信息 ---
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


def extract_booking_info(ocr_text: str):
    """
    从 OCR 文本中提取预订信息。
    """
    lines = [line.strip() for line in ocr_text.split('\n') if line.strip()]
    if not lines:
        return "错误：OCR 文本为空。"

    team_name, arrival_date, departure_date = "", "", ""
    room_details = []

    team_name_pattern = re.compile(r'(CON|FIT|WA)\d+/[^\s]+', re.IGNORECASE)
    date_pattern = re.compile(r'(\d{2}/\d{2})')
    
    spaced_room_codes = [r'\s*'.join(list(code)) for code in ALL_ROOM_CODES]
    room_pattern = re.compile(r'(' + '|'.join(spaced_room_codes) + r')\s*(\d+)')
    
    # [最终修改] 升级价格识别规则，允许小数点前后有空格
    price_pattern = re.compile(r'(\d+\s*\.\s*\d{2})')
    
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
            room_type_with_spaces = match_room.group(1)
            room_type = re.sub(r'\s+', '', room_type_with_spaces)

            num_rooms_str = match_room.group(2)
            num_rooms = int(num_rooms_str)
        except (ValueError, IndexError):
            continue
        
        price = None
        price_match = price_pattern.search(line)
        if price_match:
            try:
                # [最终修改] 在转换前清理价格字符串中的所有空格
                price_str_cleaned = re.sub(r'\s+', '', price_match.group(1))
                price = float(price_str_cleaned)
            except (ValueError, IndexError):
                price = None
        
        if price is None:
            for j in range(i + 1, len(lines)):
                next_line = lines[j]
                if team_name_pattern.search(next_line) or re.search(r'自己|团体', next_line): break
                price_match = price_pattern.search(next_line)
                if price_match:
                    try:
                        # [最终修改] 在转换前清理价格字符串中的所有空格
                        price_str_cleaned = re.sub(r'\s+', '', price_match.group(1))
                        price = float(price_str_cleaned)
                        break
                    except (ValueError, IndexError):
                        continue
        
        if num_rooms > 0 and price is not None:
            room_details.append((room_type, num_rooms, int(price)))

    if not room_details:
        return f"提示：找到了团队 {team_name}，但未能识别出任何有效的房型和价格信息。"

    team_prefix = team_name[:3].upper()
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
    根据最终确认的信息生成销售话术。
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
st.title("📑 OCR 销售通知生成器 (审核版)")
st.markdown("""
**两步走工作流**：
1.  **提取信息**：上传图片，程序自动识别并填充下面的表格。
2.  **审核并生成**：检查并**直接在表格中修改**信息，确认无误后点击“生成最终话术”。
""")

uploaded_file = st.file_uploader("上传图片文件", type=["png", "jpg", "jpeg"])

if uploaded_file is not None:
    image = Image.open(uploaded_file)
    st.image(image, caption="上传的图片", width=300)
    
    if st.button("1. 从图片提取信息"):
        with st.spinner('正在使用 Tesseract 识别中...'):
            try:
                ocr_text = pytesseract.image_to_string(image, lang='chi_sim')
                result = extract_booking_info(ocr_text)
                
                if isinstance(result, str):
                    st.error(result)
                    st.session_state.clear()
                else:
                    st.session_state['booking_info'] = result
                    st.success("信息提取成功！请在下方核对并编辑。")
            except Exception as e:
                st.error(f"处理时发生错误: {e}")
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

