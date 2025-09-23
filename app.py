import re
import streamlit as st
from PIL import Image
import pytesseract

# Point pytesseract to the Tesseract executable path if not in system PATH
# For Windows, uncomment and modify the line below if Tesseract isn't found
# pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

# --- Configuration ---
# 将团队类型配置提取出来，方便未来扩展
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
APAC_ROOM_CODES = [
    "JDEN", "JDKN", "JDKS", "JEKN", "JESN", "JESS", "JETN", "JETS", "JKN",
    "JLKN", "JTN", "JTS", "PSC", "PSD", "VCKN", "VCKD"
]
ALL_ROOM_CODES = JINLING_ROOM_CODES + APAC_ROOM_CODES
# 创建一个动态的、精确的房型正则表达式
# \b 确保我们匹配完整的单词 (e.g., "STS" 而不是 "STATUS" 的一部分)
ROOM_CODES_REGEX_PATTERN = r'\b(' + '|'.join(ALL_ROOM_CODES) + r')\b'


def generate_sales_notification(ocr_text: str) -> str:
    """
    根据 OCR 文本生成销售通知话术 (v3 - 规则增强版)。

    Args:
        ocr_text: 包含团队预订信息的 OCR 文本。

    Returns:
        格式化的销售通知话术或错误提示。
    """
    lines = [line.strip() for line in ocr_text.split('\n') if line.strip()]
    if not lines:
        return "错误：OCR 文本为空。"

    team_name = ""
    arrival_date = ""
    departure_date = ""
    room_details = []  # Stores (number_of_rooms, room_type, price)

    # --- 正则表达式模式定义 ---
    team_name_pattern = re.compile(r'(CON|FIT|WA)\d+/[^\s]+')
    date_pattern = re.compile(r'(\d{2}/\d{2})')
    # [规则更新] 使用基于“白名单”的精确房型正则
    # 模式会寻找一个合法的房型代码，然后捕捉下一个非空字符串作为可能的房数
    room_pattern = re.compile(ROOM_CODES_REGEX_PATTERN + r'\s*(\S+)')
    price_pattern = re.compile(r'(\d+\.\d{2})')
    
    # --- 1. 提取团队名称 ---
    for line in lines:
        match = team_name_pattern.search(line)
        if match:
            team_name = match.group(0)
            break
    
    if not team_name:
        return "错误：无法从文本中识别出团队名称。"

    # --- 2. 提取入住和离店日期 ---
    all_dates = []
    for line in lines:
        all_dates.extend(date_pattern.findall(line))
    
    unique_dates = sorted(list(set(all_dates)))
    if len(unique_dates) >= 2:
        arrival_date = unique_dates[0]
        departure_date = unique_dates[1]
    elif len(unique_dates) == 1:
        arrival_date = departure_date = unique_dates[0]

    if not arrival_date:
        return "错误：无法从文本中识别出有效的日期。"

    # --- 3. 提取房型、数量和价格 ---
    for i, line in enumerate(lines):
        match_room = room_pattern.search(line)
        if not match_room:
            continue
            
        try:
            room_type = match_room.group(1)
            num_rooms_str = match_room.group(2)
            # [规则更新] 尝试将识别出的房数（可能是错别字）转为整数
            num_rooms = int(num_rooms_str)
        except (ValueError, IndexError):
            # 如果房数不是有效数字(例如 OCR 识别成'于'或'工')，则忽略此行
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
            room_details.append((num_rooms, room_type, int(price))) # 价格取整

    if not room_details:
        return f"提示：找到了团队 {team_name}，但未能根据规则识别出任何有效的房型和价格信息。请检查 OCR 识别文本。"

    # --- 4. 格式化输出 ---
    team_prefix = team_name[:3]
    team_type = TEAM_TYPE_MAP.get(team_prefix, DEFAULT_TEAM_TYPE)

    room_details.sort(key=lambda x: x[0])

    formatted_rooms = [f"{num} {r_type} ({price})" for num, r_type, price in room_details]
    if len(formatted_rooms) > 1:
        room_string = "，".join(formatted_rooms[:-1]) + "，以及" + formatted_rooms[-1]
    else:
        room_string = formatted_rooms[0]

    # [规则更新] 格式化日期为 XX月xx日
    formatted_arrival = f"{int(arrival_date.split('/')[0])}月{int(arrival_date.split('/')[1])}日"
    formatted_departure = f"{int(departure_date.split('/')[0])}月{int(departure_date.split('/')[1])}日"
    date_range_string = f"{formatted_arrival}-{formatted_departure}"

    # --- 5. 拼接最终话术 ---
    speech = f"新增{team_type} {team_name} {date_range_string} {room_string}。销售通知"
    return speech

# --- Streamlit Application (UI 保持不变) ---
st.set_page_config(layout="wide")
st.title("📑 OCR 销售通知生成器 (规则增强版)")
st.markdown("""
通过上传包含团队预订信息的图片，自动识别文本并生成格式化的销售通知话术。
**新功能**：内置了精确的房型代码“白名单”，可以更准确地提取信息，并忽略无关内容。
""")

uploaded_file = st.file_uploader("上传图片文件", type=["png", "jpg", "jpeg"])

if uploaded_file is not None:
    image = Image.open(uploaded_file)
    st.subheader("原始图片:")
    st.image(image, caption="上传的图片", use_container_width=True)

    ocr_text = pytesseract.image_to_string(image, lang='chi_sim')
    
    st.subheader("OCR 识别出的文本:")
    st.text_area("OCR 内容", ocr_text, height=300)

    if st.button("生成销售通知"):
        if ocr_text.strip():
            generated_speech = generate_sales_notification(ocr_text)
            if "错误" in generated_speech or "提示" in generated_speech:
                st.warning(generated_speech)
            else:
                st.subheader("生成的销售通知:")
                st.success(generated_speech)
        else:
            st.warning("OCR 识别文本内容为空，请检查图片质量或尝试手动输入。")
else:
    st.info("请上传一个图片文件来开始。")

