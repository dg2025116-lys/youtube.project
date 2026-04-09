import streamlit as st
import pandas as pd
import re
import plotly.express as px
from googleapiclient.discovery import build
from utils import (
    get_video_info, get_comments_with_replies,
    batch_sentiment_textblob, batch_sentiment_openai,
    summarize_openai, summarize_free, show_sentiment_charts,
    OPENAI_AVAILABLE
)

st.set_page_config(page_title="유튜브 댓글 분석기", page_icon="📺", layout="wide")

# ── CSS ──
st.markdown("""
<style>
.main-title{text-align:center;color:#FF0000;font-size:2.5rem;font-weight:bold;margin-bottom:.5rem}
.sub-title{text-align:center;color:#666;font-size:1.1rem;margin-bottom:2rem}
.comment-box{background:#f9f9f9;border-left:4px solid #FF0000;padding:12px 16px;margin-bottom:10px;border-radius:0 8px 8px 0}
.reply-box{background:#f0f4ff;border-left:4px solid #4285f4;padding:10px 14px;margin-bottom:8px;margin-left:30px;border-radius:0 8px 8px 0}
.comment-author{font-weight:bold;color:#333;font-size:.95rem}
.reply-author{font-weight:bold;color:#4285f4;font-size:.9rem}
.comment-text{color:#555;font-size:.9rem;margin-top:4px}
.comment-meta{color:#999;font-size:.8rem;margin-top:4px}
.summary-box{background:linear-gradient(135deg,#667eea,#764ba2);color:#fff;padding:20px;border-radius:12px;margin:10px 0;line-height:1.6}
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="main-title">📺 유튜브 댓글 분석기</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-title">댓글+답글 수집 · AI 감성분석 · 댓글 요약</div>', unsafe_allow_html=True)


def extract_video_id(url):
    for p in [r'watch\?v=([a-zA-Z0-9_-]{11})', r'youtu\.be\/([a-zA-Z0-9_-]{11})',
              r'shorts\/([a-zA-Z0-9_-]{11})', r'embed\/([a-zA-Z0-9_-]{11})',
              r'live\/([a-zA-Z0-9_-]{11})']:
        m = re.search(p, url)
        if m:
            return m.group(1)
    return None


# ── API 키 ──
yt_key = st.secrets.get("YOUTUBE_API_KEY", None)
oa_key = st.secrets.get("OPENAI_API_KEY", None)

if not yt_key:
    st.warning("⚠️ YouTube API 키가 없습니다. Secrets에 YOUTUBE_API_KEY를 설정하세요.")
    st.stop()

# ── 입력 ──
st.markdown("---")
c1, c2, c3 = st.columns([3, 1, 1])
with c1:
    url = st.text_input("🔗 유튜브 링크", placeholder="https://www.youtube.com/watch?v=...")
with c2:
    max_n = st.selectbox("최대 댓글 수", [50, 100, 200, 500, 1000], index=1)
with c3:
    inc_reply = st.selectbox("답글", ["포함", "제외"])

if st.button("🔍 댓글 수집", use_container_width=True, type="primary") and url:
    vid = extract_video_id(url)
    if not vid:
        st.error("❌ 올바른 링크가 아닙니다.")
    else:
        yt = build("youtube", "v3", developerKey=yt_key)

        with st.spinner("📡 영상 정보 로딩..."):
            info = get_video_info(yt, vid)
        if info:
            st.markdown("---")
            st.markdown("### 📋 영상 정보")
            t1, t2 = st.columns([1, 2])
            with t1:
                if info["thumbnail"]:
                    st.image(info["thumbnail"], use_container_width=True)
            with t2:
                st.markdown(f"**{info['title']}**")
                st.markdown(f"{info['channel']} · {info['published']}")
                a, b, c = st.columns(3)
                a.metric("조회수", f"{info['views']:,}")
                b.metric("좋아요", f"{info['likes']:,}")
                c.metric("댓글", f"{info['comment_count']:,}")

        with st.spinner("💬 댓글 수집 중..."):
            data = get_comments_with_replies(yt, vid, max_n, inc_reply == "포함")

        if data:
            df = pd.DataFrame(data)
            for col in ["유형", "답글 수", "댓글ID"]:
                if col not in df.columns:
                    df[col] = "💬 댓글" if col == "유형" else (0 if col == "답글 수" else "")

            tc = len(df[df["유형"] == "💬 댓글"])
            rc = len(df[df["유형"] == "↳ 답글"])
            st.success(f"✅ 총 {len(df)}개 수집 (원댓글 {tc} + 답글 {rc})")
            st.session_state["df"] = df
            st.session_state["info"] = info
            st.session_state["vid"] = vid
        else:
            st.info("😅 댓글이 없습니다.")

# ══════════════════════════════════════════════
# 수집 후 기능
# ══════════════════════════════════════════════
if "df" in st.session_state:
    df = st.session_state["df"]
    info = st.session_state.get("info", {})
    vid = st.session_state.get("vid", "")

    st.markdown("---")
    f1, f2, f3 = st.columns([2, 1, 1])
    with f1:
        kw = st.text_input("🔎 키워드 검색", placeholder="검색어")
    with f2:
        srt = st.selectbox("정렬", ["좋아요↓", "좋아요↑", "최신", "오래된"])
    with f3:
        tp = st.selectbox("유형", ["전체", "원댓글", "답글"])

    fdf = df.copy()
    if kw:
        fdf = fdf[fdf["댓글 내용"].str.contains(kw, case=False, na=False)]
    if tp == "원댓글":
        fdf = fdf[fdf["유형"] == "💬 댓글"]
    elif tp == "답글":
        fdf = fdf[fdf["유형"] == "↳ 답글"]

    sort_map = {"좋아요↓": ("좋아요 수", False), "좋아요↑": ("좋아요 수", True),
                "최신": ("작성일", False), "오래된": ("작성일", True)}
    col, asc = sort_map[srt]
    fdf = fdf.sort_values(col, ascending=asc).reset_index(drop=True)

    if kw:
        st.info(f"'{kw}' 결과: {len(fdf)}개")

    # ── 탭 ──
    tab1, tab2, tab3, tab4 = st.tabs(["📝 카드", "📊 테이블", "🧠 감성분석", "📝 요약"])

    with tab1:
        for i, row in fdf.head(100).iterrows():
            lk = f"👍{row['좋아요 수']}" if row['좋아요 수'] > 0 else ""
            sb = ""
            if "감성" in fdf.columns:
                em = {"긍정": "😊", "부정": "😠", "중립": "😐"}.get(row.get("감성", ""), "")
                sb = f" {em}{row.get('감성', '')}" if em else ""

            if row["유형"] == "↳ 답글":
                st.markdown(f"""<div class="reply-box">
                <div class="reply-author">↳ {row['작성자']} {lk}{sb}</div>
                <div class="comment-text">{row['댓글 내용']}</div>
                <div class="comment-meta">📅 {row['작성일']}</div>
                </div>""", unsafe_allow_html=True)
            else:
                rn = f" · 답글{row['답글 수']}개" if row.get('답글 수', 0) > 0 else ""
                st.markdown(f"""<div class="comment-box">
                <div class="comment-author">{row['작성자']} {lk}{sb}{rn}</div>
                <div class="comment-text">{row['댓글 내용']}</div>
                <div class="comment-meta">📅 {row['작성일']}</div>
                </div>""", unsafe_allow_html=True)

    with tab2:
        show_cols = ["유형", "작성자", "댓글 내용", "좋아요 수", "작성일", "답글 수"]
        if "감성" in fdf.columns:
            show_cols += ["감성", "감성점수"]
        st.dataframe(fdf[show_cols], use_container_width=True, height=500)

    with tab3:
        st.markdown("### 🧠 감성 분석")
        if oa_key and OPENAI_AVAILABLE:
            mode = st.radio("방식", ["🤖 GPT (한국어 정확)", "⚡ TextBlob (무료)"], horizontal=True)
        else:
            mode = "⚡ TextBlob (무료)"
            st.info("💡 OpenAI 키 설정 시 GPT 분석 가능")

        if st.button("🧠 감성 분석 실행", use_container_width=True):
            texts = df["댓글 내용"].tolist()
            if "GPT" in mode and oa_key:
                with st.spinner("🤖 GPT 분석 중..."):
                    res = batch_sentiment_openai(texts, oa_key)
            else:
                with st.spinner("⚡ 분석 중..."):
                    res = batch_sentiment_textblob(texts)

            sdf = pd.DataFrame(res)
            df["감성"] = sdf["감성"]
            df["감성점수"] = sdf["감성점수"]
            st.session_state["df"] = df
            st.success("✅ 완료!")
            st.rerun()

        if "감성" in df.columns:
            total = len(df)
            pos = len(df[df["감성"] == "긍정"])
            neg = len(df[df["감성"] == "부정"])
            neu = len(df[df["감성"] == "중립"])
            avg = df["감성점수"].mean()

            k1, k2, k3, k4 = st.columns(4)
            k1.metric("😊 긍정", f"{pos}개 ({pos/total*100:.1f}%)")
            k2.metric("😠 부정", f"{neg}개 ({neg/total*100:.1f}%)")
            k3.metric("😐 중립", f"{neu}개 ({neu/total*100:.1f}%)")
            k4.metric("평균점수", f"{avg:.3f}")

            colors = {"긍정": "#28a745", "부정": "#dc3545", "중립": "#ffc107", "분석실패": "#6c757d"}
            p1, p2 = st.columns(2)
            with p1:
                vc = df["감성"].value_counts()
                fig = px.pie(values=vc.values, names=vc.index, title="감성 분포",
                             color=vc.index, color_discrete_map=colors, hole=0.4)
                fig.update_traces(textposition='inside', textinfo='percent+label')
                st.plotly_chart(fig, use_container_width=True)
            with p2:
                fig2 = px.histogram(df, x="감성점수", nbins=30, color="감성",
                                    color_discrete_map=colors, title="점수 분포")
                st.plotly_chart(fig2, use_container_width=True)

            if len(df[df["유형"] == "↳ 답글"]) > 0:
                fig3 = px.histogram(df, x="감성", color="유형", barmode="group",
                                    title="댓글 vs 답글 감성 비교",
                                    color_discrete_map={"💬 댓글": "#FF6B6B", "↳ 답글": "#4ECDC4"})
                st.plotly_chart(fig3, use_container_width=True)

    with tab4:
        st.markdown("### 📝 댓글 요약")
        if oa_key and OPENAI_AVAILABLE:
            sm = st.radio("요약 방식", ["🤖 AI 요약", "📊 통계 요약"], horizontal=True)
        else:
            sm = "📊 통계 요약"

        if st.button("📝 요약 생성", use_container_width=True):
            if "AI" in sm and oa_key:
                with st.spinner("🤖 AI 요약 중..."):
                    result = summarize_openai(df["댓글 내용"].tolist(), info.get("title", ""), oa_key)
            else:
                result = summarize_free(df)

            st.markdown(f'<div class="summary-box">{result}</div>', unsafe_allow_html=True)
            st.session_state["summary"] = result

        if "summary" in st.session_state:
            st.markdown(f'<div class="summary-box">{st.session_state["summary"]}</div>',
                        unsafe_allow_html=True)

    # ── CSV 다운로드 ──
    st.markdown("---")
    csv = fdf.to_csv(index=False, encoding="utf-8-sig")
    st.download_button("📥 CSV 다운로드", csv, f"comments_{vid}.csv", "text/csv",
                       use_container_width=True)

# ── 사이드바 ──
with st.sidebar:
    st.markdown("## 📖 사용 안내")
    st.markdown("1. 유튜브 링크 입력\n2. 댓글 수집\n3. 감성분석 탭에서 분석\n4. 요약 탭에서 요약\n5. CSV 다운로드")
    st.markdown("---")
    st.markdown("## ⚠️ 주의")
    st.markdown("- YouTube API 일일 10,000 units\n- 답글 포함 시 할당량 더 소모\n- OpenAI 키는 선택사항")
    st.markdown("---")
    st.caption("당곡고등학교 학습용 프로젝트")
