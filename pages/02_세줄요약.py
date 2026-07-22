# ============================================================
# 유튜브 댓글 AI 앱 1단계
#
# 주요 기능
# 1. 유튜브 영상 링크에서 영상 ID 추출
# 2. YouTube Data API로 댓글 최대 100개 수집
# 3. 댓글을 좋아요 수가 많은 순서로 정렬
# 4. 댓글과 분석 결과를 Streamlit 세션에 저장
# 5. Solar API로 전체 댓글을 한국어 세 줄 요약
# ============================================================

import re
from urllib.parse import parse_qs, urlparse

import pandas as pd
import requests
import streamlit as st
from openai import OpenAI


# ------------------------------------------------------------
# 1. Streamlit 페이지 기본 설정
# ------------------------------------------------------------
st.set_page_config(
    page_title="유튜브 댓글 AI 분석",
    page_icon="🤖",
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

        .summary-box {
            background-color: white;
            border: 1px solid #ead7c3;
            border-radius: 16px;
            padding: 22px;
            line-height: 1.8;
            font-size: 1.05rem;
            box-shadow: 0 4px 12px rgba(70, 45, 30, 0.06);
        }
    </style>
    """,
    unsafe_allow_html=True,
)


# ------------------------------------------------------------
# 4. 세션에 사용할 값 초기화
# ------------------------------------------------------------
# Streamlit은 버튼을 누를 때마다 코드를 처음부터 다시 실행합니다.
# 따라서 댓글과 AI 요약 결과를 session_state에 저장해야
# 다음 버튼을 눌러도 결과가 유지됩니다.
if "youtube_url" not in st.session_state:
    st.session_state["youtube_url"] = EXAMPLE_1_URL

if "comments_df" not in st.session_state:
    st.session_state["comments_df"] = None

if "video_id" not in st.session_state:
    st.session_state["video_id"] = None

if "ai_summary" not in st.session_state:
    st.session_state["ai_summary"] = None


# ------------------------------------------------------------
# 5. 예시 버튼을 눌렀을 때 링크 변경
# ------------------------------------------------------------
def set_example_url(example_url):
    """
    예시 버튼을 누르면 입력창에 해당 주소를 넣습니다.

    다른 영상의 주소를 선택했으므로,
    기존 댓글과 AI 요약 결과는 함께 초기화합니다.
    """

    st.session_state["youtube_url"] = example_url
    st.session_state["comments_df"] = None
    st.session_state["video_id"] = None
    st.session_state["ai_summary"] = None


# ------------------------------------------------------------
# 6. 유튜브 링크에서 영상 ID 추출
# ------------------------------------------------------------
def extract_video_id(url):
    """
    여러 형식의 유튜브 링크에서 영상 ID를 추출합니다.

    지원하는 링크:
    - https://youtu.be/영상ID
    - https://www.youtube.com/watch?v=영상ID
    - https://m.youtube.com/watch?v=영상ID
    - https://youtube.com/shorts/영상ID
    - https://youtube.com/embed/영상ID

    si, t 등의 추가 주소 값은 무시합니다.
    """

    if not url:
        return None

    url = url.strip()

    # http 또는 https가 생략된 주소에도 대응합니다.
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        parsed_url = urlparse(url)
    except ValueError:
        return None

    hostname = (parsed_url.hostname or "").lower()

    # www.youtube.com을 youtube.com으로 통일합니다.
    if hostname.startswith("www."):
        hostname = hostname[4:]

    video_id = None

    # --------------------------------------------------------
    # youtu.be 짧은 주소
    # 예: https://youtu.be/d95J8yzvjbQ?si=...
    # --------------------------------------------------------
    if hostname == "youtu.be":
        path_parts = [
            part
            for part in parsed_url.path.split("/")
            if part
        ]

        if path_parts:
            video_id = path_parts[0]

    # --------------------------------------------------------
    # youtube.com 계열 주소
    # --------------------------------------------------------
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
        # 예: youtube.com/watch?v=영상ID
        if parsed_url.path.rstrip("/") == "/watch":
            query_values = parse_qs(parsed_url.query)
            video_id = query_values.get("v", [None])[0]

        # Shorts 주소
        # 예: youtube.com/shorts/영상ID
        elif len(path_parts) >= 2 and path_parts[0] == "shorts":
            video_id = path_parts[1]

        # 임베드 주소
        # 예: youtube.com/embed/영상ID
        elif len(path_parts) >= 2 and path_parts[0] == "embed":
            video_id = path_parts[1]

        # 이전 형식 주소
        # 예: youtube.com/v/영상ID
        elif len(path_parts) >= 2 and path_parts[0] == "v":
            video_id = path_parts[1]

    if not video_id:
        return None

    # 혹시 영상 ID 뒤에 추가 값이 남아 있다면 제거합니다.
    video_id = (
        video_id
        .split("?")[0]
        .split("&")[0]
        .split("#")[0]
        .strip()
    )

    # 일반적인 유튜브 영상 ID는 영문자, 숫자, -, _로 구성됩니다.
    if not re.fullmatch(r"[A-Za-z0-9_-]{6,}", video_id):
        return None

    return video_id


# ------------------------------------------------------------
# 7. YouTube API 오류를 한국어로 바꾸기
# ------------------------------------------------------------
def make_youtube_error_message(response_data, status_code):
    """
    YouTube API의 오류 사유를 확인하여
    이해하기 쉬운 한국어 안내 메시지를 반환합니다.
    """

    default_message = (
        "유튜브 댓글을 가져오지 못했습니다. "
        "영상 링크와 API 설정을 확인한 뒤 다시 시도해 주세요."
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

    if reason == "commentsDisabled":
        return (
            "이 영상은 댓글 기능이 꺼져 있어 "
            "댓글을 가져올 수 없습니다."
        )

    if reason in {
        "videoNotFound",
        "notFound",
    } or status_code == 404:
        return (
            "영상을 찾을 수 없습니다. "
            "영상이 삭제되었거나 비공개 상태인지 확인해 주세요."
        )

    if reason in {
        "quotaExceeded",
        "dailyLimitExceeded",
        "rateLimitExceeded",
    }:
        return (
            "YouTube Data API의 사용 한도를 초과했습니다. "
            "잠시 후 또는 다음 날 다시 시도해 주세요."
        )

    if reason in {
        "keyInvalid",
        "forbidden",
        "accessNotConfigured",
        "ipRefererBlocked",
    } or status_code in {401, 403}:
        return (
            "YouTube API 인증에 실패했습니다. "
            "Streamlit Secrets의 YOUTUBE_API_KEY와 "
            "Google Cloud의 YouTube Data API v3 사용 설정을 "
            "확인해 주세요."
        )

    if api_message:
        return (
            "유튜브 댓글을 가져오지 못했습니다.\n\n"
            f"YouTube API 안내: {api_message}"
        )

    return default_message


# ------------------------------------------------------------
# 8. YouTube Data API에서 댓글 가져오기
# ------------------------------------------------------------
@st.cache_data(ttl=600, show_spinner=False)
def get_youtube_comments(api_key, video_id):
    """
    YouTube Data API v3의 commentThreads 창구에서
    최상위 댓글을 최대 100개 가져옵니다.

    order=relevance로 요청한 뒤,
    받은 댓글은 좋아요 수를 기준으로 다시 정렬합니다.
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
            "댓글을 요청하는 중 문제가 발생했습니다.\n\n"
            f"오류 내용: {error}"
        )

    try:
        response_data = response.json()

    except ValueError:
        return None, (
            "유튜브 서버의 응답을 읽지 못했습니다. "
            "잠시 후 다시 시도해 주세요."
        )

    if not response.ok:
        return None, make_youtube_error_message(
            response_data=response_data,
            status_code=response.status_code,
        )

    items = response_data.get("items", [])

    if not items:
        return None, (
            "가져올 수 있는 댓글이 없습니다. "
            "댓글이 없거나 댓글 기능이 제한된 영상일 수 있습니다."
        )

    comments = []

    for item in items:
        try:
            top_comment_snippet = (
                item["snippet"]
                ["topLevelComment"]
                ["snippet"]
            )

            # 댓글 작성자가 입력한 원문을 가져옵니다.
            comment_text = top_comment_snippet.get(
                "textOriginal",
                "",
            )

            # 좋아요 수를 가져옵니다.
            like_count = top_comment_snippet.get(
                "likeCount",
                0,
            )

            # 좋아요 수는 숫자로 변환해야 정확하게 정렬할 수 있습니다.
            try:
                like_count = int(like_count)

            except (TypeError, ValueError):
                like_count = 0

            # 빈 댓글은 제외합니다.
            comment_text = str(comment_text).strip()

            if not comment_text:
                continue

            comments.append(
                {
                    "댓글": comment_text,
                    "좋아요 수": like_count,
                }
            )

        except (KeyError, TypeError):
            # 일부 항목의 구조가 다르면 해당 댓글만 건너뜁니다.
            continue

    if not comments:
        return None, (
            "댓글 응답은 받았지만 화면에 표시할 수 있는 "
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
# 9. 댓글을 AI에 전달할 텍스트로 만들기
# ------------------------------------------------------------
def make_comments_text(comments_df):
    """
    데이터프레임의 댓글 전체를
    Solar API에 전달하기 좋은 문자열로 만듭니다.

    댓글마다 번호와 좋아요 수를 함께 넣어
    반응의 중요도를 AI가 참고할 수 있게 합니다.
    """

    comment_lines = []

    for _, row in comments_df.iterrows():
        comment_number = int(row["순번"])
        like_count = int(row["좋아요 수"])
        comment_text = str(row["댓글"]).strip()

        comment_lines.append(
            f"{comment_number}. "
            f"[좋아요 {like_count}개] "
            f"{comment_text}"
        )

    return "\n".join(comment_lines)


# ------------------------------------------------------------
# 10. Solar API로 AI 세 줄 요약
# ------------------------------------------------------------
def summarize_comments_with_solar(api_key, comments_df):
    """
    Upstage Solar API를 OpenAI Python 라이브러리로 호출합니다.

    모델:
    solar-open2

    접속 주소:
    https://api.upstage.ai/v1

    reasoning_effort='none'으로 추론 기능을 끕니다.
    """

    comments_text = make_comments_text(comments_df)

    # Upstage API는 OpenAI 호환 방식으로 접속합니다.
    client = OpenAI(
        api_key=api_key,
        base_url="https://api.upstage.ai/v1",
        timeout=60.0,
        max_retries=2,
    )

    system_prompt = """
당신은 유튜브 댓글 분석 전문가입니다.
사용자가 제공한 댓글 전체의 공통된 반응을 분석하세요.

반드시 다음 규칙을 지키세요.

1. 결과는 한국어로 정확히 세 줄만 작성합니다.
2. 첫째 줄은 시청자들이 주로 좋게 평가한 내용을 요약합니다.
3. 둘째 줄은 비판, 아쉬움, 논쟁 또는 반복적으로 언급된 반응을 요약합니다.
4. 셋째 줄은 전체 댓글의 정서를 바탕으로 긍정과 부정의 대략적인 비율을 추정합니다.
5. 셋째 줄의 형식은 반드시 다음과 비슷하게 작성합니다.
   긍정 약 75% · 부정 약 25%
6. 긍정과 부정의 합은 100%가 되어야 합니다.
7. 댓글에 없는 사실을 만들어내지 마세요.
8. 각 줄 앞에 번호나 글머리표를 붙이지 마세요.
9. 세 줄 외의 제목, 설명, 인사말을 추가하지 마세요.
""".strip()

    user_prompt = f"""
아래는 한 유튜브 영상에서 가져온 댓글입니다.
좋아요 수가 많은 댓글일수록 시청자 반응을 더 잘 대표할 수 있으니 참고하세요.

전체 반응을 한국어 세 줄로 요약해 주세요.

[댓글 시작]
{comments_text}
[댓글 끝]
""".strip()

    try:
        response = client.chat.completions.create(
            model="solar-open2",
            reasoning_effort="none",
            messages=[
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {
                    "role": "user",
                    "content": user_prompt,
                },
            ],
        )

        summary_text = response.choices[0].message.content

        if not summary_text:
            return None, (
                "Solar API의 응답은 받았지만 "
                "요약 내용이 비어 있습니다."
            )

        summary_text = summary_text.strip()

        return summary_text, None

    except Exception as error:
        error_text = str(error)

        # 사용자에게 API 키가 직접 노출되지 않도록
        # 오류 문자열은 지나치게 길지 않게 제한합니다.
        if len(error_text) > 500:
            error_text = error_text[:500] + "..."

        return None, (
            "AI 요약을 만드는 중 문제가 발생했습니다.\n\n"
            "SOLAR_API_KEY, Solar API 사용 권한과 "
            "네트워크 상태를 확인해 주세요.\n\n"
            f"오류 내용: {error_text}"
        )


# ------------------------------------------------------------
# 11. 제목
# ------------------------------------------------------------
st.markdown(
    '<div class="main-title">🤖 유튜브 댓글 AI 분석</div>',
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="sub-title">
        유튜브 인기 댓글을 최대 100개 가져오고,
        Solar AI로 전체 반응을 세 줄로 요약합니다.
    </div>
    """,
    unsafe_allow_html=True,
)


# ------------------------------------------------------------
# 12. 예시 버튼 두 개
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
# 13. 유튜브 링크 입력창
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
# 14. 댓글 가져오기 버튼
# ------------------------------------------------------------
get_comments_button = st.button(
    "💬 댓글 가져오기",
    type="primary",
    use_container_width=True,
)


# ------------------------------------------------------------
# 15. 댓글 가져오기 실행
# ------------------------------------------------------------
if get_comments_button:
    video_id = extract_video_id(youtube_url)

    if video_id is None:
        st.session_state["comments_df"] = None
        st.session_state["video_id"] = None
        st.session_state["ai_summary"] = None

        st.error(
            "올바른 유튜브 영상 링크를 입력해 주세요.\n\n"
            "예: https://youtu.be/d95J8yzvjbQ 또는 "
            "https://www.youtube.com/watch?v=d95J8yzvjbQ"
        )

    else:
        # ----------------------------------------------------
        # Streamlit Secrets에서 YouTube API 키 읽기
        # ----------------------------------------------------
        try:
            youtube_api_key = str(
                st.secrets["YOUTUBE_API_KEY"]
            ).strip()

        except KeyError:
            st.error(
                "YouTube API 키를 찾지 못했습니다. "
                "Streamlit Cloud의 Settings → Secrets에 "
                "YOUTUBE_API_KEY를 등록해 주세요."
            )

            st.code(
                'YOUTUBE_API_KEY = "발급받은_유튜브_API_키"',
                language="toml",
            )

            st.stop()

        except Exception as error:
            st.error(
                "Streamlit Secrets를 읽는 중 문제가 발생했습니다.\n\n"
                f"오류 내용: {error}"
            )

            st.stop()

        if not youtube_api_key:
            st.error(
                "Streamlit Secrets의 YOUTUBE_API_KEY 값이 "
                "비어 있습니다."
            )

            st.stop()

        with st.spinner(
            "유튜브에서 댓글을 가져오고 있습니다..."
        ):
            comments_df, error_message = get_youtube_comments(
                api_key=youtube_api_key,
                video_id=video_id,
            )

        if error_message:
            st.session_state["comments_df"] = None
            st.session_state["video_id"] = None
            st.session_state["ai_summary"] = None

            st.error(error_message)

        else:
            # 댓글과 영상 ID를 세션에 저장합니다.
            st.session_state["comments_df"] = comments_df
            st.session_state["video_id"] = video_id

            # 새 댓글을 불러왔으므로 이전 영상의 AI 요약은 지웁니다.
            st.session_state["ai_summary"] = None

            st.success(
                f"댓글 {len(comments_df):,}개를 가져왔습니다."
            )


# ------------------------------------------------------------
# 16. 세션에 저장된 댓글 결과 표시
# ------------------------------------------------------------
comments_df = st.session_state.get("comments_df")

if comments_df is not None and not comments_df.empty:
    st.divider()

    st.subheader("📊 댓글 수집 결과")

    metric_col1, metric_col2 = st.columns(2)

    with metric_col1:
        st.metric(
            label="가져온 댓글 수",
            value=f"{len(comments_df):,}개",
        )

    with metric_col2:
        most_liked_count = int(
            comments_df.iloc[0]["좋아요 수"]
        )

        st.metric(
            label="가장 많은 좋아요",
            value=f"{most_liked_count:,}개",
        )

    st.caption(
        f"영상 ID: `{st.session_state['video_id']}`"
    )

    # --------------------------------------------------------
    # AI 세 줄 요약 버튼
    # --------------------------------------------------------
    st.divider()
    st.subheader("✨ Solar AI 댓글 요약")

    ai_summary_button = st.button(
        "🤖 AI 세 줄 요약",
        type="secondary",
        use_container_width=True,
    )

    if ai_summary_button:
        # ----------------------------------------------------
        # Streamlit Secrets에서 Solar API 키 읽기
        # ----------------------------------------------------
        try:
            solar_api_key = str(
                st.secrets["SOLAR_API_KEY"]
            ).strip()

        except KeyError:
            st.error(
                "Solar API 키를 찾지 못했습니다. "
                "Streamlit Cloud의 Settings → Secrets에 "
                "SOLAR_API_KEY를 등록해 주세요."
            )

            st.code(
                'SOLAR_API_KEY = "발급받은_Solar_API_키"',
                language="toml",
            )

            st.stop()

        except Exception as error:
            st.error(
                "Streamlit Secrets를 읽는 중 문제가 발생했습니다.\n\n"
                f"오류 내용: {error}"
            )

            st.stop()

        if not solar_api_key:
            st.error(
                "Streamlit Secrets의 SOLAR_API_KEY 값이 "
                "비어 있습니다."
            )

            st.stop()

        with st.spinner(
            "Solar AI가 댓글 전체의 반응을 분석하고 있습니다..."
        ):
            summary_text, summary_error = (
                summarize_comments_with_solar(
                    api_key=solar_api_key,
                    comments_df=comments_df,
                )
            )

        if summary_error:
            st.error(summary_error)

        else:
            # 요약 결과도 세션에 저장합니다.
            st.session_state["ai_summary"] = summary_text

    # 세션에 저장된 AI 요약이 있다면 계속 표시합니다.
    if st.session_state.get("ai_summary"):
        summary_html = (
            st.session_state["ai_summary"]
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("\n", "<br>")
        )

        st.markdown(
            f"""
            <div class="summary-box">
                {summary_html}
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.caption(
            "AI가 댓글 전체의 표현을 바탕으로 추정한 요약과 "
            "감정 비율이며, 실제 여론조사 결과는 아닙니다."
        )

    # --------------------------------------------------------
    # 댓글 목록
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
        "YouTube Data API에서 order=relevance로 최대 100개를 "
        "요청한 뒤, 좋아요 수가 많은 순서로 다시 정렬했습니다."
    )
