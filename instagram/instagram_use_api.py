import os
import re
import logging
from typing import Dict, List, Optional

import requests
from dotenv import load_dotenv
from pathlib import Path
import json

load_dotenv('/home/pmi/venvs/source_code/.env')
USERNAME = os.getenv("IG_USERNAME")
PASSWORD = os.getenv("IG_PASSWORD")
INSTAGRAM_BUSINESS_ID = os.getenv("INSTAGRAM_BUSINESS_ID")
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")

# 파일 경로 (현재 파일 위치 기준)
BASE_DIR = Path(__file__).parent
COOKIE_PATH = BASE_DIR / "instagram_cookies.pkl"
DATA_FILE = BASE_DIR / "instagram_media.json"


def normalize_permalink(url: Optional[str]) -> Optional[str]:
    """
    permalink를 정규화하여 shortcode만 추출
    - instagram_media.json 형식: "https://www.instagram.com/reel/DQ5hGrqE6SP/"
    - 수집한 형식: "https://www.instagram.com/pmi_min/reel/DD4hDgTy82T/"
    → 둘 다 shortcode만 추출하여 비교: "DQ5hGrqE6SP", "DD4hDgTy82T"
    """
    if not url:
        return None
    # 쿼리 파라미터 제거
    url = url.split("?")[0]
    # 끝에 슬래시 제거
    url = url.rstrip("/")
    
    # shortcode 추출
    # 형식 1: /reel/SHORTCODE 또는 /p/SHORTCODE
    # 형식 2: /USERNAME/reel/SHORTCODE 또는 /USERNAME/p/SHORTCODE
    if "/reel/" in url:
        parts = url.split("/reel/")
        if len(parts) > 1:
            shortcode = parts[-1].split("/")[0].split("?")[0]
            return shortcode
    elif "/p/" in url:
        parts = url.split("/p/")
        if len(parts) > 1:
            shortcode = parts[-1].split("/")[0].split("?")[0]
            return shortcode
    
    return None


def setup_logging(log_file: str = "instagram.log") -> None:
    """로깅 설정: 파일과 콘솔 모두에 로그 출력"""
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    # 기존 핸들러 제거 (중복 방지)
    logger.handlers.clear()
    
    # 로그 포맷 설정
    formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # 파일 핸들러 (추가 모드로 기존 로그 보존)
    file_handler = logging.FileHandler(log_file, encoding='utf-8', mode='a')
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    # 콘솔 핸들러
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    logging.info(f"로깅이 시작되었습니다. 로그 파일: {log_file}")


def load_existing_data() -> tuple[Dict[str, Dict[str, dict]], Dict[str, dict]]:
    """
    기존 데이터를 로드하고 permalink 기준 인덱스도 생성
    
    Returns:
        (hashtag_media_data, permalink_index)
        - hashtag_media_data: {hashtag: {media_id: item}}
        - permalink_index: {shortcode: item} (permalink 기준 인덱스)
    """
    if not DATA_FILE.exists():
        return {}, {}

    with open(DATA_FILE, "r", encoding="utf-8") as file:
        try:
            raw_data = json.load(file)
        except json.JSONDecodeError:
            logging.warning("기존 JSON 파일을 읽는 중 오류가 발생했습니다. 새로 생성합니다.")
            return {}, {}

    data: Dict[str, Dict[str, dict]] = {}
    permalink_index: Dict[str, dict] = {}  # {shortcode: item}

    if isinstance(raw_data, list):
        for item in raw_data:
            if not isinstance(item, dict):
                continue
            hashtag = item.get("hashtag")
            media_id = item.get("id")
            # id는 필수, hashtag는 없으면 "unknown"으로 처리
            if not media_id:
                continue
            # hashtag가 없으면 "unknown" 사용 (기존 데이터 보존)
            # 원본 hashtag 값은 항목에 그대로 유지됨 (None 또는 없음)
            storage_hashtag = hashtag if hashtag else "unknown"
            data.setdefault(storage_hashtag, {})[media_id] = item
            
            # permalink 기준 인덱스 생성
            permalink = item.get("permalink")
            if permalink:
                shortcode = normalize_permalink(permalink)
                if shortcode and shortcode not in permalink_index:
                    # 첫 번째 발견된 항목만 인덱스에 저장 (중복 방지)
                    permalink_index[shortcode] = item

    elif isinstance(raw_data, dict):
        for hashtag, entries in raw_data.items():
            storage: Dict[str, dict] = {}
            if isinstance(entries, dict):
                for media_id, media_data in entries.items():
                    if isinstance(media_data, dict):
                        storage[media_id] = media_data
                        # permalink 기준 인덱스 생성
                        permalink = media_data.get("permalink")
                        if permalink:
                            shortcode = normalize_permalink(permalink)
                            if shortcode and shortcode not in permalink_index:
                                permalink_index[shortcode] = media_data
            elif isinstance(entries, list):
                for media_data in entries:
                    if isinstance(media_data, dict):
                        media_id = media_data.get("id")
                        if media_id:
                            storage[media_id] = media_data
                            # permalink 기준 인덱스 생성
                            permalink = media_data.get("permalink")
                            if permalink:
                                shortcode = normalize_permalink(permalink)
                                if shortcode and shortcode not in permalink_index:
                                    permalink_index[shortcode] = media_data
            data[hashtag] = storage

    return data, permalink_index


def save_data(data: dict) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    flattened: List[dict] = []
    for storage_hashtag, media_map in data.items():
        if not isinstance(media_map, dict):
            continue
        for media_id, media_item in media_map.items():
            if not isinstance(media_item, dict):
                continue
            entry = media_item.copy()
            entry["id"] = media_id
            # hashtag 필드는 원본 값을 보존
            # 원본 항목에 hashtag 필드가 있으면 그대로 유지
            # "unknown" 그룹에 있지만 원본에 hashtag가 있으면 그대로 유지
            # "unknown" 그룹에 있고 원본에 hashtag가 없으면 hashtag 필드를 추가하지 않음
            original_hashtag = entry.get("hashtag")
            if storage_hashtag != "unknown":
                # 정상적인 hashtag 그룹: storage_hashtag 사용
                entry["hashtag"] = storage_hashtag
            elif original_hashtag:
                # "unknown" 그룹이지만 원본에 hashtag가 있으면 원본 값 유지
                entry["hashtag"] = original_hashtag
            # else: "unknown" 그룹이고 원본에 hashtag가 없으면 hashtag 필드를 추가하지 않음
            flattened.append(entry)

    with open(DATA_FILE, "w", encoding="utf-8") as file:
        json.dump(flattened, file, ensure_ascii=False, indent=2)


def verify_access_token() -> bool:
    """Access Token 유효성 검증"""
    # 방법 1: Facebook Graph API로 토큰 검증
    try:
        url = "https://graph.facebook.com/v18.0/me"
        params = {"access_token": ACCESS_TOKEN}
        response = requests.get(url, params=params).json()
        
        if "error" in response:
            error = response["error"]
            error_code = error.get("code")
            error_message = error.get("message", "")
            
            logging.error(f"❌ Access Token 검증 실패: {error}")
            
            if error_code in [190, 10]:
                logging.error("🔴 토큰이 만료되었거나 유효하지 않습니다!")
                logging.error("💡 해결 방법: Facebook Developer Console에서 새 Access Token을 발급받으세요.")
                return False
            elif error_code == 200:
                logging.error("🔴 권한이 부족합니다!")
                logging.error("💡 해결 방법: Facebook App에 필요한 권한을 추가하세요.")
                return False
            else:
                logging.warning(f"⚠️ 예상치 못한 에러 코드: {error_code}")
                return False
        
        logging.info(f"✅ Access Token 검증 성공: {response.get('name', 'Unknown')} (ID: {response.get('id', 'Unknown')})")
        
        # 방법 1-2: Access Token의 권한 확인
        try:
            debug_url = "https://graph.facebook.com/v18.0/debug_token"
            debug_params = {
                "input_token": ACCESS_TOKEN,
                "access_token": ACCESS_TOKEN
            }
            debug_response = requests.get(debug_url, params=debug_params).json()
            
            if "data" in debug_response:
                data = debug_response["data"]
                scopes = data.get("scopes", [])
                logging.info(f"📋 Access Token 권한 목록:")
                for scope in scopes:
                    logging.info(f"   - {scope}")
                
                # Instagram 관련 권한 확인
                instagram_scopes = [s for s in scopes if "instagram" in s.lower()]
                if instagram_scopes:
                    logging.info(f"✅ Instagram 관련 권한 확인됨: {', '.join(instagram_scopes)}")
                else:
                    logging.warning(f"⚠️ Instagram 관련 권한이 없을 수 있습니다.")
        except Exception as e:
            logging.debug(f"권한 확인 중 예외 (무시): {e}")
        
        # 방법 2: Instagram Business Account 접근 권한 확인
        if INSTAGRAM_BUSINESS_ID:
            try:
                ig_url = f"https://graph.facebook.com/v18.0/{INSTAGRAM_BUSINESS_ID}"
                ig_params = {
                    "fields": "id,username",
                    "access_token": ACCESS_TOKEN
                }
                ig_response = requests.get(ig_url, params=ig_params).json()
                
                if "error" in ig_response:
                    error = ig_response["error"]
                    error_code = error.get("code")
                    if error_code == 100:
                        # 필드 관련 에러는 무시하고 기본 정보만 확인
                        logging.warning(f"⚠️ 일부 필드 접근 실패 (무시): {error.get('message', '')}")
                        # 필드 없이 다시 시도
                        ig_params = {
                            "fields": "id",
                            "access_token": ACCESS_TOKEN
                        }
                        ig_response = requests.get(ig_url, params=ig_params).json()
                        if "error" in ig_response:
                            logging.warning(f"⚠️ Instagram Business Account 접근 확인 실패: {ig_response['error']}")
                            logging.warning("💡 Instagram Business Account ID가 올바른지 확인하세요.")
                        else:
                            logging.info(f"✅ Instagram Business Account 확인: ID {ig_response.get('id', 'Unknown')}")
                    else:
                        logging.warning(f"⚠️ Instagram Business Account 접근 확인 실패: {error}")
                        logging.warning("💡 Instagram Business Account ID가 올바른지 확인하세요.")
                else:
                    logging.info(f"✅ Instagram Business Account 확인: {ig_response.get('username', 'Unknown')} (ID: {ig_response.get('id', 'Unknown')})")
            except Exception as e:
                logging.warning(f"⚠️ Instagram Business Account 확인 중 예외: {e}")
        
        return True
    except Exception as e:
        logging.error(f"❌ Access Token 검증 중 예외 발생: {e}")
        return False


def fetch_hashtag_id(hashtag: str) -> Optional[str]:
    url = "https://graph.facebook.com/v18.0/ig_hashtag_search"
    
    # 해시태그에서 # 제거 (API는 # 없이도 검색 가능하지만, 일관성을 위해 제거)
    query_string = hashtag.lstrip('#')
    
    params = {
        "user_id": INSTAGRAM_BUSINESS_ID,
        "q": query_string,
        "access_token": ACCESS_TOKEN
    }
    
    # 디버깅: 실제 전송되는 URL 확인
    import urllib.parse
    full_url = f"{url}?{urllib.parse.urlencode(params)}"
    logging.debug(f"🔍 요청 URL: {full_url.replace(ACCESS_TOKEN, 'ACCESS_TOKEN_HIDDEN')}")
    logging.debug(f"🔍 해시태그 원본: {repr(hashtag)}, 쿼리 문자열: {repr(query_string)}")
    
    response = requests.get(url, params=params).json()
    logging.info(f"해시태그 검색결과 ({hashtag}): {response}")

    if "error" in response:
        error = response["error"]
        error_code = error.get("code")
        error_subcode = error.get("error_subcode")
        
        # 토큰 관련 에러 코드 확인
        if error_code in [190, 10]:
            logging.error(f"🔴 토큰이 만료되었거나 유효하지 않습니다! (해시태그: {hashtag})")
            logging.error(f"   에러: {error}")
            return None
        elif error_code == 200:
            logging.error(f"🔴 권한이 부족합니다! (해시태그: {hashtag})")
            logging.error(f"   에러: {error}")
            return None
        elif error_code == 24 and error_subcode == 2207024:
            # Code 24는 해시태그를 찾을 수 없다는 의미
            # Instagram Graph API의 정책 변경으로 해시태그 검색이 제한되었을 가능성
            error_msg = error.get("error_user_msg", "").lower()
            if "유효하지 않" in error_msg or "invalid" in error_msg:
                logging.warning(f"⚠️ 해시태그 검색 실패 ({hashtag}): 토큰 문제 가능성")
            else:
                logging.warning(f"⚠️ 해시태그를 찾을 수 없습니다: {hashtag}")
                logging.warning(f"   💡 Instagram Graph API의 정책 변경으로 해시태그 검색이 제한되었을 수 있습니다.")
                logging.warning(f"   💡 대안: Selenium 크롤링 사용 (instagram_crawling_userposts.py)")
        
        logging.error(f"해시태그 검색 중 오류 발생 ({hashtag}): {error}")
        return None

    data = response.get("data", [])
    if not data:
        logging.warning(f"해당 해시태그를 찾을 수 없습니다: {hashtag}")
        return None

    hashtag_id = data[0].get("id")
    logging.info(f"해시태그 ID ({hashtag}): {hashtag_id}")
    return hashtag_id


def fetch_all_media(hashtag_id: str) -> List[dict]:
    media_url = f"https://graph.facebook.com/v24.0/{hashtag_id}/recent_media"
    params = {
        "user_id": INSTAGRAM_BUSINESS_ID,
        "fields": "id,caption,media_type,media_url,permalink,timestamp,like_count,comments_count",
        "access_token": ACCESS_TOKEN,
        "limit": 50
    }

    all_media = []
    next_url = media_url
    next_params = params

    while next_url:
        response = requests.get(next_url, params=next_params).json()
        if "error" in response:
            logging.error(f"미디어 조회 중 오류 발생: {response['error']}")
            break

        media_data = response.get("data", [])
        all_media.extend(media_data)

        paging = response.get("paging", {})
        next_url = paging.get("next")
        next_params = None  # next URL에 모든 파라미터가 포함되어 있음

        if not media_data:
            break

    return all_media


WHITESPACE_PATTERN = re.compile(r"\s+")
HASHTAG_PATTERN = re.compile(r"#([\w\d_]+)", re.UNICODE)


def clean_content(text: Optional[str]) -> str:
    if not text:
        return ""
    cleaned = text.replace("\u200b", " ").replace("\r", " ").replace("\n", " ")
    cleaned = WHITESPACE_PATTERN.sub(" ", cleaned).strip()
    return cleaned


def extract_hashtags(text: str) -> List[str]:
    return [f"#{tag}" for tag in HASHTAG_PATTERN.findall(text)]


def process_media_item(media_item: dict) -> dict:
    media_id = media_item.get("id")
    media_type = media_item.get("media_type")

    if media_type == "CAROUSEL_ALBUM":
        # 캐러셀 하위 미디어는 해시태그 검색 결과로는 조회할 수 없으므로 대표 URL만 저장
        media_urls = [media_item.get("media_url")] if media_item.get("media_url") else []
    else:
        media_url = media_item.get("media_url")
        media_urls = [media_url] if media_url else []

    content = clean_content(media_item.get("caption"))
    hashtags = extract_hashtags(content)
    content_count = len(content)
    hashtag_count = len(hashtags)

    processed = {
        "id": media_id,
        "media_type": media_type,
        "media_url": media_urls,
        "media_count": len(media_urls),
        "content": content,
        "hashtags": hashtags,
        "content_count": content_count,
        "hashtag_count": hashtag_count,
        "permalink": media_item.get("permalink"),
        "timestamp": media_item.get("timestamp"),
        "like_count": media_item.get("like_count"),
        "comments_count": media_item.get("comments_count")
    }

    return processed


hashtags = ["#독일피엠",
    "#피엠주스",
    "#액티바이즈",
    "#리스토레이트",
    "#피트라인",
    "#파워칵테일",
    "#탑쉐이프",
    "#부산피엠",
    "#여주피엠",
    "#광주피엠",
    "#성남피엠",
    "#천안피엠",
    "#파주피엠",
    "#대구피엠",
    "#경주피엠",
    "#김해피엠",
    "#수원피엠",
    "#인천피엠",
    "#남양주피엠",
    "#강서피엠",
    "#의정부피엠",
    "#서울피엠",
    "#피엠사업",
    "#피트라인앰버서더",
    "#피엠다이어트"]

# 로깅 초기화
setup_logging(str(BASE_DIR / "instagram.log"))

# Access Token 유효성 검증
logging.info("=" * 70)
logging.info("🔍 Access Token 유효성 검증 중...")
logging.info("=" * 70)
if not verify_access_token():
    logging.error("=" * 70)
    logging.error("❌ Access Token이 유효하지 않습니다. 스크립트를 종료합니다.")
    logging.error("=" * 70)
    exit(1)
logging.info("=" * 70)
logging.info("")

existing_data, permalink_index = load_existing_data()
logging.info(f"기존 데이터 로드 완료: {sum(len(media_map) for media_map in existing_data.values())}개 항목, {len(permalink_index)}개 고유 permalink")


for hashtag in hashtags:
    hashtag_id = fetch_hashtag_id(hashtag)
    if not hashtag_id:
        continue

    media_items = fetch_all_media(hashtag_id)
    logging.info(f"가져온 게시물 수 ({hashtag}): {len(media_items)}")

    hashtag_storage = existing_data.setdefault(hashtag, {})
    new_count = 0
    updated_count = 0
    duplicate_by_permalink_count = 0
    duplicate_by_media_id_count = 0

    for item in media_items:
        processed_item = process_media_item(item)
        media_id = processed_item.get("id")
        if not media_id:
            continue
        processed_item["hashtag"] = hashtag
        
        permalink = processed_item.get("permalink")
        shortcode = normalize_permalink(permalink) if permalink else None

        # 1. permalink 기준 중복 체크 (우선)
        duplicate_by_permalink = False
        if shortcode and shortcode in permalink_index:
            existing_item = permalink_index[shortcode]
            existing_hashtag = existing_item.get("hashtag")
            existing_media_id = existing_item.get("id")
            
            # 같은 permalink가 다른 해시태그에 있으면 중복
            if existing_hashtag != hashtag:
                duplicate_by_permalink = True
                duplicate_by_permalink_count += 1
                logging.info(f"⚠️ 중복 발견 (permalink 기준) - {hashtag}: permalink={permalink}, shortcode={shortcode}, 기존 해시태그={existing_hashtag}, 기존 media_id={existing_media_id}, 새 media_id={media_id}")
                # 중복이므로 스킵
                continue
            # 같은 해시태그에 같은 permalink가 있으면 media_id 기준으로 처리 (아래 로직으로)
        
        # 2. media_id 기준 중복 체크
        stored_item = hashtag_storage.get(media_id)

        if stored_item:
            duplicate_by_media_id_count += 1
            logging.info(f"🔄 중복 발견 (media_id 기준) - {hashtag}: media_id={media_id}, permalink={permalink}")
            
            # 기존 데이터와 새 데이터 병합
            # 단, media_url, media_count, media_caption, audio_caption은 기존 데이터 보존
            merged_item = {**stored_item, **processed_item}
            
            # media_url 보존 로직: 기존에 수집한 이미지가 더 많으면 보존
            existing_media_urls = stored_item.get("media_url", [])
            new_media_urls = processed_item.get("media_url", [])
            
            if isinstance(existing_media_urls, list) and len(existing_media_urls) > 1:
                # 기존에 instagram_extract_imgurl.py에서 수집한 데이터가 있으면 보존
                # 단, 새로운 URL이 있고 기존에 없으면 추가
                existing_urls_set = set(existing_media_urls)
                for new_url in new_media_urls:
                    if new_url and new_url not in existing_urls_set:
                        existing_media_urls.append(new_url)
                merged_item["media_url"] = existing_media_urls
                merged_item["media_count"] = len(existing_media_urls)
            elif isinstance(new_media_urls, list) and len(new_media_urls) > 0:
                # 기존 데이터가 없거나 1개 이하면 새 데이터 사용
                merged_item["media_url"] = new_media_urls
                merged_item["media_count"] = len(new_media_urls)
            
            # media_caption 보존 (instagram_extract_imgurl.py에서 OCR로 생성한 데이터, 리스트 형식)
            existing_media_caption = stored_item.get("media_caption", [])
            # 기존 media_caption이 문자열이면 리스트로 변환 (하위 호환성)
            if isinstance(existing_media_caption, str):
                existing_media_caption = [line.strip() for line in existing_media_caption.split("\n") if line.strip()]
            elif not isinstance(existing_media_caption, list):
                existing_media_caption = []
            
            if existing_media_caption:
                merged_item["media_caption"] = existing_media_caption
            
            # audio_caption 보존 (instagram_extract_audio_from_json.py에서 추출한 오디오 텍스트)
            existing_audio_caption = stored_item.get("audio_caption")
            if existing_audio_caption:
                merged_item["audio_caption"] = existing_audio_caption
            
            # is_video 보존 (instagram_extract_audio_from_json.py에서 설정한 비디오 여부)
            existing_is_video = stored_item.get("is_video")
            if existing_is_video:
                merged_item["is_video"] = existing_is_video
            
            hashtag_storage[media_id] = merged_item
            # permalink 인덱스도 업데이트
            if shortcode:
                permalink_index[shortcode] = merged_item
            updated_count += 1
        else:
            # 신규 항목
            hashtag_storage[media_id] = processed_item
            # permalink 인덱스에 추가
            if shortcode:
                permalink_index[shortcode] = processed_item
            new_count += 1
            logging.debug(f"✅ 신규 항목 추가 - {hashtag}: media_id={media_id}, permalink={permalink}")

    logging.info(f"처리 완료 ({hashtag}): 신규={new_count}개, 업데이트(media_id 중복)={updated_count}개, 스킵(permalink 중복)={duplicate_by_permalink_count}개")

save_data(existing_data)
total_posts = sum(len(media_map) for media_map in existing_data.values())
logging.info(f"총 {total_posts}개 게시물을 `{DATA_FILE}`에 저장했습니다.")