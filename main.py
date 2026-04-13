import streamlit as st
import pandas as pd
import re
import time
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from textblob import TextBlob
import plotly.express as px
import plotly.graph_objects as go

# OpenAI는 선택적 import
try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

# ──────────────────────────────────────────────
# 페이지 설정
# ──────────────────────────────────────────────
st.set_page_config(
    page_title="유튜브 댓글 분석기",
    page_icon="📺",
    layout="wide"
)

# ──────────────────────────────────────────────
# CSS 스타일
# ──────────────────────────────────────────────
st.markdown("""
<style>
    .main-title {
        text-align: center;
        color: #FF0000;
        font-size: 2.5rem;
        font-weight: bold;
        margin-bottom: 0.5rem;
    }
    .sub-title {
        text-align: center;
        color: #666;
        font-size: 1.1rem;
        margin-bottom: 2rem;
    }
    .comment-box {
        background-color: #f9f9f9;
        border-left: 4px solid #FF0000;
        padding: 12px 16px;
        margin-bottom: 10px;
        border-radius: 0 8px 8px 0;
    }
    .comment-author {
        font-weight: bold;
        color: #333;
        font-size: 0.95rem;
    }
    .comment-text {
        color: #555;
        font-size: 0.9rem;
        margin-top: 4px;
    }
    .comment-meta {
        color: #999;
        font-size: 0.8rem;
        margin-top: 4px;
    }
    .positive { color: #28a745; font-weight: bold; }
    .negative { color: #dc3545; font-weight: bold; }
    .neutral { color: #ffc107; font-weight: bold; }
    .summary-box {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        padding: 20px;
        border-radius: 12px;
        margin: 10px 0;
        font-size: 1rem;
        line-height: 1.6;
    }
    .sentiment-card {
        padding: 15px;
        border-radius: 10px;
        text-align: center;
        margin: 5px;
    }
    .sentiment-positive {
        background-color: #d4edda;
        border: 2px solid #28a745;
    }
    .sentiment-negative {
        background-color: #f8d7da;
        border: 2px solid #dc3545;
    }
    .sentiment-neutral {
        background-color: #fff3cd;
        border: 2px solid #ffc107;
    }
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="main-title">📺 유튜브 댓글 분석기</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-title">댓글 수집 + AI 감성 분석 + 댓글 요약까지 한번에!</div>', unsafe_allow_html=True)


# ──────────────────────────────────────────────
# API 키 불러오기
# ──────────────────────────────────────────────
def get_api_key():
    try:
        return st.secrets["YOUTUBE_API_KEY"]
    except Exception:
        return None


def get_openai_key():
    try:
        return st.secrets["OPENAI_API_KEY"]
    except Exception:
        return None


# ──────────────────────────────────────────────
# 유튜브 영상 ID 추출
# ──────────────────────────────────────────────
def extract_video_id(url):
    patterns = [
        r'(?:youtube\.com\/watch\?v=)([a-zA-Z0-9_-]{11})',
        r'(?:youtu\.be\/)([a-zA-Z0-9_-]{11})',
        r'(?:youtube\.com\/embed\/)([a-zA-Z0-9_-]{11})',
        r'(?:youtube\.com\/shorts\/)([a-zA-Z0-9_-]{11})',
        r'(?:youtube\.com\/live\/)([a-zA-Z0-9_-]{11})',
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


# ──────────────────────────────────────────────
# 영상 정보 가져오기
# ──────────────────────────────────────────────
def get_video_info(youtube, video_id):
    try:
        request = youtube.videos().list(
            part="snippet,statistics",
            id=video_id
        )
        response = request.execute()

        if response["items"]:
            item = response["items"][0]
            snippet = item["snippet"]
            stats = item["statistics"]
            return {
                "title": snippet.get("title", "제목 없음"),
                "channel": snippet.get("channelTitle", "채널 없음"),
                "published": snippet.get("publishedAt", "")[:10],
                "views": int(stats.get("viewCount", 0)),
                "likes": int(stats.get("likeCount", 0)),
                "comment_count": int(stats.get("commentCount", 0)),
                "thumbnail": snippet.get("thumbnails", {}).get("high", {}).get("url", "")
            }
    except HttpError:
        return None
    return None


# ──────────────────────────────────────────────
# 댓글 수집
# ──────────────────────────────────────────────
def get_comments(youtube, video_id, max_comments=100):
    comments = []
    next_page_token = None

    try:
        while len(comments) < max_comments:
            request = youtube.commentThreads().list(
                part="snippet",
                videoId=video_id,
                maxResults=min(100, max_comments - len(comments)),
                pageToken=next_page_token,
                textFormat="plainText",
                order="relevance"
            )
            response = request.execute()

            for item in response.get("items", []):
                snippet = item["snippet"]["topLevelComment"]["snippet"]
                comments.append({
                    "작성자": snippet.get("authorDisplayName", "익명"),
                    "댓글 내용": snippet.get("textDisplay", ""),
                    "좋아요 수": snippet.get("likeCount", 0),
                    "작성일": snippet.get("publishedAt", "")[:10],
                    "수정일": snippet.get("updatedAt", "")[:10],
                })

            next_page_token = response.get("nextPageToken")
            if not next_page_token:
                break

    except HttpError as e:
        if "commentsDisabled" in str(e):
            st.error("⚠️ 이 영상은 댓글이 비활성화되어 있습니다.")
        elif "forbidden" in str(e).lower():
            st.error("⚠️ API 키 권한 문제가 발생했습니다.")
        else:
            st.error(f"⚠️ API 오류: {e}")
        return []

    return comments


# ──────────────────────────────────────────────
# 감성 분석 (무료 - TextBlob)
# ──────────────────────────────────────────────
def analyze_sentiment_textblob(text):
    """TextBlob을 이용한 무료 감성 분석"""
    try:
        blob = TextBlob(str(text))
        polarity = blob.sentiment.polarity

        if polarity > 0.1:
            return "긍정", polarity
        elif polarity < -0.1:
            return "부정", polarity
        else:
            return "중립", polarity
    except Exception:
        return "중립", 0.0


def batch_sentiment_textblob(comments_list):
    """댓글 리스트에 대해 일괄 감성 분석 (TextBlob)"""
    results = []
    for text in comments_list:
        sentiment, score = analyze_sentiment_textblob(text)
        results.append({"감성": sentiment, "감성점수": round(score, 3)})
    return results


# ──────────────────────────────────────────────
# 감성 분석 (OpenAI GPT)
# ──────────────────────────────────────────────
def batch_sentiment_openai(comments_list, openai_key):
    """OpenAI GPT를 이용한 고급 감성 분석 (한국어 지원)"""
    client = OpenAI(api_key=openai_key)
    results = []

    # 20개씩 묶어서 분석 (API 비용 절약)
    batch_size = 20
    for i in range(0, len(comments_list), batch_size):
        batch = comments_list[i:i + batch_size]
        numbered = "\n".join([f"{j+1}. {c[:200]}" for j, c in enumerate(batch)])

        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "너는 댓글 감성 분석 전문가야. "
                            "각 댓글을 '긍정', '부정', '중립' 중 하나로 분류하고 "
                            "감성 점수를 -1.0 ~ 1.0 사이로 매겨줘. "
                            "반드시 아래 형식으로만 답해:\n"
                            "1.긍정|0.8\n2.부정|-0.6\n3.중립|0.0\n"
                            "다른 설명 없이 번호.감성|점수 형식만 출력해."
                        )
                    },
                    {
                        "role": "user",
                        "content": f"다음 댓글들의 감성을 분석해줘:\n\n{numbered}"
                    }
                ],
                temperature=0.1,
                max_tokens=1000
            )

            answer = response.choices[0].message.content.strip()
            lines = answer.strip().split("\n")

            for line in lines:
                try:
                    parts = line.split("|")
                    sentiment_part = parts[0].split(".")[-1].strip()
                    score_part = float(parts[1].strip())

                    if sentiment_part in ["긍정", "부정", "중립"]:
                        results.append({"감성": sentiment_part, "감성점수": round(score_part, 3)})
                    else:
                        results.append({"감성": "중립", "감성점수": 0.0})
                except Exception:
                    results.append({"감성": "중립", "감성점수": 0.0})

        except Exception as e:
            for _ in batch:
                results.append({"감성": "분석실패", "감성점수": 0.0})

        time.sleep(0.5)

    # 댓글 수와 결과 수가 다르면 보정
    while len(results) < len(comments_list):
        results.append({"감성": "중립", "감성점수": 0.0})

    return results[:len(comments_list)]


# ──────────────────────────────────────────────
# 댓글 요약 (OpenAI GPT)
# ──────────────────────────────────────────────
def summarize_comments_openai(comments_list, video_title, openai_key):
    """OpenAI GPT를 이용한 댓글 요약"""
    client = OpenAI(api_key=openai_key)

    # 최대 50개 댓글, 각 200자 제한으로 토큰 절약
    sample = comments_list[:50]
    comments_text = "\n".join([f"- {c[:200]}" for c in sample])

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "너는 유튜브 댓글 분석 전문가야. "
                        "댓글들을 읽고 아래 형식으로 한국어 요약을 작성해:\n\n"
                        "📌 **전체 분위기**: (한 줄 요약)\n\n"
                        "👍 **긍정적 의견 TOP 3**:\n"
                        "1. ...\n2. ...\n3. ...\n\n"
                        "👎 **부정적 의견 TOP 3**:\n"
                        "1. ...\n2. ...\n3. ...\n\n"
                        "💡 **핵심 키워드**: (쉼표로 구분)\n\n"
                        "🎯 **한줄 결론**: ..."
                    )
                },
                {
                    "role": "user",
                    "content": (
                        f"영상 제목: {video_title}\n\n"
                        f"댓글 {len(sample)}개:\n{comments_text}"
                    )
                }
            ],
            temperature=0.3,
            max_tokens=1500
        )
        return response.choices[0].message.content.strip()

    except Exception as e:
        return f"❌ 요약 생성 중 오류가 발생했습니다: {str(e)}"


def summarize_comments_free(df):
    """무료 버전 댓글 요약 (통계 기반)"""
    total = len(df)
    if total == 0:
        return "댓글이 없습니다."

    avg_likes = df["좋아요 수"].mean()
    max_likes_row = df.loc[df["좋아요 수"].idxmax()]
    avg_length = df["댓글 내용"].str.len().mean()

    # 감성 분포
    if "감성" in df.columns:
        pos = len(df[df["감성"] == "긍정"])
        neg = len(df[df["감성"] == "부정"])
        neu = len(df[df["감성"] == "중립"])
        sentiment_text = (
            f"- 긍정 {pos}개 ({pos/total*100:.1f}%) | "
            f"부정 {neg}개 ({neg/total*100:.1f}%) | "
            f"중립 {neu}개 ({neu/total*100:.1f}%)"
        )
        if pos > neg * 2:
            mood = "😊 전반적으로 매우 긍정적인 분위기입니다."
        elif pos > neg:
            mood = "🙂 긍정적인 의견이 다소 많습니다."
        elif neg > pos * 2:
            mood = "😠 부정적인 반응이 많습니다."
        elif neg > pos:
            mood = "😕 부정적인 의견이 다소 많습니다."
        else:
            mood = "😐 긍정과 부정이 비슷하게 섞여 있습니다."
    else:
        sentiment_text = "- 감성 분석을 먼저 실행해주세요."
        mood = ""

    summary = f"""
📌 **전체 분위기**: {mood}

📊 **기본 통계**:
- 총 댓글 수: {total}개
- 평균 좋아요: {avg_likes:.1f}개
- 평균 댓글 길이: {avg_length:.0f}자

{sentiment_text}

⭐ **가장 인기있는 댓글** (👍 {max_likes_row['좋아요 수']}개):
> {max_likes_row['댓글 내용'][:200]}
"""
    return summary


# ──────────────────────────────────────────────
# 감성 분석 시각화
# ──────────────────────────────────────────────
def show_sentiment_charts(df):
    """감성 분석 결과를 차트로 시각화"""

    col1, col2 = st.columns(2)

    with col1:
        # 파이 차트
        sentiment_counts = df["감성"].value_counts()
        colors = {"긍정": "#28a745", "부정": "#dc3545", "중립": "#ffc107", "분석실패": "#6c757d"}
        color_list = [colors.get(s, "#6c757d") for s in sentiment_counts.index]

        fig_pie = px.pie(
            values=sentiment_counts.values,
            names=sentiment_counts.index,
            title="💭 감성 분포",
            color=sentiment_counts.index,
            color_discrete_map=colors,
            hole=0.4
        )
        fig_pie.update_traces(textposition='inside', textinfo='percent+label')
        fig_pie.update_layout(
            font=dict(size=14),
            showlegend=True,
            height=400
        )
        st.plotly_chart(fig_pie, use_container_width=True)

    with col2:
        # 감성 점수 분포 히스토그램
        fig_hist = px.histogram(
            df,
            x="감성점수",
            nbins=30,
            title="📊 감성 점수 분포",
            color="감성",
            color_discrete_map=colors,
            labels={"감성점수": "감성 점수 (-1: 부정 ~ +1: 긍정)", "count": "댓글 수"}
        )
        fig_hist.update_layout(
            font=dict(size=14),
            height=400,
            bargap=0.1
        )
        st.plotly_chart(fig_hist, use_container_width=True)

    # 감성별 좋아요 수 비교
    if "좋아요 수" in df.columns:
        fig_box = px.box(
            df,
            x="감성",
            y="좋아요 수",
            color="감성",
            color_discrete_map=colors,
            title="👍 감성별 좋아요 수 분포"
        )
        fig_box.update_layout(font=dict(size=14), height=350, showlegend=False)
        st.plotly_chart(fig_box, use_container_width=True)


# ──────────────────────────────────────────────
# 메인 UI
# ──────────────────────────────────────────────
api_key = get_api_key()
openai_key = get_openai_key()

if not api_key:
    st.warning("⚠️ YouTube API 키가 설정되지 않았습니다.")
    st.info("""
    **API 키 설정 방법:**
    
    1. [Google Cloud Console](https://console.cloud.google.com/)에 접속합니다.
    2. 새 프로젝트를 만들고 **YouTube Data API v3**를 활성화합니다.
    3. **사용자 인증 정보 → API 키**를 생성합니다.
    4. Streamlit Cloud의 **Settings → Secrets**에 아래 내용을 입력합니다:
    
    ```
    YOUTUBE_API_KEY = "발급받은_API_키"
    OPENAI_API_KEY = "sk-..."   # (선택) AI 요약/감성분석용
    ```
    """)
    st.stop()

# ── 입력 영역 ──
st.markdown("---")
col_input, col_option = st.columns([3, 1])

with col_input:
    url = st.text_input(
        "🔗 유튜브 영상 링크를 입력하세요",
        placeholder="https://www.youtube.com/watch?v=...",
        help="유튜브 영상 URL을 붙여넣기 하세요"
    )

with col_option:
    max_comments = st.selectbox(
        "📊 최대 수집 댓글 수",
        options=[50, 100, 200, 500, 1000],
        index=1,
        help="수집할 최대 댓글 수를 선택하세요"
    )

# ── 검색 버튼 ──
search_clicked = st.button("🔍 댓글 수집 시작", use_container_width=True, type="primary")

if search_clicked and url:
    video_id = extract_video_id(url)

    if not video_id:
        st.error("❌ 올바른 유튜브 링크가 아닙니다. 다시 확인해주세요.")
    else:
        youtube = build("youtube", "v3", developerKey=api_key)

        # ── 영상 정보 표시 ──
        with st.spinner("📡 영상 정보를 불러오는 중..."):
            video_info = get_video_info(youtube, video_id)

        if video_info:
            st.markdown("---")
            st.markdown("### 📋 영상 정보")

            col_thumb, col_info = st.columns([1, 2])

            with col_thumb:
                if video_info["thumbnail"]:
                    st.image(video_info["thumbnail"], use_container_width=True)

            with col_info:
                st.markdown(f"**제목:** {video_info['title']}")
                st.markdown(f"**채널:** {video_info['channel']}")
                st.markdown(f"**업로드일:** {video_info['published']}")

                metric_cols = st.columns(3)
                with metric_cols[0]:
                    st.metric("조회수", f"{video_info['views']:,}")
                with metric_cols[1]:
                    st.metric("좋아요", f"{video_info['likes']:,}")
                with metric_cols[2]:
                    st.metric("댓글 수", f"{video_info['comment_count']:,}")

        # ── 댓글 수집 ──
        with st.spinner(f"💬 댓글을 수집하는 중... (최대 {max_comments}개)"):
            comments = get_comments(youtube, video_id, max_comments)

        if comments:
            df = pd.DataFrame(comments)

            # ═══════════════════════════════════════
            # 감성 분석 실행
            # ═══════════════════════════════════════
            st.markdown("---")
            st.markdown("### 🧠 감성 분석")

            # 분석 방식 선택
            if openai_key and OPENAI_AVAILABLE:
                analysis_mode = st.radio(
                    "분석 방식 선택",
                    options=["🤖 AI 분석 (GPT - 한국어 정확도 높음)", "⚡ 빠른 분석 (TextBlob - 무료)"],
                    horizontal=True,
                    help="GPT 분석은 더 정확하지만 OpenAI API 비용이 발생합니다."
                )
            else:
                analysis_mode = "⚡ 빠른 분석 (TextBlob - 무료)"
                if not openai_key:
                    st.info("💡 OpenAI API 키를 설정하면 GPT 기반 고급 분석을 사용할 수 있습니다.")

            analyze_clicked = st.button("🧠 감성 분석 실행", use_container_width=True)

            if analyze_clicked:
                comments_text_list = df["댓글 내용"].tolist()

                if "GPT" in analysis_mode and openai_key:
                    with st.spinner("🤖 GPT가 댓글을 분석하는 중... (시간이 좀 걸릴 수 있어요)"):
                        sentiment_results = batch_sentiment_openai(comments_text_list, openai_key)
                else:
                    with st.spinner("⚡ 감성 분석 중..."):
                        sentiment_results = batch_sentiment_textblob(comments_text_list)

                # 결과를 DataFrame에 추가
                sentiment_df = pd.DataFrame(sentiment_results)
                df["감성"] = sentiment_df["감성"]
                df["감성점수"] = sentiment_df["감성점수"]

                # 세션에 저장
                st.session_state["analyzed_df"] = df
                st.session_state["video_info"] = video_info
                st.session_state["video_id"] = video_id
                st.session_state["analysis_mode"] = analysis_mode

                st.success("✅ 감성 분석 완료!")

            # ── 분석 결과 표시 ──
            if "analyzed_df" in st.session_state:
                df = st.session_state["analyzed_df"]

                # 감성 요약 카드
                total = len(df)
                pos_count = len(df[df["감성"] == "긍정"])
                neg_count = len(df[df["감성"] == "부정"])
                neu_count = len(df[df["감성"] == "중립"])

                card_cols = st.columns(4)
                with card_cols[0]:
                    st.markdown(f"""
                    <div class="sentiment-card" style="background-color:#e8f5e9; border:2px solid #28a745;">
                        <h2 style="color:#28a745; margin:0;">😊 {pos_count}</h2>
                        <p style="margin:0;">긍정 ({pos_count/total*100:.1f}%)</p>
                    </div>
                    """, unsafe_allow_html=True)
                with card_cols[1]:
                    st.markdown(f"""
                    <div class="sentiment-card" style="background-color:#fce4ec; border:2px solid #dc3545;">
                        <h2 style="color:#dc3545; margin:0;">😠 {neg_count}</h2>
                        <p style="margin:0;">부정 ({neg_count/total*100:.1f}%)</p>
                    </div>
                    """, unsafe_allow_html=True)
                with card_cols[2]:
                    st.markdown(f"""
                    <div class="sentiment-card" style="background-color:#fff8e1; border:2px solid #ffc107;">
                        <h2 style="color:#ffc107; margin:0;">😐 {neu_count}</h2>
                        <p style="margin:0;">중립 ({neu_count/total*100:.1f}%)</p>
                    </div>
                    """, unsafe_allow_html=True)
                with card_cols[3]:
                    avg_score = df["감성점수"].mean()
                    score_color = "#28a745" if avg_score > 0 else "#dc3545" if avg_score < 0 else "#ffc107"
                    st.markdown(f"""
                    <div class="sentiment-card" style="background-color:#e3f2fd; border:2px solid #2196f3;">
                        <h2 style="color:{score_color}; margin:0;">{avg_score:.3f}</h2>
                        <p style="margin:0;">평균 감성 점수</p>
                    </div>
                    """, unsafe_allow_html=True)

                # 차트 표시
                show_sentiment_charts(df)

                # ═══════════════════════════════════════
                # 댓글 요약
                # ═══════════════════════════════════════
                st.markdown("---")
                st.markdown("### 📝 댓글 요약")

                if openai_key and OPENAI_AVAILABLE:
                    summary_mode = st.radio(
                        "요약 방식",
                        options=["🤖 AI 요약 (GPT)", "📊 통계 기반 요약 (무료)"],
                        horizontal=True
                    )
                else:
                    summary_mode = "📊 통계 기반 요약 (무료)"

                summarize_clicked = st.button("📝 댓글 요약 생성", use_container_width=True)

                if summarize_clicked:
                    if "GPT" in summary_mode and openai_key:
                        with st.spinner("🤖 AI가 댓글을 요약하는 중
