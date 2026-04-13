import streamlit as st
import pandas as pd
import re
import plotly.express as px
from googleapiclient.discovery import build
from utils import (
    get_video_info,
    get_comments_with_replies,
    batch_sentiment_textblob,
    batch_sentiment_openai,
    summarize_openai,
    summarize_free,
    OPENAI_AVAILABLE,
)

st.set_page_config(
    page_title="YT Comment Analyzer",
    page_icon="📺",
    layout="wide",
)

st.markdown(
    """
<style>
.mt{text-align:center;color:#FF0000;font-size:2.5rem;
font-weight:bold;margin-bottom:.5rem}
.st{text-align:center;color:#666;font-size:1.1rem;
margin-bottom:2rem}
.cb{background:#f9f9f9;border-left:4px solid #FF0000;
padding:12px 16px;margin-bottom:10px;border-radius:0 8px 8px 0}
.rb{background:#f0f4ff;border-left:4px solid #4285f4;
padding:10px 14px;margin-bottom:8px;margin-left:30px;
border-radius:0 8px 8px 0}
.ca{font-weight:bold;color:#333;font-size:.95rem}
.ra{font-weight:bold;color:#4285f4;font-size:.9rem}
.ct{color:#555;font-size:.9rem;margin-top:4px}
.cm{color:#999;font-size:.8rem;margin-top:4px}
.sb{background:linear-gradient(135deg,#667eea,#764ba2);
color:#fff;padding:20px;border-radius:12px;margin:10px 0;
line-height:1.6}
</style>
""",
    unsafe_allow_html=True,
)

st.markdown(
    '<div class="mt">📺 유튜브 댓글 분석기</div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<div class="st">댓글+답글 수집 · 감성분석 · 요약</div>',
    unsafe_allow_html=True,
)

SENT_KR = {
    "positive": "긍정",
    "negative": "부정",
    "neutral": "중립",
    "error": "오류",
}
SENT_EMOJI = {
    "positive": "😊",
    "negative": "😠",
    "neutral": "😐",
    "error": "❓",
}
SENT_COLOR = {
    "긍정": "#28a745",
    "부정": "#dc3545",
    "중립": "#ffc107",
    "오류": "#6c757d",
}


def extract_video_id(url):
    for p in [
        r"watch\?v=([a-zA-Z0-9_-]{11})",
        r"youtu\.be\/([a-zA-Z0-9_-]{11})",
        r"shorts\/([a-zA-Z0-9_-]{11})",
        r"embed\/([a-zA-Z0-9_-]{11})",
        r"live\/([a-zA-Z0-9_-]{11})",
    ]:
        m = re.search(p, url)
        if m:
            return m.group(1)
    return None


yt_key = st.secrets.get("YOUTUBE_API_KEY", None)
oa_key = st.secrets.get("OPENAI_API_KEY", None)

if not yt_key:
    st.warning("YouTube API 키를 Secrets에 설정하세요.")
    st.stop()

st.markdown("---")
c1, c2, c3 = st.columns([3, 1, 1])
with c1:
    url = st.text_input(
        "🔗 유튜브 링크",
        placeholder="https://www.youtube.com/watch?v=...",
    )
with c2:
    max_n = st.selectbox(
        "최대 댓글", [50, 100, 200, 500, 1000], index=1
    )
with c3:
    inc_reply = st.selectbox("답글", ["포함", "제외"])

clicked = st.button(
    "🔍 댓글 수집", use_container_width=True, type="primary"
)

if clicked and url:
    vid = extract_video_id(url)
    if not vid:
        st.error("올바른 링크가 아닙니다.")
    else:
        yt = build("youtube", "v3", developerKey=yt_key)
        with st.spinner("영상 정보 로딩..."):
            info = get_video_info(yt, vid)
        if info:
            st.markdown("---")
            st.markdown("### 📋 영상 정보")
            t1, t2 = st.columns([1, 2])
            with t1:
                if info["thumbnail"]:
                    st.image(
                        info["thumbnail"],
                        use_container_width=True,
                    )
            with t2:
                st.markdown(f"**{info['title']}**")
                st.markdown(
                    f"{info['channel']} · {info['published']}"
                )
                a, b, c = st.columns(3)
                a.metric("조회수", f"{info['views']:,}")
                b.metric("좋아요", f"{info['likes']:,}")
                c.metric("댓글", f"{info['comment_count']:,}")

        do_rep = inc_reply == "포함"
        with st.spinner("댓글 수집 중..."):
            data = get_comments_with_replies(
                yt, vid, max_n, do_rep
            )

        if data:
            df = pd.DataFrame(data)
            tc = len(df[df["ctype"] == "comment"])
            rc = len(df[df["ctype"] == "reply"])
            st.success(
                f"총 {len(df)}개 수집 "
                f"(원댓글 {tc} + 답글 {rc})"
            )
            st.session_state["df"] = df
            st.session_state["info"] = info
            st.session_state["vid"] = vid
        else:
            st.info("댓글이 없습니다.")
elif clicked and not url:
    st.warning("링크를 입력하세요.")

if "df" in st.session_state:
    df = st.session_state["df"]
    info = st.session_state.get("info", {})
    vid = st.session_state.get("vid", "")

    st.markdown("---")
    f1, f2, f3 = st.columns([2, 1, 1])
    with f1:
        kw = st.text_input("🔎 검색", placeholder="키워드")
    with f2:
        srt = st.selectbox(
            "정렬",
            ["좋아요 많은순", "좋아요 적은순", "최신순", "오래된순"],
        )
    with f3:
        tp = st.selectbox("유형", ["전체", "원댓글", "답글"])

    fdf = df.copy()
    if kw:
        fdf = fdf[
            fdf["text"].str.contains(kw, case=False, na=False)
        ]
    if tp == "원댓글":
        fdf = fdf[fdf["ctype"] == "comment"]
    elif tp == "답글":
        fdf = fdf[fdf["ctype"] == "reply"]

    sort_map = {
        "좋아요 많은순": ("likes", False),
        "좋아요 적은순": ("likes", True),
        "최신순": ("date", False),
        "오래된순": ("date", True),
    }
    scol, sasc = sort_map[srt]
    fdf = fdf.sort_values(scol, ascending=sasc).reset_index(
        drop=True
    )

    if kw:
        st.info(f"'{kw}' 결과: {len(fdf)}개")

    tab1, tab2, tab3, tab4 = st.tabs(
        ["📝 카드", "📊 테이블", "🧠 감성분석", "📝 요약"]
    )

    # ── 카드 보기 ──
    with tab1:
        for i, row in fdf.head(100).iterrows():
            lk = (
                f" 👍{row['likes']}"
                if row["likes"] > 0
                else ""
            )
            sb = ""
            if "sentiment" in fdf.columns:
                em = SENT_EMOJI.get(row.get("sentiment", ""), "")
                kr = SENT_KR.get(row.get("sentiment", ""), "")
                if em:
                    sb = f" {em}{kr}"

            if row["ctype"] == "reply":
                html = (
                    f'<div class="rb">'
                    f'<div class="ra">↳ {row["writer"]}{lk}{sb}</div>'
                    f'<div class="ct">{row["text"]}</div>'
                    f'<div class="cm">📅 {row["date"]}</div>'
                    f"</div>"
                )
            else:
                rn = ""
                if row.get("reply_count", 0) > 0:
                    rn = f" · 답글 {row['reply_count']}개"
                html = (
                    f'<div class="cb">'
                    f'<div class="ca">{row["writer"]}{lk}{sb}{rn}</div>'
                    f'<div class="ct">{row["text"]}</div>'
                    f'<div class="cm">📅 {row["date"]}</div>'
                    f"</div>"
                )
            st.markdown(html, unsafe_allow_html=True)

    # ── 테이블 ──
    with tab2:
        display_df = fdf.copy()
        rename = {
            "writer": "작성자",
            "text": "댓글내용",
            "likes": "좋아요",
            "date": "작성일",
            "ctype": "유형",
            "reply_count": "답글수",
        }
        display_df = display_df.rename(columns=rename)
        cols = ["유형", "작성자", "댓글내용", "좋아요", "작성일", "답글수"]
        if "sentiment" in fdf.columns:
            display_df["감성"] = display_df.get(
                "sentiment", ""
            ).map(lambda x: SENT_KR.get(x, x))
            display_df["감성점수"] = fdf.get("sent_score", 0)
            cols += ["감성", "감성점수"]
        show = [c for c in cols if c in display_df.columns]
        st.dataframe(
            display_df[show],
            use_container_width=True,
            height=500,
        )

    # ── 감성 분석 ──
    with tab3:
        st.markdown("### 🧠 감성 분석")
        if oa_key and OPENAI_AVAILABLE:
            mode = st.radio(
                "방식",
                ["🤖 GPT (정확)", "⚡ TextBlob (무료)"],
                horizontal=True,
            )
        else:
            mode = "⚡ TextBlob (무료)"
            st.info("OpenAI 키 설정 시 GPT 분석 가능")

        if st.button(
            "🧠 분석 실행", use_container_width=True
        ):
            texts = df["text"].tolist()
            if "GPT" in mode and oa_key:
                with st.spinner("GPT 분석 중..."):
                    res = batch_sentiment_openai(texts, oa_key)
            else:
                with st.spinner("분석 중..."):
                    res = batch_sentiment_textblob(texts)

            df["sentiment"] = [r["label"] for r in res]
            df["sent_score"] = [r["score"] for r in res]
            st.session_state["df"] = df
            st.success("분석 완료!")
            st.rerun()

        if "sentiment" in df.columns:
            total = len(df)
            pos = len(df[df["sentiment"] == "positive"])
            neg = len(df[df["sentiment"] == "negative"])
            neu = len(df[df["sentiment"] == "neutral"])
            avg = df["sent_score"].mean()

            k1, k2, k3, k4 = st.columns(4)
            k1.metric(
                "😊 긍정",
                f"{pos}개 ({pos/total*100:.1f}%)",
            )
            k2.metric(
                "😠 부정",
                f"{neg}개 ({neg/total*100:.1f}%)",
            )
            k3.metric(
                "😐 중립",
                f"{neu}개 ({neu/total*100:.1f}%)",
            )
            k4.metric("평균", f"{avg:.3f}")

            chart_df = df.copy()
            chart_df["감성"] = chart_df["sentiment"].map(SENT_KR)

            p1, p2 = st.columns(2)
            with p1:
                vc = chart_df["감성"].value_counts()
                fig = px.pie(
                    values=vc.values,
                    names=vc.index,
                    title="감성 분포",
                    color=vc.index,
                    color_discrete_map=SENT_COLOR,
                    hole=0.4,
                )
                fig.update_traces(
                    textposition="inside",
                    textinfo="percent+label",
                )
                st.plotly_chart(fig, use_container_width=True)
            with p2:
                fig2 = px.histogram(
                    chart_df,
                    x="sent_score",
                    nbins=30,
                    color="감성",
                    color_discrete_map=SENT_COLOR,
                    title="점수 분포",
                )
                st.plotly_chart(
                    fig2, use_container_width=True
                )

            if len(df[df["ctype"] == "reply"]) > 0:
                chart_df["유형"] = chart_df["ctype"].map(
                    {"comment": "💬 댓글", "reply": "↳ 답글"}
                )
                fig3 = px.histogram(
                    chart_df,
                    x="감성",
                    color="유형",
                    barmode="group",
                    title="댓글 vs 답글 감성",
                    color_discrete_map={
                        "💬 댓글": "#FF6B6B",
                        "↳ 답글": "#4ECDC4",
                    },
                )
                st.plotly_chart(
                    fig3, use_container_width=True
                )

    # ── 요약 ──
    with tab4:
        st.markdown("### 📝 요약")
        if oa_key and OPENAI_AVAILABLE:
            sm = st.radio(
                "요약 방식",
                ["🤖 AI 요약", "📊 통계 요약"],
                horizontal=True,
            )
        else:
            sm = "📊 통계 요약"

        if st.button("📝 요약 생성", use_container_width=True):
            if "AI" in sm and oa_key:
                with st.spinner("AI 요약 중..."):
                    result = summarize_openai(
                        df["text"].tolist(),
                        info.get("title", ""),
                        oa_key,
                    )
            else:
                result = summarize_free(df)
            st.session_state["summary"] = result

        if "summary" in st.session_state:
            st.markdown(
                f'<div class="sb">'
                f'{st.session_state["summary"]}'
                f"</div>",
                unsafe_allow_html=True,
            )

    st.markdown("---")
    csv = fdf.to_csv(index=False, encoding="utf-8-sig")
    st.download_button(
        "📥 CSV 다운로드",
        csv,
        f"comments_{vid}.csv",
        "text/csv",
        use_container_width=True,
    )

with st.sidebar:
    st.markdown("## 📖 사용법")
    st.markdown(
        "1. 링크 입력\n"
        "2. 수집 클릭\n"
        "3. 감성분석 탭\n"
        "4. 요약 탭\n"
        "5. CSV 다운로드"
    )
    st.markdown("---")
    st.caption("당곡고등학교 학습용")
