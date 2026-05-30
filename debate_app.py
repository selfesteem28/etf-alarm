import streamlit as st
import anthropic
import google.generativeai as genai
import time

st.set_page_config(page_title="AI 다중 토론 허브", page_icon="🤖", layout="wide")

st.markdown("""
<style>
.claude-bubble {
    background: #e8f0fb; border-left: 4px solid #4a8adc;
    padding: 12px 16px; border-radius: 0 10px 10px 0;
    margin: 6px 0; font-size: 14px; line-height: 1.7;
}
.gemini-bubble {
    background: #e8f5e9; border-left: 4px solid #4a9a4a;
    padding: 12px 16px; border-radius: 0 10px 10px 0;
    margin: 6px 0; font-size: 14px; line-height: 1.7;
}
.owner-bubble {
    background: #fff0f5; border: 2px solid #d4537e;
    padding: 12px 16px; border-radius: 10px 0 10px 10px;
    margin: 6px 0; font-size: 14px; line-height: 1.7;
    text-align: right;
}
.sys-bubble {
    background: #f5f5f0; border: 1px dashed #ccc;
    padding: 8px 16px; border-radius: 8px;
    margin: 6px 0; font-size: 13px; color: #888;
    text-align: center;
}
.label-claude { color: #1a4a8a; font-size: 12px; font-weight: 600; margin-bottom: 2px; }
.label-gemini { color: #1b5e20; font-size: 12px; font-weight: 600; margin-bottom: 2px; }
.label-owner  { color: #8a1a4a; font-size: 12px; font-weight: 600; margin-bottom: 2px; text-align: right; }
.opinion-tag {
    display: inline-block; background: #f0c0d0; color: #4a0a20;
    padding: 3px 10px; border-radius: 99px; font-size: 12px; margin: 2px;
}
</style>
""", unsafe_allow_html=True)

ROUND_TOPICS = [
    "코스닥 단타 승률 높은 조건식 최적 조합",
    "VWAP 기준 최적 매수 진입 조건",
    "단타 최적 손절·익절 비율 (ATR 활용)",
    "거래량·변동성 기반 종목 필터 조건",
    "리스크 관리 및 일일 손실 한도 설정"
]

if 'history' not in st.session_state:
    st.session_state.history = []
if 'owner_opinions' not in st.session_state:
    st.session_state.owner_opinions = []
if 'round' not in st.session_state:
    st.session_state.round = 0
if 'chat_log' not in st.session_state:
    st.session_state.chat_log = []

def owner_ctx():
    if not st.session_state.owner_opinions:
        return ""
    lines = "\n".join([f"{i+1}. {o}" for i, o in enumerate(st.session_state.owner_opinions)])
    return f"\n\n[사용자 핵심 의견 — 반드시 최우선 반영]:\n{lines}"

def call_claude(prompt, claude_key):
    client = anthropic.Anthropic(api_key=claude_key)
    system = (
        "당신은 한국 코스닥/코스피 ETF 단타 자동매매 전략 전문가이자 AI 토론 중재자입니다. "
        "사용자 의견이 최우선입니다. 전문가로서 본인 의견도 명확하게 제시하고, "
        "Gemini와 적극적으로 논쟁하며 최적 조건식을 찾아주세요. 한국어로 답변해주세요."
        + owner_ctx()
    )
    msg = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=1000,
        system=system,
        messages=[{"role": "user", "content": prompt}]
    )
    return msg.content[0].text

def call_gemini(prompt, gemini_key):
    genai.configure(api_key=gemini_key)
    model = genai.GenerativeModel(
        model_name="gemini-1.5-flash",
        system_instruction=(
            "당신은 한국 코스닥/코스피 ETF 단타 전략 전문가입니다. "
            "사용자 의견을 최우선으로 반영하며, Claude와 적극적으로 토론하여 "
            "최적 조건식을 찾아주세요. 동의할 땐 동의하고, 반박할 땐 근거를 들어 반박하세요. "
            "한국어로 답변해주세요." + owner_ctx()
        )
    )
    res = model.generate_content(prompt)
    return res.text

def add_chat(role, content, label):
    st.session_state.chat_log.append({"role": role, "content": content, "label": label})
    st.session_state.history.append({"role": role, "content": content})

def render_chat():
    for msg in st.session_state.chat_log:
        role = msg["role"]
        content = msg["content"].replace("\n", "<br>")
        label = msg["label"]
        if role == "claude":
            st.markdown(f'<div class="label-claude">{label}</div><div class="claude-bubble">{content}</div>', unsafe_allow_html=True)
        elif role == "gemini":
            st.markdown(f'<div class="label-gemini">{label}</div><div class="gemini-bubble">{content}</div>', unsafe_allow_html=True)
        elif role == "owner":
            st.markdown(f'<div class="label-owner">{label}</div><div class="owner-bubble">{content}</div>', unsafe_allow_html=True)
        elif role == "sys":
            st.markdown(f'<div class="sys-bubble">{content}</div>', unsafe_allow_html=True)

def save_md():
    topic = st.session_state.get("current_topic", "")
    opinions = "\n".join([f"{i+1}. {o}" for i, o in enumerate(st.session_state.owner_opinions)])
    body = "\n\n---\n\n".join([f"**[{h['role'].upper()}]**\n{h['content']}" for h in st.session_state.history])
    return f"# AI 토론 결과 — Round {st.session_state.round}\n\n**주제**: {topic}\n\n## 내 핵심 의견\n{opinions}\n\n## 토론 내용\n\n{body}"

st.title("🤖 AI 다중 토론 허브")
st.caption("Claude + Gemini — 트레이딩 조건식 최적화")

with st.sidebar:
    st.header("⚙️ 설정")
    st.subheader("API 키")
    claude_key = st.text_input("Claude API Key", type="password", placeholder="sk-ant-...")
    gemini_key = st.text_input("Gemini API Key", type="password", placeholder="AIzaSy...")
    st.divider()
    st.subheader("📋 라운드 주제")
    for i, t in enumerate(ROUND_TOPICS):
        st.caption(f"{i+1}. {t}")
    st.divider()
    if st.session_state.owner_opinions:
        st.subheader("⭐ 내 누적 의견")
        for i, op in enumerate(st.session_state.owner_opinions):
            col1, col2 = st.columns([4, 1])
            col1.caption(f"• {op}")
            if col2.button("×", key=f"del_{i}"):
                st.session_state.owner_opinions.pop(i)
                st.rerun()

col1, col2 = st.columns([3, 1])
with col1:
    topic = st.text_input("토론 주제", value=ROUND_TOPICS[0] if st.session_state.round == 0 else st.session_state.get("current_topic", ROUND_TOPICS[0]))
with col2:
    st.write("")
    st.write("")
    start_btn = st.button("🚀 토론 시작", use_container_width=True, type="primary")

col_a, col_b, col_c = st.columns(3)
synth_btn = col_a.button("📊 최종 취합", use_container_width=True)
next_btn = col_b.button("⏭ 다음 라운드", use_container_width=True)
clear_btn = col_c.button("🗑 초기화", use_container_width=True)

st.divider()

chat_container = st.container()
with chat_container:
    render_chat()

st.divider()

mode = st.radio("입력 모드", ["⭐ 내 의견 (최우선)", "Claude에게", "Gemini에게"], horizontal=True)
user_input = st.text_area("메시지 입력", placeholder="입력 후 전송 버튼 클릭...", height=80, label_visibility="collapsed")
send_btn = st.button("전송", type="primary")

md_data = save_md()
st.download_button("💾 결과 저장 (md)", data=md_data, file_name=f"debate_round{st.session_state.round}.md", mime="text/markdown")

if start_btn:
    if not claude_key or not gemini_key:
        st.error("Claude API 키와 Gemini API 키를 모두 입력해주세요!")
    else:
        st.session_state.round += 1
        st.session_state.current_topic = topic
        st.session_state.history = []
        add_chat("sys", f"━━━ Round {st.session_state.round} 시작 — {topic} ━━━", "")
        with st.spinner("Claude 분석 중..."):
            try:
                cr = call_claude(f'토론 주제: "{topic}"\n\n전문가 관점에서 의견 제시:\n1. 핵심 조건식 후보 2-3개 (구체적 수치 포함)\n2. 가장 추천하는 조합과 이유\n3. Gemini에게 토론하고 싶은 포인트')
                add_chat("claude", cr, "Claude (전문가 의견)")
            except Exception as e:
                st.error(f"Claude 오류: {e}")
                st.stop()
        with st.spinner("Gemini 분석 중..."):
            try:
                gr = call_gemini(f'토론 주제: "{topic}"\n\nClaude 의견: "{cr}"\n\n동의/반박하며 당신 의견 제시:\n1. Claude 의견 중 동의 부분\n2. 반박 또는 보완할 부분\n3. 당신이 추천하는 조건식')
                add_chat("gemini", gr, "Gemini (전문가 의견)")
            except Exception as e:
                st.error(f"Gemini 오류: {e}")
                st.stop()
        with st.spinner("Claude 반박 중..."):
            try:
                cr2 = call_claude(f'Gemini 의견: "{gr}"\n\n이에 대해 동의/반박하고, 현재까지 합의 가능한 최적 조건식 방향을 정리해주세요.')
                add_chat("claude", cr2, "Claude (반박·합의)")
            except Exception as e:
                st.error(f"Claude 오류: {e}")
        st.rerun()

if send_btn and user_input.strip():
    if not claude_key or not gemini_key:
        st.error("API 키를 먼저 입력해주세요!")
    else:
        text = user_input.strip()
        if "내 의견" in mode:
            st.session_state.owner_opinions.append(text)
            add_chat("owner", "⭐ " + text, "내 의견 (최우선)")
            add_chat("sys", "⏸ 토론 일시 정지 — 내 의견 반영 중", "")
            with st.spinner("Claude가 내 의견 반영 중..."):
                try:
                    hist_str = "\n\n".join([f"{h['role']}: {h['content']}" for h in st.session_state.history])
                    cr = call_claude(f'사용자 핵심 의견: "{text}"\n\n지금까지 토론:\n{hist_str}\n\n이 의견 최우선 반영:\n1. 토론 방향 재조정\n2. 수정된 조건식 방향\n3. 계속 논의할 포인트')
                    add_chat("claude", cr, "Claude (의견 반영)")
                except Exception as e:
                    st.error(f"오류: {e}")
            with st.spinner("Gemini 재조정 중..."):
                try:
                    gr = call_gemini(f'사용자 의견: "{text}"\nClaude 재조정: "{cr}"\n\n이 방향에 동의하나요? 추가 의견?')
                    add_chat("gemini", gr, "Gemini (재조정)")
                except Exception as e:
                    st.error(f"오류: {e}")
        elif "Claude" in mode:
            add_chat("sys", f"사용자 → Claude: {text}", "")
            with st.spinner("Claude 답변 중..."):
                try:
                    r = call_claude(text)
                    add_chat("claude", r, "Claude")
                except Exception as e:
                    st.error(f"오류: {e}")
        elif "Gemini" in mode:
            add_chat("sys", f"사용자 → Gemini: {text}", "")
            with st.spinner("Gemini 답변 중..."):
                try:
                    r = call_gemini(text)
                    add_chat("gemini", r, "Gemini")
                except Exception as e:
                    st.error(f"오류: {e}")
        st.rerun()

if synth_btn:
    if not claude_key:
        st.error("Claude API 키를 입력해주세요!")
    else:
        with st.spinner("최종 취합 중..."):
            try:
                hist_str = "\n\n".join([f"[{h['role'].upper()}]: {h['content']}" for h in st.session_state.history])
                r = call_claude(f'토론 전체:\n{hist_str}\n\n"{topic}" 최종 결론:\n1. 최적 조건식 (사용자 의견 최우선, 구체적 수치)\n2. 매수/매도/손절 조건\n3. 백테스트 계획\n4. 주의사항')
                add_chat("claude", r, "Claude (최종 결론)")
            except Exception as e:
                st.error(f"오류: {e}")
        st.rerun()

if next_btn:
    next_idx = st.session_state.round
    if next_idx < len(ROUND_TOPICS):
        st.session_state.current_topic = ROUND_TOPICS[next_idx]
        add_chat("sys", f"다음 라운드 주제: {ROUND_TOPICS[next_idx]}", "")
        st.rerun()
    else:
        st.info("모든 라운드 완료! 최종 취합을 눌러주세요.")

if clear_btn:
    st.session_state.history = []
    st.session_state.owner_opinions = []
    st.session_state.round = 0
    st.session_state.chat_log = []
    st.rerun()
