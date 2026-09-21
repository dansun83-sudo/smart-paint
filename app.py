import streamlit as st
from google import genai
from google.genai.errors import APIError
from PIL import Image
import os
import io
import re
import json
import pandas as pd
from datetime import datetime

# Supabase 클라우드 DB 라이브러리
try:
    from supabase import create_client, Client
    HAS_SUPABASE_LIB = True
except ImportError:
    HAS_SUPABASE_LIB = False

# PIL 고화질 필터 호환성 설정
RESAMPLE_FILTER = getattr(Image, 'LANCZOS', getattr(Image, 'Resampling', Image).LANCZOS if hasattr(Image, 'Resampling') else Image.BICUBIC)

# ----------------------------------------------------
# 0-1. 스마트폰 카메라 기종별 보정 프로필 데이터베이스
# ----------------------------------------------------
CAMERA_PROFILES = {
    "애플 (Apple)": {
        "iPhone 17 / Pro / Max (최신)": "애플 Smart HDR 6 적용 (자연스러운 색감, 특유의 웜톤/노란기 미세 영점 보정, 펄 입자 정밀 분석)",
        "iPhone 16 / Pro / Max": "애플 Photonic Engine 적용 (특유의 웜톤 화이트밸런스 차감 보정)",
        "iPhone 15 시리즈": "애플 Smart HDR 5 적용 (온색계열 렌즈 화세 보정)",
        "iPhone 14 / Pro (기본)": "애플 Deep Fusion 적용 (기본 웜톤 및 입자 텍스처 보정)",
        "기타 아이폰": "아이폰 표준 렌즈 색감 보정"
    },
    "삼성 (Samsung)": {
        "Galaxy S26 / Ultra (최신)": "삼성 ProVisual Engine 적용 (인공 고채도/원색 강조 차감 보정, 샤프닝 억제 정밀 분석)",
        "Galaxy S25 / Ultra": "삼성 ProVisual Engine 적용 (고채도 및 명암 대비 영점 보정)",
        "Galaxy S24 / Ultra": "삼성 Nightography & ISP (선명한 색감 및 원색 강조 보정)",
        "Galaxy S23 / S22 시리즈": "삼성 씬 오프티마이저 (채도 보정 및 에지 강조 보정)",
        "Galaxy Z Fold / Flip 시리즈": "삼성 폴더블 전용 센서 특성 보정",
        "기타 갤럭시": "갤럭시 표준 렌즈 색감 보정"
    },
    "기타 브랜드": {
        "표준 스마트폰 (보정 기본)": "표준 RGB/CIE L*a*b* 하드웨어 렌즈 보정 기준 적용"
    }
}

# ----------------------------------------------------
# 0-2. 페인트 브랜드별 기본 설정 데이터베이스
# ----------------------------------------------------
BRAND_CONFIGS = {
    "WATER-Q (노루페인트)": {
        "code_prefix": "Q-Code",
        "regex_pattern": r"(Q-\d{3,4})\s*[:\=\|\s]+([\d\.]+)\s*g?",
        "thinner_info": "WATER-Q 수성 전용 희석제 규정 비율 준수",
        "special_rules": "Q-7000 사용 시 전체 배합 내 10% 이상 초과 금지 (초과 시 Q-7800/Q-7900 교체)",
        "code_example": "Q-9760: 88.0g, Q-9800: 60.3g"
    },
    "시켄스 옵티마 (노루/Sikkens Optima)": {
        "code_prefix": "안료 코드",
        "regex_pattern": r"([A-Za-z0-9\-\.]+)\s*[:\=\|\s]+([\d\.]+)\s*g?",
        "thinner_info": "★ 표준희석제 10% ~ 15% 희석 비율 필히 준수",
        "special_rules": "시켄스 옵티마 전용 하이솔리드 특성 고려, 표준희석제 10~15% 혼합 후 점도 측정 후 교반",
        "code_example": "WB 334AB: 80.0g, WB 00: 20.0g"
    },
    "시켄스 오토웨이브 2.0 (노루/Sikkens)": {
        "code_prefix": "안료 코드",
        "regex_pattern": r"([A-Za-z0-9\-\.]+)\s*[:\=\|\s]+([\d\.]+)\s*g?",
        "thinner_info": "오토웨이브 전용 수성 희석제 규정 비율 준수",
        "special_rules": "수성 베이스코트 전용 건조 시간 및 에어 블로우 규정 준수",
        "code_example": "WB334: 50.0g, WB00: 10.0g"
    },
    "Glasurit 90Line (Glasurit)": {
        "code_prefix": "안료 코드",
        "regex_pattern": r"(90-[A-Za-z0-9]+)\s*[:\=\|\s]+([\d\.]+)\s*g?",
        "thinner_info": "93-E3 / 93-E10 전용 희석제 50% 혼합",
        "special_rules": "Glasurit 90Line 전용 교반 및 플롭 조절제 투입 수칙 준수",
        "code_example": "90-M4: 70.0g, 90-A010: 15.0g"
    },
    "R-M 오닉스 HD (삼화/R-M Onyx)": {
        "code_prefix": "안료 코드",
        "regex_pattern": r"([A-Z]{1,2}\d{3,4})\s*[:\=\|\s]+([\d\.]+)\s*g?",
        "thinner_info": "Hydropure 전용 희석제 규정 비율 준수",
        "special_rules": "오닉스 HD 전용 점도 및 입자 정렬 가이드 적용",
        "code_example": "HB010: 60.0g, CB020: 30.0g"
    },
    "수믹스 (KCC/Sumix)": {
        "code_prefix": "안료 코드",
        "regex_pattern": r"(WT-\d{3,4})\s*[:\=\|\s]+([\d\.]+)\s*g?",
        "thinner_info": "KCC 수믹스 전용 수성 희석제 준수",
        "special_rules": "WT 수성 안료 계량 정밀도 확보",
        "code_example": "WT-101: 50.0g, WT-202: 25.0g"
    },
    "퍼마하이드 하이텍 (엑솔타/Permacron Hi-TEC)": {
        "code_prefix": "안료 코드",
        "regex_pattern": r"([A-Za-z0-9\-\.]+)\s*[:\=\|\s]+([\d\.]+)\s*g?",
        "thinner_info": "Permacron Hi-TEC 전용 컨트롤러 및 희석제 혼합 비율 준수",
        "special_rules": "퍼마하이드 하이텍 480 전용 단방향 스프레이 도포 및 건조 수칙 적용",
        "code_example": "WT300: 45.0g, WT310: 15.0g"
    },
    "엔바이로베이스 (PPG/Envirobase)": {
        "code_prefix": "안료 코드",
        "regex_pattern": r"([T|P]\d{3,4})\s*[:\=\|\s]+([\d\.]+)\s*g?",
        "thinner_info": "PPG T494 / T495 전용 희석제 준수",
        "special_rules": "PPG 하이솔리드 마이크로 펄 조색 수칙 준수",
        "code_example": "T400: 55.0g, P990-1: 20.0g"
    }
}

# ----------------------------------------------------
# 1. 이미지 처리 함수
# ----------------------------------------------------
def load_and_resize(image_file_or_bytes, max_size=(2500, 2500)):
    if isinstance(image_file_or_bytes, bytes):
        img = Image.open(io.BytesIO(image_file_or_bytes))
    else:
        img = Image.open(image_file_or_bytes)
        
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    img.thumbnail(max_size, RESAMPLE_FILTER)
    return img

def crop_center(img, crop_ratio=0.4):
    w, h = img.size
    cw, ch = int(w * crop_ratio), int(h * crop_ratio)
    left = (w - cw) // 2
    top = (h - ch) // 2
    return img.crop((left, top, left + cw, top + ch))

def create_3way_split_view(bytes_prev, bytes_target, bytes_curr, crop_ratio=0.4):
    img_prev = load_and_resize(bytes_prev, max_size=(2500, 2500))
    img_target = load_and_resize(bytes_target, max_size=(2500, 2500))
    img_curr = load_and_resize(bytes_curr, max_size=(2500, 2500))
    
    crop1 = crop_center(img_prev, crop_ratio)
    crop_t = crop_center(img_target, crop_ratio)
    crop2 = crop_center(img_curr, crop_ratio)
    
    h = min(crop1.height, crop_t.height, crop2.height)
    w1 = int(crop1.width * (h / crop1.height))
    wt = int(crop_t.width * (h / crop_t.height))
    w2 = int(crop2.width * (h / crop2.height))
    
    c1_resized = crop1.resize((w1, h), RESAMPLE_FILTER)
    ct_resized = crop_t.resize((wt, h), RESAMPLE_FILTER)
    c2_resized = crop2.resize((w2, h), RESAMPLE_FILTER)
    
    merged_img = Image.new("RGB", (w1 + wt + w2, h))
    merged_img.paste(c1_resized, (0, 0))
    merged_img.paste(ct_resized, (w1, 0))
    merged_img.paste(c2_resized, (w1 + wt, 0))
    
    return merged_img

def extract_recipe_df_from_ai_text(text, brand_name):
    if not text: return None
    try:
        json_match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
        if not json_match: json_match = re.search(r"(\{[\s\S]*?\"[A-Za-z0-9\-\.]+\"[\s\S]*?\})", text)
        if json_match:
            data = json.loads(json_match.group(1))
            codes = [str(k).upper().strip() for k in data.keys()]
            weights = [float(v) for v in data.values()]
            if codes: return pd.DataFrame({"안료 코드": codes, "1차 배합 중량 (g)": weights})
    except: pass

    pattern = BRAND_CONFIGS[brand_name]["regex_pattern"]
    matches = re.findall(pattern, text, re.IGNORECASE)
    if matches:
        codes, weights, seen = [], [], set()
        for m in matches:
            code = m[0].upper().strip()
            try:
                weight = float(m[1])
                if code not in seen and weight >= 0:
                    codes.append(code); weights.append(weight); seen.add(code)
            except: continue
        if codes: return pd.DataFrame({"안료 코드": codes, "1차 배합 중량 (g)": weights})
    return None

def extract_df_from_recipe_image(client, image_bytes, brand_name):
    try:
        img = load_and_resize(image_bytes)
        prompt = f"""
        첨부된 [{brand_name}] 도료 배합표/시편 카드 이미지에서 안료 코드와 해당 중량(g)을 읽어 JSON으로만 출력하세요.
        ```json\n{{ "코드1": 88.0, "코드2": 60.31 }}\n```
        """
        res = client.models.generate_content(model="gemini-3.5-flash", contents=[img, prompt])
        return extract_recipe_df_from_ai_text(res.text, brand_name)
    except Exception as e:
        st.error(f"사진 인식 중 오류가 발생했습니다: {e}")
        return None

# ----------------------------------------------------
# 2. 페이지 설정 및 초기화
# ----------------------------------------------------
st.set_page_config(page_title="Multi-Brand AI Smart Color System", page_icon="🎨", layout="wide", initial_sidebar_state="expanded")

if "GEMINI_API_KEY" in st.secrets: api_key = st.secrets["GEMINI_API_KEY"]
else: st.error("⚠️ Secrets에 GEMINI_API_KEY가 없습니다."); st.stop()

client = genai.Client(api_key=api_key)

supabase_client = None
if HAS_SUPABASE_LIB and "SUPABASE_URL" in st.secrets and "SUPABASE_KEY" in st.secrets:
    try: supabase_client = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
    except: pass

# --- 세션 상태 완벽 초기화 ---
valid_brands = list(BRAND_CONFIGS.keys())
valid_phone_brands = list(CAMERA_PROFILES.keys())

if "pref_brand" not in st.session_state: st.session_state.pref_brand = valid_brands[0]
if "pref_phone_brand" not in st.session_state: st.session_state.pref_phone_brand = valid_phone_brands[0]
if "pref_phone_model" not in st.session_state: st.session_state.pref_phone_model = list(CAMERA_PROFILES[st.session_state.pref_phone_brand].keys())[0]

if "logged_in" not in st.session_state: st.session_state.logged_in = False
if "current_user" not in st.session_state: st.session_state.current_user = ""
if "user_email" not in st.session_state: st.session_state.user_email = ""

if "current_stage" not in st.session_state: st.session_state.current_stage = 1
if "color_name" not in st.session_state: st.session_state.color_name = ""
if "target_img_bytes" not in st.session_state: st.session_state.target_img_bytes = None
if "prev_sample_bytes" not in st.session_state: st.session_state.prev_sample_bytes = None
if "temp_sample_bytes" not in st.session_state: st.session_state.temp_sample_bytes = None
if "recipe_table_df" not in st.session_state: st.session_state.recipe_table_df = pd.DataFrame({"안료 코드": ["", "", "", ""], "1차 배합 중량 (g)": [0.0, 0.0, 0.0, 0.0]})
if "ai_result_text" not in st.session_state: st.session_state.ai_result_text = ""
if "show_next_btn" not in st.session_state: st.session_state.show_next_btn = False
if "is_passed" not in st.session_state: st.session_state.is_passed = False

def go_next_stage():
    st.session_state.current_stage += 1
    st.session_state.show_next_btn = False
    st.session_state.ai_result_text = ""
    st.session_state.is_passed = False
    if st.session_state.temp_sample_bytes is not None:
        st.session_state.prev_sample_bytes = st.session_state.temp_sample_bytes
        st.session_state.temp_sample_bytes = None

def reset_workspace():
    """화면 꼬임 없는 완벽한 작업 초기화 (설정은 유지)"""
    st.session_state.current_stage = 1
    st.session_state.color_name = ""
    st.session_state.target_img_bytes = None
    st.session_state.prev_sample_bytes = None
    st.session_state.temp_sample_bytes = None
    st.session_state.recipe_table_df = pd.DataFrame({"안료 코드": ["", "", "", ""], "1차 배합 중량 (g)": [0.0, 0.0, 0.0, 0.0]})
    st.session_state.ai_result_text = ""
    st.session_state.show_next_btn = False
    st.session_state.is_passed = False
    
    # 임시 생성된 카메라, 텍스트 입력창 위젯 키 완벽 삭제
    keys_to_delete = [k for k in st.session_state.keys() if k.startswith(("cam_", "file_", "editor_", "r_text_", "weight_", "lab_", "color_name_input"))]
    for k in keys_to_delete:
        del st.session_state[k]

# Custom CSS (모바일 토글 버튼 건드리지 않고 브랜딩만 깔끔하게 제거)
st.markdown("""<style>
    @import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css');
    html, body, [class*="css"] { font-family: 'Pretendard', -apple-system, sans-serif; }
    
    /* Streamlit 브랜딩만 제거 (사이드바 버튼은 절대 건드리지 않음) */
    #MainMenu {visibility: hidden !important;}
    footer {visibility: hidden !important; display: none !important;}
    .stAppDeployButton {display: none !important;}
    header[data-testid="stHeader"] {background: transparent !important;}

    .noroo-header-box {
        background: linear-gradient(135deg, #091936 0%, #003375 50%, #005BB5 100%);
        padding: 22px 28px; border-radius: 16px; color: #FFFFFF;
        box-shadow: 0 8px 24px rgba(0, 51, 117, 0.18);
    }
    .noroo-brand-name { font-size: 13px; font-weight: 700; color: #82B1FF; letter-spacing: 2px; }
    .noroo-main-title { font-size: 23px; font-weight: 800; color: #FFFFFF; margin: 4px 0 0 0; }
    .stage-badge { background-color: #003375; color: #FFFFFF; padding: 6px 16px; border-radius: 20px; font-weight: 800; font-size: 15px; display: inline-block; margin-bottom: 15px; }
    .distance-guide-box { background-color: #EBF8FF; border-left: 4px solid #3182CE; padding: 10px 14px; border-radius: 6px; font-size: 13px; color: #2B6CB0; margin-bottom: 12px; }
    .comparison-card { background-color: #F8FAFC; border: 2px solid #005BB5; border-radius: 12px; padding: 18px; margin-bottom: 20px; }
    div.stButton > button[kind="primary"] { background: linear-gradient(135deg, #003375 0%, #005BB5 100%); color: white; border: none; padding: 14px 28px; font-size: 17px; font-weight: 700; border-radius: 10px; }
</style>""", unsafe_allow_html=True)

# ----------------------------------------------------
# 3. 로그인 모듈 (클라우드 설정 연동)
# ----------------------------------------------------
if not st.session_state.logged_in:
    st.markdown("""<div class="noroo-header-box" style="text-align:center;">
        <span class="noroo-brand-name">MULTI-BRAND AUTO COLOR SYSTEM</span>
        <h1 class="noroo-main-title">🔐 Smart-Paint 클라우드 로그인</h1>
    </div>""", unsafe_allow_html=True)
    st.markdown("---")

    col_auth_center = st.columns([1, 1.2, 1])[1]
    with col_auth_center:
        auth_tab1, auth_tab2 = st.tabs(["🔑 로그인", "📝 테스터 회원가입"])
        
        with auth_tab1:
            saved_email_val = st.query_params.get("saved_email", "")
            remember_email_init = True if saved_email_val else False
            
            with st.form("login_form", clear_on_submit=False):
                login_email = st.text_input("이메일 (Email)", value=saved_email_val, key="login_email_input")
                login_pw = st.text_input("비밀번호 (Password)", type="password", key="login_pw_input")
                remember_email_chk = st.checkbox("☑️ 이메일(아이디) 기억하기", value=remember_email_init)
                submitted = st.form_submit_button("🚀 로그인하기", type="primary", use_container_width=True)
                
                if submitted:
                    if remember_email_chk: st.query_params["saved_email"] = login_email.strip()
                    else:
                        if "saved_email" in st.query_params: del st.query_params["saved_email"]
                            
                    if supabase_client:
                        try:
                            res = supabase_client.auth.sign_in_with_password({"email": login_email.strip(), "password": login_pw.strip()})
                            st.session_state.logged_in = True
                            st.session_state.user_email = res.user.email
                            user_meta = res.user.user_metadata
                            st.session_state.current_user = user_meta.get("display_name", res.user.email.split("@")[0])
                            
                            # 로그인 시 DB에서 설정 불러오기
                            if user_meta.get("pref_brand") in valid_brands: st.session_state.pref_brand = user_meta.get("pref_brand")
                            if user_meta.get("pref_phone_brand") in valid_phone_brands:
                                st.session_state.pref_phone_brand = user_meta.get("pref_phone_brand")
                                if user_meta.get("pref_phone_model") in CAMERA_PROFILES[st.session_state.pref_phone_brand]:
                                    st.session_state.pref_phone_model = user_meta.get("pref_phone_model")

                            st.success(f"🎉 {st.session_state.current_user}님, 환영합니다!")
                            st.rerun()
                        except: st.error("❌ 로그인 실패: 이메일 또는 비밀번호를 확인하세요.")
                    else:
                        if login_email == "admin@test.com" and login_pw == "1234":
                            st.session_state.logged_in = True; st.session_state.current_user = "관리자"; st.session_state.user_email = login_email; st.rerun()
                        else: st.error("❌ 아이디/비밀번호가 맞지 않습니다.")
        
        with auth_tab2:
            with st.form("register_form", clear_on_submit=False):
                reg_name = st.text_input("작업자 성함 / 공장명", key="reg_name_input")
                reg_email = st.text_input("사용할 이메일", key="reg_email_input")
                reg_pw = st.text_input("사용할 비밀번호 (6자리 이상)", type="password", key="reg_pw_input")
                reg_submitted = st.form_submit_button("📝 테스터 등록 신청", use_container_width=True)
                
                if reg_submitted:
                    if len(reg_pw.strip()) < 6: st.warning("⚠️ 비밀번호는 최소 6자리 이상이어야 합니다.")
                    elif supabase_client:
                        try:
                            supabase_client.auth.sign_up({"email": reg_email.strip(), "password": reg_pw.strip(), "options": {"data": {"display_name": reg_name.strip()}}})
                            st.success("🎉 가입 성공! [로그인] 탭에서 로그인해 주세요.")
                        except Exception as e: st.error(f"가입 실패: {e}")
    st.stop()

# ----------------------------------------------------
# 4. DB 저장 및 불러오기 함수
# ----------------------------------------------------
MAX_SAVE_LIMIT = 20

def db_fetch_user_history():
    if not supabase_client: return []
    try:
        res = supabase_client.table("work_history").select("*").eq("username", st.session_state.current_user).order("created_at", desc=True).execute()
        return res.data
    except: return []

def db_save_work(title_name, current_brand):
    if not title_name.strip(): return False
    user_history = db_fetch_user_history()
    if supabase_client and len(user_history) >= MAX_SAVE_LIMIT:
        for old_item in user_history[MAX_SAVE_LIMIT - 1:]:
            try: supabase_client.table("work_history").delete().eq("id", old_item['id']).execute()
            except: pass
            
    payload = {
        "username": st.session_state.current_user, "title": title_name.strip(), "brand": current_brand,
        "color_name": st.session_state.color_name, "stage": st.session_state.current_stage,
        "recipe_json": st.session_state.recipe_table_df.to_json(orient="records"),
        "ai_result": st.session_state.ai_result_text, "is_passed": st.session_state.is_passed
    }
    
    if supabase_client:
        try:
            supabase_client.table("work_history").insert(payload).execute()
            st.toast(f"☁️ '{title_name}' 저장 완료!", icon="💾")
            return True
        except: return False
    return True

def db_get_successful_recipes_rag(brand_name, color_name):
    if not supabase_client or not color_name.strip(): return ""
    try:
        res = supabase_client.table("work_history").select("recipe_json, color_name, stage").eq("brand", brand_name).ilike("color_name", f"%{color_name.strip()}%").eq("is_passed", True).limit(3).execute()
        if not res.data: return ""
        txt = "\n\n[★ 과거 성공 레시피]\n"
        for i, r in enumerate(res.data, 1): txt += f" 사례{i} [{r['color_name']}]: {r['recipe_json']}\n"
        return txt
    except: return ""

def db_delete_work(history_id):
    if supabase_client:
        try: supabase_client.table("work_history").delete().eq("id", history_id).execute()
        except: pass

# ----------------------------------------------------
# 5. 좌측 사이드바 (원상복구 완벽 구현)
# ----------------------------------------------------
with st.sidebar:
    st.markdown(f"👤 **접속 계정**: `{st.session_state.current_user}`")
    st.caption(f"📧 `{st.session_state.user_email}`")
    if supabase_client: st.caption("🟢 **Supabase Auth & DB**: 연결 완료")
    if st.button("🔒 로그아웃", use_container_width=True):
        st.session_state.logged_in = False; st.rerun()

    st.markdown("---")
    
    # 1) 페인트 설정
    st.header("🎨 도료 브랜드 설정")
    new_brand = st.selectbox("브랜드 선택", valid_brands, index=valid_brands.index(st.session_state.pref_brand))
    if new_brand != st.session_state.pref_brand:
        st.session_state.pref_brand = new_brand
        if supabase_client:
            try: supabase_client.auth.update_user({"data": {"pref_brand": new_brand}})
            except: pass
        st.rerun()
    st.info(f"📌 {BRAND_CONFIGS[st.session_state.pref_brand]['special_rules']}")

    st.markdown("---")

    # 2) 스마트폰 카메라 설정
    st.header("📱 스마트폰 카메라 설정")
    new_p_brand = st.selectbox("제조사 선택", valid_phone_brands, index=valid_phone_brands.index(st.session_state.pref_phone_brand))
    
    p_models = list(CAMERA_PROFILES[new_p_brand].keys())
    # 제조사가 바뀌면 모델 인덱스가 없을 수 있으므로 안전 처리
    m_index = p_models.index(st.session_state.pref_phone_model) if st.session_state.pref_phone_model in p_models else 0
    new_p_model = st.selectbox("기종 선택", p_models, index=m_index)

    if new_p_brand != st.session_state.pref_phone_brand or new_p_model != st.session_state.pref_phone_model:
        st.session_state.pref_phone_brand = new_p_brand
        st.session_state.pref_phone_model = new_p_model
        if supabase_client:
            try: supabase_client.auth.update_user({"data": {"pref_phone_brand": new_p_brand, "pref_phone_model": new_p_model}})
            except: pass
        st.rerun()

    st.markdown("---")

    # 3) 저장된 내역 불러오기
    st.header("📁 저장된 내역 불러오기")
    db_history = db_fetch_user_history()
    if db_history:
        titles = [f"{h['title']} ({h['created_at'][:10]})" for h in db_history]
        selected_idx = st.selectbox("불러올 작업 선택", range(len(titles)), format_func=lambda x: titles[x])
        selected_row = db_history[selected_idx]
        
        col_s1, col_s2 = st.columns(2)
        with col_s1:
            if st.button("📂 불러오기", use_container_width=True):
                st.session_state.color_name = selected_row.get("color_name", "")
                st.session_state.color_name_input_field = st.session_state.color_name  # 강제 업데이트용 키
                st.session_state.current_stage = selected_row["stage"]
                st.session_state.pref_brand = selected_row["brand"]
                st.session_state.ai_result_text = selected_row.get("ai_result", "")
                try: st.session_state.recipe_table_df = pd.read_json(io.StringIO(selected_row["recipe_json"]))
                except: pass
                st.toast(f"📂 '{selected_row['title']}' 내역을 불러왔습니다.")
                st.rerun()
        with col_s2:
            if st.button("🗑️ 삭제하기", use_container_width=True):
                db_delete_work(selected_row['id'])
                st.toast("🗑️ 데이터가 삭제되었습니다.")
                st.rerun()
    else:
        st.caption("보관함이 비어있습니다.")

    st.markdown("---")
    
    # 4) 초기화
    st.header("⚙️ 시스템 설정")
    if st.button("🔄 새로운 작업 시작 (Reset)", use_container_width=True):
        reset_workspace()
        st.toast("✨ 새로운 작업 화면으로 초기화되었습니다.")
        st.rerun()

# ----------------------------------------------------
# 6. 메인 화면 구성
# ----------------------------------------------------
current_brand = st.session_state.pref_brand
current_camera = f"{st.session_state.pref_phone_brand} {st.session_state.pref_phone_model}"

st.markdown(f"""<div class="noroo-header-box">
    <span class="noroo-brand-name">MULTI-BRAND AUTO COLOR SYSTEM</span>
    <h1 class="noroo-main-title">[{current_brand}] AI 스마트 조색 & 결함 진단</h1>
</div>""", unsafe_allow_html=True)
st.markdown("---")

tab_tuning, tab_defect = st.tabs([f"🎨 {current_brand} AI 미세 조색", "🔍 도장 결함 진단"])

with tab_tuning:
    current_stage = st.session_state.current_stage
    is_stage_1 = (current_stage == 1)
    stage_code = f"{current_stage}차"
    prev_stage_code = "1차" if current_stage == 2 else f"{current_stage-1}차"
    
    st.markdown(f'<div class="stage-badge">📍 현재 진행 단계: {current_brand} {stage_code} 조색 프로세스</div>', unsafe_allow_html=True)
    st.subheader("0. 차종 및 색상명/코드 입력")
    
    col_c1, col_c2 = st.columns([3.5, 1])
    with col_c1:
        # 불러오기 했을 때 값이 제대로 채워지도록 설정
        input_color_val = st.text_input("차종 및 목표 색상코드/색상명을 입력하세요", value=st.session_state.get("color_name_input_field", st.session_state.color_name), placeholder="예: 기아 ABT, 현대 SWP 등", key="color_name_input_field")
        st.session_state.color_name = input_color_val

    with col_c2:
        st.write(""); st.write("")
        color_code_str = st.session_state.color_name.strip()
        auto_default_title = f"{datetime.now().strftime('%Y-%m-%d')}_{color_code_str}" if color_code_str else f"{datetime.now().strftime('%Y-%m-%d')}_색상미지정"
        if st.button("💾 클라우드 저장", type="primary", use_container_width=True):
            if not color_code_str: st.warning("⚠️ 차종 및 색상명을 입력한 후 저장해 주세요.")
            else: db_save_work(auto_default_title, current_brand); st.rerun()

    st.markdown("---")
    col_t1, col_t2 = st.columns(2)
    
    with col_t1:
        st.write("1. 목표 차체/판넬 사진 (Target)")
        st.markdown("""<div class="distance-guide-box"><b>📏 15cm 거리 촬영</b> <br>💡 <b>팁</b>: 모바일은 [📷 앱 내 직접 촬영]에서 <b>(🔄)버튼</b>을 누르거나 [📁 갤러리 / 후면 카메라] 탭을 이용하세요.</div>""", unsafe_allow_html=True)
        if st.session_state.target_img_bytes is None:
            t_tab1, t_tab2 = st.tabs(["📷 앱 내 직접 촬영", "📁 갤러리 / 후면 카메라"])
            with t_tab1:
                cam = st.camera_input("목표 차체 촬영", key="cam_target")
                if cam: st.session_state.target_img_bytes = cam.getvalue(); st.rerun()
            with t_tab2:
                up = st.file_uploader("목표 차체 파일", type=["jpg", "png", "jpeg"], key="file_target")
                if up: st.session_state.target_img_bytes = up.getvalue(); st.rerun()
        else:
            st.image(load_and_resize(st.session_state.target_img_bytes), caption=f"🎯 목표 [{st.session_state.color_name}] - [{current_camera}]", use_container_width=True)
            if st.button("🔄 목표 사진 다시 찍기"): st.session_state.target_img_bytes = None; st.rerun()

    with col_t2:
        st.write(f"2. {stage_code} 도장 시편 사진 (Sample)")
        st.markdown("""<div class="distance-guide-box"><b>📏 15cm 거리 촬영</b> <br>💡 <b>팁</b>: 모바일은 [📷 앱 내 직접 촬영]에서 <b>(🔄)버튼</b>을 누르거나 [📁 갤러리 / 후면 카메라] 탭을 이용하세요.</div>""", unsafe_allow_html=True)
        s_tab1, s_tab2 = st.tabs(["📷 앱 내 직접 촬영", "📁 갤러리 / 후면 카메라"])
        with s_tab1:
            cam_s = st.camera_input(f"{stage_code} 시편 촬영", key=f"cam_sample_{current_stage}")
            if cam_s: st.session_state.temp_sample_bytes = cam_s.getvalue()
        with s_tab2:
            up_s = st.file_uploader(f"{stage_code} 시편 파일", type=["jpg", "png", "jpeg"], key=f"file_sample_{current_stage}")
            if up_s: st.session_state.temp_sample_bytes = up_s.getvalue()
        if st.session_state.temp_sample_bytes:
            st.image(load_and_resize(st.session_state.temp_sample_bytes), caption=f"🧪 {stage_code} 시편 - [{current_camera}]", use_container_width=True)

    if not is_stage_1 and st.session_state.prev_sample_bytes and st.session_state.target_img_bytes and st.session_state.temp_sample_bytes:
        st.markdown("---")
        st.markdown(f"""<div class="comparison-card"><h4 style="margin-top:0; color:#003375;">📱 [{current_brand}] 초고화질 3분할 정밀 대조</h4></div>""", unsafe_allow_html=True)
        st.image(create_3way_split_view(st.session_state.prev_sample_bytes, st.session_state.target_img_bytes, st.session_state.temp_sample_bytes, crop_ratio=0.4), caption=f"◀️ {prev_stage_code} 시편 | 🎯 목표 차체 [{st.session_state.color_name}] | {stage_code} 신규 시편 ▶️", use_container_width=True)

    st.markdown("---")
    col_r1, col_r2 = st.columns([1.2, 0.8])

    with col_r1:
        if is_stage_1:
            st.subheader(f"3. 1차 기본 배합 레시피 ({current_brand})")
            r_tab1, r_tab2 = st.tabs(["📷 카드 촬영/업로드", "✍️ 직접 작성"])
            recipe_img_bytes = None
            with r_tab1:
                cam_r = st.camera_input("배합표 촬영", key="cam_recipe")
                file_r = st.file_uploader("카드 사진 업로드", type=["jpg", "png"], key="file_recipe")
                if cam_r: recipe_img_bytes = cam_r.getvalue()
                elif file_r: recipe_img_bytes = file_r.getvalue()

                if recipe_img_bytes:
                    st.image(Image.open(io.BytesIO(recipe_img_bytes)), width=350)
                    if st.button("🔍 사진에서 안료 수치 읽기"):
                        with st.spinner("AI 분석 중..."):
                            df = extract_df_from_recipe_image(client, recipe_img_bytes, current_brand)
                            if df is not None and not df.empty:
                                st.session_state.recipe_table_df = df; st.success("자동 입력 완료!"); st.rerun()
                            else: st.warning("인식 실패. 직접 입력해 주세요.")
            with r_tab2:
                r_txt = st.text_area("직접 작성", value="", placeholder=BRAND_CONFIGS[current_brand]['code_example'], key="r_text")
                if r_txt.strip():
                    df = extract_recipe_df_from_ai_text(r_txt, current_brand)
                    if df is not None and not df.empty: st.session_state.recipe_table_df = df

            st.write(f"📋 **1차 배합표 ({current_brand}):**")
            st.session_state.recipe_table_df = st.data_editor(st.session_state.recipe_table_df, use_container_width=True, num_rows="dynamic", key="editor_1")
        else:
            st.subheader(f"3. {prev_stage_code} 확정 레시피 ({current_brand})")
            st.session_state.recipe_table_df = st.data_editor(st.session_state.recipe_table_df, use_container_width=True, num_rows="dynamic", key=f"editor_{stage_code}")

    with col_r2:
        st.subheader(f"4. {stage_code} 목표 중량 및 측색기")
        target_total_weight = st.number_input("🎯 총 중량 (g)", min_value=10.0, value=100.0, step=10.0, key=f"weight_{stage_code}")
        lab_data = st.text_input("측색기 수치 (선택)", placeholder="예: L*: 45.2, a*: 12.3", key=f"lab_{stage_code}")

    st.markdown("---")

    if st.button(f"🚀 [{current_brand}] {stage_code} AI 미세 조색 실행", type="primary", use_container_width=True):
        if not st.session_state.target_img_bytes or not st.session_state.temp_sample_bytes:
            st.warning("⚠️ 목표 사진과 시편 사진을 모두 등록해 주세요.")
        elif is_stage_1 and st.session_state.recipe_table_df.empty:
            st.warning("⚠️ 배합표를 입력해 주세요.")
        else:
            with st.spinner("AI 실시간 분석 중..."):
                try:
                    img_t = load_and_resize(st.session_state.target_img_bytes)
                    img_c = load_and_resize(st.session_state.temp_sample_bytes)
                    rag = db_get_successful_recipes_rag(current_brand, st.session_state.color_name)
                    
                    prompt = f"""
                    [{current_brand}] 페인트 정밀 분석.
                    - 색상명: {st.session_state.color_name}
                    - 배합표: \n{st.session_state.recipe_table_df.to_string(index=False)}
                    - 목표량: {target_total_weight}g
                    - 촬영: {current_camera} ({CAMERA_PROFILES[st.session_state.pref_phone_brand][st.session_state.pref_phone_model]})
                    - 측색: {lab_data}
                    {rag}
                    Delta E <= 0.5 판정 시 '[판정: 🎉 조색 완벽 합격 (Delta E <= 0.5)]' 명시.
                    아니면 '[판정: 🔺 미세 보정 필요]' 명시.
                    표 출력형태: | 안료 코드 | {prev_stage_code} 중량 | {stage_code} 신규 중량 | 차이 | 처방 역할 |
                    """
                    res = client.models.generate_content(model="gemini-3.5-flash", contents=[img_t, img_c, prompt])
                    st.session_state.ai_result_text = res.text
                    
                    if "조색 완벽 합격" in res.text or "Delta E <= 0.5" in res.text: st.session_state.is_passed = True; st.session_state.show_next_btn = False
                    else: st.session_state.is_passed = False; st.session_state.show_next_btn = True
                    df = extract_recipe_df_from_ai_text(res.text, current_brand)
                    if df is not None and not df.empty: st.session_state.recipe_table_df = df
                except Exception as e: st.error(f"오류: {e}")

    if st.session_state.ai_result_text:
        st.markdown(f"### 📊 AI 리포트")
        st.markdown(st.session_state.ai_result_text)
        if st.session_state.is_passed: st.balloons(); st.success("🎉 완벽 합격! 성공 족보로 등록됩니다.")
    if st.session_state.show_next_btn and not st.session_state.is_passed:
        st.button(f"➡️ {current_stage + 1}차 조색으로 진행", on_click=go_next_stage, type="primary", use_container_width=True)

with tab_defect:
    st.subheader(f"🔍 [{current_brand}] 도장 결함 진단")
    col1, col2 = st.columns(2)
    with col1:
        d_tab1, d_tab2 = st.tabs(["📷 카메라", "📁 갤러리"])
        def_img = None
        with d_tab1:
            cam_d = st.camera_input("촬영", key="cam_def")
            if cam_d: def_img = cam_d.getvalue()
        with d_tab2:
            up_d = st.file_uploader("파일 선택", type=["jpg", "png"], key="file_def")
            if up_d: def_img = up_d.getvalue()
        if def_img: st.image(load_and_resize(def_img), use_container_width=True)
    with col2:
        def_ctx = st.text_area("현장 증상 요약", placeholder="예: 오렌지필 현상, 건조 60도")
    if st.button("🚨 진단 실행", type="primary", use_container_width=True):
        if def_img:
            with st.spinner("분석 중..."):
                res = client.models.generate_content(model="gemini-3.5-flash", contents=[load_and_resize(def_img), f"결함 진단. 브랜드:{current_brand}, 기기:{current_camera}, 증상:{def_ctx}"])
                st.success("진단 완료!"); st.markdown(res.text)
        else: st.warning("사진을 등록하세요.")