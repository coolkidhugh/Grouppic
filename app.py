
import re
import streamlit as st
from PIL import Image
import pytesseract

# Point pytesseract to the Tesseract executable path if not in system PATH
# For Windows, uncomment and modify the line below if Tesseract isn't found
# pytesseract.pytesseract.tesseract_cmd = r'<path_to_your_tesseract_executable>'

def generate_sales_notification(ocr_text: str) -> str:
    """
    根据 OCR 文本生成销售通知话术。

    Args:
        ocr_text: 包含团队预订信息的 OCR 文本。

    Returns:
        格式化的销售通知话术。
    """
    lines = [line.strip() for line in ocr_text.split('\n') if line.strip()]

    team_name = ""
    arrival_date = ""
    departure_date = ""
    room_details = []  # Stores (number_of_rooms, room_type, price)

    # --- Step 1: Extract basic information (team name, arrival/departure dates) ---
    # Find team name
    for line in lines:
        match = re.search(r'(CON|FIT|WA)\d+/[^\s]+', line)
        if match:
            team_name = match.group(0)
            break

    # Find arrival and departure dates
    dates = []
    for line in lines:
        match_date = re.search(r'(\d{2}/\d{2})\s+\d{2}:\d{2}', line)
        if match_date:
            dates.append(match_date.group(1))
    
    if len(dates) >= 2:
        arrival_date = dates[0]
        departure_date = dates[1]

    # --- Step 2: Extract all detailed room entries ---
    for i, line in enumerate(lines):
        # Look for room type and number pattern (e.g., "STS 32", "JKN 50")
        match_room = re.match(r'([A-Z]{3,4})\s+(\d+)', line)
        if match_room:
            current_room_type = match_room.group(1)
            current_num_rooms = int(match_room.group(2))
            
            # Now, search for the price in subsequent lines within this block.
            # The price is a float and is usually the first token on its line (e.g., "580.00 BRK2, NSV")
            j = i + 1
            while j < len(lines):
                price_match = re.match(r'^(\d+\.\d{2})', lines[j])
                if price_match:
                    price = float(price_match.group(1))
                    room_details.append((current_num_rooms, current_room_type, int(price)))
                    break
                # Stop if we hit another team name or end of a logical block for this room type
                if re.search(r'(CON|FIT|WA)\d+/.+', lines[j]) or "自己" in lines[j] or "团体" in lines[j]:
                    break
                j += 1

    # --- Step 3: Determine team type based on prefix ---
    team_type = "旅游团"
    if team_name.startswith("CON"):
        team_type = "会议团"
    elif team_name.startswith("FIT"):
        team_type = "散客团"
    elif team_name.startswith("WA"):
        team_type = "婚宴团"

    # --- Step 4: Sort room details by number of rooms (ascending) ---
    room_details.sort(key=lambda x: x[0])

    # --- Step 5: Format room details into a string, excluding "间" and "元/间" ---
    formatted_rooms = []
    for num, r_type, price in room_details:
        formatted_rooms.append(f"{num} {r_type} ({price})")
    
    room_string = ""
    if formatted_rooms:
        if len(formatted_rooms) == 1:
            room_string = formatted_rooms[0]
        else:
            room_string = "，".join(formatted_rooms[:-1]) + "，以及" + formatted_rooms[-1]
    
    # --- Step 6: Construct the final speech ---
    formatted_arrival = f"{int(arrival_date.split('/')[0])}月{int(arrival_date.split('/')[1])}日" if arrival_date else ""
    formatted_departure = f"{int(departure_date.split('/')[0])}月{int(departure_date.split('/')[1])}日" if departure_date else ""
    date_range_string = f"{formatted_arrival}-{formatted_departure}" if formatted_arrival and formatted_departure else ""

    speech = f"新增{team_type} {team_name} {date_range_string} {room_string}。销售通知"
    
    return speech

# --- Streamlit Application ---
st.set_page_config(layout="wide")
st.title("📑 OCR 销售通知生成器")
st.markdown("""
通过上传包含团队预订信息的图片，自动识别文本并生成格式化的销售通知话术。
支持根据团队名称前缀自动识别团队类型（CON-会议团, FIT-散客团, WA-婚宴团, 其他默认为旅游团），
并按房间数量从小到大排序房间详情。
""")

uploaded_file = st.file_uploader("上传图片文件", type=["png", "jpg", "jpeg"])

if uploaded_file is not None:
    image = Image.open(uploaded_file)
    st.subheader("原始图片:")
    st.image(image, caption="上传的图片", use_container_width=True)

    # Perform OCR
    ocr_text = pytesseract.image_to_string(image, lang='chi_sim') # 'chi_sim' for simplified Chinese
    
    st.subheader("OCR 识别出的文本:")
    st.text_area("OCR 内容", ocr_text, height=300)

    if st.button("生成销售通知"):
        if ocr_text.strip():
            generated_speech = generate_sales_notification(ocr_text)
            st.subheader("生成的销售通知:")
            st.success(generated_speech)
        else:
            st.warning("OCR 识别文本内容为空，请检查图片质量或尝试手动输入。")
else:
    st.info("请上传一个图片文件来开始。")
