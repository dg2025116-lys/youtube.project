import streamlit as st
import pandas as pd
import re
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# ──────────────────────────────────────────────
# 페이지 설정
# ──────────────────────────────────────────────
st.set_page_config(
    page_title="유튜브 댓글 수집기",
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
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="main-title">📺 유튜브 댓글 수집기</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-title">유튜브 영상 링크를 입력하면 댓글을 자동으로 수집합니다</div>', unsafe_allow_html=True)


# ──────────────────────────────────────────────
# API 키 불러오기
# ──────────────────────────────────────────────
def get_api_key():
    """Streamlit secrets에서 API 키를 가져옵니다."""
    try:
        return st.secrets["YOUTUBE_API_KEY"]
    except Exception:
        return None


# ──────────────────────────────────────────────
# 유튜브 영상 ID 추출
# ──────────────────────────────────────────────
def extract_video_id(url):
    """
    다양한 유튜브 URL 형식에서 영상 ID를 추출합니다.
    지원 형식:
      - https://www.youtube.com/watch?v=VIDEO_ID
      - https://youtu.be/VIDEO_ID
      - https://www.youtube.com/embed/VIDEO_ID
      - https://www.youtube.com/shorts/VIDEO_ID
    """
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
    """영상 제목, 채널명, 조회수 등 기본 정보를 가져옵니다."""
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
    """
    유튜브 영상의 댓글을 수집합니다.
    max_comments: 최대 수집할 댓글 수
    """
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
            st.error("⚠️ API 키 권한 문제가 발생했습니다. API 키를 확인해주세요.")
        else:
            st.error(f"⚠️ API 오류가 발생했습니다: {e}")
        return []

    return comments


# ──────────────────────────────────────────────
# 메인 UI
# ──────────────────────────────────────────────
api_key = get_api_key()

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
        # YouTube API 클라이언트 생성
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

            st.markdown("---")
            st.markdown(f"### 💬 수집된 댓글 ({len(df)}개)")

            # ── 필터 & 검색 ──
            col_search, col_sort = st.columns([2, 1])

            with col_search:
                search_keyword = st.text_input(
                    "🔎 댓글 내 키워드 검색",
                    placeholder="검색할 키워드를 입력하세요"
                )

            with col_sort:
                sort_option = st.selectbox(
                    "정렬 기준",
                    options=["좋아요 수 (높은 순)", "좋아요 수 (낮은 순)", "최신순", "오래된순"]
                )

            # 필터링 적용
            filtered_df = df.copy()

            if search_keyword:
                filtered_df = filtered_df[
                    filtered_df["댓글 내용"].str.contains(search_keyword, case=False, na=False)
                ]

            # 정렬 적용
            if sort_option == "좋아요 수 (높은 순)":
                filtered_df = filtered_df.sort_values("좋아요 수", ascending=False)
            elif sort_option == "좋아요 수 (낮은 순)":
                filtered_df = filtered_df.sort_values("좋아요 수", ascending=True)
            elif sort_option == "최신순":
                filtered_df = filtered_df.sort_values("작성일", ascending=False)
            elif sort_option == "오래된순":
                filtered_df = filtered_df.sort_values("작성일", ascending=True)

            filtered_df = filtered_df.reset_index(drop=True)

            if search_keyword:
                st.info(f"🔎 '{search_keyword}' 검색 결과: {len(filtered_df)}개")

            # ── 탭으로 보기 ──
            tab_card, tab_table = st.tabs(["📝 카드 보기", "📊 테이블 보기"])

            with tab_card:
                # 카드 형태로 댓글 표시
                for idx, row in filtered_df.iterrows():
                    likes_badge = f"👍 {row['좋아요 수']}" if row['좋아요 수'] > 0 else ""
                    st.markdown(f"""
                    <div class="comment-box">
                        <div class="comment-author">{row['작성자']} {likes_badge}</div>
                        <div class="comment-text">{row['댓글 내용']}</div>
                        <div class="comment-meta">📅 {row['작성일']}</div>
                    </div>
                    """, unsafe_allow_html=True)

                    if idx >= 99:
                        st.info("카드 보기는 최대 100개까지 표시됩니다. 전체 데이터는 테이블 보기를 이용하세요.")
                        break

            with tab_table:
                st.dataframe(
                    filtered_df,
                    use_container_width=True,
                    height=500
                )

            # ── CSV 다운로드 ──
            st.markdown("---")
            csv_data = filtered_df.to_csv(index=False, encoding="utf-8-sig")

            st.download_button(
                label="📥 CSV 파일로 다운로드",
                data=csv_data,
                file_name=f"youtube_comments_{video_id}.csv",
                mime="text/csv",
                use_container_width=True
            )

        elif not comments:
            st.info("😅 수집된 댓글이 없습니다.")

elif search_clicked and not url:
    st.warning("⚠️ 유튜브 링크를 입력해주세요!")

# ── 사이드바 안내 ──
with st.sidebar:
    st.markdown("## 📖 사용 안내")
    st.markdown("""
    1. 유튜브 영상 URL을 입력합니다.
    2. 최대 수집할 댓글 수를 선택합니다.
    3. **댓글 수집 시작** 버튼을 클릭합니다.
    4. 키워드 검색 및 정렬이 가능합니다.
    5. CSV 파일로 다운로드할 수 있습니다.
    """)

    st.markdown("---")
    st.markdown("## 🔗 지원하는 URL 형식")
    st.code("https://www.youtube.com/watch?v=...", language=None)
    st.code("https://youtu.be/...", language=None)
    st.code("https://www.youtube.com/shorts/...", language=None)

    st.markdown("---")
    st.markdown("## ⚠️ 주의사항")
    st.markdown("""
    - YouTube Data API v3 일일 할당량이 있습니다 (10,000 units/일).
    - 댓글이 비활성화된 영상은 수집이 불가합니다.
    - 대댓글(답글)은 수집하지 않습니다.
    """)

    st.markdown("---")
    st.markdown(
        "<div style='text-align:center; color:#999; font-size:0.85rem;'>"
        "당곡고등학교 학습용 프로젝트"
        "</div>",
        unsafe_allow_html=True
    )
