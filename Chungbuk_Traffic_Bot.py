import datetime
import os

import requests

# 1. 설정값 (환경 변수 사용 권장, 로컬 테스트 시 직접 입력 가능)
# GitHub Actions 사용 시 Secrets에 등록한 변수명을 가져옵니다.
NAVER_CLIENT_ID = os.environ.get("NAVER_ID")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_SECRET")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

def get_jaccard_sim(str1, str2):
    """두 문장의 단어 집합 유사도를 계산하여 중복 여부 판별"""
    a = set(str1.split())
    b = set(str2.split())
    c = a.intersection(b)
    union = len(a) + len(b) - len(c)
    return float(len(c)) / union if union > 0 else 0


def is_valid_news(title):
    """범죄 및 잡다한 뉴스를 강력하게 차단하고 교통 뉴스만 골라냄"""

    # 1. 강력 금칙어 (범죄, 일반 사건, 연예 등 제외)
    # 제목에 아래 단어가 하나라도 있으면 무조건 버립니다.
    blacklist = [
        "직업군인이야기",
        "칼럼",
        "인사",
        "부고",
        "운세",
        "게시판",
        "동정",
        "검거",
        "구속",
        "살인",
        "폭행",
        "사기",
        "마약",
        "성범죄",
        "횡령",
        "절도",
        "압수수색",
        "재판",
        "법원",
        "검찰",
        "경찰관",
        "습격",
        "화재",
        "불",
    ]
    for word in blacklist:
        if word in title:
            return False

    # 2. 교통 필수 키워드 (Whitelist)
    # 제목에 아래 단어 중 하나는 '반드시' 포함되어야 합니다.
    traffic_keywords = [
        "도로",
        "교통",
        "사고",
        "통제",
        "공사",
        "정체",
        "단속",
        "개통",
        "우회",
        "차량",
        "신호",
        "운전",
        "면허",
        "하이패스",
        "터널",
    ]

    # 3. 최종 검증: 교통 키워드가 있으면서, 범죄 관련 맥락이 아닌 것
    if any(word in title for word in traffic_keywords):
        return True

    return False


def fetch_traffic_news():
    """네이버 API를 통해 뉴스 수집 및 정제"""
    # 검색 키워드 리스트 (충북 지역 특화)
    search_queries = [
        "충북 교통 사고",
        "청주 도로 통제",
        "충북 도로공사",
        "충북 실시간 교통",
        "충북 교통 정체",
    ]
    collected_news = []

    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
    }

    for query in search_queries:
        # 유사도순(sim)으로 가져와서 노이즈를 1차로 줄임
        url = f"https://openapi.naver.com/v1/search/news.json?query={query}&display=15&sort=sim"
        res = requests.get(url, headers=headers)

        if res.status_code == 200:
            items = res.json().get("items", [])
            for item in items:
                # HTML 태그 제거 및 제목 정제
                title = (
                    item["title"]
                    .replace("<b>", "")
                    .replace("</b>", "")
                    .replace("&quot;", '"')
                    .replace("&apos;", "'")
                )
                link = item["link"]

                # 필터링 알고리즘 적용
                if is_valid_news(title):
                    collected_news.append({"title": title, "link": link})

    # 중복 제거 (유사도 45% 이상이면 동일 기사로 간주하여 하나만 남김)
    unique_news = []
    for news in collected_news:
        is_duplicate = False
        for existing in unique_news:
            if get_jaccard_sim(news["title"], existing["title"]) > 0.45:
                is_duplicate = True
                break
        if not is_duplicate:
            unique_news.append(news)

    return unique_news


def send_telegram(news_list):
    """정제된 뉴스 리스트를 텔레그램으로 전송"""
    now = datetime.datetime.now()
    date_str = now.strftime("%Y년 %m월 %d일")

    if not news_list:
        message = f"📢 {date_str}\n오늘 충북 지역의 특이 교통 뉴스가 없습니다."
    else:
        message = f"🚗 [{date_str} 충북 교통 뉴스 브리핑]\n\n"
        for i, news in enumerate(news_list[:12], 1):  # 너무 길지 않게 최대 12개
            message += f"{i}. {news['title']}\n🔗 {news['link']}\n\n"
        message += "💡 본 뉴스는 매일 아침 자동으로 수집됩니다."

    send_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "disable_web_page_preview": True,  # 링크 미리보기 꺼서 메시지 간결화
    }
    requests.post(send_url, data=payload)


if __name__ == "__main__":
    try:
        news_data = fetch_traffic_news()
        send_telegram(news_data)
        print(f"[{datetime.datetime.now()}] 전송 성공: {len(news_data)}건")
    except Exception as e:
        print(f"오류 발생: {e}")
