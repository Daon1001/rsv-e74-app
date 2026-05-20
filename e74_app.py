# -*- coding: utf-8 -*-
"""
E-7-4 숙련기능인력 비자 전환 컨설팅 앱
RSV (부자들의 비밀금고) - 중소기업경영지원단
- 사전 자격 진단
- 점수제 시뮬레이션 (300점 만점)
- Claude API 기반 AI 보강 플랜 생성
- 사용자 승인 / 사용량 추적
"""

import streamlit as st
import json
import os
import requests
from datetime import datetime, date
import pandas as pd
from anthropic import Anthropic

# ============================================================
# 0. 페이지 설정 & RSV 디자인
# ============================================================
st.set_page_config(
    page_title="E-7-4 비자 컨설팅 | RSV",
    page_icon="🛂",
    layout="wide",
    initial_sidebar_state="expanded",
)

# RSV 프리미엄 다크 네이비 + 골드
RSV_NAVY = "#0A1628"
RSV_NAVY_LIGHT = "#162A47"
RSV_GOLD = "#D4AF37"
RSV_GOLD_LIGHT = "#E8C964"
RSV_TEXT = "#E8E6E1"
RSV_MUTED = "#8B95A7"

st.markdown(f"""
<style>
.stApp {{
    background: linear-gradient(135deg, {RSV_NAVY} 0%, {RSV_NAVY_LIGHT} 100%);
    color: {RSV_TEXT};
}}
section[data-testid="stSidebar"] {{
    background: {RSV_NAVY};
    border-right: 1px solid {RSV_GOLD}33;
}}
h1, h2, h3, h4 {{
    color: {RSV_GOLD} !important;
    font-weight: 700;
}}
.stButton button {{
    background: linear-gradient(135deg, {RSV_GOLD} 0%, {RSV_GOLD_LIGHT} 100%);
    color: {RSV_NAVY};
    border: none;
    font-weight: 700;
    padding: 0.5rem 1.5rem;
    border-radius: 8px;
}}
.stButton button:hover {{
    background: {RSV_GOLD_LIGHT};
    color: {RSV_NAVY};
}}
[data-testid="stMetricValue"] {{
    color: {RSV_GOLD};
    font-size: 2rem;
}}
.rsv-card {{
    background: {RSV_NAVY_LIGHT};
    border: 1px solid {RSV_GOLD}44;
    border-radius: 12px;
    padding: 1.5rem;
    margin: 1rem 0;
}}
.rsv-success {{
    background: #1a4d2e;
    border-left: 4px solid #4ade80;
    padding: 1rem;
    border-radius: 8px;
    margin: 0.5rem 0;
}}
.rsv-warning {{
    background: #5c4317;
    border-left: 4px solid {RSV_GOLD};
    padding: 1rem;
    border-radius: 8px;
    margin: 0.5rem 0;
}}
.rsv-danger {{
    background: #5c1a1a;
    border-left: 4px solid #ef4444;
    padding: 1rem;
    border-radius: 8px;
    margin: 0.5rem 0;
}}
.score-big {{
    font-size: 3rem;
    font-weight: 800;
    color: {RSV_GOLD};
    text-align: center;
}}
</style>
""", unsafe_allow_html=True)

# ============================================================
# 1. 상수 / 설정 (벤처·KOITA 앱과 동일 패턴)
# ============================================================
GIST_ID = "958084eac7f7fcb31a441dcc7d0cd7cd"
ADMIN_EMAIL = "incheon00@gmail.com"
USD_TO_KRW = 1380

MODEL_PRICES = {
    "claude-haiku-4-5-20251001": {"input": 1.0, "output": 5.0, "name": "Haiku 4.5"},
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0, "name": "Sonnet 4.6"},
    "claude-opus-4-7": {"input": 5.0, "output": 25.0, "name": "Opus 4.7"},
}

DEFAULT_MODEL = "claude-haiku-4-5-20251001"  # 비용 최적화

# ============================================================
# 2. 사용자 DB (Gist 연동) - 벤처/KOITA 앱 패턴 재사용
# ============================================================
def get_github_token():
    return st.secrets.get("GITHUB_TOKEN", os.getenv("GITHUB_TOKEN", ""))

def get_anthropic_key():
    return st.secrets.get("ANTHROPIC_API_KEY", os.getenv("ANTHROPIC_API_KEY", ""))

@st.cache_data(ttl=60)
def load_user_db():
    """Gist에서 사용자 DB 로드"""
    token = get_github_token()
    if not token:
        return {"users": {}, "usage_logs": []}
    try:
        r = requests.get(
            f"https://api.github.com/gists/{GIST_ID}",
            headers={"Authorization": f"token {token}"},
            timeout=10,
        )
        if r.status_code == 200:
            files = r.json().get("files", {})
            if "e74_users.json" in files:
                return json.loads(files["e74_users.json"]["content"])
        return {"users": {}, "usage_logs": []}
    except Exception as e:
        st.error(f"DB 로드 실패: {e}")
        return {"users": {}, "usage_logs": []}

def save_user_db(db):
    """Gist에 사용자 DB 저장"""
    token = get_github_token()
    if not token:
        st.error("❌ GITHUB_TOKEN이 Streamlit Secrets에 없습니다.")
        return False
    try:
        r = requests.patch(
            f"https://api.github.com/gists/{GIST_ID}",
            headers={"Authorization": f"token {token}"},
            json={"files": {"e74_users.json": {"content": json.dumps(db, ensure_ascii=False, indent=2)}}},
            timeout=10,
        )
        st.cache_data.clear()
        if r.status_code != 200:
            st.error(f"❌ Gist 저장 실패 (HTTP {r.status_code}): {r.text[:300]}")
            return False
        return True
    except Exception as e:
        st.error(f"❌ DB 저장 예외: {type(e).__name__}: {e}")
        return False

def add_usage_log(db, email, model, input_tokens, output_tokens):
    """사용 로그 추가 (5000개 제한)"""
    prices = MODEL_PRICES.get(model, {"input": 1.0, "output": 5.0})
    cost_usd = (input_tokens * prices["input"] + output_tokens * prices["output"]) / 1_000_000
    log = {
        "timestamp": datetime.now().isoformat(),
        "email": email,
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": round(cost_usd, 6),
    }
    db.setdefault("usage_logs", []).append(log)
    if len(db["usage_logs"]) > 5000:
        db["usage_logs"] = db["usage_logs"][-5000:]
    save_user_db(db)

# ============================================================
# 3. Claude API 호출 (벤처/KOITA와 동일 시그니처)
# ============================================================
def claude_generate(prompt, system="", model=DEFAULT_MODEL, max_tokens=2000):
    """
    Returns: {"ok": bool, "text": str, "error": str,
              "input_tokens": int, "output_tokens": int}
    """
    api_key = get_anthropic_key()
    if not api_key:
        return {"ok": False, "text": "", "error": "API 키 미설정",
                "input_tokens": 0, "output_tokens": 0}
    try:
        client = Anthropic(api_key=api_key)
        msg = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system if system else "당신은 한국 비자(E-7-4 숙련기능인력) 전문 컨설턴트입니다. 친절하고 정확하게 답변하세요.",
            messages=[{"role": "user", "content": prompt}],
        )
        return {
            "ok": True,
            "text": msg.content[0].text,
            "error": "",
            "input_tokens": msg.usage.input_tokens,
            "output_tokens": msg.usage.output_tokens,
        }
    except Exception as e:
        return {"ok": False, "text": "", "error": str(e),
                "input_tokens": 0, "output_tokens": 0}

# ============================================================
# 4. E-7-4 점수제 핵심 로직
# ============================================================
# 출처: 법무부 K-point E74 (2025년 기준)
# 기본항목 300점 만점 + 가점 / 평균소득·한국어 각 최소 50점 필수

INDUSTRY_SECTORS = ["제조업", "뿌리산업", "농축산업", "조선업", "어업/내항상선", "건설업"]

def calc_income_score(annual_salary_krw, sector):
    """평균소득 점수 (최대 120점)"""
    # 단위: 만원
    s = annual_salary_krw / 10000
    if sector in ("농축산업", "어업/내항상선"):
        # 농축산·어업 기준
        if s >= 4000: return 120
        if s >= 3500: return 100
        if s >= 3000: return 80
        if s >= 2700: return 65
        if s >= 2400: return 50
        return 0
    else:
        if s >= 4000: return 120
        if s >= 3500: return 100
        if s >= 3000: return 80
        if s >= 2800: return 65
        if s >= 2600: return 50
        return 0

def calc_korean_score(topik_level, kiip_stage, kiip_pretest):
    """한국어 능력 점수 (최대 120점) - 가장 높은 값 1개 적용"""
    scores = []
    # TOPIK
    topik_map = {"4급 이상": 120, "3급": 100, "2급": 50, "없음/1급": 0}
    scores.append(topik_map.get(topik_level, 0))
    # 사회통합프로그램 이수
    kiip_map = {"4단계 이상": 120, "3단계": 100, "2단계": 50, "이수안함": 0}
    scores.append(kiip_map.get(kiip_stage, 0))
    # 사회통합 사전평가
    pre_map = {"81점 이상": 120, "61~80점": 100, "41~60점": 50, "응시안함/40점이하": 0}
    scores.append(pre_map.get(kiip_pretest, 0))
    return max(scores)

def calc_age_score(age):
    """나이 점수 (최대 60점)"""
    if 18 <= age <= 24: return 60
    if 25 <= age <= 29: return 50
    if 30 <= age <= 34: return 40
    if 35 <= age <= 39: return 30
    if 40 <= age <= 49: return 20
    return 10

def calc_career_score(years_in_korea):
    """경력 점수 (최대 50점) - 근무기간"""
    if years_in_korea >= 8: return 50
    if years_in_korea >= 7: return 40
    if years_in_korea >= 6: return 30
    if years_in_korea >= 5: return 20
    if years_in_korea >= 4: return 10
    return 0

def calc_bonus_score(data):
    """가점 항목 (중복 가능)"""
    bonus = 0
    items = []
    if data.get("license"):
        bonus += 10
        items.append("국가기술자격증 +10")
    if data.get("rural_area"):
        years = data.get("rural_years", 0)
        if years >= 4: bonus += 10; items.append("읍·면지역 4년+ +10")
        elif years >= 3: bonus += 7; items.append("읍·면지역 3년+ +7")
        elif years >= 2: bonus += 5; items.append("읍·면지역 2년+ +5")
    if data.get("population_decline"):
        years = data.get("decline_years", 0)
        if years >= 4: bonus += 5; items.append("인구감소지역 4년+ +5")
        elif years >= 3: bonus += 3; items.append("인구감소지역 3년+ +3")
        elif years >= 2: bonus += 2; items.append("인구감소지역 2년+ +2")
    if data.get("study_korea"):
        level = data.get("study_level", "")
        if level == "석사 이상": bonus += 10; items.append("국내 석사+ +10")
        elif level == "학사": bonus += 5; items.append("국내 학사 +5")
        elif level == "전문학사": bonus += 3; items.append("국내 전문학사 +3")
    if data.get("kiip_5"):
        bonus += 5; items.append("사회통합 5단계 이수 +5")
    if data.get("tax_paid"):
        bonus += 5; items.append("납세 300만원+ +5")
    if data.get("award"):
        bonus += 5; items.append("국가/지자체 표창 +5")
    if data.get("central_recommend"):
        bonus += 10; items.append("중앙부처 추천 +10")
    return bonus, items

def calculate_total_score(data):
    """전체 점수 계산"""
    income = calc_income_score(data["salary"], data["sector"])
    korean = calc_korean_score(data["topik"], data["kiip"], data["kiip_pre"])
    age = calc_age_score(data["age"])
    career = calc_career_score(data["years"])
    bonus, bonus_items = calc_bonus_score(data)
    
    # 학력 점수 (최대 35점)
    edu_map = {"박사": 35, "석사": 25, "학사": 15, "전문학사": 10, "고졸": 5, "없음": 0}
    edu = edu_map.get(data.get("education", "없음"), 0)
    
    base_total = income + korean + age + career + edu
    grand_total = base_total + bonus
    
    return {
        "income": income,
        "korean": korean,
        "age": age,
        "career": career,
        "education": edu,
        "bonus": bonus,
        "bonus_items": bonus_items,
        "base_total": base_total,
        "grand_total": grand_total,
        "passed": grand_total >= 200 and income >= 50 and korean >= 50,
    }

# ============================================================
# 5. 사전 자격 진단 (Eligibility Check)
# ============================================================
def check_eligibility(data):
    """결격사유 / 기본요건 진단"""
    issues = []
    warnings = []
    passed_items = []
    
    # 필수 요건
    if data["current_visa"] not in ["E-9", "E-10", "H-2"]:
        issues.append("❌ 현재 비자가 E-9/E-10/H-2가 아님 (E-7-4 전환 불가)")
    else:
        passed_items.append(f"✅ 현재 비자: {data['current_visa']}")
    
    if data["years"] < 4:
        if data.get("kiip_3plus"):
            warnings.append("⚠️ 근무기간 4년 미만이나 사회통합 3단계 이상 이수로 충족 인정")
        else:
            issues.append(f"❌ E-9/E-10/H-2 근무기간 부족 ({data['years']}년, 4년 필요)")
    else:
        passed_items.append(f"✅ 근무기간: {data['years']}년")
    
    if data["salary"] < 26000000 and data["sector"] not in ("농축산업", "어업/내항상선"):
        issues.append(f"❌ 연봉 2,600만원 미만 (현재 {data['salary']/10000:.0f}만원)")
    elif data["salary"] < 25000000 and data["sector"] in ("농축산업", "어업/내항상선"):
        issues.append(f"❌ 연봉 2,500만원 미만 (현재 {data['salary']/10000:.0f}만원)")
    else:
        passed_items.append(f"✅ 연봉: {data['salary']/10000:.0f}만원")
    
    if data.get("current_employer_months", 0) < 12:
        issues.append(f"❌ 현 사업장 근무 1년 미만 ({data.get('current_employer_months',0)}개월)")
    else:
        passed_items.append(f"✅ 현 사업장 근무: {data.get('current_employer_months',0)}개월")
    
    # 결격사유
    if data.get("criminal"):
        issues.append("❌ 벌금 100만원 이상 형사처벌 이력 (신청 불가)")
    if data.get("tax_unpaid"):
        issues.append("❌ 세금 체납 중 (완납 후 신청 가능)")
    if data.get("immigration_violation_4plus"):
        issues.append("❌ 출입국관리법 4회 이상 위반 (신청 불가)")
    if data.get("illegal_stay_3m"):
        issues.append("❌ 3개월 이상 불법체류 이력 (신청 불가)")
    
    if not data.get("criminal") and not data.get("tax_unpaid") and not data.get("immigration_violation_4plus") and not data.get("illegal_stay_3m"):
        passed_items.append("✅ 결격사유 없음")
    
    # 한국어 최소 요건 (2026.12.31까지 유예 가능)
    has_korean = (data["topik"] != "없음/1급" or data["kiip"] != "이수안함" or data["kiip_pre"] != "응시안함/40점이하")
    if not has_korean:
        warnings.append("⚠️ 한국어 능력 미충족 - 2026.12.31까지 한시 유예 가능, 이후 TOPIK 2급+ 필수")
    else:
        passed_items.append("✅ 한국어 능력 보유")
    
    return {
        "eligible": len(issues) == 0,
        "issues": issues,
        "warnings": warnings,
        "passed_items": passed_items,
    }

# ============================================================
# 6. 인증 / 사용자 관리 (벤처·KOITA와 동일)
# ============================================================
def is_admin():
    return st.session_state.get("user_email") == ADMIN_EMAIL

def login_signup_ui():
    st.markdown("### 🔐 로그인 / 회원가입")
    db = load_user_db()
    
    tab1, tab2 = st.tabs(["로그인", "회원가입"])
    
    with tab1:
        email = st.text_input("이메일", key="login_email")
        if st.button("로그인", key="btn_login"):
            users = db.get("users", {})
            if email in users:
                user = users[email]
                if user.get("approved") or email == ADMIN_EMAIL:
                    st.session_state["user_email"] = email
                    st.session_state["user_name"] = user.get("name", email)
                    st.success(f"환영합니다, {user.get('name', email)}님!")
                    st.rerun()
                else:
                    st.warning("⏳ 관리자 승인 대기 중입니다.")
            else:
                st.error("등록되지 않은 이메일입니다.")
    
    with tab2:
        name = st.text_input("이름", key="signup_name")
        email_new = st.text_input("이메일", key="signup_email")
        phone = st.text_input("연락처", key="signup_phone")
        company = st.text_input("소속 회사 (선택)", key="signup_company")
        if st.button("회원가입 신청", key="btn_signup"):
            if not (name and email_new):
                st.error("이름과 이메일은 필수입니다.")
            elif email_new in db.get("users", {}):
                st.warning("이미 등록된 이메일입니다.")
            else:
                db.setdefault("users", {})[email_new] = {
                    "name": name, "phone": phone, "company": company,
                    "approved": email_new == ADMIN_EMAIL,
                    "created_at": datetime.now().isoformat(),
                }
                if save_user_db(db):
                    st.success("✅ 가입 신청 완료! 관리자 승인 후 이용 가능합니다.")
                else:
                    st.error("저장 실패. 관리자에게 문의하세요.")

# ============================================================
# 7. 메인 화면 - 진단 + 점수 시뮬레이션
# ============================================================
def diagnostic_ui():
    st.title("🛂 E-7-4 비자 사전 진단 & AI 보강 플랜")
    st.markdown(f"<p style='color:{RSV_MUTED}'>RSV 부자들의 비밀금고 · 중소기업경영지원단</p>", unsafe_allow_html=True)
    
    st.markdown("""
    <div class="rsv-card">
    <b>이 도구로 알 수 있는 것</b><br>
    • E-7-4 신청 자격 충족 여부 (결격사유 자가진단)<br>
    • 현재 점수 (300점 만점) — 합격선 200점<br>
    • 부족한 점수를 채우는 <b>최단 경로 AI 플랜</b> (Claude 기반)<br>
    </div>
    """, unsafe_allow_html=True)
    
    with st.form("diag_form"):
        st.markdown("### 1️⃣ 기본 정보")
        c1, c2, c3 = st.columns(3)
        with c1:
            current_visa = st.selectbox("현재 비자", ["E-9", "E-10", "H-2", "기타"])
            age = st.number_input("나이", 18, 65, 30)
        with c2:
            sector = st.selectbox("종사 분야", INDUSTRY_SECTORS)
            years = st.number_input("E-9/E-10/H-2 누적 근무기간 (년)", 0.0, 15.0, 4.0, step=0.5)
        with c3:
            current_employer_months = st.number_input("현 사업장 근무 (개월)", 0, 120, 12)
            salary = st.number_input("연봉 (원)", 0, 100000000, 28000000, step=1000000)
        
        st.markdown("### 2️⃣ 한국어 능력")
        c1, c2, c3 = st.columns(3)
        with c1:
            topik = st.selectbox("TOPIK 등급", ["없음/1급", "2급", "3급", "4급 이상"])
        with c2:
            kiip = st.selectbox("사회통합프로그램 이수", ["이수안함", "2단계", "3단계", "4단계 이상"])
        with c3:
            kiip_pre = st.selectbox("사회통합 사전평가", ["응시안함/40점이하", "41~60점", "61~80점", "81점 이상"])
        
        kiip_3plus = st.checkbox("사회통합 3단계 이상 이수 (근무기간 1년 단축 우대)")
        
        st.markdown("### 3️⃣ 학력 / 가점 항목")
        c1, c2 = st.columns(2)
        with c1:
            education = st.selectbox("최종 학력", ["없음", "고졸", "전문학사", "학사", "석사", "박사"])
            study_korea = st.checkbox("국내 대학에서 2년 이상 유학")
            study_level = st.selectbox("국내 유학 학위", ["전문학사", "학사", "석사 이상"]) if study_korea else None
            license_held = st.checkbox("국가기술자격증 보유")
            kiip_5 = st.checkbox("사회통합프로그램 5단계 이수")
        with c2:
            rural_area = st.checkbox("읍·면지역 근무 중")
            rural_years = st.number_input("읍·면지역 근무 연수", 0, 10, 0) if rural_area else 0
            population_decline = st.checkbox("인구감소지역 근무 중")
            decline_years = st.number_input("인구감소지역 근무 연수", 0, 10, 0) if population_decline else 0
            tax_paid = st.checkbox("최근 1년 소득세 납부 300만원 이상")
            award = st.checkbox("국가/지자체 표창 또는 200시간 이상 봉사")
            central_recommend = st.checkbox("중앙부처 추천 (고용부/산업부 등)")
        
        st.markdown("### 4️⃣ 결격사유 자가진단")
        c1, c2 = st.columns(2)
        with c1:
            criminal = st.checkbox("⚠️ 벌금 100만원 이상 형사처벌 이력")
            tax_unpaid = st.checkbox("⚠️ 현재 세금 체납 중")
        with c2:
            immigration_violation_4plus = st.checkbox("⚠️ 출입국관리법 4회 이상 위반")
            illegal_stay_3m = st.checkbox("⚠️ 3개월 이상 불법체류 이력")
        
        submitted = st.form_submit_button("🔍 진단하기", use_container_width=True)
    
    if submitted:
        data = {
            "current_visa": current_visa, "age": age, "sector": sector, "years": years,
            "current_employer_months": current_employer_months, "salary": salary,
            "topik": topik, "kiip": kiip, "kiip_pre": kiip_pre, "kiip_3plus": kiip_3plus,
            "education": education, "study_korea": study_korea, "study_level": study_level,
            "license": license_held, "kiip_5": kiip_5,
            "rural_area": rural_area, "rural_years": rural_years,
            "population_decline": population_decline, "decline_years": decline_years,
            "tax_paid": tax_paid, "award": award, "central_recommend": central_recommend,
            "criminal": criminal, "tax_unpaid": tax_unpaid,
            "immigration_violation_4plus": immigration_violation_4plus,
            "illegal_stay_3m": illegal_stay_3m,
        }
        st.session_state["diag_data"] = data
        st.session_state["diag_done"] = True
    
    if st.session_state.get("diag_done"):
        show_results(st.session_state["diag_data"])


def show_results(data):
    st.markdown("---")
    st.markdown("## 📋 진단 결과")
    
    # 1) 자격 진단
    elig = check_eligibility(data)
    
    if elig["eligible"]:
        st.markdown(f'<div class="rsv-success"><h3>✅ 신청 자격 충족</h3>기본 요건과 결격사유 모두 통과했습니다.</div>',
                    unsafe_allow_html=True)
    else:
        st.markdown(f'<div class="rsv-danger"><h3>❌ 신청 불가 사유 있음</h3></div>', unsafe_allow_html=True)
        for issue in elig["issues"]:
            st.markdown(f"- {issue}")
    
    if elig["warnings"]:
        for w in elig["warnings"]:
            st.markdown(f'<div class="rsv-warning">{w}</div>', unsafe_allow_html=True)
    
    with st.expander("✅ 통과한 항목"):
        for p in elig["passed_items"]:
            st.markdown(f"- {p}")
    
    # 2) 점수 계산
    score = calculate_total_score(data)
    st.markdown("---")
    st.markdown("## 🎯 점수 시뮬레이션")
    
    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        st.markdown(f'<div class="score-big">{score["grand_total"]} / 300점</div>', unsafe_allow_html=True)
        st.markdown(f"<p style='text-align:center; color:{RSV_MUTED}'>기본 {score['base_total']}점 + 가점 {score['bonus']}점</p>",
                    unsafe_allow_html=True)
    with c2:
        pass_status = "✅ 합격선 통과" if score["passed"] else "❌ 부족"
        st.metric("합격선 (200점)", pass_status)
    with c3:
        gap = max(0, 200 - score["grand_total"])
        st.metric("부족 점수", f"{gap}점")
    
    # 점수 상세
    score_df = pd.DataFrame([
        {"항목": "평균소득 (최소 50)", "점수": score["income"], "최대": 120},
        {"항목": "한국어능력 (최소 50)", "점수": score["korean"], "최대": 120},
        {"항목": "나이", "점수": score["age"], "최대": 60},
        {"항목": "경력", "점수": score["career"], "최대": 50},
        {"항목": "학력", "점수": score["education"], "최대": 35},
        {"항목": "가점", "점수": score["bonus"], "최대": "-"},
    ])
    st.dataframe(score_df, use_container_width=True, hide_index=True)
    
    if score["bonus_items"]:
        with st.expander(f"가점 내역 ({score['bonus']}점)"):
            for item in score["bonus_items"]:
                st.markdown(f"- {item}")
    
    # 최소점 미달 경고
    if score["income"] < 50:
        st.markdown('<div class="rsv-danger">⚠️ 평균소득 50점 미달 — 합격 자체가 불가합니다. 연봉 인상 필수.</div>',
                    unsafe_allow_html=True)
    if score["korean"] < 50:
        st.markdown('<div class="rsv-danger">⚠️ 한국어 50점 미달 — TOPIK 2급 또는 사회통합 2단계 이상 필수.</div>',
                    unsafe_allow_html=True)
    
    # 3) AI 보강 플랜
    st.markdown("---")
    st.markdown("## 🤖 AI 맞춤 보강 플랜")
    
    if st.button("🚀 Claude AI로 최단 경로 플랜 생성", use_container_width=True):
        generate_ai_plan(data, score, elig)


def generate_ai_plan(data, score, elig):
    """Claude API로 맞춤 플랜 생성"""
    email = st.session_state.get("user_email", "guest")
    
    prompt = f"""아래는 E-7-4 비자 전환을 준비 중인 외국인 근로자의 진단 결과입니다.

【기본 정보】
- 현재 비자: {data['current_visa']}, 나이: {data['age']}세
- 종사 분야: {data['sector']}, 누적 근무: {data['years']}년
- 현 사업장 근무: {data['current_employer_months']}개월
- 연봉: {data['salary']/10000:.0f}만원

【점수 현황】 (300점 만점, 합격선 200점)
- 평균소득: {score['income']}/120점 (최소 50 필수)
- 한국어능력: {score['korean']}/120점 (최소 50 필수)
- 나이: {score['age']}/60점
- 경력: {score['career']}/50점
- 학력: {score['education']}/35점
- 가점: {score['bonus']}점
- **총점: {score['grand_total']}점**

【자격 진단】
- 신청 자격: {'충족' if elig['eligible'] else '불충족'}
- 결격사유: {', '.join(elig['issues']) if elig['issues'] else '없음'}

다음 형식으로 맞춤 보강 플랜을 작성해주세요:

## 1. 종합 진단
- 현재 상태 한 줄 요약 (합격 가능성)

## 2. 우선순위 보강 항목 TOP 3
각 항목별로:
- 항목명과 예상 추가 점수
- 구체적 실행 방법 (학원/시험/서류 등)
- 소요 기간과 비용 추정

## 3. 6개월 실행 로드맵
- 1~2개월차 / 3~4개월차 / 5~6개월차로 나누어 단계별 액션 제시

## 4. 주의사항
- 이 신청자가 특히 주의해야 할 점 2~3가지

한국어로, 친근하고 실용적인 톤으로 작성하세요. 구체적인 숫자와 액션을 포함하세요."""

    with st.spinner("Claude AI가 맞춤 플랜을 생성하고 있습니다..."):
        result = claude_generate(prompt, max_tokens=2500)
    
    if result["ok"]:
        st.markdown(result["text"])
        # 사용량 로깅
        db = load_user_db()
        add_usage_log(db, email, DEFAULT_MODEL, result["input_tokens"], result["output_tokens"])
        
        prices = MODEL_PRICES[DEFAULT_MODEL]
        cost_usd = (result["input_tokens"] * prices["input"] + result["output_tokens"] * prices["output"]) / 1_000_000
        st.caption(f"💰 사용 토큰: 입력 {result['input_tokens']} / 출력 {result['output_tokens']} · 비용: ${cost_usd:.4f} (₩{cost_usd*USD_TO_KRW:.0f})")
    else:
        st.error(f"AI 생성 실패: {result['error']}")


# ============================================================
# 8. 기업체 추천서 초안 생성기
# ============================================================
def recommendation_letter_ui():
    st.title("📝 기업체 추천서 초안 생성기")
    st.markdown(f"<p style='color:{RSV_MUTED}'>E-7-4 비자 전환 신청용 기업 추천서 — Claude AI 기반 자동 작성</p>",
                unsafe_allow_html=True)
    
    st.markdown("""
    <div class="rsv-card">
    <b>이 도구의 용도</b><br>
    • 외국인 근로자 정보와 기업 정보를 입력하면 <b>추천서 초안</b>을 자동 생성합니다<br>
    • 생성된 초안은 검토·수정 후 실제 양식(법무부/지자체 별도양식)에 옮겨 사용합니다<br>
    • <b>주의</b>: 최종 서명·날인 및 제출은 반드시 사업주가 직접 진행해야 합니다
    </div>
    """, unsafe_allow_html=True)
    
    with st.form("recommend_form"):
        st.markdown("### 1️⃣ 기업 정보")
        c1, c2 = st.columns(2)
        with c1:
            company_name = st.text_input("회사명 *", placeholder="(주)RSV코리아")
            ceo_name = st.text_input("대표자명 *", placeholder="홍길동")
            business_no = st.text_input("사업자등록번호", placeholder="123-45-67890")
            industry = st.selectbox("산업 분야 *", INDUSTRY_SECTORS)
        with c2:
            company_address = st.text_input("회사 주소", placeholder="경기도 안산시 ...")
            total_employees = st.number_input("상시근로자 수 *", 1, 10000, 30)
            foreign_employees = st.number_input("외국인 근로자 수", 0, 1000, 5)
            company_years = st.number_input("기업 설립 후 경과 연수", 0, 100, 10)
        
        st.markdown("### 2️⃣ 외국인 근로자 정보")
        c1, c2 = st.columns(2)
        with c1:
            worker_name = st.text_input("이름 *", placeholder="NGUYEN VAN A")
            worker_nationality = st.text_input("국적 *", placeholder="베트남")
            worker_birth = st.text_input("생년월일", placeholder="1995-03-15")
            worker_visa = st.selectbox("현재 비자 *", ["E-9", "E-10", "H-2"])
        with c2:
            worker_position = st.text_input("직무·직책 *", placeholder="용접 숙련공")
            employment_start = st.text_input("현 사업장 입사일 *", placeholder="2021-05-01")
            total_years_korea = st.number_input("국내 총 근무기간 (년)", 0.0, 15.0, 5.0, step=0.5)
            annual_salary = st.number_input("현재 연봉 (원)", 0, 100000000, 32000000, step=1000000)
        
        st.markdown("### 3️⃣ 추천 사유 (핵심 정보)")
        st.caption("아래 항목을 자세히 적을수록 AI가 설득력 있는 추천서를 만듭니다")
        
        skills = st.text_area(
            "보유 기술·숙련도 *",
            placeholder="예: TIG·MIG 용접 4년 이상 숙련, 박판 용접 가능, 도면 해독 능력, 무사고 작업 이력 등",
            height=100,
        )
        contribution = st.text_area(
            "회사 기여도 *",
            placeholder="예: 신입 외국인 근로자 통역 및 OJT 담당, 생산성 OO% 향상에 기여, 안전관리 우수 등",
            height=100,
        )
        korean_ability = st.text_area(
            "한국어 능력 / 한국사회 적응도",
            placeholder="예: 일상 의사소통 원활, TOPIK 3급, 사회통합프로그램 3단계 이수, 동료들과 협업 우수",
            height=80,
        )
        future_plan = st.text_area(
            "향후 고용 계획 *",
            placeholder="예: E-7-4 전환 시 향후 5년 이상 지속 고용 예정, 반장급 승진 계획, 연봉 인상 계획 등",
            height=80,
        )
        special_reason = st.text_area(
            "특기사항 (선택)",
            placeholder="예: 회사의 핵심 기술 보유자, 대체 인력 확보 어려움, 표창 이력 등",
            height=60,
        )
        
        st.markdown("### 4️⃣ 생성 옵션")
        c1, c2 = st.columns(2)
        with c1:
            tone = st.selectbox("문체", ["격식체 (공문서)", "정중체 (일반 비즈니스)"])
        with c2:
            length = st.selectbox("분량", ["표준 (A4 1장)", "상세 (A4 1.5장)", "간결 (A4 0.5장)"])
        
        submitted = st.form_submit_button("🤖 추천서 초안 생성", use_container_width=True)
    
    if submitted:
        # 필수 항목 체크
        required = {
            "회사명": company_name, "대표자명": ceo_name, "이름": worker_name,
            "국적": worker_nationality, "직무": worker_position,
            "입사일": employment_start, "보유 기술": skills,
            "회사 기여도": contribution, "향후 고용 계획": future_plan,
        }
        missing = [k for k, v in required.items() if not v.strip()]
        if missing:
            st.error(f"필수 항목이 비어있습니다: {', '.join(missing)}")
            return
        
        # 프롬프트 구성
        length_guide = {
            "표준 (A4 1장)": "약 600~800자",
            "상세 (A4 1.5장)": "약 1000~1200자",
            "간결 (A4 0.5장)": "약 400~500자",
        }[length]
        
        prompt = f"""당신은 한국 비자 행정 문서 작성 전문가입니다.
아래 정보를 바탕으로 **E-7-4 (숙련기능인력) 비자 전환을 위한 기업체 추천서 초안**을 작성하세요.

【기업 정보】
- 회사명: {company_name}
- 대표자: {ceo_name}
- 사업자번호: {business_no or "(미입력)"}
- 주소: {company_address or "(미입력)"}
- 산업분야: {industry}
- 상시근로자: {total_employees}명 (외국인 {foreign_employees}명)
- 설립 경과: {company_years}년

【외국인 근로자】
- 성명: {worker_name}
- 국적: {worker_nationality}
- 생년월일: {worker_birth or "(미입력)"}
- 현재 비자: {worker_visa}
- 직무/직책: {worker_position}
- 현 사업장 입사일: {employment_start}
- 국내 총 근무기간: {total_years_korea}년
- 현재 연봉: {annual_salary:,}원

【보유 기술·숙련도】
{skills}

【회사 기여도】
{contribution}

【한국어/적응도】
{korean_ability or "(미입력)"}

【향후 고용 계획】
{future_plan}

【특기사항】
{special_reason or "(없음)"}

【작성 지침】
1. 한국어 {tone}로 작성
2. 분량: {length_guide}
3. 다음 구조를 따르되 자연스럽게 풀어쓰기:
   - 도입: 추천 대상자 명시 ("당사는 ... ㅇㅇㅇ을(를) E-7-4 비자로 추천합니다")
   - 근무 이력: 입사일·근무기간·직무 구체적으로
   - 숙련도와 기여: 위 정보를 바탕으로 구체적 사례 중심으로 서술
   - 한국사회 적응 및 인성
   - 향후 고용 계획과 회사의 약속 (2년 이상 고용계약, 연봉 등)
   - 마무리: 추천 의사 재확인
4. 과장 표현 금지, 사실 기반으로 작성
5. 한국 공문서 관례에 맞는 격식 유지
6. 맨 아래에 다음 형식의 서명란 포함:
   
   ```
   202X년 X월 X일
   
   회사명: {company_name}
   대표이사: {ceo_name}  (인)
   ```

추천서 본문만 출력하세요. 다른 설명은 붙이지 마세요."""

        with st.spinner("Claude AI가 추천서 초안을 작성하고 있습니다... (약 15초)"):
            # 추천서는 품질이 중요하므로 Sonnet 사용
            model = "claude-sonnet-4-6"
            result = claude_generate(prompt, model=model, max_tokens=2500)
        
        if result["ok"]:
            st.markdown("---")
            st.markdown("## 📄 생성된 추천서 초안")
            
            st.markdown(f'<div class="rsv-warning">⚠️ <b>반드시 검토 후 수정하여 사용하세요.</b> AI가 생성한 초안이므로 사실관계·금액·날짜를 직접 확인해야 합니다.</div>',
                        unsafe_allow_html=True)
            
            # 편집 가능한 텍스트 영역
            edited = st.text_area(
                "추천서 본문 (편집 가능)",
                value=result["text"],
                height=600,
            )
            
            c1, c2 = st.columns(2)
            with c1:
                st.download_button(
                    "📥 텍스트 파일로 다운로드 (.txt)",
                    data=edited.encode("utf-8"),
                    file_name=f"추천서_{worker_name}_{datetime.now().strftime('%Y%m%d')}.txt",
                    mime="text/plain",
                    use_container_width=True,
                )
            with c2:
                # HTML 형식 다운로드 (워드에 붙여넣기 좋게)
                html_doc = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>추천서</title>
<style>body{{font-family:'맑은 고딕',serif;line-height:1.8;max-width:800px;margin:40px auto;padding:20px;}}</style>
</head><body><pre style="white-space:pre-wrap;font-family:inherit;">{edited}</pre></body></html>"""
                st.download_button(
                    "📥 HTML 파일로 다운로드 (워드 붙여넣기용)",
                    data=html_doc.encode("utf-8"),
                    file_name=f"추천서_{worker_name}_{datetime.now().strftime('%Y%m%d')}.html",
                    mime="text/html",
                    use_container_width=True,
                )
            
            # 사용량 로깅
            email = st.session_state.get("user_email", "guest")
            db = load_user_db()
            add_usage_log(db, email, model, result["input_tokens"], result["output_tokens"])
            
            prices = MODEL_PRICES[model]
            cost_usd = (result["input_tokens"] * prices["input"] + result["output_tokens"] * prices["output"]) / 1_000_000
            st.caption(f"💰 사용 토큰: 입력 {result['input_tokens']} / 출력 {result['output_tokens']} · 비용: ${cost_usd:.4f} (₩{cost_usd*USD_TO_KRW:.0f})")
        else:
            st.error(f"AI 생성 실패: {result['error']}")


# ============================================================
# 9. 관리자 대시보드 (벤처/KOITA와 동일 4탭 구조)
# ============================================================
def admin_dashboard():
    st.title("👑 관리자 대시보드")
    db = load_user_db()
    
    tab1, tab2, tab3, tab4 = st.tabs(["📊 사용 통계", "👥 사용자 관리", "⏳ 승인 대기", "📋 상세 로그"])
    
    with tab1:
        logs = db.get("usage_logs", [])
        if not logs:
            st.info("아직 사용 로그가 없습니다.")
        else:
            df = pd.DataFrame(logs)
            # KeyError 방어
            for col in ["timestamp", "email", "model", "input_tokens", "output_tokens", "cost_usd"]:
                if col not in df.columns:
                    df[col] = 0 if col.endswith("tokens") or col.endswith("usd") else ""
            
            total_cost_usd = df["cost_usd"].sum()
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("총 호출 수", f"{len(df):,}")
            c2.metric("총 비용 (USD)", f"${total_cost_usd:.2f}")
            c3.metric("총 비용 (KRW)", f"₩{total_cost_usd * USD_TO_KRW:,.0f}")
            c4.metric("사용자 수", df["email"].nunique())
            
            st.markdown("#### 사용자별 비용")
            by_user = df.groupby("email")["cost_usd"].agg(["sum", "count"]).reset_index()
            by_user.columns = ["이메일", "총 비용 (USD)", "호출 수"]
            by_user["총 비용 (KRW)"] = (by_user["총 비용 (USD)"] * USD_TO_KRW).round(0)
            st.dataframe(by_user, use_container_width=True, hide_index=True)
    
    with tab2:
        users = db.get("users", {})
        if users:
            user_df = pd.DataFrame([
                {"이메일": e, "이름": u.get("name", ""), "회사": u.get("company", ""),
                 "승인": "✅" if u.get("approved") else "⏳", "가입일": u.get("created_at", "")[:10]}
                for e, u in users.items()
            ])
            st.dataframe(user_df, use_container_width=True, hide_index=True)
        else:
            st.info("등록된 사용자가 없습니다.")
    
    with tab3:
        pending = {e: u for e, u in db.get("users", {}).items() if not u.get("approved")}
        if not pending:
            st.success("✅ 승인 대기 중인 사용자가 없습니다.")
        else:
            for email, user in pending.items():
                with st.container():
                    c1, c2, c3 = st.columns([3, 2, 1])
                    c1.markdown(f"**{user.get('name')}** ({email})")
                    c2.markdown(f"📞 {user.get('phone', '-')} · 🏢 {user.get('company', '-')}")
                    if c3.button("승인", key=f"approve_{email}"):
                        db["users"][email]["approved"] = True
                        save_user_db(db)
                        st.rerun()
    
    with tab4:
        logs = db.get("usage_logs", [])
        if logs:
            df = pd.DataFrame(logs[-100:])  # 최근 100건
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.info("로그가 없습니다.")


# ============================================================
# 9. 메인 라우터
# ============================================================
def main():
    with st.sidebar:
        st.markdown(f"<h2 style='color:{RSV_GOLD}'>RSV E-7-4</h2>", unsafe_allow_html=True)
        st.markdown("*부자들의 비밀금고*")
        st.markdown("---")
        
        if "user_email" in st.session_state:
            st.markdown(f"👤 **{st.session_state.get('user_name', st.session_state['user_email'])}**")
            st.caption(st.session_state['user_email'])
            if st.button("로그아웃"):
                for k in ["user_email", "user_name", "diag_done", "diag_data"]:
                    st.session_state.pop(k, None)
                st.rerun()
            
            st.markdown("---")
            if is_admin():
                page = st.radio("메뉴", ["진단 도구", "추천서 생성기", "관리자 대시보드"])
            else:
                page = st.radio("메뉴", ["진단 도구", "추천서 생성기"])
        else:
            page = "로그인"
        
        st.markdown("---")
        st.caption("📞 임원근 지사장")
        st.caption("중소기업경영지원단")
    
    if "user_email" not in st.session_state:
        login_signup_ui()
    elif page == "관리자 대시보드" and is_admin():
        admin_dashboard()
    elif page == "추천서 생성기":
        recommendation_letter_ui()
    else:
        diagnostic_ui()


if __name__ == "__main__":
    main()
