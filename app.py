import re
import streamlit as st
from PIL import Image
import pandas as pd
import io

# --- SDK 依赖 ---
# requirements.txt 需要包含: google-cloud-vision, google-auth-oauthlib, pandas, streamlit
try:
    from google.cloud import vision
    from google.oauth2 import service_account
    GOOGLE_SDK_AVAILABLE = True
except ImportError:
    GOOGLE_SDK_AVAILABLE = False

# --- 配置信息 ---
TEAM_TYPE_MAP = { "CON": "会议团", "FIT": "散客团", "WA": "婚宴团" }
DEFAULT_TEAM_TYPE = "旅游团"
ALL_ROOM_CODES = [
    "DETN", "DKN", "DQN", "DSKN", "DSTN", "DTN", "EKN", "EKS", "ESN", "ESS",
    "ETN", "ETS", "FSN", "FSB", "FSC", "OTN", "PSA", "PSB", "RSN", "SKN",
    "SQN", "SQS", "SSN", "SSS", "STN", "STS", "JDEN", "JDKN", "JDKS", "JEKN",
    "JESN", "JESS", "JETN", "JETS", "JKN", "JLKN", "JTN", "JTS", "PSC", "PSD",
    "VCKN", "VCKD", "SITN", "JEN", "JIS", "JTIN"
]

# --- 登录检查函数 ---
def check_password():
    """返回 True 如果用户已登录, 否则返回 False."""
    def login_form():
        """显示登录表单。"""
        with st.form("Credentials"):
            st.text_input("用户名", key="username")
            st.text_input("密码", type="password", key="password")
            st.form_submit_button("登录", on_click=password_entered)

    def password_entered():
        """检查密码是否正确。"""
        app_username = st.secrets.get("app_credentials", {}).get("username")
        app_password = st.secrets.get("app_credentials", {}).get("password")

        if st.session_state["username"] == app_username and st.session_state["password"] == app_password:
            st.session_state["password_correct"] = True
            del st.session_state["password"]
            del st.session_state["username"]
        else:
            st.session_state["password_correct"] = False

    if not st.secrets.get("app_credentials", {}).get("username") or not st.secrets.get("app_credentials", {}).get("password"):
        st.error("错误：应用用户名和密码未在 Streamlit Secrets 中配置。")
        return False

    if st.session_state.get("password_correct", False):
        return True

    login_form()
    if "password_correct" in st.session_state and not st.session_state.password_correct:
        st.error("😕 用户名或密码不正确。")
    return False

# --- OCR 引擎函数 (已更新为文档模式) ---
def get_ocr_text_from_google(image: Image.Image) -> str:
    if not GOOGLE_SDK_AVAILABLE:
        st.error("错误：Google SDK 未安装。请确保 requirements.txt 文件配置正确。")
        return None
    if "google_credentials" not in st.secrets:
        st.error("错误：Google API 凭证未在 Streamlit Cloud 的 Secrets 中配置。")
        return None
    try:
        creds_dict = st.secrets["google_credentials"]
        credentials = service_account.Credentials.from_service_account_info(creds_dict)
        client = vision.ImageAnnotatorClient(credentials=credentials)
        buffered = io.BytesIO()
        image.save(buffered, format="PNG")
        content = buffered.getvalue()
        image_for_api = vision.Image(content=content)
        response = client.document_text_detection(image=image_for_api)
        if response.error.message: raise Exception(f"{response.error.message}")
        return response.full_text_annotation.text
    except Exception as e:
        st.error(f"调用 Google Cloud Vision API 失败: {e}")
        return None

# --- [全新重构] 信息提取与格式化 ---
def extract_booking_info(ocr_text: str):
    """
    使用全新的、更健壮的启发式逻辑从 OCR 文本中提取信息。
    它不再依赖于严格的行格式，而是查找关键字并根据它们在文本中的邻近度进行关联。
    """
    team_name_pattern = re.compile(r'((?:CON|FIT|WA)\d+\s*/\s*[\u4e00-\u9fa5\w]+)', re.IGNORECASE)
    date_pattern = re.compile(r'(\d{1,2}/\d{1,2})')
    
    # 1. 提取基本信息（团队名称和日期）
    team_name_match = team_name_pattern.search(ocr_text)
    if not team_name_match: return "错误：无法识别出团队名称。"
    team_name = re.sub(r'\s*/\s*', '/', team_name_match.group(1).strip())

    all_dates = date_pattern.findall(ocr_text)
    unique_dates = sorted(list(set(all_dates)))
    if not unique_dates: return "错误：无法识别出有效的日期。"
    arrival_date = unique_dates[0]
    departure_date = unique_dates[-1] # 取第一个和最后一个作为到达和离开日期

    # 2. 找出所有可能的“线索”（房型+房数，以及价格）
    room_codes_pattern_str = '|'.join(ALL_ROOM_CODES)
    # 这个模式寻找一个房型代码，后面紧跟着一个数字
    room_finder_pattern = re.compile(f'({room_codes_pattern_str})\\s*(\\d+)', re.IGNORECASE)
    # 这个模式寻找所有看起来像价格的数字（3位或更多，可选小数）
    price_finder_pattern = re.compile(r'\b(\d{3,}(?:\.\d{2})?)\b')

    # 找到所有线索及其在文本中的位置
    found_rooms = [(m.group(1).upper(), int(m.group(2)), m.span()) for m in room_finder_pattern.finditer(ocr_text)]
    found_prices = [(float(m.group(1)), m.span()) for m in price_finder_pattern.finditer(ocr_text)]
    
    # 3. 智能关联：为每个房型找到最匹配的价格
    room_details = []
    available_prices = list(found_prices)

    for room_type, num_rooms, room_span in found_rooms:
        best_price = None
        best_price_index = -1
        min_distance = float('inf')

        # 寻找距离最近的、尚未被匹配的价格
        for i, (price_val, price_span) in enumerate(available_prices):
            # 价格必须出现在房型之后
            if price_span[0] > room_span[1]:
                distance = price_span[0] - room_span[1]
                if distance < min_distance:
                    min_distance = distance
                    best_price = price_val
                    best_price_index = i
        
        # 如果找到了匹配的价格，就记录下来，并从可用价格中移除
        if best_price is not None and best_price > 0:
            room_details.append((room_type, num_rooms, int(best_price)))
            available_prices.pop(best_price_index)

    if not room_details:
        return f"提示：找到了团队 {team_name}，但未能自动匹配任何有效的房型和价格。请检查原始文本并手动填写。"

    # 4. 格式化并返回结果
    team_prefix = team_name[:3].upper()
    team_type = TEAM_TYPE_MAP.get(team_prefix, DEFAULT_TEAM_TYPE)
    room_details.sort(key=lambda x: x[1]) # 按房数排序
    
    try:
        arr_month, arr_day = map(int, arrival_date.split('/'))
        dep_month, dep_day = map(int, departure_date.split('/'))
        formatted_arrival = f"{arr_month}月{arr_day}日"
        formatted_departure = f"{dep_month}月{dep_day}日"
    except ValueError:
        return "错误：日期格式无法解析。"
        
    df = pd.DataFrame(room_details, columns=['房型', '房数', '定价'])
    return {"team_name": team_name, "team_type": team_type, "arrival_date": formatted_arrival, "departure_date": formatted_departure, "room_dataframe": df}

def format_notification_speech(team_name, team_type, arrival_date, departure_date, room_df):
    date_range_string = f"{arrival_date}至{departure_date}"
    room_details = room_df.to_dict('records')
    formatted_rooms = [f"{item['房数']}间{item['房型']}({item['定价']}元)" for item in room_details]
    room_string = ("，".join(formatted_rooms[:-1]) + "，以及" + formatted_rooms[-1]) if len(formatted_rooms) > 1 else (formatted_rooms[0] if formatted_rooms else "无房间详情")
    return f"新增{team_type} {team_name} {date_range_string} {room_string}。销售通知"

# --- Streamlit 主应用 ---
st.set_page_config(layout="wide", page_title="OCR 销售通知生成器")
st.title("📑 OCR 销售通知生成器")

if check_password():
    st.markdown("""
    **全新工作流**：
    1.  **上传图片，点击提取**：程序将调用 Google OCR 并将**原始识别文本**显示在下方。
    2.  **自动填充与人工修正**：程序会尝试自动填充结构化信息。您可以**参照原始文本**，直接在表格中修改，确保信息完全准确。
    3.  **生成话术**：确认无误后，生成最终话术。
    """)

    uploaded_file = st.file_uploader("上传图片文件", type=["png", "jpg", "jpeg"])

    if uploaded_file is not None:
        image = Image.open(uploaded_file)
        st.image(image, caption="上传的图片", width=300)
        
        if st.button("1. 从图片提取信息 (Google Cloud OCR)"):
            st.session_state.clear()
            with st.spinner('正在调用 Google Cloud Vision API 识别中...'):
                ocr_text = get_ocr_text_from_google(image)
                if ocr_text:
                    st.session_state['raw_ocr_text'] = ocr_text
                    result = extract_booking_info(ocr_text)
                    if isinstance(result, str):
                        st.warning(f"自动解析提示：{result}")
                        st.info("请参考下方识别出的原始文本，手动填写信息。")
                        empty_df = pd.DataFrame(columns=['房型', '房数', '定价'])
                        st.session_state['booking_info'] = {
                            "team_name": "", "team_type": DEFAULT_TEAM_TYPE, 
                            "arrival_date": "", "departure_date": "", 
                            "room_dataframe": empty_df
                        }
                    else:
                        st.session_state['booking_info'] = result
                        st.success("信息提取成功！请在下方核对并编辑。")

    if 'booking_info' in st.session_state:
        info = st.session_state['booking_info']
        
        if 'raw_ocr_text' in st.session_state:
            st.markdown("---")
            st.subheader("原始识别结果 (供参考)")
            st.text_area("您可以从这里复制内容来修正下面的表格", st.session_state['raw_ocr_text'], height=200)

        st.markdown("---")
        st.subheader("核对与编辑信息")
        col1, col2, col3, col4 = st.columns(4)
        with col1: info['team_name'] = st.text_input("团队名称", value=info['team_name'])
        with col2: info['team_type'] = st.selectbox("团队类型", options=list(TEAM_TYPE_MAP.values()) + [DEFAULT_TEAM_TYPE], index=(list(TEAM_TYPE_MAP.values()) + [DEFAULT_TEAM_TYPE]).index(info['team_type']))
        with col3: arrival = st.text_input("到达日期", value=info['arrival_date'])
        with col4: departure = st.text_input("离开日期", value=info['departure_date'])
        st.markdown("##### 房间详情 (可直接在表格中编辑)")
        edited_df = st.data_editor(info['room_dataframe'], num_rows="dynamic", use_container_width=True)
        if st.button("✅ 生成最终话术"):
            final_speech = format_notification_speech(info['team_name'], info['team_type'], arrival, departure, edited_df)
            st.subheader("🎉 生成成功！")
            st.success(final_speech)
            st.code(final_speech, language=None)

