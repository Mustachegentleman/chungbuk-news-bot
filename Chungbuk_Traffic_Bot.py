import datetime
import os
import requests
import email.utils
import difflib
from datetime import timedelta

# 1. 설정값
NAVER_CLIENT_ID = os.environ.get("NAVER_ID")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_SECRET")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

def get_similarity(str1, str2):
    """두 문장의 공백을 제거하고 글자 배열의 유사도를 반환"""
    s1 = str1.replace(" ", "").replace(",", "").replace("'", "").replace('"', "")
    s2 = str2.replace(" ", "").replace(",", "").replace("'", "").replace('"', "")
    return difflib.SequenceMatcher(None, s1, s2).ratio()

def is_recent_news(pub_date_str):
    """기사 발행일이 24시간 이내인지 확인"""
    try:
        pub_date = email.utils.parsedate_to_datetime(pub_date_str)
        now = datetime.datetime.now(pub_date.tzinfo)
        return (now - pub_date) < timedelta(days=1)
    except Exception:
        return False

def get_news_score(item):
    """언론사 원문 링크(originallink)를 분석하여 정확한 신뢰도 점수 부여"""
    score = 0
    title = item.get('title', '')
    link = item.get('link', '')
    originallink = item.get('originallink', '') # 언론사 실제 주소
    
    # 1. 네이버 뉴스 플랫폼 링크 우선 (+10점)
    if "n.news.naver.com" in link:
        score += 10
        
    # 2. 메이저 통신사 및 주요 방송사 원문 도메인 가점 (+5점)
    reputable_domains = [
        "yna.co.kr", "newsis.com", "news1.kr", "nocutnews.co.kr", 
        "kbs.co.kr", "mbc.com", "sbs.co.kr", "ytn.co.kr"
    ]
    if any(domain in originallink.lower() for domain in reputable_domains):
        score += 5
        
    # 3. 충북 지역 유력지 도메인 가점 (+5점)
    local_domains = [
        "inews365", "ccdailynews", "jbnews", "cctoday", "chungbuk"
    ]
    if any(domain in originallink.lower() for domain in local_domains):
        score += 5
        
    # 4. 제목이 길수록 상세 정보 포함 확률 높음
    score += len(title) * 0.1
    
    return score

def is_valid_news(title):
    """노이즈 기사 필터링"""
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
    search_queries = ["충북 교통 사고", "청주 도로 통제", "충북 도로공사", "충북 실시간 교통", "충북 교통 정체"]
    raw_news = []

    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
    }

    # 1. 1차 수집 (조건에 맞는 기사 모두 모으기)
    for query in search_queries:
        url = f"https://openapi.naver.com/v1/search/news.json?query={query}&display=20&sort=sim"
        res = requests.get(url, headers=headers)

        if res.status_code == 200:
            items = res.json().get("items", [])
            for item in items:
                title = item["title"].replace("<b>", "").replace("</b>", "").replace("&quot;", '"').replace("&apos;", "'")
                pub_date = item.get("pubDate", "")

                if is_recent_news(pub_date) and is_valid_news(title):
                    # 점수 계산 시 item 전체를 넘겨 originallink까지 검사하도록 수정
                    item['title'] = title 
                    news_obj = {
                        "title": title,
                        "link": item["link"],
                        "score": get_news_score(item) 
                    }
                    raw_news.append(news_obj)

    # 2. [가장 중요한 변화] 기사를 점수(신뢰도)가 높은 순서대로 내림차순 정렬합니다.
    raw_news.sort(key=lambda x: x["score"], reverse=True)

    # 3. 1등부터 장바구니에 담으면서, 중복되는 하위 기사들은 가차 없이 버립니다.
    unique_news = []
    for news in raw_news:
        is_duplicate = False
        for existing in unique_news:
            # 이미 장바구니에 있는 상위 점수 기사와 45% 이상 일치하면 버림
            if get_similarity(news["title"], existing["title"]) > 0.45:
                is_duplicate = True
                break
                
        if not is_duplicate:
            unique_news.append(news)

    return unique_news

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

if __name__ == "__main__":
    try:
        news_data = fetch_traffic_news()
        send_telegram(news_data)
        print(f"[{datetime.datetime.now()}] 전송 성공: {len(news_data)}건")
    except Exception as e:
        print(f"오류 발생: {e}")