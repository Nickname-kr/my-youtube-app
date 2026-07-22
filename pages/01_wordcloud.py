# ============================================================
# 유튜브 댓글 분석 앱 3단계
#
# 1. 유튜브 댓글 최대 100개 가져오기
# 2. 형태소 분석 후 자주 나온 단어 상위 20개 표시
# 3. 정제된 단어로 워드클라우드 만들기
# ============================================================

import re
import tempfile
from collections import Counter
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pandas as pd
import plotly.express as px
import requests
import streamlit as st
from kiwipiepy import Kiwi
from wordcloud import WordCloud


# ------------------------------------------------------------
# 1. Streamlit 페이지 기본 설정
# ------------------------------------------------------------
st.set_page_config(
    page_title="유튜브 댓글 분석",
    page_icon="💬",
    layout="wide",
)


# ------------------------------------------------------------
# 2. 예시 영상 주소와 폰트 주소
# ------------------------------------------------------------
EXAMPLE_1_URL = (
    "https://youtu.be/d95J8yzvjbQ?si=LfL5DLwCL8Pk077r"
)

EXAMPLE_2_URL = (
    "https://youtu.be/I9vK5EVTt0U?si=NEZ8L7MRuNvrzINa"
)

FONT_URL = (
    "https://raw.githubusercontent.com/google/fonts/main/"
    "ofl/nanumgothic/NanumGothic-Regular.ttf"
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
# 4. 한국어 형태소 분석기
# ------------------------------------------------------------
# Kiwi는 '축구가', '축구를', '축구는'에서
# 조사 등을 분리하고 핵심 단어인 '축구'를 추출합니다.
kiwi = Kiwi()


# ------------------------------------------------------------
# 5. 분석에서 제외할 한국어 불용어
# ------------------------------------------------------------
KOREAN_STOPWORDS = {
    # 의미가 약한 의존 명사와 일반 표현
    "것", "수", "때", "점", "중", "등", "거", "게",
    "곳", "분", "말", "번", "듯", "쪽", "정도", "부분",
    "경우", "자체", "관련", "모습",

    # 연결 표현
    "그리고", "그러나", "하지만", "그래서", "또한",
    "그런데", "그러면", "따라서",

    # 강조·부사 표현
    "그냥", "정말", "진짜", "너무", "아주", "많이",
    "조금", "완전", "계속", "항상", "아직", "다시",

    # 지시 표현
    "이것", "그것", "저것", "여기", "저기",
    "이런", "그런", "저런",
    "이렇게", "그렇게", "저렇게",

    # 댓글에서 지나치게 흔한 표현
    "영상", "댓글", "유튜브", "사람", "생각", "느낌",
    "지금", "오늘", "어제", "이번", "하나",
    "보다", "하다", "있다", "없다", "되다", "같다",

    # 감탄 및 반복 문자
    "ㅋㅋ", "ㅋㅋㅋ", "ㅎㅎ", "ㅎㅎㅎ",
    "ㅠㅠ", "ㅜㅜ", "와우", "대박", "오오",
}


# ------------------------------------------------------------
# 6. 분석에서 제외할 영어 불용어
# ------------------------------------------------------------
ENGLISH_STOPWORDS = {
    # 관사·접속사
    "the", "a", "an", "and", "or", "but", "so", "because",
    "if", "then", "than", "that", "this", "these", "those",

    # 대명사
    "it", "its", "they", "them", "their",
    "we", "our", "ours",
    "you", "your", "yours",
    "he", "she", "his", "her",
    "i", "me", "my", "mine",

    # 기본 동사와 조동사
    "is", "am", "are", "was", "were",
    "be", "been", "being",
    "do", "does", "did",
    "have", "has", "had",
    "can", "could", "will", "would",
    "should", "may", "might", "must",

    # 전치사
    "to", "of", "in", "on", "at", "for", "from",
    "with", "about", "as", "by", "into", "over",
    "after", "before", "through", "between",

    # 의문사·부사
    "what", "when", "where", "why", "who", "how",
    "not", "no", "yes", "very", "really", "just",
    "more", "most", "much", "many", "some", "any",
    "all", "also", "even", "still", "only",

    # 유튜브 댓글에서 지나치게 흔한 단어
    "video", "youtube", "comment", "comments",
    "like", "likes", "get", "got", "make", "made",
    "know", "think", "one", "people", "thing",
    "things", "see", "watch", "watching",

    # 영어 축약형의 일부
    "ve", "re", "ll", "don", "doesn", "didn",
    "isn", "aren", "wasn", "weren", "won",
    "wouldn", "couldn", "shouldn",
}


# ------------------------------------------------------------
# 7. 유튜브 링크에서 영상 ID 추출
# ------------------------------------------------------------
def extract_video_id(url):
    """
    여러 종류의 유튜브 주소에서 영상 ID를 추출합니다.

    지원하는 예:
    - https://youtu.be/영상ID
    - https://www.youtube.com/watch?v=영상ID
    - https://youtube.com/shorts/영상ID
    - https://youtube.com/embed/영상ID

    si, t와 같이 주소 뒤에 붙는 값은 무시합니다.
    """

    if not url:
        return None

    url = url.strip()

    # http 또는 https가 없다면 자동으로 붙입니다.
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        parsed_url = urlparse(url)
    except ValueError:
        return None

    hostname = (parsed_url.hostname or "").lower()
    hostname = hostname.replace("www.", "")

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
        if parsed_url.path == "/watch":
            query_values = parse_qs(parsed_url.query)
            video_id = query_values.get("v", [None])[0]

        # Shorts 주소
        elif (
            len(path_parts) >= 2
            and path_parts[0] == "shorts"
        ):
            video_id = path_parts[1]

        # 임베드 주소
        elif (
            len(path_parts) >= 2
            and path_parts[0] == "embed"
        ):
            video_id = path_parts[1]

        # youtube.com/v/영상ID 형식
        elif (
            len(path_parts) >= 2
            and path_parts[0] == "v"
        ):
            video_id = path_parts[1]

    if not video_id:
        return None

    # 혹시 남아 있는 추가 주소 값을 제거합니다.
    video_id = (
        video_id
        .split("?")[0]
        .split("&")[0]
        .split("#")[0]
        .strip()
    )

    # 영상 ID에서 허용되는 문자만 검사합니다.
    if not re.fullmatch(r"[A-Za-z0-9_-]{6,}", video_id):
        return None

    return video_id


# ------------------------------------------------------------
# 8. YouTube API 오류를 한국어 안내로 바꾸기
# ------------------------------------------------------------
def make_friendly_error_message(response_data, status_code):
    """
    YouTube API가 반환한 오류를
    이해하기 쉬운 한국어 안내로 바꿉니다.
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
            "영상이 삭제되었거나 비공개인지 확인해 주세요."
        )

    if reason in {
        "quotaExceeded",
        "dailyLimitExceeded",
        "rateLimitExceeded",
    }:
        return (
            "YouTube API의 사용 한도를 초과했습니다. "
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
            "YouTube Data API v3 사용 설정을 확인해 주세요."
        )

    if api_message:
        return (
            "유튜브 댓글을 가져오지 못했습니다.\n\n"
            f"API 안내: {api_message}"
        )

    return default_message


# ------------------------------------------------------------
# 9. YouTube Data API에서 댓글 가져오기
# ------------------------------------------------------------
@st.cache_data(ttl=600, show_spinner=False)
def get_youtube_comments(api_key, video_id):
    """
    YouTube Data API v3의 commentThreads를 이용하여
    최상위 댓글을 최대 100개 가져옵니다.
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

    try:
        response_data = response.json()

    except ValueError:
        return None, (
            "유튜브 서버의 응답을 읽지 못했습니다. "
            "잠시 후 다시 시도해 주세요."
        )

    if not response.ok:
        return None, make_friendly_error_message(
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
            top_comment = (
                item["snippet"]
                ["topLevelComment"]
                ["snippet"]
            )

            comment_text = top_comment.get(
                "textOriginal",
                "",
            )

            like_count = top_comment.get(
                "likeCount",
                0,
            )

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
            # 구조가 다른 항목은 해당 댓글만 건너뜁니다.
            continue

    if not comments:
        return None, (
            "댓글 응답은 받았지만 표시할 수 있는 "
            "댓글을 찾지 못했습니다."
        )

    comments_df = pd.DataFrame(comments)

    comments_df = (
        comments_df
        .sort_values(
            by="좋아요 수",
            ascending=False,
        )
        .reset_index(drop=True)
    )

    comments_df.insert(
        0,
        "순번",
        range(1, len(comments_df) + 1),
    )

    return comments_df, None


# ------------------------------------------------------------
# 10. 댓글 정리와 형태소 분석
# ------------------------------------------------------------
@st.cache_data(show_spinner=False)
def extract_meaningful_words(comment_texts):
    """
    댓글 전체에서 의미 있는 단어를 추출합니다.

    한국어:
    - 일반 명사와 고유 명사를 추출합니다.
    - 동사와 형용사는 기본형에 가깝게 통일합니다.
    - 조사, 어미, 접속사 등을 제외합니다.

    영어:
    - 소문자로 통일합니다.
    - 일반적인 영어 불용어를 제외합니다.

    공통:
    - 한 글자 단어를 제외합니다.
    - URL과 이메일 주소를 제외합니다.
    - 숫자로만 된 단어를 제외합니다.
    """

    all_comments = " ".join(
        str(text)
        for text in comment_texts
        if text is not None
    )

    # URL 제거
    clean_text = re.sub(
        r"https?://\S+|www\.\S+",
        " ",
        all_comments,
    )

    # 이메일 주소 제거
    clean_text = re.sub(
        r"\S+@\S+\.\S+",
        " ",
        clean_text,
    )

    # HTML 태그 제거
    clean_text = re.sub(
        r"<[^>]+>",
        " ",
        clean_text,
    )

    # ㅋㅋㅋㅋ, ㅎㅎㅎㅎ처럼 같은 글자가 과도하게 반복되면 줄입니다.
    clean_text = re.sub(
        r"(.)\1{2,}",
        r"\1\1",
        clean_text,
    )

    meaningful_words = []

    # --------------------------------------------------------
    # 한국어 형태소 분석
    # --------------------------------------------------------
    tokens = kiwi.tokenize(
        clean_text,
        normalize_coda=True,
    )

    for token in tokens:
        word = token.form.strip()
        tag = token.tag

        # 일반 명사와 고유 명사만 추출합니다.
        if tag in {"NNG", "NNP"}:
            normalized_word = word

        # 동사와 형용사는 기본형처럼 '다'를 붙입니다.
        elif tag in {"VV", "VA"}:
            normalized_word = word + "다"

        else:
            # 조사, 어미, 접속사, 기호 등은 제외합니다.
            continue

        # 한 글자 단어 제외
        if len(normalized_word) < 2:
            continue

        # 숫자만 있는 단어 제외
        if normalized_word.isdigit():
            continue

        # 불용어 제외
        if normalized_word in KOREAN_STOPWORDS:
            continue

        meaningful_words.append(normalized_word)

    # --------------------------------------------------------
    # 영어 단어 분석
    # --------------------------------------------------------
    # 영어는 Kiwi 결과와 별도로 찾습니다.
    # 이렇게 하면 영어 단어가 중복 집계되는 것을 막을 수 있습니다.
    english_words = re.findall(
        r"\b[a-zA-Z][a-zA-Z'-]*\b",
        clean_text.lower(),
    )

    for word in english_words:
        word = word.strip("'-")

        # 한 글자 영어 단어 제외
        if len(word) < 2:
            continue

        if word in ENGLISH_STOPWORDS:
            continue

        meaningful_words.append(word)

    return meaningful_words


# ------------------------------------------------------------
# 11. 단어 빈도표 만들기
# ------------------------------------------------------------
def make_word_frequency(words, top_n=20):
    """
    추출한 단어의 등장 횟수를 계산하고
    상위 단어를 데이터프레임으로 만듭니다.
    """

    word_counts = Counter(words)

    most_common_words = word_counts.most_common(top_n)

    word_df = pd.DataFrame(
        most_common_words,
        columns=["단어", "빈도"],
    )

    return word_counts, word_df


# ------------------------------------------------------------
# 12. 나눔고딕 폰트 다운로드
# ------------------------------------------------------------
@st.cache_resource(show_spinner=False)
def download_korean_font():
    """
    워드클라우드에서 한글이 깨지지 않도록
    나눔고딕 폰트를 내려받습니다.

    내려받은 파일은 Streamlit 서버의 임시 폴더에 저장합니다.
    """

    font_path = (
        Path(tempfile.gettempdir())
        / "NanumGothic-Regular.ttf"
    )

    # 이미 정상적인 폰트 파일이 있다면 다시 받지 않습니다.
    if font_path.exists() and font_path.stat().st_size > 10_000:
        return str(font_path), None

    try:
        response = requests.get(
            FONT_URL,
            timeout=(10, 30),
        )

        response.raise_for_status()

        # 지나치게 작은 파일이라면 폰트가 아닐 가능성이 큽니다.
        if len(response.content) < 10_000:
            return None, (
                "다운로드된 폰트 파일의 크기가 너무 작아 "
                "정상적인 폰트로 확인되지 않았습니다."
            )

        font_path.write_bytes(response.content)

        return str(font_path), None

    except requests.exceptions.Timeout:
        return None, (
            "한글 폰트 다운로드 시간이 초과되었습니다. "
            "잠시 후 다시 시도해 주세요."
        )

    except requests.exceptions.ConnectionError:
        return None, (
            "한글 폰트 다운로드 서버에 연결하지 못했습니다. "
            "인터넷 연결 상태를 확인해 주세요."
        )

    except requests.exceptions.HTTPError as error:
        return None, (
            "한글 폰트를 내려받지 못했습니다.\n\n"
            f"서버 응답 오류: {error}"
        )

    except OSError as error:
        return None, (
            "내려받은 한글 폰트 파일을 저장하지 못했습니다.\n\n"
            f"파일 저장 오류: {error}"
        )

    except requests.exceptions.RequestException as error:
        return None, (
            "한글 폰트 다운로드 중 문제가 발생했습니다.\n\n"
            f"오류 내용: {error}"
        )


# ------------------------------------------------------------
# 13. 워드클라우드 이미지 만들기
# ------------------------------------------------------------
@st.cache_data(show_spinner=False)
def create_wordcloud_image(word_counts, font_path):
    """
    단어별 등장 횟수를 이용해 워드클라우드를 만듭니다.

    matplotlib은 사용하지 않습니다.
    WordCloud가 만든 PIL 이미지를 바로 반환합니다.
    """

    if not word_counts:
        return None

    wordcloud = WordCloud(
        font_path=font_path,
        width=1200,
        height=650,
        background_color="white",
        max_words=100,

        # 두 단어를 자동으로 묶는 기능은 끕니다.
        collocations=False,

        # 한 글자짜리 단어가 들어오더라도 다시 제외합니다.
        min_word_length=2,

        # 여백을 조금 줍니다.
        margin=3,

        # 같은 단어가 지나치게 크게 보이지 않도록 조절합니다.
        relative_scaling=0.5,

        # 실행할 때마다 모양이 크게 달라지지 않게 합니다.
        random_state=42,
    )

    wordcloud.generate_from_frequencies(
        dict(word_counts)
    )

    # matplotlib을 거치지 않고 PIL 이미지로 변환합니다.
    return wordcloud.to_image()


# ------------------------------------------------------------
# 14. 예시 버튼 처리
# ------------------------------------------------------------
def set_example_url(example_url):
    """
    예시 버튼을 누르면 입력창의 영상 주소를 변경합니다.
    """

    st.session_state["youtube_url"] = example_url


# ------------------------------------------------------------
# 15. 화면 제목
# ------------------------------------------------------------
st.markdown(
    '<div class="main-title">💬 유튜브 댓글 분석</div>',
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="sub-title">
        유튜브 인기 댓글을 가져와 자주 나온 단어와
        워드클라우드를 확인합니다.
    </div>
    """,
    unsafe_allow_html=True,
)


# ------------------------------------------------------------
# 16. 입력창 기본값
# ------------------------------------------------------------
if "youtube_url" not in st.session_state:
    st.session_state["youtube_url"] = EXAMPLE_1_URL


# ------------------------------------------------------------
# 17. 예시 영상 버튼
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
# 18. 유튜브 링크 입력창
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
# 19. 분석 실행 버튼
# ------------------------------------------------------------
analyze_button = st.button(
    "🔍 댓글 가져오기 및 분석하기",
    type="primary",
    use_container_width=True,
)


# ------------------------------------------------------------
# 20. 댓글 분석 실행
# ------------------------------------------------------------
if analyze_button:

    # 유튜브 링크에서 영상 ID를 추출합니다.
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

    youtube_api_key = str(youtube_api_key).strip()

    if not youtube_api_key:
        st.error(
            "Streamlit Secrets의 YOUTUBE_API_KEY 값이 비어 있습니다."
        )
        st.stop()

    st.caption(f"추출한 영상 ID: `{video_id}`")

    # --------------------------------------------------------
    # 댓글 가져오기
    # --------------------------------------------------------
    with st.spinner(
        "유튜브 댓글을 가져오고 단어를 분석하고 있습니다..."
    ):
        comments_df, error_message = get_youtube_comments(
            api_key=youtube_api_key,
            video_id=video_id,
        )

    if error_message:
        st.error(error_message)
        st.stop()

    # --------------------------------------------------------
    # 의미 있는 단어 추출
    # --------------------------------------------------------
    meaningful_words = extract_meaningful_words(
        tuple(comments_df["댓글"].fillna("").astype(str))
    )

    word_counts, word_df = make_word_frequency(
        words=meaningful_words,
        top_n=20,
    )

    # --------------------------------------------------------
    # 댓글 수집 결과
    # --------------------------------------------------------
    st.divider()
    st.subheader("📊 댓글 수집 결과")

    metric_col1, metric_col2, metric_col3 = st.columns(3)

    with metric_col1:
        st.metric(
            label="가져온 댓글 수",
            value=f"{len(comments_df):,}개",
        )

    with metric_col2:
        st.metric(
            label="분석한 단어 수",
            value=f"{len(meaningful_words):,}개",
        )

    with metric_col3:
        most_liked_comment = comments_df.iloc[0]

        st.metric(
            label="가장 많은 좋아요",
            value=f"{most_liked_comment['좋아요 수']:,}개",
        )

    # --------------------------------------------------------
    # 자주 나온 단어 상위 20개
    # --------------------------------------------------------
    st.divider()
    st.subheader("🔤 자주 나온 단어 상위 20개")

    if word_df.empty:
        st.info(
            "댓글에서 분석할 수 있는 의미 있는 단어를 "
            "찾지 못했습니다."
        )

    else:
        # Plotly 가로 막대그래프에서는 작은 값을 먼저 두면
        # 가장 많이 나온 단어가 화면 위쪽에 표시됩니다.
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
            "한국어는 형태소 분석을 통해 조사와 어미를 제거하고, "
            "명사·동사·형용사를 중심으로 추출했습니다. "
            "한국어와 영어의 일반적인 불용어, 숫자 및 "
            "한 글자 단어는 제외했습니다."
        )

    # --------------------------------------------------------
    # 워드클라우드
    # --------------------------------------------------------
    st.divider()
    st.subheader("☁️ 댓글 워드클라우드")

    if not word_counts:
        st.info(
            "워드클라우드를 만들 수 있는 단어가 없습니다."
        )

    else:
        with st.spinner(
            "한글 폰트를 준비하고 워드클라우드를 만들고 있습니다..."
        ):
            font_path, font_error = download_korean_font()

        # 폰트를 받지 못하면 안내 메시지를 보여줍니다.
        if font_error:
            st.warning(
                "워드클라우드에 필요한 한글 폰트를 "
                "준비하지 못했습니다.\n\n"
                f"{font_error}\n\n"
                "잠시 후 페이지를 새로고침해 주세요."
            )

        else:
            try:
                wordcloud_image = create_wordcloud_image(
                    word_counts=word_counts,
                    font_path=font_path,
                )

                if wordcloud_image is None:
                    st.info(
                        "워드클라우드에 표시할 단어가 없습니다."
                    )

                else:
                    # WordCloud가 만든 PIL 이미지를
                    # matplotlib 없이 바로 화면에 표시합니다.
                    st.image(
                        wordcloud_image,
                        use_container_width=True,
                    )

                    st.caption(
                        "막대그래프와 동일하게 형태소 분석 및 "
                        "불용어 제거를 거친 단어로 만들었습니다. "
                        "글자가 클수록 댓글에서 더 자주 등장한 단어입니다."
                    )

            except Exception as error:
                st.error(
                    "워드클라우드를 만드는 중 문제가 발생했습니다.\n\n"
                    f"오류 내용: {error}"
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
