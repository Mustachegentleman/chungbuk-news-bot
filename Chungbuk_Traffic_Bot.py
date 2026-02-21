import datetime
import os
import requests
import email.utils
import difflib  # 글자 패턴 기반 유사도 분석을 위해 추가
from datetime import timedelta

# 1. 설정값 (GitHub Secrets 연동)
NAVER_CLIENT_ID = os.environ.get("NAVER_ID")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_SECRET")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

def get_similarity(str1, str2):
    """두 문장의 공백을 제거하고 글자 배열의 유사도를 0~1 사이로 반환"""
    # 띄어쓰기, 쉼표, 따옴표 등 노이즈 제거
    s1 = str1.replace(" ", "").replace(",", "").replace("'", "").replace('"', "")
    s2 = str2.replace(" ", "").replace(",", "").replace("'", "").replace('"', "")
    
    # 두 문자열의 연속된 겹침 정도를 계산
    return difflib.SequenceMatcher(None, s1, s2).ratio()

def is_recent_news(pub_date_str):
    """기사 발행일이 현재로부터 24시간 이내인지 확인"""
    try:
        pub_date = email.utils.parsedate_to_datetime(pub_date_str)
        now = datetime.datetime.now(pub_date.tzinfo)
        return (now - pub_date) < timedelta(days=1)
    except Exception:
        return False

def get_news_score(item):
    """기사의 신뢰도 및 정보량을 점수로 환산"""
    score = 0
    title = item['title']
    link = item['link']
    
    # 1. 네이버 뉴스 플랫폼 링크 우선 (+10점)
    if "n.news.naver.com" in link:
        score += 10
        
    # 2. 주요 언론사 및 통신사 가점 (+5점)
    reputable_sources = [
        "연합뉴스", "뉴시스", "뉴스1", "노컷뉴스", "MBC", "KBS", "SBS", 
        "충북일보", "동양일보", "중부매일", "충청일보", "충청매일"
    ]
    if any(src in title or src in link for src in reputable_sources):
        score += 5
        
    # 3. 제목이 길수록 상세한 정보를 담고 있을 확률이 높음
    score += len(title) * 0.1
    
    return score

def is_valid_news(title):
    """범죄 및 불필요한 노이즈 기사 필터링"""
    blacklist = [
        "직업군인이야기", "칼럼", "인사", "부고", "운세", "게시판", "동정", 
        "검거", "구속", "살인", "폭행", "사기", "마약", "성범죄", "횡령", "절도",
        "압수수색", "재판", "법원", "검찰", "경찰관", "습격", "화재", "불", "공채", "채용"
    ]
    for word in blacklist:
        if word in title:
            return False

    traffic_keywords = [
        "도로", "교통", "사고", "통제", "공사", "정체", "단속", 
        "개통", "우회", "차량", "신호", "운전", "면허", "하이패스", "터널"
    ]
    return any(word in title for word in traffic_keywords)

def fetch_traffic_news():
    """뉴스 수집, 최신순/키워드 필터링 및 스마트 중복 제거"""
    search_queries = ["충북 교통 사고", "청주 도로 통제", "충북 도로공사", "충북 실시간 교통", "충북 교통 정체"]
    raw_news = []

    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
    }

    # 1. API 호출 및 1차 필터링 (최신 날짜 & 키워드)
    for query in search_queries:
        url = f"https://openapi.naver.com/v1/search/news.json?query={query}&display=20&sort=sim"
        res = requests.get(url, headers=headers)

        if res.status_code == 200:
            items = res.json().get("items", [])
            for item in items:
                title = item["title"].replace("<b>", "").replace("</b>", "").replace("&quot;", '"').replace("&apos;", "'")
                pub_date = item.get("pubDate", "")

                if is_recent_news(pub_date) and is_valid_news(title):
                    news_obj = {
                        "title": title,
                        "link": item["link"],
                        "score": get_news_score({"title": title, "link": item["link"]})
                    }
                    raw_news.append(news_obj)

    # 2. 스마트 중복 제거 (difflib 활용)
    unique_news = []
    for news in raw_news:
        is_duplicate = False
        for i, existing in enumerate(unique_news):
            # 글자 유사도가 45%(0.45) 이상이면 같은 기사로 취급
            if get_similarity(news["title"], existing["title"]) > 0.45:
                is_duplicate = True
                # 기존 기사보다 현재 기사의 신뢰도 점수가 더 높으면 교체
                if news["score"] > existing["score"]:
                    unique_news[i] = news
                break
                
        if not is_duplicate:
            unique_news.append(news)

    return unique_news

def send_telegram(news_list):
    """최종 정제된 뉴스를 텔레그램으로 전송"""
    now = datetime.datetime.now()
    date_str = now.strftime("%Y년 %m월 %d일")

    if not news_list:
        message = f"📢 {date_str}\n오늘 충북 지역의 신규 교통 뉴스가 없습니다."
    else:
        message = f"🚗 [{date_str} 충북 교통 뉴스 브리핑]\n\n"
        # 점수가 높은 순으로 정렬하여 출력
        sorted_news = sorted(news_list, key=lambda x: x['score'], reverse=True)
        for i, news in enumerate(sorted_news[:10], 1):
            message += f"{i}. {news['title']}\n🔗 {news['link']}\n\n"
        message += "💡 24시간 이내 최신 뉴스 중 신뢰도가 높은 기사를 엄선했습니다."

    send_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "disable_web_page_preview": True}
    requests.post(send_url, data=payload)

if __name__ == "__main__":
    try:
        news_data = fetch_traffic_news()
        send_telegram(news_data)
        print(f"[{datetime.datetime.now()}] 전송 성공: {len(news_data)}건")
    except Exception as e:
        print(f"오류 발생: {e}")