
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
    team_name_found_idx = -1
    for idx, line in enumerate(lines):
        match = re.search(r'(CON|FIT|WA)\d+/[^\s]+', line)
        if match:
            team_name = match.group(0)
            team_name_found_idx = idx
            break

    # Search for arrival and departure dates starting from the line where team_name was found, or from the beginning
    search_start_line_for_dates = team_name_found_idx if team_name_found_idx != -1 else 0
    
    for i in range(search_start_line_for_dates, len(lines)):
        line = lines[i]
        # Find all date-time patterns on the line (e.g., 12/19 18:00)
        all_date_time_matches = re.findall(r'(\d{2}/\d{2})\s+\d{2}:\d{2}', line)
        if len(all_date_time_matches) >= 2:
            arrival_date = all_date_time_matches[0] # Get the MM/DD part
            departure_date = all_date_time_matches[1] # Get the MM/DD part
            break # Found the group dates, stop searching

    # If only one date is found, assume departure is the same as arrival (addresses 12月19日-12月19日 issue)
    if arrival_date and not departure_date:
        departure_date = arrival_date

    # --- Step 2: Extract all detailed room entries ---
    for i, line in enumerate(lines):
        # Use re.search and more flexible whitespace
        # Room type and number (e.g., "STS 32", "JKN 50")
        # Use negative lookahead to ensure the number is not part of a date/time/price (e.g., 1 from 12/19 1)
        match_room_and_count = re.search(r'([A-Z]{3,4})\s*(\d+)\s*(?![:/.])', line)

        if match_room_and_count:
            current_room_type = match_room_and_count.group(1)
            current_num_rooms = int(match_room_and_count.group(2))
            
            price = None
            # First, try to find price on the same line (anywhere on the line)
            price_match_on_line = re.search(r'(\d+\.\d{2})', line)
            if price_match_on_line:
                price = float(price_match_on_line.group(1))
            
            # If not found on same line, look in subsequent lines (starting at line start)
            if price is None:
                j = i + 1
                while j < len(lines):
                    price_match_subsequent = re.search(r'^(\d+\.\d{2})', lines[j])
                    if price_match_subsequent:
                        price = float(price_match_subsequent.group(1))
                        break
                    # Stop if we hit another team name or end of a logical block for this room type
                    # Fixed regex for the break condition
                    if re.search(r'(CON|FIT|WA)\d+/.+|自己|团体', lines[j]):
                        break
                    j += 1
            
            if current_num_rooms > 0 and price is not None:
                room_details.append((current_num_rooms, current_room_type, int(price)))

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
