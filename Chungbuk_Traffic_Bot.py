import datetime
import os
import requests
import email.utils
from datetime import timedelta
from kiwipiepy import Kiwi
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# ──────────────────────────────────────────────
# 1. 설정값
# ──────────────────────────────────────────────
NAVER_CLIENT_ID = os.environ.get("NAVER_ID")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_SECRET")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

# Kiwi 형태소 분석기 (모듈 로드 시 1회만 초기화)
kiwi = Kiwi()

# ──────────────────────────────────────────────
# 2. 시간 필터
# ──────────────────────────────────────────────
def is_recent_news(pub_date_str):
    """기사 발행일이 24시간 이내인지 확인"""
    try:
        pub_date = email.utils.parsedate_to_datetime(pub_date_str)
        now = datetime.datetime.now(pub_date.tzinfo)
        return (now - pub_date) < timedelta(days=1)
    except Exception:
        return False

# ──────────────────────────────────────────────
# 3. 키워드 필터링 (화이트리스트 / 블랙리스트)
# ──────────────────────────────────────────────
BLACKLIST = [
    "살인", "마약", "성폭행", "보이스피싱",
    "기획부동산", "아파트 분양", "프로야구", "K리그",
]

WHITELIST = [
    "교통사고", "추돌", "정체", "통제", "공사",
    "도로교통공단", "무인단속", "단속장비",
    "스쿨존", "어린이보호구역", "신호체계",
    "교통안전", "교차로", "통행제한",
]

def is_valid_news(title):
    """블랙리스트 포함 시 즉시 제외, 화이트리스트 1개 이상 포함 시 통과"""
    for word in BLACKLIST:
        if word in title:
            return False
    return any(word in title for word in WHITELIST)

# ──────────────────────────────────────────────
# 4. 신뢰도 및 중요도 점수(Scoring)
# ──────────────────────────────────────────────
REGION_KEYWORDS = [
    "충북", "청주", "충주", "제천", "보은", "옥천",
    "영동", "증평", "진천", "괴산", "음성", "단양",
]

INFRA_KEYWORDS = [
    "도로교통공단", "무인단속", "스쿨존",
    "어린이보호구역", "교통안전",
]

def get_news_score(item):
    """기사별 점수를 산출하여 중복 제거·정렬 기준으로 활용"""
    score = 0
    title = item.get("title", "")
    link = item.get("link", "")

    # 네이버 뉴스 in-link 가점
    if "n.news.naver.com" in link:
        score += 10

    # 제목 길이 30자 초과 가점
    if len(title) > 30:
        score += 5

    # 지역 키워드 가점 (1개 이상 포함 시 +5)
    if any(region in title for region in REGION_KEYWORDS):
        score += 5

    # 행정/인프라 키워드 가점 (1개 이상 포함 시 +5)
    if any(kw in title for kw in INFRA_KEYWORDS):
        score += 5

    return score

# ──────────────────────────────────────────────
# 5. NLP 기반 중복 제거 (Kiwi + TF-IDF + Cosine)
# ──────────────────────────────────────────────
def extract_nouns(text):
    """
    Kiwi 형태소 분석기로 일반명사(NNG), 고유명사(NNP), 숫자(SN)만 추출하여
    띄어쓰기로 연결한 코퍼스 문자열을 반환합니다.
    숫자(SN)는 사상자 수·도로 번호 등 기사를 식별하는 핵심 단서이므로 반드시 포함합니다.
    """
    tokens = kiwi.tokenize(text)
    # tag가 NNG(일반명사), NNP(고유명사), SN(숫자)인 형태소만 선별
    nouns = [token.form for token in tokens if token.tag in ("NNG", "NNP", "SN")]
    return " ".join(nouns)


def deduplicate_news(news_list):
    """
    TF-IDF 벡터화 → 코사인 유사도 행렬을 구해 55% 초과 쌍을 중복으로 판정합니다.
    중복 쌍 중 점수가 낮은 기사를 제거하며, 입력 리스트는 이미 점수 내림차순 정렬 상태입니다.
    """
    if len(news_list) <= 1:
        return news_list

    # 각 기사 제목에서 명사 코퍼스 생성
    corpus = [extract_nouns(news["title"]) for news in news_list]

    # 빈 코퍼스(명사 0개)가 섞여 있으면 TfidfVectorizer가 ValueError를 발생시킴
    # → 빈 문자열을 더미 토큰으로 대체하여 방어
    corpus = [doc if doc.strip() else "_empty_" for doc in corpus]

    try:
        vectorizer = TfidfVectorizer()
        tfidf_matrix = vectorizer.fit_transform(corpus)
        sim_matrix = cosine_similarity(tfidf_matrix)
    except ValueError:
        # 모든 문서가 빈 문자열이거나 vocabulary가 비는 극단적 케이스 → 중복 제거 없이 반환
        return news_list

    # 제거 대상 인덱스를 수집 (점수 내림차순이므로 뒤쪽이 낮은 점수)
    removed = set()
    for i in range(len(news_list)):
        if i in removed:
            continue
        for j in range(i + 1, len(news_list)):
            if j in removed:
                continue
            if sim_matrix[i][j] > 0.55:
                # i가 j보다 점수가 높거나 같으므로 j를 제거
                removed.add(j)

    return [news for idx, news in enumerate(news_list) if idx not in removed]

# ──────────────────────────────────────────────
# 6. 뉴스 수집 파이프라인
# ──────────────────────────────────────────────
def fetch_traffic_news():
    search_queries = [
        "충북 교통 사고",
        "청주 도로 통제",
        "충북 도로공사",
        "충북 실시간 교통",
        "충북 교통 정체",
    ]
    raw_news = []

    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
    }

    # 1단계: Naver API로 기사 수집 + HTML 정리 + 시간·키워드 필터
    for query in search_queries:
        url = f"https://openapi.naver.com/v1/search/news.json?query={query}&display=20&sort=sim"
        res = requests.get(url, headers=headers)

        if res.status_code == 200:
            items = res.json().get("items", [])
            for item in items:
                title = (
                    item["title"]
                    .replace("<b>", "")
                    .replace("</b>", "")
                    .replace("&quot;", '"')
                    .replace("&apos;", "'")
                )
                pub_date = item.get("pubDate", "")

                if is_recent_news(pub_date) and is_valid_news(title):
                    item["title"] = title
                    raw_news.append({
                        "title": title,
                        "link": item["link"],
                        "score": get_news_score(item),
                    })

    # 2단계: 점수 내림차순 정렬
    raw_news.sort(key=lambda x: x["score"], reverse=True)

    # 3단계: NLP 기반 중복 제거
    unique_news = deduplicate_news(raw_news)

    return unique_news

# ──────────────────────────────────────────────
# 7. 텔레그램 발송
# ──────────────────────────────────────────────
def send_telegram(news_list):
    now = datetime.datetime.now()
    date_str = now.strftime("%Y년 %m월 %d일")

    if not news_list:
        message = f"📢 {date_str}\n오늘 충북 지역의 신규 교통 뉴스가 없습니다."
    else:
        message = f"🚗 [{date_str} 충북 교통 뉴스 브리핑]\n\n"
        for i, news in enumerate(news_list[:10], 1):
            message += f"{i}. {news['title']}\n🔗 {news['link']}\n\n"
        message += "💡 24시간 이내 최신 뉴스 중 신뢰도가 높은 기사를 엄선했습니다."

    send_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "disable_web_page_preview": True}
    requests.post(send_url, data=payload)

# ──────────────────────────────────────────────
# 8. 실행
# ──────────────────────────────────────────────
if __name__ == "__main__":
    try:
        news_data = fetch_traffic_news()
        send_telegram(news_data)
        print(f"[{datetime.datetime.now()}] 전송 성공: {len(news_data)}건")
    except Exception as e:
        print(f"오류 발생: {e}")
