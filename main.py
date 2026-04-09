import streamlit as st
import pandas as pd
import re
import time
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from textblob import TextBlob
import plotly.express as px
import plotly.graph_objects as go

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
    .reply-box {
        background-color: #f0f4ff;
        border-left: 4px solid #4285f4;
        padding: 10px 14px;
        margin-bottom: 8px;
        margin-left: 30px;
        border-radius: 0 8px 8px 0;
        font-size: 0.9rem;
    }
    .comment-author {
        font-weight: bold;
        color: #333;
        font-size: 0.95rem;
    }
    .reply-author {
        font-weight: bold;
        color: #4285f4;
        font-size: 0.9rem;
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
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="main-title">📺 유튜브 댓글 분석기</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-title">댓글 + 답글 수집 · AI 감성 분석 · 댓글 요약까지 한번에!</div>', unsafe_allow_html=True)


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
# ★ 답글(대댓글) 수집 함수
# ──────────────────────────────────────────────
def get_replies(youtube, parent_id, max_replies=50):
    """특정 댓글의 답글(대댓글)을 수집합니다."""
    replies = []
    next_page_token = None

    try:
        while len(replies) < max_replies:
            request = youtube.comments().list(
                part="snippet",
                parentId=parent_id,
                maxResults=min(100, max_replies - len(replies)),
                pageToken=next_page_token,
                textFormat="plainText"
            )
            response = request.execute()

            for item in response.get("items", []):
                snippet = item["snippet"]
                replies.append({
                    "작성자": snippet.get("authorDisplayName", "익명"),
                    "댓글 내용": snippet.get("textDisplay", ""),
                    "좋아요 수": snippet.get("likeCount", 0),
                    "작성일": snippet.get("publishedAt", "")[:10],
                    "수정일": snippet.get("updatedAt", "")[:10],
                    "유형": "↳ 답글",
                    "부모댓글ID": parent_id
                })

            next_page_token = response.get("nextPageToken")
            if not next_page_token:
                break

    except HttpError:
        pass

    return replies


# ──────────────────────────────────────────────
# ★ 댓글 + 답글 통합 수집
# ──────────────────────────────────────────────
def get_comments_with_replies(youtube, video_id, max_comments=100, include_replies=True):
    """
    댓글과 답글을 함께 수집합니다.
    include_replies=True이면 각 댓글의 답글도 수집합니다.
    """
    all_comments = []
    next_page_token = None
    top_level_count = 0

    try:
        while top_level_count < max_comments:
            request = youtube.commentThreads().list(
                part="snippet,replies",
                videoId=video_id,
                maxResults=min(100, max_comments - top_level_count),
                pageToken=next_page_token,
                textFormat="plainText",
                order="relevance"
            )
            response = request.execute()

            for item in response.get("items", []):
                # ── 원본 댓글 ──
                top_snippet = item["snippet"]["topLevelComment"]["snippet"]
                comment_id = item["snippet"]["topLevelComment"]["id"]
                reply_count = item["snippet"].get("totalReplyCount", 0)

                all_comments.append({
                    "작성자": top_snippet.get("authorDisplayName", "익명"),
                    "댓글 내용": top_snippet.get("textDisplay", ""),
                    "좋아요 수": top_snippet.get("likeCount", 0),
                    "작성일": top_snippet.get("publishedAt", "")[:10],
                    "수정일": top_snippet.get("updatedAt", "")[:10],
                    "유형": "💬 댓글",
                    "답글 수": reply_count,
                    "댓글ID": comment_id
                })
                top_level_count += 1

                # ── 답글 수집 ──
                if include_replies and reply_count > 0:
                    # API 응답에 포함된 답글 (최대 5개)
                    if "replies" in item:
                        for reply_item in item["replies"]["comments"]:
                            r_snippet = reply_item["snippet"]
                            all_comments.append({
                                "작성자": r_snippet.get("authorDisplayName", "익명"),
                                "댓글 내용": r_snippet.get("textDisplay", ""),
                                "좋아요 수": r_snippet.get("likeCount", 0),
                                "작성일": r_snippet.get("publishedAt", "")[:10],
                                "수정일": r_snippet.get("updatedAt", "")[:10],
                                "유형": "↳ 답글",
                                "답글 수": 0,
                                "댓글ID": reply_item["id"]
                            })

                    # 답글이 5개 넘으면 추가 API 호출로 나머지 수집
                    if reply_count > 5:
                        extra_replies = get_replies(youtube, comment_id, max_replies=reply_count)
                        # 이미 가져온 답글 ID 목록
                        existing_ids = {c["댓글ID"] for c in all_comments}
                        for r in extra_replies:
                            r["답글 수"] = 0
                            r["댓글ID"] = ""
                            all_comments.append(r)

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

    return all_comments


# ──────────────────────────────────────────────
# 감성 분석 (TextBlob - 무료)
# ──────────────────────────────────────────────
def batch_sentiment_textblob(comments_list):
    results = []
    for text in comments_list:
        try:
            blob = TextBlob(str(text))
            polarity = blob.sentiment.polarity
            if polarity > 0.1:
                results.append({"감성": "긍정", "감성점수": round(polarity, 3)})
            elif polarity < -0.1:
                results.append({"감성": "부정", "감성점수": round(polarity, 3)})
            else:
                results.append({"감성": "중립", "감성점수": round(polarity, 3)})
        except Exception:
            results.append({"감성": "중립", "감성점수": 0.0})
    return results


# ──────────────────────────────────────────────
# 감성 분석 (OpenAI GPT)
# ──────────────────────────────────────────────
def batch_sentiment_openai(comments_list, openai_key):
    client = OpenAI(api_key=openai_key)
    results = []
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
                    {"role": "user", "content": f"다음 댓글들의 감성을 분석해줘:\n\n{numbered}"}
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

        except Exception:
            for _ in batch:
                results.append({"감성": "분석실패", "감성점수": 0.0})

        time.sleep(0.5)

    while len(results) < len(comments_list):
        results.append({"감성": "중립", "감성점수": 0.0})
    return results[:len(comments_list)]


# ──────────────────────────────────────────────
# 댓글 요약 (OpenAI)
# ──────────────────────────────────────────────
def summarize_comments_openai(comments_list, video_title, openai_key):
    client = OpenAI(api_key=openai_key)
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
                        "👍 **긍정적 의견 TOP 3**:\n1. ...\n2. ...\n3. ...\n\n"
                        "👎 **부정적 의견 TOP 3**:\n1. ...\n2. ...\n3. ...\n\n"
                        "💡 **핵심 키워드**: (쉼표로 구분)\n\n"
                        "🎯 **한줄 결론**: ..."
                    )
                },
                {
                    "role": "user",
                    "content": f"영상 제목: {video_title}\n\n댓글 {len(sample)}개:\n{comments_text}"
                }
            ],
            temperature=0.3,
            max_tokens=1500
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"❌ 요약 생성 중 오류: {str(e)}"


def summarize_comments_free(df):
    total = len(df)
    if total == 0:
        return "댓글이 없습니다."

    avg_likes = df["좋아요 수"].mean()
    max_likes_row = df.loc[df["좋아요 수"].idxmax()]
    avg_length = df["댓글 내용"].str.len().mean()

    top_comments = len(df[df["유형"] == "💬 댓글"])
    reply_comments = len(df[df["유형"] == "↳ 답글"])

    sentiment_text = ""
    mood = ""
    if "감성" in df.columns:
        pos = len(df[df["감성"] == "긍정"])
        neg = len(df[df["감성"] == "부정"])
        neu = len(df[df["감성"] == "중립"])
        sentiment_text = (
            f"\n🧠 **감성 분포**: 긍정 {pos}개 ({pos/total*100:.1f}%) | "
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

    summary = f"""
📌 **전체 분위기**: {mood}

📊 **기본 통계**:
- 총 댓글: {total}개 (원댓글 {top_comments}개 + 답글 {reply_comments}개)
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
    col1, col2 = st.columns(2)
    colors = {"긍정": "#28a745", "부정": "#dc3545", "중립": "#ffc107", "분석실패": "#6c757d"}

    with col1:
        sentiment_counts = df["감성"].value_counts()
        fig_pie = px.pie(
            values=sentiment_counts.values,
            names=sentiment_counts.index,
            title="💭 감성 분포",
            color=sentiment_counts.index,
            color_discrete_map=colors,
            hole=0.4
        )
        fig_pie.update_traces(textposition='inside', textinfo='percent+label')
        fig_pie.update_layout(font=dict(size=14), height=400)
        st.plotly_chart(fig_pie, use_container_width=True)

    with col2:
        fig_hist = px.histogram(
            df, x="감성점수", nbins=30,
            title="📊 감성 점수 분포",
            color="감성", color_discrete_map=colors,
            labels={"감성점수": "감성 점수 (-1:부정 ~ +1:긍정)", "count": "댓글 수"}
        )
        fig_hist.update_layout(font=dict(size=14), height=400, bargap=0.1)
        st.plotly_chart(fig_hist, use_container_width=True)

    # 댓글 vs 답글 감성 비교
    if "유형" in df.columns:
        fig_grouped = px.histogram(
            df, x="감성", color="유형",
            barmode="group",
            title="💬 댓글 vs ↳ 답글 감성 비교",
            color_discrete_map={"💬 댓글": "#FF6B6B", "↳ 답글": "#4ECDC4"}
        )
        fig_grouped.update_layout(font=dict(size=14), height=350)
        st.plotly_chart(fig_grouped, use_container_width=True)

    # 감성별 좋아요 분포
    fig_box = px.box(
        df, x="감성", y="좋아요 수", color="감성",
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
    **Streamlit Cloud → Settings → Secrets에 입력:**
    ```
    YOUTUBE_API_KEY = "발급받은_유튜브_API_키"
    OPENAI_API_KEY = "sk-..."   # (선택사항)
    ```
    """)
    st.stop()

# ── 입력 영역 ──
st.markdown("---")
col_input, col_option1, col_option2 = st.columns([3, 1, 1])

with col_input:
    url = st.text_input(
        "🔗 유튜브 영상 링크를 입력하세요",
        placeholder="https://www.youtube.com/watch?v=..."
    )

with col_option1:
    max_comments = st.selectbox(
        "📊 최대 댓글 수",
        options=[50, 100, 200, 500, 1000],
        index=1
    )

with col_option2:
    include_replies = st.selectbox(
        "💬 답글 수집",
        options=["답글 포함", "답글 제외"],
        index=0,
        help="답글을 포함하면 API 할당량을 더 사용합니다."
    )

# ── 수집 버튼 ──
search_clicked = st.button("🔍 댓글 수집 시작", use_container_width=True, type="primary")

if search_clicked and url:
    video_id = extract_video_id(url)

    if not video_id:
        st.error("❌ 올바른 유튜브 링크가 아닙니다.")
    else:
        youtube = build("youtube", "v3", developerKey=api_key)

        # ── 영상 정보 ──
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
                m1, m2, m3 = st.columns(3)
                with m1:
                    st.metric("조회수", f"{video_info['views']:,}")
                with m2:
                    st.metric("좋아요", f"{video_info['likes']:,}")
                with m3:
                    st.metric("댓글 수", f"{video_info['comment_count']:,}")

        # ── 댓글 + 답글 수집 ──
        do_replies = (include_replies == "답글 포함")
        reply_label = " (답글 포함)" if do_replies else ""

        with st.spinner(f"💬 댓글을 수집하는 중...{reply_label} (최대 {max_comments}개)"):
            comments = get_comments_with_replies(
                youtube, video_id, max_comments, include_replies=do_replies
            )

        if comments:
            df = pd.DataFrame(comments)

            # 빠진 컬럼 보정
            if "유형" not in df.columns:
                df["유형"] = "💬 댓글"
            if "답글 수" not in df.columns:
                df["답글 수"] = 0
            if "댓글ID" not in df.columns:
                df["댓글ID"] = ""

            # 수집 결과 요약
            top_count = len(df[df["유형"] == "💬 댓글"])
            reply_count = len(df[df["유형"] == "↳ 답글"])

            st.markdown("---")
            st.markdown(f"### 💬 수집된 댓글 ({len(df)}개)")

            info_cols = st.columns(3)
            with info_cols[0]:
                st.metric("전체", f"{len(df)}개")
            with info_cols[1]:
                st.metric("💬 원댓글", f"{top_count}개")
            with info_cols[2]:
                st.metric("↳ 답글", f"{reply_count}개")

            # session_state에 저장
            st.session_state["df"] = df
            st.session_state["video_info"] = video_info
            st.session_state["video_id"] = video_id

        elif not comments:
            st.info("😅 수집된 댓글이 없습니다.")

elif search_clicked and not url:
    st.warning("⚠️ 유튜브 링크를 입력해주세요!")


# ══════════════════════════════════════════════
# 댓글이 수집된 후의 기능들
# ══════════════════════════════════════════════
if "df" in st.session_state:
    df = st.session_state["df"]
    video_info = st.session_state.get("video_info", {})
    video_id = st.session_state.get("video_id", "")

    # ── 필터 & 검색 ──
    st.markdown("---")
    col_search, col_sort, col_type = st.columns([2, 1, 1])

    with col_search:
        search_keyword = st.text_input(
            "🔎 키워드 검색",
            placeholder="검색할 키워드를 입력하세요"
        )
    with col_sort:
        sort_option = st.selectbox(
            "정렬 기준",
            options=["좋아요 수 (높은 순)", "좋아요 수 (낮은 순)", "최신순", "오래된순"]
        )
    with col_type:
        type_filter = st.selectbox(
            "댓글 유형",
            options=["전체", "💬 원댓글만", "↳ 답글만"]
        )

    filtered_df = df.copy()

    if search_keyword:
        filtered_df = filtered_df[
            filtered_df["댓글 내용"].str.contains(search_keyword, case=False, na=False)
        ]
    if type_filter == "💬 원댓글만":
        filtered_df = filtered_df[filtered_df["유형"] == "💬 댓글"]
    elif type_filter == "↳ 답글만":
        filtered_df = filtered_df[filtered_df["유형"] == "↳ 답글"]

    if sort_option == "좋아요 수 (높은 순)":
        filtered_df = filtered_df.sort_values("좋아요 수", ascending=False)
    elif sort_option == "
