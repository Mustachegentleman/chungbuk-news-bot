import datetime
import os
import requests
import email.utils  # 날짜 파싱을 위해 추가

# 1. 설정값 (환경 변수 사용 권장)
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

def is_recent_news(pub_date_str):
    """기사 발행일이 현재로부터 24시간 이내인지 확인 (추가된 함수)"""
    try:
        # 네이버 pubDate (RFC822 형식)를 datetime 객체로 변환
        pub_date = email.utils.parsedate_to_datetime(pub_date_str)
        now = datetime.datetime.now(pub_date.tzinfo) # 타임존 유지
        
        # 현재 시간과 발행 시간의 차이가 24시간(1일) 이내인지 확인
        diff = now - pub_date
        return diff < datetime.timedelta(days=1)
    except Exception:
        return False

def is_valid_news(title):
    """범죄 및 잡다한 뉴스를 강력하게 차단하고 교통 뉴스만 골라냄"""
    blacklist = [
        "직업군인이야기", "칼럼", "인사", "부고", "운세", "게시판", "동정", 
        "검거", "구속", "살인", "폭행", "사기", "마약", "성범죄", "횡령", "절도",
        "압수수색", "재판", "법원", "검찰", "경찰관", "습격", "화재", "불"
    ]
    for word in blacklist:
        if word in title:
            return False

    traffic_keywords = [
        "도로", "교통", "사고", "통제", "공사", "정체", "단속", 
        "개통", "우회", "차량", "신호", "운전", "면허", "하이패스", "터널"
    ]

    if any(word in title for word in traffic_keywords):
        return True

    return False

def fetch_traffic_news():
    """네이버 API를 통해 뉴스 수집 및 정제"""
    search_queries = [
        "충북 교통 사고", "청주 도로 통제", "충북 도로공사", 
        "충북 실시간 교통", "충북 교통 정체"
    ]
    collected_news = []

    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
    }

    for query in search_queries:
        url = f"https://openapi.naver.com/v1/search/news.json?query={query}&display=15&sort=sim"
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
                link = item["link"]
                pub_date = item.get("pubDate", "") # 날짜 정보 가져오기

                # [수정된 부분] 날짜 필터링(최근 24시간)과 키워드 필터링을 동시에 만족해야 함
                if is_recent_news(pub_date) and is_valid_news(title):
                    collected_news.append({"title": title, "link": link})

    # 중복 제거
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
        message = f"📢 {date_str}\n오늘 충북 지역의 신규 교통 뉴스가 없습니다. (24시간 이내 기준)"
    else:
        message = f"🚗 [{date_str} 충북 교통 뉴스 브리핑]\n\n"
        for i, news in enumerate(news_list[:12], 1):
            message += f"{i}. {news['title']}\n🔗 {news['link']}\n\n"
        message += "💡 24시간 이내 최신 뉴스만 수집되었습니다."

    send_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "disable_web_page_preview": True,
    }
    requests.post(send_url, data=payload)

if __name__ == "__main__":
    try:
        news_data = fetch_traffic_news()
        send_telegram(news_data)
        print(f"[{datetime.datetime.now()}] 전송 성공: {len(news_data)}건")
    except Exception as e:
        print(f"오류 발생: {e}")