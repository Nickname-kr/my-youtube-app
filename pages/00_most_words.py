# ============================================================
# 유튜브 댓글 분석 앱 2단계
#
# 1. 유튜브 영상 링크에서 댓글을 최대 100개 가져오기
# 2. 좋아요가 많은 순서로 댓글 정렬하기
# 3. 댓글에서 자주 나온 단어 상위 20개 분석하기
# ============================================================

import re
from collections import Counter
from urllib.parse import parse_qs, urlparse

import pandas as pd
import plotly.express as px
import requests
import streamlit as st


# ------------------------------------------------------------
# 1. Streamlit 페이지 기본 설정
# ------------------------------------------------------------
st.set_page_config(
    page_title="유튜브 댓글 분석",
    page_icon="💬",
    layout="wide",
)


# ------------------------------------------------------------
# 2. 예시 영상 주소
# ------------------------------------------------------------
EXAMPLE_1_URL = (
    "https://youtu.be/d95J8yzvjbQ?si=LfL5DLwCL8Pk077r"
)

EXAMPLE_2_URL = (
    "https://youtu.be/I9vK5EVTt0U?si=NEZ8L7MRuNvrzINa"
)


# ------------------------------------------------------------
# 3. 화면 디자인
# ------------------------------------------------------------
st.markdown(
    """
    <style>
        .stApp {
            background-color: #fffaf2;
        }

        .main-title {
            font-size: 2.5rem;
            font-weight: 800;
            color: #3f2d25;
            margin-bottom: 0.3rem;
        }

        .sub-title {
            font-size: 1.05rem;
            color: #766158;
            margin-bottom: 1.5rem;
        }

        div[data-testid="stMetric"] {
            background-color: white;
            border: 1px solid #f0dfcc;
            border-radius: 16px;
            padding: 20px;
            box-shadow: 0 4px 12px rgba(70, 45, 30, 0.08);
        }

        div.stButton > button {
            border-radius: 10px;
        }
    </style>
    """,
    unsafe_allow_html=True,
)


# ------------------------------------------------------------
# 4. 링크에서 유튜브 영상 ID 추출
# ------------------------------------------------------------
def extract_video_id(url):
    """
    여러 형식의 유튜브 링크에서 영상 ID를 추출합니다.

    처리할 수 있는 주소 예시:
    - https://youtu.be/영상ID
    - https://www.youtube.com/watch?v=영상ID
    - https://youtube.com/shorts/영상ID
    - https://youtube.com/embed/영상ID

    링크 뒤에 붙는 si, t 등의 값은 무시합니다.
    """

    if not url:
        return None

    # 입력값 앞뒤의 공백을 제거합니다.
    url = url.strip()

    # http 또는 https가 생략된 경우 자동으로 붙입니다.
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        parsed_url = urlparse(url)
    except ValueError:
        return None

    hostname = parsed_url.hostname or ""

    # www.youtube.com과 youtube.com을 똑같이 처리합니다.
    hostname = hostname.lower().replace("www.", "")

    video_id = None

    # youtu.be 짧은 주소
    if hostname == "youtu.be":
        video_id = parsed_url.path.strip("/").split("/")[0]

    # youtube.com 계열 주소
    elif hostname in {
        "youtube.com",
        "m.youtube.com",
        "music.youtube.com",
    }:
        path_parts = [
            part
            for part in parsed_url.path.split("/")
            if part
        ]

        # 일반 영상 주소
        # youtube.com/watch?v=영상ID
        if parsed_url.path == "/watch":
            query_values = parse_qs(parsed_url.query)
            video_id = query_values.get("v", [None])[0]

        # Shorts 주소
        # youtube.com/shorts/영상ID
        elif (
            len(path_parts) >= 2
            and path_parts[0] == "shorts"
        ):
            video_id = path_parts[1]

        # 임베드 주소
        # youtube.com/embed/영상ID
        elif (
            len(path_parts) >= 2
            and path_parts[0] == "embed"
        ):
            video_id = path_parts[1]

        # 이전 형식 주소
        # youtube.com/v/영상ID
        elif (
            len(path_parts) >= 2
            and path_parts[0] == "v"
        ):
            video_id = path_parts[1]

    if not video_id:
        return None

    # 영상 ID 뒤에 불필요한 값이 붙은 경우 제거합니다.
    video_id = (
        video_id
        .split("?")[0]
        .split("&")[0]
        .split("#")[0]
        .strip()
    )

    # 일반적인 유튜브 영상 ID는 11자리입니다.
    # 너무 짧거나 형식에 맞지 않는 값은 잘못된 링크로 처리합니다.
    if not re.fullmatch(r"[A-Za-z0-9_-]{6,}", video_id):
        return None

    return video_id


# ------------------------------------------------------------
# 5. YouTube API 오류를 한국어 안내로 바꾸기
# ------------------------------------------------------------
def make_friendly_error_message(response_data, status_code):
    """
    YouTube API가 반환한 오류 내용을 확인하여
    이해하기 쉬운 한국어 메시지로 바꿉니다.
    """

    default_message = (
        "유튜브 댓글을 가져오지 못했습니다. "
        "영상 링크와 API 키를 확인한 뒤 다시 시도해 주세요."
    )

    try:
        error_info = response_data.get("error", {})
        api_message = error_info.get("message", "")

        errors = error_info.get("errors", [])

        reason = (
            errors[0].get("reason", "")
            if errors
            else ""
        )

    except (AttributeError, IndexError, TypeError):
        return default_message

    # 댓글 기능이 꺼진 영상
    if reason == "commentsDisabled":
        return (
            "이 영상은 댓글 기능이 꺼져 있어 "
            "댓글을 가져올 수 없습니다."
        )

    # 영상이 없거나 비공개인 경우
    if reason in {
        "videoNotFound",
        "notFound",
    } or status_code == 404:
        return (
            "영상을 찾을 수 없습니다. "
            "영상이 삭제되었거나 비공개인지 확인해 주세요."
        )

    # API 사용 한도를 초과한 경우
    if reason in {
        "quotaExceeded",
        "dailyLimitExceeded",
        "rateLimitExceeded",
    }:
        return (
            "YouTube API의 사용 한도를 초과했습니다. "
            "잠시 후 또는 다음 날 다시 시도해 주세요."
        )

    # API 키 또는 권한 문제
    if reason in {
        "keyInvalid",
        "forbidden",
        "accessNotConfigured",
        "ipRefererBlocked",
    } or status_code in {401, 403}:
        return (
            "YouTube API 인증에 실패했습니다. "
            "Streamlit Secrets의 YOUTUBE_API_KEY와 "
            "YouTube Data API v3 사용 설정을 확인해 주세요."
        )

    if api_message:
        return (
            "유튜브 댓글을 가져오지 못했습니다.\n\n"
            f"API 안내: {api_message}"
        )

    return default_message


# ------------------------------------------------------------
# 6. YouTube Data API에서 댓글 가져오기
# ------------------------------------------------------------
@st.cache_data(ttl=600, show_spinner=False)
def get_youtube_comments(api_key, video_id):
    """
    YouTube Data API v3의 commentThreads를 사용하여
    최상위 댓글을 최대 100개 가져옵니다.

    order=relevance를 사용하여 관련성과 인기도가 높은
    댓글을 우선적으로 요청합니다.
    """

    api_url = (
        "https://www.googleapis.com/youtube/v3/"
        "commentThreads"
    )

    params = {
        "part": "snippet",
        "videoId": video_id,
        "maxResults": 100,
        "order": "relevance",
        "textFormat": "plainText",
        "key": api_key,
    }

    try:
        response = requests.get(
            api_url,
            params=params,
            timeout=(10, 30),
        )

    except requests.exceptions.Timeout:
        return None, (
            "유튜브 서버의 응답이 늦어지고 있습니다. "
            "잠시 후 다시 시도해 주세요."
        )

    except requests.exceptions.ConnectionError:
        return None, (
            "유튜브 서버에 연결하지 못했습니다. "
            "인터넷 연결 상태를 확인해 주세요."
        )

    except requests.exceptions.RequestException as error:
        return None, (
            "댓글 요청 중 문제가 발생했습니다.\n\n"
            f"오류 내용: {error}"
        )

    # JSON 응답을 읽습니다.
    try:
        response_data = response.json()

    except ValueError:
        return None, (
            "유튜브 서버의 응답을 읽지 못했습니다. "
            "잠시 후 다시 시도해 주세요."
        )

    # HTTP 요청이 정상적으로 처리되지 않은 경우
    if not response.ok:
        error_message = make_friendly_error_message(
            response_data=response_data,
            status_code=response.status_code,
        )

        return None, error_message

    # 응답에서 댓글 목록을 가져옵니다.
    items = response_data.get("items", [])

    if not items:
        return None, (
            "가져올 수 있는 댓글이 없습니다. "
            "댓글이 없거나 댓글 기능이 제한된 영상일 수 있습니다."
        )

    comments = []

    for item in items:
        try:
            # 댓글 묶음에서 최상위 댓글의 snippet을 가져옵니다.
            top_comment = (
                item["snippet"]
                ["topLevelComment"]
                ["snippet"]
            )

            # 화면에 표시된 가공 텍스트가 아니라
            # 댓글 작성자가 입력한 원문을 사용합니다.
            comment_text = top_comment.get(
                "textOriginal",
                "",
            )

            like_count = top_comment.get(
                "likeCount",
                0,
            )

            # 좋아요 수를 정렬할 수 있도록 숫자로 바꿉니다.
            try:
                like_count = int(like_count)

            except (TypeError, ValueError):
                like_count = 0

            comments.append(
                {
                    "댓글": comment_text,
                    "좋아요 수": like_count,
                }
            )

        except (KeyError, TypeError):
            # 일부 댓글의 응답 구조가 다르면
            # 해당 댓글만 건너뜁니다.
            continue

    if not comments:
        return None, (
            "댓글 응답은 받았지만 표시할 수 있는 "
            "댓글을 찾지 못했습니다."
        )

    comments_df = pd.DataFrame(comments)

    # 좋아요가 많은 댓글부터 정렬합니다.
    comments_df = (
        comments_df
        .sort_values(
            by="좋아요 수",
            ascending=False,
        )
        .reset_index(drop=True)
    )

    # 보기 편하도록 순번을 추가합니다.
    comments_df.insert(
        0,
        "순번",
        range(1, len(comments_df) + 1),
    )

    return comments_df, None


# ------------------------------------------------------------
# 7. 댓글에서 자주 나온 단어 분석
# ------------------------------------------------------------
def count_frequent_words(comments_df, top_n=20):
    """
    댓글 전체를 단어로 나눈 뒤 자주 나온 단어를 셉니다.

    분석 방법:
    - 한국어, 영어, 숫자로 이루어진 단어를 찾습니다.
    - 영어는 대문자와 소문자를 같은 단어로 처리합니다.
    - 한 글자짜리 단어는 제외합니다.
    - URL은 단어 분석 전에 제거합니다.
    """

    # 댓글 전체를 하나의 긴 문자열로 합칩니다.
    all_comments = " ".join(
        comments_df["댓글"]
        .fillna("")
        .astype(str)
        .tolist()
    )

    # 댓글에 들어 있는 인터넷 주소를 제거합니다.
    all_comments = re.sub(
        r"https?://\S+|www\.\S+",
        " ",
        all_comments,
    )

    # 영어 대문자와 소문자를 같은 단어로 세기 위해
    # 전체 문자열을 소문자로 바꿉니다.
    all_comments = all_comments.lower()

    # 한국어, 영어, 숫자로 이루어진 단어를 찾습니다.
    words = re.findall(
        r"[가-힣a-z0-9]+",
        all_comments,
    )

    # 한 글자짜리 단어를 제외합니다.
    words = [
        word
        for word in words
        if len(word) > 1
    ]

    # Counter를 사용하여 각 단어가 나온 횟수를 셉니다.
    word_counts = Counter(words)

    # 가장 자주 나온 단어를 top_n개 선택합니다.
    most_common_words = word_counts.most_common(top_n)

    if not most_common_words:
        return pd.DataFrame(
            columns=["단어", "빈도"]
        )

    word_df = pd.DataFrame(
        most_common_words,
        columns=["단어", "빈도"],
    )

    return word_df


# ------------------------------------------------------------
# 8. 예시 버튼을 눌렀을 때 주소 바꾸기
# ------------------------------------------------------------
def set_example_url(example_url):
    """
    예시 버튼을 누르면 입력창에 해당 영상 주소를 넣습니다.
    """

    st.session_state["youtube_url"] = example_url


# ------------------------------------------------------------
# 9. 제목
# ------------------------------------------------------------
st.markdown(
    '<div class="main-title">💬 유튜브 댓글 분석</div>',
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="sub-title">
        유튜브 인기 댓글을 가져오고,
        댓글에서 자주 나온 단어를 분석합니다.
    </div>
    """,
    unsafe_allow_html=True,
)


# ------------------------------------------------------------
# 10. 입력창 최초 기본값 설정
# ------------------------------------------------------------
if "youtube_url" not in st.session_state:
    st.session_state["youtube_url"] = EXAMPLE_1_URL


# ------------------------------------------------------------
# 11. 예시 영상 버튼
# ------------------------------------------------------------
st.markdown("#### 예시 영상 선택")

example_col1, example_col2 = st.columns(2)

with example_col1:
    st.button(
        "예시 1 · 딥마인드 다큐(영어 댓글)",
        use_container_width=True,
        on_click=set_example_url,
        args=(EXAMPLE_1_URL,),
    )

with example_col2:
    st.button(
        "예시 2 · 2002 월드컵 추억(한국어 댓글)",
        use_container_width=True,
        on_click=set_example_url,
        args=(EXAMPLE_2_URL,),
    )


# ------------------------------------------------------------
# 12. 유튜브 링크 입력창
# ------------------------------------------------------------
youtube_url = st.text_input(
    "유튜브 영상 링크",
    key="youtube_url",
    placeholder="https://www.youtube.com/watch?v=영상ID",
    help=(
        "youtu.be 짧은 주소와 youtube.com/watch 주소를 "
        "모두 사용할 수 있습니다."
    ),
)


# ------------------------------------------------------------
# 13. 댓글 분석 버튼
# ------------------------------------------------------------
analyze_button = st.button(
    "🔍 댓글 가져오기 및 분석하기",
    type="primary",
    use_container_width=True,
)


# ------------------------------------------------------------
# 14. 버튼을 눌렀을 때 분석 실행
# ------------------------------------------------------------
if analyze_button:

    # 입력한 링크에서 영상 ID를 추출합니다.
    video_id = extract_video_id(youtube_url)

    if video_id is None:
        st.error(
            "올바른 유튜브 영상 링크를 입력해 주세요.\n\n"
            "예: https://youtu.be/d95J8yzvjbQ 또는 "
            "https://www.youtube.com/watch?v=d95J8yzvjbQ"
        )
        st.stop()

    # --------------------------------------------------------
    # Streamlit Secrets에서 API 키 가져오기
    # --------------------------------------------------------
    try:
        youtube_api_key = st.secrets["YOUTUBE_API_KEY"]

    except KeyError:
        st.error(
            "YouTube API 키를 찾지 못했습니다. "
            "Streamlit Cloud의 Settings → Secrets에 "
            "YOUTUBE_API_KEY를 등록해 주세요."
        )

        st.code(
            'YOUTUBE_API_KEY = "발급받은_API_키"',
            language="toml",
        )

        st.stop()

    except Exception as error:
        st.error(
            "Streamlit Secrets를 읽는 중 문제가 발생했습니다.\n\n"
            f"오류 내용: {error}"
        )
        st.stop()

    # API 키가 빈 값인지 확인합니다.
    youtube_api_key = str(youtube_api_key).strip()

    if not youtube_api_key:
        st.error(
            "Streamlit Secrets의 YOUTUBE_API_KEY 값이 비어 있습니다."
        )
        st.stop()

    st.caption(f"추출한 영상 ID: `{video_id}`")

    # --------------------------------------------------------
    # YouTube API에서 댓글 가져오기
    # --------------------------------------------------------
    with st.spinner(
        "유튜브에서 댓글을 가져오고 분석하고 있습니다..."
    ):
        comments_df, error_message = get_youtube_comments(
            api_key=youtube_api_key,
            video_id=video_id,
        )

    if error_message:
        st.error(error_message)
        st.stop()

    # 댓글에서 자주 나온 단어 상위 20개를 분석합니다.
    word_df = count_frequent_words(
        comments_df=comments_df,
        top_n=20,
    )

    # --------------------------------------------------------
    # 댓글 수집 결과
    # --------------------------------------------------------
    st.divider()
    st.subheader("📊 댓글 수집 결과")

    metric_col1, metric_col2 = st.columns(2)

    with metric_col1:
        st.metric(
            label="가져온 댓글 수",
            value=f"{len(comments_df):,}개",
        )

    with metric_col2:
        most_liked_comment = comments_df.iloc[0]

        st.metric(
            label="가장 많은 좋아요",
            value=f"{most_liked_comment['좋아요 수']:,}개",
        )

    # --------------------------------------------------------
    # 자주 나온 단어 상위 20개 그래프
    # --------------------------------------------------------
    st.divider()
    st.subheader("🔤 자주 나온 단어 상위 20개")

    if word_df.empty:
        st.info(
            "댓글에서 분석할 수 있는 단어를 찾지 못했습니다."
        )

    else:
        # 가로 막대그래프에서는 작은 값부터 큰 값 순서로
        # 데이터프레임을 정렬하면 큰 값이 위에 표시됩니다.
        chart_df = (
            word_df
            .sort_values(
                by="빈도",
                ascending=True,
            )
            .copy()
        )

        word_chart = px.bar(
            chart_df,
            x="빈도",
            y="단어",
            orientation="h",
            text="빈도",
            labels={
                "단어": "단어",
                "빈도": "등장 횟수",
            },
        )

        word_chart.update_traces(
            texttemplate="%{text:,}회",
            textposition="outside",
            cliponaxis=False,
            hovertemplate=(
                "<b>%{y}</b><br>"
                "등장 횟수: %{x:,}회"
                "<extra></extra>"
            ),
        )

        word_chart.update_layout(
            height=650,
            margin=dict(
                l=20,
                r=80,
                t=20,
                b=20,
            ),
            xaxis_title="등장 횟수",
            yaxis_title="",
            showlegend=False,
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
        )

        word_chart.update_xaxes(
            dtick=1,
            showgrid=True,
            gridcolor="rgba(120, 100, 80, 0.15)",
        )

        st.plotly_chart(
            word_chart,
            use_container_width=True,
        )

        st.caption(
            "댓글 전체에서 한국어·영어·숫자 단어를 찾았으며, "
            "한 글자짜리 단어는 제외했습니다."
        )

    # --------------------------------------------------------
    # 댓글 목록 표
    # --------------------------------------------------------
    st.divider()
    st.subheader("📝 좋아요가 많은 댓글 순위")

    st.dataframe(
        comments_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "순번": st.column_config.NumberColumn(
                "순번",
                format="%d",
                width="small",
            ),
            "댓글": st.column_config.TextColumn(
                "댓글 원문",
                width="large",
            ),
            "좋아요 수": st.column_config.NumberColumn(
                "좋아요 수",
                format="%,d개",
                width="small",
            ),
        },
    )

    st.caption(
        "YouTube Data API에서 relevance 순서로 최대 100개를 "
        "요청한 뒤 좋아요 수가 많은 순서로 다시 정렬했습니다."
    )
