import re
import streamlit as st
from PIL import Image
import pytesseract
import pandas as pd

# Point pytesseract to the Tesseract executable path if not in system PATH
# For Windows, uncomment and modify the line below if Tesseract isn't found
# pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

# --- Configuration ---
TEAM_TYPE_MAP = {
    "CON": "会议团",
    "FIT": "散客团",
    "WA": "婚宴团",
}
DEFAULT_TEAM_TYPE = "旅游团"

# [规则更新] 房型代码“白名单”，只识别列表中的代码
JINLING_ROOM_CODES = [
    "DETN", "DKN", "DQN", "DSKN", "DSTN", "DTN", "EKN", "EKS", "ESN", "ESS",
    "ETN", "ETS", "FSN", "FSB", "FSC", "OTN", "PSA", "PSB", "RSN", "SKN",
    "SQN", "SQS", "SSN", "SSS", "STN", "STS"
]
# [更新] 根据用户提供的图片示例，添加了几个新的房型代码
APAC_ROOM_CODES = [
    "JDEN", "JDKN", "JDKS", "JEKN", "JESN", "JESS", "JETN", "JETS", "JKN",
    "JLKN", "JTN", "JTS", "PSC", "PSD", "VCKN", "VCKD", "SITN", "JEN", "JIS", "JTIN"
]
ALL_ROOM_CODES = JINLING_ROOM_CODES + APAC_ROOM_CODES
ROOM_CODES_REGEX_PATTERN = r'\b(' + '|'.join(ALL_ROOM_CODES) + r')\b'


def generate_sales_notification(ocr_text: str):
    """
    根据 OCR 文本提取预订信息，并以结构化数据返回 (v4 - 表格输出版)。

    Args:
        ocr_text: 包含团队预订信息的 OCR 文本。

    Returns:
        包含预订详情的字典，或错误提示字符串。
    """
    lines = [line.strip() for line in ocr_text.split('\n') if line.strip()]
    if not lines:
        return "错误：OCR 文本为空。"

    team_name = ""
    arrival_date = ""
    departure_date = ""
    room_details = []

    team_name_pattern = re.compile(r'(CON|FIT|WA)\d+/[^\s]+')
    date_pattern = re.compile(r'(\d{2}/\d{2})')
    room_pattern = re.compile(ROOM_CODES_REGEX_PATTERN + r'\s*(\S+)')
    price_pattern = re.compile(r'(\d+\.\d{2})')
    
    # 1. 提取团队名称
    for line in lines:
        match = team_name_pattern.search(line)
        if match:
            team_name = match.group(0)
            break
    if not team_name:
        return "错误：无法从文本中识别出团队名称。"

    # 2. 提取日期
    all_dates = []
    for line in lines:
        all_dates.extend(date_pattern.findall(line))
    
    unique_dates = sorted(list(set(all_dates)))
    if len(unique_dates) >= 2:
        arrival_date, departure_date = unique_dates[0], unique_dates[1]
    elif len(unique_dates) == 1:
        arrival_date = departure_date = unique_dates[0]
    if not arrival_date:
        return "错误：无法从文本中识别出有效的日期。"

    # 3. 提取房型、数量和价格
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
            try:
                price = float(price_match.group(1))
            except (ValueError, IndexError):
                price = None
        
        if price is None:
            for j in range(i + 1, len(lines)):
                next_line = lines[j]
                if team_name_pattern.search(next_line) or re.search(r'自己|团体', next_line):
                    break
                price_match = price_pattern.search(next_line)
                if price_match:
                    try:
                        price = float(price_match.group(1))
                        break
                    except (ValueError, IndexError):
                        continue
        
        if num_rooms > 0 and price is not None:
            room_details.append((room_type, num_rooms, int(price)))

    if not room_details:
        return f"提示：找到了团队 {team_name}，但未能根据规则识别出任何有效的房型和价格信息。"

    # 4. 格式化输出
    team_prefix = team_name[:3]
    team_type = TEAM_TYPE_MAP.get(team_prefix, DEFAULT_TEAM_TYPE)
    room_details.sort(key=lambda x: x[1]) # 按房数排序

    formatted_arrival = f"{int(arrival_date.split('/')[0])}月{int(arrival_date.split('/')[1])}日"
    formatted_departure = f"{int(departure_date.split('/')[0])}月{int(departure_date.split('/')[1])}日"
    date_range_string = f"{formatted_arrival} 至 {formatted_departure}"
    
    # [新功能] 将房间详情转换为 DataFrame 以便表格显示
    df = pd.DataFrame(room_details, columns=['房型', '房数', '定价'])
    
    # 5. 返回结构化数据
    return {
        "team_name": team_name,
        "team_type": team_type,
        "date_range": date_range_string,
        "room_dataframe": df
    }

# --- Streamlit Application (UI 更新为表格显示) ---
st.set_page_config(layout="wide")
st.title("📑 OCR 销售通知生成器 (表格版)")
st.markdown("""
上传预订信息图片，程序将自动识别并提取关键信息，以清晰的摘要和表格形式呈现。
""")

uploaded_file = st.file_uploader("上传图片文件", type=["png", "jpg", "jpeg"])

if uploaded_file is not None:
    image = Image.open(uploaded_file)
    st.subheader("原始图片:")
    st.image(image, caption="上传的图片", use_container_width=True)

    ocr_text = pytesseract.image_to_string(image, lang='chi_sim')
    
    st.subheader("OCR 识别出的文本:")
    st.text_area("OCR 内容", ocr_text, height=200)

    if st.button("生成销售通知"):
        if ocr_text.strip():
            result = generate_sales_notification(ocr_text)
            
            if isinstance(result, str):
                st.warning(result)
            else:
                st.subheader("✅ 预订信息提取成功")
                st.info(f"**团队名称**: {result['team_name']}\n\n"
                        f"**团队类型**: {result['team_type']}\n\n"
                        f"**入住时段**: {result['date_range']}")
                
                st.markdown("---")
                st.markdown("#### 房间预订详情")
                st.dataframe(result['room_dataframe'], use_container_width=True)
        else:
            st.warning("OCR 识别文本内容为空，请检查图片质量或尝试手动输入。")
else:
    st.info("请上传一个图片文件来开始。")

