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
    if not text:
        return None
    try:
        json_match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
        if not json_match:
            json_match = re.search(r"(\{[\s\S]*?\"[A-Za-z0-9\-\.]+\"[\s\S]*?\})", text)
            
        if json_match:
            data = json.loads(json_match.group(1))
            codes = [str(k).upper().strip() for k in data.keys()]
            weights = [float(v) for v in data.values()]
            if codes:
                return pd.DataFrame({"안료 코드": codes, "1차 배합 중량 (g)": weights})
    except Exception:
        pass

    pattern = BRAND_CONFIGS[brand_name]["regex_pattern"]
    matches = re.findall(pattern, text, re.IGNORECASE)
    if matches:
        codes = []
        weights = []
        seen = set()
        for m in matches:
            code = m[0].upper().strip()
            try:
                weight = float(m[1])
                if code not in seen and weight >= 0:
                    codes.append(code)
                    weights.append(weight)
                    seen.add(code)
            except ValueError:
                continue
        if codes:
            return pd.DataFrame({"안료 코드": codes, "1차 배합 중량 (g)": weights})

    return None

def extract_df_from_recipe_image(client, image_bytes, brand_name):
    try:
        img = load_and_resize(image_bytes)
        ex_code = BRAND_CONFIGS[brand_name]["code_example"]
        prompt = f"""
        첨부된 [{brand_name}] 도료 배합표/시편 카드 이미지에서 안료 코드와 해당 중량(g)을 읽어 JSON으로만 출력하세요.
        ```json
        {{ "코드1": 88.0, "코드2": 60.31 }}
        ```
        예시 형태 참고: {ex_code}
        """
        res = client.models.generate_content(model="gemini-3.5-flash", contents=[img, prompt])
        return extract_recipe_df_from_ai_text(res.text, brand_name)
    except Exception as e:
        st.error(f"사진 인식 중 오류가 발생했습니다: {e}")
        return None

# ----------------------------------------------------
# 2. 페이지 설정 및 Supabase 클라우드 DB 연동
# ----------------------------------------------------
st.set_page_config(
    page_title="Multi-Brand AI Smart Color System",
    page_icon="🎨",
    layout="wide",
    initial_sidebar_state="expanded"
)

if "GEMINI_API_KEY" in st.secrets:
    api_key = st.secrets["GEMINI_API_KEY"]
else:
    st.error("⚠️ Streamlit Secrets에 GEMINI_API_KEY가 설정되지 않았습니다.")
    st.stop()

client = genai.Client(api_key=api_key)

# Supabase 클라이언트 초기화
supabase_client = None
if HAS_SUPABASE_LIB and "SUPABASE_URL" in st.secrets and "SUPABASE_KEY" in st.secrets:
    try:
        supabase_client = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
    except Exception as e:
        st.sidebar.warning(f"⚠️ Supabase 연결 실패: {e}")

# ----------------------------------------------------
# ★ 상태(Session) 변수 및 기본 설정값 초기화 (오류 원천 차단) ★
# ----------------------------------------------------
valid_brands = list(BRAND_CONFIGS.keys())
valid_phone_brands = list(CAMERA_PROFILES.keys())

if "pref_brand" not in st.session_state:
    st.session_state.pref_brand = valid_brands[0]
if "pref_phone_brand" not in st.session_state:
    st.session_state.pref_phone_brand = valid_phone_brands[0]
if "pref_phone_model" not in st.session_state:
    st.session_state.pref_phone_model = list(CAMERA_PROFILES[st.session_state.pref_phone_brand].keys())[0]

# 설정 저장 성공 알림 띄우기용 플래그
if "show_save_toast" not in st.session_state:
    st.session_state.show_save_toast = False

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "current_user" not in st.session_state:
    st.session_state.current_user = ""
if "user_email" not in st.session_state:
    st.session_state.user_email = ""

if "current_stage" not in st.session_state: st.session_state.current_stage = 1
if "color_name" not in st.session_state: st.session_state.color_name = ""
if "target_img_bytes" not in st.session_state: st.session_state.target_img_bytes = None
if "target_img_name" not in st.session_state: st.session_state.target_img_name = "카메라 직촬 Target"
if "prev_sample_bytes" not in st.session_state: st.session_state.prev_sample_bytes = None
if "temp_sample_bytes" not in st.session_state: st.session_state.temp_sample_bytes = None
if "recipe_table_df" not in st.session_state:
    st.session_state.recipe_table_df = pd.DataFrame({"안료 코드": ["", "", "", ""], "1차 배합 중량 (g)": [0.0, 0.0, 0.0, 0.0]})
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
    st.session_state.current_stage = 1
    st.session_state.color_name = ""
    st.session_state.color_name_input_field = ""
    st.session_state.target_img_bytes = None
    st.session_state.target_img_name = "카메라 직촬 Target"
    st.session_state.prev_sample_bytes = None
    st.session_state.temp_sample_bytes = None
    st.session_state.recipe_table_df = pd.DataFrame({"안료 코드": ["", "", "", ""], "1차 배합 중량 (g)": [0.0, 0.0, 0.0, 0.0]})
    st.session_state.ai_result_text = ""
    st.session_state.show_next_btn = False
    st.session_state.is_passed = False
    widget_keys = [k for k in st.session_state.keys() if k.startswith(("cam_", "file_", "editor_", "r_text_"))]
    for k in widget_keys:
        del st.session_state[k]

# ★ 클라우드에 설정 자동 업데이트 함수
def save_cloud_settings(brand, p_brand, p_model):
    if not supabase_client: return
    try:
        supabase_client.auth.update_user({
            "data": {
                "pref_brand": brand,
                "pref_phone_brand": p_brand,
                "pref_phone_model": p_model
            }
        })
    except Exception:
        pass

# 설정 저장 확인 토스트 (페이지 새로고침 직후 실행됨)
if st.session_state.show_save_toast:
    st.toast("✅ 설정이 클라우드에 안전하게 저장되었습니다.", icon="☁️")
    st.session_state.show_save_toast = False

# Custom CSS
st.markdown("""<style>
    @import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css');
    html, body, [class*="css"] {
        font-family: 'Pretendard', -apple-system, BlinkMacSystemFont, system-ui, Roboto, sans-serif;
    }
    
    #MainMenu {visibility: hidden !important;}
    footer {visibility: hidden !important; display: none !important;}
    [data-testid="stDecoration"] {display: none !important;}
    [data-testid="stStatusWidget"] {display: none !important;}
    [data-testid="stToolbar"] {display: none !important;}
    [class*="viewerBadge"] {display: none !important;}
    [class*="stAppDeployButton"] {display: none !important;}
    
    header[data-testid="stHeader"] {
        background: transparent !important;
        z-index: 1000 !important;
    }

    [data-testid="stSidebarCollapsedControl"] {
        display: block !important;
        visibility: visible !important;
        z-index: 999999 !important;
        position: fixed !important;
        top: 10px !important;
        left: 10px !important;
    }
    [data-testid="stSidebarCollapsedControl"] button {
        background-color: #003375 !important;
        color: #FFFFFF !important;
        border: 1px solid #82B1FF !important;
        border-radius: 8px !important;
        box-shadow: 0 4px 12px rgba(0,0,0,0.3) !important;
        width: 42px !important;
        height: 42px !important;
    }
    [data-testid="stSidebarCollapsedControl"] button svg {
        fill: #FFFFFF !important;
        color: #FFFFFF !important;
        width: 24px !important;
        height: 24px !important;
    }

    .noroo-header-box {
        background: linear-gradient(135deg, #091936 0%, #003375 50%, #005BB5 100%);
        padding: 22px 28px;
        border-radius: 16px;
        color: #FFFFFF;
        box-shadow: 0 8px 24px rgba(0, 51, 117, 0.18);
    }
    .noroo-brand-name {
        font-size: 13px;
        font-weight: 700;
        color: #82B1FF;
        letter-spacing: 2px;
        text-transform: uppercase;
    }
    .noroo-main-title {
        font-size: 23px;
        font-weight: 800;
        color: #FFFFFF;
        margin: 4px 0 0 0;
        letter-spacing: -0.5px;
        word-break: keep-all;
    }
    .stage-badge {
        background-color: #003375;
        color: #FFFFFF;
        padding: 6px 16px;
        border-radius: 20px;
        font-weight: 800;
        font-size: 15px;
        display: inline-block;
        margin-bottom: 15px;
    }
    .distance-guide-box {
        background-color: #EBF8FF;
        border-left: 4px solid #3182CE;
        padding: 10px 14px;
        border-radius: 6px;
        font-size: 13px;
        color: #2B6CB0;
        margin-bottom: 12px;
    }
    .comparison-card {
        background-color: #F8FAFC;
        border: 2px solid #005BB5;
        border-radius: 12px;
        padding: 18px;
        margin-bottom: 20px;
    }
    div.stButton > button[kind="primary"] {
        background: linear-gradient(135deg, #003375 0%, #005BB5 100%);
        color: white;
        border: none;
        padding: 14px 28px;
        font-size: 17px;
        font-weight: 700;
        border-radius: 10px;
        box-shadow: 0 4px 14px rgba(0, 51, 117, 0.25);
    }
</style>""", unsafe_allow_html=True)

# ----------------------------------------------------
# 3. Supabase Auth (클라우드 설정 완벽 복원)
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
            st.subheader("클라우드 로그인")
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
                            res = supabase_client.auth.sign_in_with_password({
                                "email": login_email.strip(), "password": login_pw.strip()
                            })
                            st.session_state.logged_in = True
                            st.session_state.user_email = res.user.email
                            
                            user_meta = res.user.user_metadata
                            st.session_state.current_user = user_meta.get("display_name", res.user.email.split("@")[0])
                            
                            # ★ 내 프로필에 저장된 설정을 세션에 안전하게 덮어쓰기
                            saved_brand = user_meta.get("pref_brand")
                            if saved_brand in valid_brands:
                                st.session_state.pref_brand = saved_brand
                                
                            saved_p_brand = user_meta.get("pref_phone_brand")
                            if saved_p_brand in valid_phone_brands:
                                st.session_state.pref_phone_brand = saved_p_brand
                                saved_p_model = user_meta.get("pref_phone_model")
                                if saved_p_model in CAMERA_PROFILES[saved_p_brand]:
                                    st.session_state.pref_phone_model = saved_p_model

                            st.success(f"🎉 {st.session_state.current_user}님, 환영합니다!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"❌ 로그인 실패: 이메일 또는 비밀번호를 확인하세요.")
                    else:
                        if login_email == "admin@test.com" and login_pw == "1234":
                            st.session_state.logged_in = True
                            st.session_state.current_user = "관리자"
                            st.session_state.user_email = login_email
                            st.rerun()
                        else:
                            st.error("❌ 아이디/비밀번호가 맞지 않습니다.")
        
        with auth_tab2:
            st.subheader("테스터 신규 회원가입")
            with st.form("register_form", clear_on_submit=False):
                reg_name = st.text_input("작업자 성함 / 공장명", key="reg_name_input")
                reg_email = st.text_input("사용할 이메일", key="reg_email_input")
                reg_pw = st.text_input("사용할 비밀번호 (6자리 이상)", type="password", key="reg_pw_input")
                reg_submitted = st.form_submit_button("📝 테스터 등록 신청", use_container_width=True)
                
                if reg_submitted:
                    if not reg_email.strip() or not reg_pw.strip() or not reg_name.strip():
                        st.warning("⚠️ 모든 항목을 작성해 주세요.")
                    elif len(reg_pw.strip()) < 6:
                        st.warning("⚠️ 비밀번호는 최소 6자리 이상이어야 합니다.")
                    elif supabase_client:
                        try:
                            res = supabase_client.auth.sign_up({
                                "email": reg_email.strip(), "password": reg_pw.strip(),
                                "options": {"data": {"display_name": reg_name.strip()}}
                            })
                            st.success("🎉 Smart-Paint 클라우드에 성공적으로 회원등록 되었습니다! [로그인] 탭에서 로그인해 주세요.")
                        except Exception as e:
                            st.error(f"회원가입 실패: {e}")
                    else:
                        st.error("⚠️ Supabase DB가 연결되어 있지 않습니다.")
    st.stop()

# ----------------------------------------------------
# 4. Supabase DB 데이터 저장 (20개 초과 시 자동 삭제)
# ----------------------------------------------------
MAX_SAVE_LIMIT = 20

def db_fetch_user_history():
    if not supabase_client: return []
    try:
        res = supabase_client.table("work_history").select("id, title, color_name, brand, stage, recipe_json, ai_result, created_at").eq("username", st.session_state.current_user).order("created_at", desc=True).execute()
        return res.data
    except: return []

def db_save_work(title_name, current_brand):
    if not title_name.strip():
        st.error("⚠️ 저장 제목을 입력해 주세요.")
        return False
    user_history = db_fetch_user_history()
    if supabase_client and len(user_history) >= MAX_SAVE_LIMIT:
        oldest_items = user_history[MAX_SAVE_LIMIT - 1:]
        try:
            for old_item in oldest_items:
                supabase_client.table("work_history").delete().eq("id", old_item['id']).execute()
            st.toast(f"♻️ 저장 한도({MAX_SAVE_LIMIT}개) 초과로 가장 과거 데이터를 지우고 새 데이터를 저장합니다.", icon="♻️")
        except: pass

    data_payload = {
        "username": st.session_state.current_user, "title": title_name.strip(), "brand": current_brand,
        "color_name": st.session_state.color_name, "stage": st.session_state.current_stage,
        "recipe_json": st.session_state.recipe_table_df.to_json(orient="records"),
        "ai_result": st.session_state.ai_result_text, "is_passed": st.session_state.is_passed
    }
    
    if supabase_client:
        try:
            supabase_client.table("work_history").insert(data_payload).execute()
            st.toast(f"☁️ '{title_name}' 클라우드 DB 저장 완료! ({min(len(user_history) + 1, MAX_SAVE_LIMIT)}/{MAX_SAVE_LIMIT}개)", icon="💾")
            return True
        except: return False
    else:
        st.toast(f"💾 메모리에 '{title_name}' 내역 저장완료.", icon="⚠️")
        return True

def db_get_successful_recipes_rag(brand_name, color_name):
    if not supabase_client or not color_name.strip(): return ""
    try:
        res = supabase_client.table("work_history").select("recipe_json, color_name, stage, created_at").eq("brand", brand_name).ilike("color_name", f"%{color_name.strip()}%").eq("is_passed", True).order("created_at", desc=True).limit(3).execute()
        if not res.data: return ""
        success_text = "\n\n[★ 축적된 클라우드 DB의 과거 동일/유사 색상 성공 족보 레시피 (Delta E <= 0.5 참조)]\n"
        for idx, r in enumerate(res.data, 1): success_text += f" 성공사례 {idx} [{r['color_name']} / {r['stage']}차 조색]: {r['recipe_json']}\n"
        return success_text
    except: return ""

def db_delete_work(history_id, history_title):
    if supabase_client:
        try:
            supabase_client.table("work_history").delete().eq("id", history_id).execute()
            st.sidebar.success(f"🗑️ '{history_title}' 데이터가 삭제되었습니다.")
            st.rerun()
        except: pass

# ----------------------------------------------------
# 5. 사이드바 구성
# ----------------------------------------------------
with st.sidebar:
    st.markdown(f"👤 **접속 계정**: `{st.session_state.current_user}`")
    st.caption(f"📧 `{st.session_state.user_email}`")
    
    if supabase_client: st.caption("🟢 **Supabase Auth & DB**: 연결 완료")
    else: st.caption("🟡 **오프라인 데모 모드**")

    if st.button("🔒 로그아웃", use_container_width=True):
        st.session_state.logged_in = False
        st.session_state.current_user = ""
        st.session_state.user_email = ""
        st.rerun()

    st.markdown("---")
    st.header("📁 저장된 내역 불러오기")
    db_history = db_fetch_user_history()
    
    if db_history:
        st.caption(f"현재 보관 수량: **{len(db_history)} / {MAX_SAVE_LIMIT} 개**")
        titles = [f"{h['title']} ({h['created_at'][:10]})" for h in db_history]
        selected_idx = st.selectbox("불러올 작업 선택", range(len(titles)), format_func=lambda x: titles[x], key="db_select_box")
        
        selected_row = db_history[selected_idx]
        col_s1, col_s2 = st.columns(2)
        with col_s1:
            if st.button("📂 불러오기", use_container_width=True):
                loaded_color = selected_row.get("color_name", "")
                st.session_state.color_name = loaded_color
                st.session_state.color_name_input_field = loaded_color
                st.session_state.current_stage = selected_row["stage"]
                # 불러오기 시 브랜드도 임시 변경
                st.session_state.pref_brand = selected_row["brand"]
                st.session_state.ai_result_text = selected_row["ai_result"]
                try: st.session_state.recipe_table_df = pd.read_json(io.StringIO(selected_row["recipe_json"]))
                except: pass
                st.sidebar.success(f"📂 DB에서 '{selected_row['title']}' 내역을 불러왔습니다.")
                st.rerun()
        with col_s2:
            if st.button("🗑️ 삭제하기", use_container_width=True):
                db_delete_work(selected_row['id'], selected_row['title'])
    else:
        st.caption("보관함이 비어있습니다.")

    st.markdown("---")
    st.header("⚙️ 시스템 설정")
    if st.button("🔄 새로운 작업 시작 (Reset)", use_container_width=True):
        reset_workspace()
        st.sidebar.success("✨ 새로운 작업 화면으로 초기화되었습니다.")
        st.rerun()

# ----------------------------------------------------
# ★ 모바일/메인 화면 상단: 내 설정 표시 및 변경 바 (안전한 분리형 방식 적용)
# ----------------------------------------------------
selected_brand = st.session_state.pref_brand
selected_camera = f"{st.session_state.pref_phone_brand} {st.session_state.pref_phone_model}"

st.markdown(f"""<div class="noroo-header-box">
    <span class="noroo-brand-name">MULTI-BRAND AUTO COLOR SYSTEM</span>
    <h1 class="noroo-main-title">[{selected_brand}] AI 스마트 조색 & 결함 진단</h1>
</div>""", unsafe_allow_html=True)

st.write("")
with st.expander(f"⚙️ 내 설정 (클라우드 동기화): [{selected_brand}] | [{selected_camera}] (터치하여 변경)", expanded=False):
    col_mb1, col_mb2 = st.columns(2)
    
    with col_mb1:
        st.markdown("##### 🎨 도료 브랜드 설정")
        # Streamlit 버그 회피: key 직접 매핑을 없애고 index 기반으로 상태를 완벽 분리
        b_idx = valid_brands.index(st.session_state.pref_brand) if st.session_state.pref_brand in valid_brands else 0
        new_brand = st.selectbox("브랜드 변경", valid_brands, index=b_idx)
        
        # 값이 변경되었을 때만 세션과 DB에 저장 후 1번만 새로고침
        if new_brand != st.session_state.pref_brand:
            st.session_state.pref_brand = new_brand
            save_cloud_settings(st.session_state.pref_brand, st.session_state.pref_phone_brand, st.session_state.pref_phone_model)
            st.session_state.show_save_toast = True
            st.rerun()
            
        b_info = BRAND_CONFIGS[st.session_state.pref_brand]
        st.info(f"📌 **브랜드 수칙**: {b_info['special_rules']}\n\n🧪 **희석 수칙**: {b_info['thinner_info']}")

    with col_mb2:
        st.markdown("##### 📱 스마트폰 카메라 보정 설정")
        pb_idx = valid_phone_brands.index(st.session_state.pref_phone_brand) if st.session_state.pref_phone_brand in valid_phone_brands else 0
        new_p_brand = st.selectbox("제조사 선택", valid_phone_brands, index=pb_idx)
        
        p_models = list(CAMERA_PROFILES[new_p_brand].keys())
        pm_idx = p_models.index(st.session_state.pref_phone_model) if st.session_state.pref_phone_model in p_models else 0
        new_p_model = st.selectbox("기종 선택", p_models, index=pm_idx)
        
        if new_p_brand != st.session_state.pref_phone_brand or new_p_model != st.session_state.pref_phone_model:
            st.session_state.pref_phone_brand = new_p_brand
            st.session_state.pref_phone_model = new_p_model
            save_cloud_settings(st.session_state.pref_brand, st.session_state.pref_phone_brand, st.session_state.pref_phone_model)
            st.session_state.show_save_toast = True
            st.rerun()

        st.caption(f"🎯 **카메라 보정 알고리즘**: {CAMERA_PROFILES[st.session_state.pref_phone_brand][st.session_state.pref_phone_model]}")

st.markdown("---")

# ----------------------------------------------------
# 6. 메인 탭 구성
# ----------------------------------------------------
tab_tuning, tab_defect = st.tabs([f"🎨 {st.session_state.pref_brand} AI 미세 조색", "🔍 도장 결함 진단"])

with tab_tuning:
    current_stage = st.session_state.current_stage
    is_stage_1 = (current_stage == 1)
    stage_code = f"{current_stage}차"
    prev_stage_code = "1차" if current_stage == 2 else f"{current_stage-1}차"
    
    st.markdown(f'<div class="stage-badge">📍 현재 진행 단계: {st.session_state.pref_brand} {stage_code} 조색 프로세스</div>', unsafe_allow_html=True)
    st.subheader("0. 차종 및 색상명/코드 입력")
    
    col_c1, col_c2 = st.columns([3.5, 1])
    with col_c1:
        st.session_state.color_name = st.text_input("차종 및 목표 색상코드/색상명을 입력하세요", value=st.session_state.color_name, placeholder="예: 기아 ABT, 현대 SWP 등", key="color_name_input_field")

    with col_c2:
        st.write("") 
        st.write("")
        color_code_str = st.session_state.color_name.strip()
        auto_default_title = f"{datetime.now().strftime('%Y-%m-%d')}_{color_code_str}" if color_code_str else f"{datetime.now().strftime('%Y-%m-%d')}_색상미지정"
        
        if st.button("💾 클라우드 저장", type="primary", use_container_width=True, key="btn_step0_save"):
            if not color_code_str: st.warning("⚠️ 차종 및 색상명을 먼저 입력한 후 저장해 주세요.")
            else:
                db_save_work(auto_default_title, st.session_state.pref_brand)
                st.rerun()

    st.markdown("---")
    col_t1, col_t2 = st.columns(2)
    
    # 1. 목표 차체 사진
    with col_t1:
        st.write("1. 목표 차체/판넬 사진 (Target)")
        st.markdown("""<div class="distance-guide-box">
            <b>📏 촬영 가이드</b>: 차체 표면으로부터 <b>약 15cm 거리</b>에서 수직(90°)으로 촬영해 주세요.<br>
            💡 <b>모바일 후면 카메라 팁</b>: [📷 앱 내 직접 촬영] 시 화면의 <b>카메라 전환(🔄) 버튼</b>을 누르시거나, <b>[📁 갤러리/후면 카메라]</b> 탭 선택 후 [카메라]를 누르시면 됩니다.
        </div>""", unsafe_allow_html=True)
        
        if st.session_state.target_img_bytes is None:
            t_input_tab1, t_input_tab2 = st.tabs(["📷 앱 내 직접 촬영", "📁 갤러리 / 후면 카메라"])
            with t_input_tab1:
                cam_target = st.camera_input("목표 차체 촬영 (거리 15cm)", key="cam_target_input")
                if cam_target:
                    st.session_state.target_img_bytes = cam_target.getvalue()
                    st.session_state.target_img_name = "카메라 직접 촬영"
                    st.rerun()
            with t_input_tab2:
                uploaded_target = st.file_uploader("목표 차체 사진 파일 (후면 카메라 추천)", type=["jpg", "png", "jpeg"], key="file_target_input")
                if uploaded_target:
                    st.session_state.target_img_bytes = uploaded_target.getvalue()
                    st.session_state.target_img_name = uploaded_target.name
                    st.rerun()
        else:
            st.image(load_and_resize(st.session_state.target_img_bytes), caption=f"목표 색상 [{st.session_state.color_name if st.session_state.color_name else '미지정'}] (Target) - [{selected_camera}]", use_container_width=True)
            if st.button("🔄 목표 사진 다시 찍기"):
                st.session_state.target_img_bytes = None
                st.rerun()

    # 2. 시편 사진
    with col_t2:
        st.write(f"2. {stage_code} 도장 시편 사진 (Sample)")
        st.markdown("""<div class="distance-guide-box">
            <b>📏 촬영 가이드</b>: 시편 표면으로부터 <b>약 15cm 거리</b>에서 수직(90°)으로 촬영해 주세요.<br>
            💡 <b>모바일 후면 카메라 팁</b>: [📷 앱 내 직접 촬영] 시 화면의 <b>카메라 전환(🔄) 버튼</b>을 누르시거나, <b>[📁 갤러리/후면 카메라]</b> 탭 선택 후 [카메라]를 누르시면 됩니다.
        </div>""", unsafe_allow_html=True)
        
        s_input_tab1, s_input_tab2 = st.tabs(["📷 앱 내 직접 촬영", "📁 갤러리 / 후면 카메라"])
        with s_input_tab1:
            cam_sample = st.camera_input(f"{stage_code} 시편 촬영 (거리 15cm)", key=f"cam_sample_{current_stage}")
            if cam_sample: st.session_state.temp_sample_bytes = cam_sample.getvalue()
        with s_input_tab2:
            file_sample = st.file_uploader(f"{stage_code} 시편 파일 (후면 카메라 추천)", type=["jpg", "png", "jpeg"], key=f"file_sample_{current_stage}")
            if file_sample: st.session_state.temp_sample_bytes = file_sample.getvalue()

        if st.session_state.temp_sample_bytes:
            st.image(load_and_resize(st.session_state.temp_sample_bytes), caption=f"{stage_code} 신규 도장 시편 (Sample) - [{selected_camera}]", use_container_width=True)

    # 3. 초선명 대조
    if not is_stage_1 and st.session_state.prev_sample_bytes and st.session_state.target_img_bytes and st.session_state.temp_sample_bytes:
        st.markdown("---")
        st.markdown(f"""<div class="comparison-card">
            <h4 style="margin-top:0; color:#003375;">📱 [{st.session_state.pref_brand}] 초고화질 3분할 입자 정밀 대조</h4>
            <p style="font-size:14px; color:#2D3748; margin-bottom:8px;"><b>[좌: {prev_stage_code} 시편]</b> | <b>[중앙: 🎯 목표 차체]</b> | <b>[우: {stage_code} 신규 시편]</b></p>
        </div>""", unsafe_allow_html=True)
        st.image(create_3way_split_view(st.session_state.prev_sample_bytes, st.session_state.target_img_bytes, st.session_state.temp_sample_bytes, crop_ratio=0.4), caption=f"◀️ {prev_stage_code} 시편 | 🎯 목표 차체 [{st.session_state.color_name}] | {stage_code} 신규 시편 ▶️", use_container_width=True)

    st.markdown("---")
    col_r1, col_r2 = st.columns([1.2, 0.8])

    # 4. 배합 레시피
    with col_r1:
        if is_stage_1:
            st.subheader(f"3. 1차 기본 배합 레시피 ({st.session_state.pref_brand})")
            r_input_tab1, r_input_tab2 = st.tabs(["📷 카드 촬영 / 업로드 (추천)", "✍️ 텍스트 직접 작성"])
            recipe_img_bytes = None
            with r_input_tab1:
                cam_recipe = st.camera_input("배합표/시편 카드 촬영", key="cam_recipe_1차")
                file_recipe = st.file_uploader("또는 카드 사진 파일 업로드", type=["jpg", "png", "jpeg"], key="file_recipe_1차")
                if cam_recipe: recipe_img_bytes = cam_recipe.getvalue()
                elif file_recipe: recipe_img_bytes = file_recipe.getvalue()

                if recipe_img_bytes:
                    st.image(Image.open(io.BytesIO(recipe_img_bytes)), caption="촬영/업로드된 배합표 카드", width=350)
                    if st.button("🔍 카드 사진에서 배합표 읽어와 표에 반영하기", key="btn_ocr_recipe"):
                        with st.spinner(f"AI가 [{st.session_state.pref_brand}] 카드 속 수치를 분석 중입니다..."):
                            extracted_df = extract_df_from_recipe_image(client, recipe_img_bytes, st.session_state.pref_brand)
                            if extracted_df is not None and not extracted_df.empty:
                                st.session_state.recipe_table_df = extracted_df
                                st.success("🎉 배합표 수치가 성공적으로 읽혀 아래 표에 자동 입력되었습니다!")
                                st.rerun()
                            else: st.warning("⚠️ 사진에서 안료 수치를 완전히 읽지 못했습니다. 아래 표에 직접 입력해 주세요.")
            with r_input_tab2:
                recipe_text = st.text_area("1차 배합 레시피 직접 작성", value="", placeholder=f"예: {BRAND_CONFIGS[st.session_state.pref_brand]['code_example']}", key="r_text_1차")
                if recipe_text.strip():
                    parsed_df = extract_recipe_df_from_ai_text(recipe_text, st.session_state.pref_brand)
                    if parsed_df is not None and not parsed_df.empty: st.session_state.recipe_table_df = parsed_df

            st.write(f"📋 **1차 확정 배합표 ({st.session_state.pref_brand}):**")
            st.session_state.recipe_table_df = st.data_editor(st.session_state.recipe_table_df, use_container_width=True, num_rows="dynamic", key="editor_1차_preview")
        else:
            st.subheader(f"3. {prev_stage_code} 확정 배합 레시피 ({st.session_state.pref_brand})")
            st.session_state.recipe_table_df = st.data_editor(st.session_state.recipe_table_df, use_container_width=True, num_rows="dynamic", key=f"editor_{stage_code}")

    with col_r2:
        st.subheader(f"4. {stage_code} 목표 중량 및 측색 수치")
        target_total_weight = st.number_input(f"🎯 새로 배합할 총 중량 (g)", min_value=10.0, max_value=10000.0, value=100.0, step=10.0, key=f"weight_{stage_code}")
        lab_data = st.text_input("측색기 $L^*a*b^*$ 수치 (선택 사항)", placeholder="예: [목표] L*: 45.2, a*: 12.3 / [시편] L*: 43.8, a*: 13.5", key=f"lab_{stage_code}")

    st.markdown("---")

    # 5. AI 실행
    btn_label = f"🚀 [{st.session_state.pref_brand}] {stage_code} AI 미세 조색 실행"
    if st.button(btn_label, type="primary", use_container_width=True):
        if st.session_state.target_img_bytes is None: st.warning("⚠️ 목표 차체/판넬 사진(Target)을 촬영하거나 업로드해 주세요.")
        elif st.session_state.temp_sample_bytes is None: st.warning(f"⚠️ {stage_code} 도장 시편 사진(Sample)을 촬영하거나 업로드해 주세요.")
        elif is_stage_1 and st.session_state.recipe_table_df.empty: st.warning("⚠️ 배합표 카드를 인식시키거나 안료 수치를 입력해 주세요.")
        else:
            with st.spinner(f"AI가 클라우드 DB의 과거 성공 족보 데이터를 실시간 조회하여 분석 중입니다..."):
                try:
                    img_target = load_and_resize(st.session_state.target_img_bytes)
                    img_current = load_and_resize(st.session_state.temp_sample_bytes)
                    table_str = st.session_state.recipe_table_df.to_string(index=False)
                    rag_successful_recipes = db_get_successful_recipes_rag(st.session_state.pref_brand, st.session_state.color_name)

                    brand_system_prompt = f"""
                    당신은 [{st.session_state.pref_brand}] 페인트 도장 및 조색 분야 최고 기술 전문가입니다.
                    첫 번째 이미지('목표 색상')와 두 번째 이미지('{stage_code} 도장 시편')를 정밀 분석하세요.

                    [선택 브랜드 및 현장 기술 수칙]
                    - **선택 브랜드**: {st.session_state.pref_brand}
                    - **목표 차종/색상명**: {st.session_state.color_name if st.session_state.color_name else '미지정'}
                    - **브랜드 특수 수칙**: {BRAND_CONFIGS[st.session_state.pref_brand]['special_rules']}
                    - **희석제 수칙**: {BRAND_CONFIGS[st.session_state.pref_brand]['thinner_info']}
                    - **현재 진행 단계**: {stage_code} 조색
                    - **이전 배합표**: \n{table_str}
                    - **목표 총 중량**: {target_total_weight}g
                    - **촬영 기기 정보**: {selected_camera}
                    - **스마트폰 카메라 보정 수칙**: {CAMERA_PROFILES[st.session_state.pref_phone_brand][st.session_state.pref_phone_model]}
                    - **측색 수치**: {lab_data if lab_data else '없음 (CIE L*a*b* 정밀 추정 분석)'}
                    {rag_successful_recipes}

                    [★ 핵심: 색공간 분석 및 Delta E <= 0.5 판정 규칙 ★]
                    1. CIE L*a*b* 정밀 평가 (Delta L*, Delta a*, Delta b*, Flop 감도 오차)
                    2. 두 사진 구분 불가능 시 **예상 Delta E <= 0.5** 판정.
                    3. 합격 시 상단에 `[판정: 🎉 조색 완벽 합격 (Delta E <= 0.5)]` 명시.
                    4. 불합격 시 상단에 `[판정: 🔺 미세 보정 필요]` 명시 후 신규 배합 산출.

                    [작성 양식]
                    1. **CIE L*a*b* 평가**: 추정 색차 (Delta E), 최종 판정, 명도/색상 오차 상세
                    2. **[{st.session_state.pref_brand}] 배합 변경 처방 이유**:
                    3. **📊 AI 신규 배합 대조표 ({target_total_weight}g 기준)**: | 안료 코드 | {prev_stage_code} 중량 | {stage_code} 신규 중량 | 차이 | 처방 역할 |
                    4. **교반 및 희석 지침**: 권장 혼합비 명시
                    """
                    response = client.models.generate_content(model="gemini-3.5-flash", contents=[img_target, img_current, brand_system_prompt])
                    st.session_state.ai_result_text = response.text
                    
                    if "조색 완벽 합격" in response.text or "Delta E <= 0.5" in response.text:
                        st.session_state.is_passed = True
                        st.session_state.show_next_btn = False
                    else:
                        st.session_state.is_passed = False
                        st.session_state.show_next_btn = True

                    parsed_df = extract_recipe_df_from_ai_text(response.text, st.session_state.pref_brand)
                    if parsed_df is not None and not parsed_df.empty: st.session_state.recipe_table_df = parsed_df
                except APIError as e: st.error(f"API 오류가 발생했습니다: {e}")

    # 6. 결과 출력
    if st.session_state.ai_result_text:
        st.markdown(f"### 📊 [{st.session_state.pref_brand}] [{st.session_state.color_name}] AI 색공간 분석 리포트")
        st.markdown(st.session_state.ai_result_text)
        if st.session_state.is_passed:
            st.balloons()
            st.success("🎉 Delta E <= 0.5 이하로 조색이 완벽히 합격 처리되었습니다! 해당 레시피가 클라우드 DB에 '성공 족보'로 등록되었습니다.")
    if st.session_state.show_next_btn and not st.session_state.is_passed:
        st.markdown("---")
        st.button(f"➡️ {current_stage + 1}차 조색으로 계속 진행하기", on_click=go_next_stage, type="primary", use_container_width=True)

with tab_defect:
    st.subheader(f"🔍 [{st.session_state.pref_brand}] 도장 결함 원인 분석 및 재작업 가이드")
    col1, col2 = st.columns([1, 1])
    with col1:
        st.write("결함 부위 사진 입력")
        d_input_tab1, d_input_tab2 = st.tabs(["📷 앱 내 직접 촬영", "📁 갤러리 / 후면 카메라"])
        defect_img_bytes = None
        with d_input_tab1:
            cam_defect = st.camera_input("결함 부위 직접 촬영", key="cam_defect_input")
            if cam_defect: defect_img_bytes = cam_defect.getvalue()
        with d_input_tab2:
            file_defect = st.file_uploader("결함 부위 사진 파일 선택", type=["jpg", "png", "jpeg"], key="file_defect_input")
            if file_defect: defect_img_bytes = file_defect.getvalue()
        if defect_img_bytes: st.image(load_and_resize(defect_img_bytes), caption=f"진단 대상 결함 이미지 - [{selected_camera}]", use_container_width=True)

    with col2:
        defect_context = st.text_area("작업 환경 및 현장 증상 요약", placeholder="예: 클리어 코트 도포 후 오렌지필 현상 발생. 건조 온도 60도.")

    if st.button("🚨 결함 진단 실행", type="primary", use_container_width=True):
        if defect_img_bytes:
            with st.spinner("AI가 결함 형태 및 작업 환경을 분석 중입니다..."):
                try:
                    img = load_and_resize(defect_img_bytes)
                    defect_prompt = f"""
                    당신은 자동차 도장 및 표면처리 최고 전문가입니다.
                    전달된 결함 부위 이미지와 작업 환경을 분석해 진단 리포트를 작성해 주세요.
                    - 사용 도료 브랜드: {st.session_state.pref_brand}
                    - 촬영 기기: {selected_camera} ({CAMERA_PROFILES[st.session_state.pref_phone_brand][st.session_state.pref_phone_model]})
                    - 현장 정보: {defect_context}
                    
                    아래 항목으로 답변하세요: 1. 결함명 2. 원인 3. 재작업 솔루션 4. [{st.session_state.pref_brand}] 전용 예방 대책
                    """
                    response = client.models.generate_content(model="gemini-3.5-flash", contents=[img, defect_prompt])
                    st.success("결함 진단 완료!")
                    st.markdown(response.text)
                except APIError as e: st.error(f"오류가 발생했습니다: {e}")
        else: st.warning("⚠️ 결함 부위 사진을 촬영하거나 업로드해 주세요.")