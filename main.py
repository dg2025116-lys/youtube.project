import streamlit as st
import pandas as pd
import re
import time
import plotly.express as px
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from textblob import TextBlob

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

st.set_page_config(page_title="YT Analyzer", page_icon="📺", layout="wide")

st.markdown("""
<style>
.mt{text-align:center;color:#FF0000;font-size:2.5rem;font-weight:bold;margin-bottom:.5rem}
.su{text-align:center;color:#666;font-size:1.1rem;margin-bottom:2rem}
.cb{background:#f9f9f9;border-left:4px solid #FF0000;padding:12px 16px;margin-bottom:10px;border-radius:0 8px 8px 0}
.rb{background:#f0f4ff;border-left:4px solid #4285f4;padding:10px 14px;margin-bottom:8px;margin-left:30px;border-radius:0 8px 8px 0}
.ca{font-weight:bold;color:#333;font-size:.95rem}
.ra{font-weight:bold;color:#4285f4;font-size:.9rem}
.ct{color:#555;font-size:.9rem;margin-top:4px}
.cm{color:#999;font-size:.8rem;margin-top:4px}
.sb{background:linear-gradient(135deg,#667eea,#764ba2);color:#fff;padding:20px;border-radius:12px;margin:10px 0;line-height:1.6;white-space:pre-wrap}
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="mt">📺 유튜브 댓글 분석기</div>', unsafe_allow_html=True)
st.markdown('<div class="su">댓글+답글 수집 · 감성분석 · 요약</div>', unsafe_allow_html=True)

SK = {"positive": "긍정", "negative": "부정", "neutral": "중립", "error": "오류"}
SE = {"positive": "😊", "negative": "😠", "neutral": "😐", "error": "❓"}
SC = {"긍정": "#28a745", "부정": "#dc3545", "중립": "#ffc107", "오류": "#6c757d"}


def extract_video_id(url):
    for p in [r"watch\?v=([a-zA-Z0-9_-]{11})", r"youtu\.be\/([a-zA-Z0-9_-]{11})",
              r"shorts\/([a-zA-Z0-9_-]{11})", r"embed\/([a-zA-Z0-9_-]{11})",
              r"live\/([a-zA-Z0-9_-]{11})"]:
        m = re.search(p, url)
        if m:
            return m.group(1)
    return None


def get_video_info(youtube, video_id):
    try:
        resp = youtube.videos().list(part="snippet,statistics", id=video_id).execute()
        if resp["items"]:
            s = resp["items"][0]["snippet"]
            t = resp["items"][0]["statistics"]
            return {"title": s.get("title", ""), "channel": s.get("channelTitle", ""),
                    "published": s.get("publishedAt", "")[:10],
                    "views": int(t.get("viewCount", 0)),
                    "likes": int(t.get("likeCount", 0)),
                    "comment_count": int(t.get("commentCount", 0)),
                    "thumbnail": s.get("thumbnails", {}).get("high", {}).get("url", "")}
    except HttpError:
        return None
    return None


def get_replies(youtube, parent_id, max_r=50):
    replies, npt = [], None
    try:
        while len(replies) < max_r:
            resp = youtube.comments().list(
                part="snippet", parentId=parent_id,
                maxResults=min(100, max_r - len(replies)),
                pageToken=npt, textFormat="plainText").execute()
            for item in resp.get("items", []):
                sn = item["snippet"]
                replies.append({"writer": sn.get("authorDisplayName", ""),
                    "text": sn.get("textDisplay", ""), "likes": sn.get("likeCount", 0),
                    "date": sn.get("publishedAt", "")[:10],
                    "ctype": "reply", "reply_count": 0, "cid": item["id"]})
            npt = resp.get("nextPageToken")
            if not npt:
                break
    except HttpError:
        pass
    return replies


def get_comments(youtube, video_id, max_c=100, inc_replies=True):
    all_data, npt, top_n = [], None, 0
    try:
        while top_n < max_c:
            resp = youtube.commentThreads().list(
                part="snippet,replies", videoId=video_id,
                maxResults=min(100, max_c - top_n),
                pageToken=npt, textFormat="plainText", order="relevance").execute()
            for item in resp.get("items", []):
                ts = item["snippet"]["topLevelComment"]["snippet"]
                cid = item["snippet"]["topLevelComment"]["id"]
                rc = item["snippet"].get("totalReplyCount", 0)
                all_data.append({"writer": ts.get("authorDisplayName", ""),
                    "text": ts.get("textDisplay", ""), "likes": ts.get("likeCount", 0),
                    "date": ts.get("publishedAt", "")[:10],
                    "ctype": "comment", "reply_count": rc, "cid": cid})
                top_n += 1
                if inc_replies and rc > 0:
                    eids = set()
                    if "replies" in item:
                        for ri in item["replies"]["comments"]:
                            rs = ri["snippet"]
                            all_data.append({"writer": rs.get("authorDisplayName", ""),
                                "text": rs.get("textDisplay", ""),
                                "likes": rs.get("likeCount", 0),
                                "date": rs.get("publishedAt", "")[:10],
                                "ctype": "reply", "reply_count": 0, "cid": ri["id"]})
                            eids.add(ri["id"])
                    if rc > 5:
                        for r in get_replies(youtube, cid, rc):
                            if r["cid"] not in eids:
                                all_data.append(r)
            npt = resp.get("nextPageToken")
            if not npt:
                break
    except HttpError as e:
        if "commentsDisabled" in str(e):
            st.error("댓글이 비활성화된 영상입니다.")
        else:
            st.error(f"API 오류: {e}")
        return []
    return all_data


def sentiment_tb(texts):
    res = []
    for t in texts:
        try:
            p = TextBlob(str(t)).sentiment.polarity
            lb = "positive" if p > 0.1 else ("negative" if p < -0.1 else "neutral")
            res.append({"label": lb, "score": round(p, 3)})
        except Exception:
            res.append({"label": "neutral", "score": 0.0})
    return res


def sentiment_gpt(texts, key):
    client = OpenAI(api_key=key)
    res = []
    for i in range(0, len(texts), 20):
        batch = texts[i:i+20]
        numbered = "\n".join([f"{j+1}. {c[:200]}" for j, c in enumerate(batch)])
        try:
            r = client.chat.completions.create(model="gpt-4o-mini", messages=[
                {"role": "system", "content": "Classify each comment as positive/negative/neutral with score -1 to 1. Format: 1.positive|0.8 (nothing else)"},
                {"role": "user", "content": numbered}], temperature=0.1, max_tokens=1000)
            for line in r.choices[0].message.content.strip().split("\n"):
                try:
                    parts = line.split("|")
                    lb = parts[0].split(".")[-1].strip().lower()
                    sc = float(parts[1].strip())
                    if lb not in ["positive", "negative", "neutral"]:
                        lb = "neutral"
                    res.append({"label": lb, "score": round(sc, 3)})
                except Exception:
                    res.append({"label": "neutral", "score": 0.0})
        except Exception:
            res.extend([{"label": "error", "score": 0.0}] * len(batch))
        time.sleep(0.5)
    while len(res) < len(texts):
        res.append({"label": "neutral", "score": 0.0})
    return res[:len(texts)]


def summary_gpt(texts, title, key):
    client = OpenAI(api_key=key)
    sample = texts[:50]
    joined = "\n".join([f"- {c[:200]}" for c in sample])
    try:
        r = client.chat.completions.create(model="gpt-4o-mini", messages=[
            {"role": "system", "content": "YouTube comment analyst. Korean summary:\n1.Overall mood\n2.Top3 positive\n3.Top3 negative\n4.Keywords\n5.Conclusion"},
            {"role": "user", "content": f"Title:{title}\nComments({len(sample)}):\n{joined}"}],
            temperature=0.3, max_tokens=1500)
        return r.choices[0].message.content.strip()
    except Exception as e:
        return f"오류: {e}"


def summary_free(df):
    n = len(df)
    if n == 0:
        return "댓글 없음"
    tc = len(df[df["ctype"] == "comment"])
    rc = len(df[df["ctype"] == "reply"])
    al = df["likes"].mean()
    best = df.loc[df["likes"].idxmax()]
    mood, sent = "", ""
    if "sentiment" in df.columns:
        p = len(df[df["sentiment"] == "positive"])
        ng = len(df[df["sentiment"] == "negative"])
        nu = len(df[df["sentiment"] == "neutral"])
        sent = f"\n긍정{p}({p/n*100:.1f}%) 부정{ng}({ng/n*100:.1f}%) 중립{nu}({nu/n*100:.1f}%)"
        if p > ng * 2: mood = "매우 긍정적"
        elif p > ng: mood = "다소 긍정적"
        elif ng > p * 2: mood = "매우 부정적"
        elif ng > p: mood = "다소 부정적"
        else: mood = "혼재"
    return f"분위기: {mood}\n총{n}개(댓글{tc}+답글{rc}) 평균좋아요{al:.1f}{sent}\n인기댓글(👍{best['likes']}): {best['text'][:200]}"
    # ══════════════════════════════════════════════
# 메인 UI
# ══════════════════════════════════════════════
yt_key = st.secrets.get("YOUTUBE_API_KEY", None)
oa_key = st.secrets.get("OPENAI_API_KEY", None)
if not yt_key:
    st.warning("Secrets에 YOUTUBE_API_KEY를 설정하세요.")
    st.stop()

st.markdown("---")
c1, c2, c3 = st.columns([3, 1, 1])
with c1:
    url = st.text_input("🔗 링크", placeholder="https://www.youtube.com/watch?v=...")
with c2:
    max_n = st.selectbox("최대댓글", [50, 100, 200, 500, 1000], index=1)
with c3:
    inc_r = st.selectbox("답글", ["포함", "제외"])

if st.button("🔍 수집", use_container_width=True, type="primary") and url:
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
                    st.image(info["thumbnail"], use_container_width=True)
            with t2:
                st.markdown(f"**{info['title']}**")
                st.markdown(f"{info['channel']} · {info['published']}")
                a, b, c = st.columns(3)
                a.metric("조회수", f"{info['views']:,}")
                b.metric("좋아요", f"{info['likes']:,}")
                c.metric("댓글", f"{info['comment_count']:,}")
        with st.spinner("댓글 수집 중..."):
            data = get_comments(yt, vid, max_n, inc_r == "포함")
        if data:
            df = pd.DataFrame(data)
            tc = len(df[df["ctype"] == "comment"])
            rc = len(df[df["ctype"] == "reply"])
            st.success(f"총 {len(df)}개 (원댓글{tc} + 답글{rc})")
            st.session_state["df"] = df
            st.session_state["info"] = info
            st.session_state["vid"] = vid
        else:
            st.info("댓글이 없습니다.")

if "df" in st.session_state:
    df = st.session_state["df"]
    info = st.session_state.get("info", {})
    vid = st.session_state.get("vid", "")
    st.markdown("---")
    f1, f2, f3 = st.columns([2, 1, 1])
    with f1:
        kw = st.text_input("🔎 검색", placeholder="키워드")
    with f2:
        srt = st.selectbox("정렬", ["좋아요많은순", "좋아요적은순", "최신순", "오래된순"])
    with f3:
        tp = st.selectbox("유형", ["전체", "원댓글", "답글"])
    fdf = df.copy()
    if kw:
        fdf = fdf[fdf["text"].str.contains(kw, case=False, na=False)]
    if tp == "원댓글":
        fdf = fdf[fdf["ctype"] == "comment"]
    elif tp == "답글":
        fdf = fdf[fdf["ctype"] == "reply"]
    sm = {"좋아요많은순": ("likes", False), "좋아요적은순": ("likes", True),
          "최신순": ("date", False), "오래된순": ("date", True)}
    scol, sasc = sm[srt]
    fdf = fdf.sort_values(scol, ascending=sasc).reset_index(drop=True)
    if kw:
        st.info(f"'{kw}' 결과: {len(fdf)}개")

    tab1, tab2, tab3, tab4 = st.tabs(["📝카드", "📊테이블", "🧠감성", "📝요약"])

    with tab1:
        for i, row in fdf.head(100).iterrows():
            lk = f" 👍{row['likes']}" if row["likes"] > 0 else ""
            sb = ""
            if "sentiment" in fdf.columns:
                em = SE.get(row.get("sentiment", ""), "")
                kr = SK.get(row.get("sentiment", ""), "")
                if em:
                    sb = f" {em}{kr}"
            if row["ctype"] == "reply":
                st.markdown(f'<div class="rb"><div class="ra">↳ {row["writer"]}{lk}{sb}</div><div class="ct">{row["text"]}</div><div class="cm">📅 {row["date"]}</div></div>', unsafe_allow_html=True)
            else:
                rn = f" · 답글{row['reply_count']}개" if row.get("reply_count", 0) > 0 else ""
                st.markdown(f'<div class="cb"><div class="ca">{row["writer"]}{lk}{sb}{rn}</div><div class="ct">{row["text"]}</div><div class="cm">📅 {row["date"]}</div></div>', unsafe_allow_html=True)

    with tab2:
        ddf = fdf.rename(columns={"writer": "작성자", "text": "내용", "likes": "좋아요", "date": "날짜", "ctype": "유형", "reply_count": "답글수"})
        cols = ["유형", "작성자", "내용", "좋아요", "날짜", "답글수"]
        if "sentiment" in fdf.columns:
            ddf["감성"] = fdf["sentiment"].map(SK)
            ddf["점수"] = fdf.get("sent_score", 0)
            cols += ["감성", "점수"]
        st.dataframe(ddf[[c for c in cols if c in ddf.columns]], use_container_width=True, height=500)

    with tab3:
        st.markdown("### 🧠 감성 분석")
        if oa_key and OPENAI_AVAILABLE:
            mode = st.radio("방식", ["🤖GPT", "⚡TextBlob(무료)"], horizontal=True)
        else:
            mode = "⚡TextBlob(무료)"
            st.info("OpenAI키 설정시 GPT분석 가능")
        if st.button("🧠 분석실행", use_container_width=True):
            texts = df["text"].tolist()
            if "GPT" in mode and oa_key:
                with st.spinner("GPT 분석중..."):
                    res = sentiment_gpt(texts, oa_key)
            else:
                with st.spinner("분석중..."):
                    res = sentiment_tb(texts)
            df["sentiment"] = [r["label"] for r in res]
            df["sent_score"] = [r["score"] for r in res]
            st.session_state["df"] = df
            st.success("완료!")
            st.rerun()
        if "sentiment" in df.columns:
            tot = len(df)
            pos = len(df[df["sentiment"] == "positive"])
            neg = len(df[df["sentiment"] == "negative"])
            neu = len(df[df["sentiment"] == "neutral"])
            avg = df["sent_score"].mean()
            k1, k2, k3, k4 = st.columns(4)
            k1.metric("😊긍정", f"{pos}개({pos/tot*100:.1f}%)")
            k2.metric("😠부정", f"{neg}개({neg/tot*100:.1f}%)")
            k3.metric("😐중립", f"{neu}개({neu/tot*100:.1f}%)")
            k4.metric("평균", f"{avg:.3f}")
            cdf = df.copy()
            cdf["감성"] = cdf["sentiment"].map(SK)
            p1, p2 = st.columns(2)
            with p1:
                vc = cdf["감성"].value_counts()
                fig = px.pie(values=vc.values, names=vc.index, title="감성분포", color=vc.index, color_discrete_map=SC, hole=0.4)
                fig.update_traces(textposition="inside", textinfo="percent+label")
                st.plotly_chart(fig, use_container_width=True)
            with p2:
                fig2 = px.histogram(cdf, x="sent_score", nbins=30, color="감성", color_discrete_map=SC, title="점수분포")
                st.plotly_chart(fig2, use_container_width=True)
            if len(df[df["ctype"] == "reply"]) > 0:
                cdf["유형"] = cdf["ctype"].map({"comment": "💬댓글", "reply": "↳답글"})
                fig3 = px.histogram(cdf, x="감성", color="유형", barmode="group", title="댓글vs답글", color_discrete_map={"💬댓글": "#FF6B6B", "↳답글": "#4ECDC4"})
                st.plotly_chart(fig3, use_container_width=True)

    with tab4:
        st.markdown("### 📝 요약")
        if oa_key and OPENAI_AVAILABLE:
            smode = st.radio("방식", ["🤖AI요약", "📊통계요약"], horizontal=True)
        else:
            smode = "📊통계요약"
        if st.button("📝 요약생성", use_container_width=True):
            if "AI" in smode and oa_key:
                with st.spinner("AI 요약중..."):
                    result = summary_gpt(df["text"].tolist(), info.get("title", ""), oa_key)
            else:
                result = summary_free(df)
            st.session_state["summary"] = result
        if "summary" in st.session_state:
            st.markdown(f'<div class="sb">{st.session_state["summary"]}</div>', unsafe_allow_html=True)

    st.markdown("---")
    csv = fdf.to_csv(index=False, encoding="utf-8-sig")
    st.download_button("📥 CSV", csv, f"comments_{vid}.csv", "text/csv", use_container_width=True)

with st.sidebar:
    st.markdown("## 📖 사용법")
    st.markdown("1.링크입력 → 2.수집 → 3.감성분석 → 4.요약 → 5.다운로드")
    st.markdown("---")
    st.caption("당곡고등학교 학습용")
