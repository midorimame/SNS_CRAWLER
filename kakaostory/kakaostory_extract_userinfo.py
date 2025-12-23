from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import List, Optional

# 파일 경로 (현재 파일 위치 기준)
BASE_DIR = Path(__file__).parent
INPUT_PATH = BASE_DIR / "kakaostory_popup_posts.json"
OUTPUT_PATH = BASE_DIR / "kakaostory_user.json"
LOG_PATH = BASE_DIR / "kakaostory.log"
# user_num 추출 정규식: 핸드폰 번호(010, 011, 016, 017, 018, 019로 시작) 제외
# (?<!0(?:10|11|16|17|18|19)): 앞에 핸드폰 번호 패턴이 오지 않도록
# (?!\d): 뒤에 추가 숫자가 오지 않도록
USER_NUM_REGEX = r"(?:추천(?:아이디|인)?\s*)?(?<!0(?:10|11|16|17|18|19))((?:[678]\d{6})|[124]\d{7})(?!\d)"
FORCE_REPROCESS = False

# 로깅 설정: 콘솔과 파일 둘 다에 출력
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),  # 콘솔 출력
        logging.FileHandler(LOG_PATH, encoding="utf-8", mode="a"),  # 파일 출력 (추가 모드)
    ],
)
logger = logging.getLogger(__name__)

USER_NUM_PATTERN = re.compile(USER_NUM_REGEX, re.IGNORECASE)

# 핸드폰 번호 패턴: 010으로 시작하는 11자리 숫자 (점, 하이픈, 공백 포함 가능)
# 예: 01020026867, 010-5280-4990, 010 7753 9299, 010.4564.7102 등
PHONE_NUM_REGEX = r"0(?:10|11|16|17|18|19)[\s.\-]*\d{3,4}[\s.\-]*\d{4}"
PHONE_NUM_PATTERN = re.compile(PHONE_NUM_REGEX)

# SNS ID 패턴: ID만 있는 경우와 URL이 있는 경우 모두 처리
# 카카오톡: "카톡", "카카오톡", "카스" + ID 또는 URL
# 예: "카톡.카스 choeeunji94" 또는 "https://story.kakao.com/hongsool"
KAKAO_ID_REGEX = r"(?:카톡|카카오톡|카스)[.\s]+([a-zA-Z0-9._-]+)|https?://(?:story\.)?kakao\.com/([a-zA-Z0-9._-]+)"
# 인스타그램: "인스타", "인스타그램" + ID 또는 URL (프로필 링크만, 게시물 링크 제외)
# 예: "페북.인스타 choeeunji351" 또는 "https://instagram.com/hongsoollee"
# 게시물 링크(/reel/, /p/, /tv/, /stories/ 등)는 제외
INSTAGRAM_ID_REGEX = r"(?:인스타|인스타그램)[.\s]+(?:[가-힣a-zA-Z]+[.\s]+)?([a-zA-Z0-9._-]+)|https?://(?:www\.)?instagram\.com/(?!reel/|p/|tv/|stories/)([a-zA-Z0-9._@-]+)"
# 페이스북: "페북", "페이스북" + ID 또는 URL
# 예: "페북.인스타 choeeunji351" 또는 "https://www.facebook.com/hongsool"
# "페북.인스타 choeeunji351"에서 "페북" 다음에 점이 있고, 그 다음 "인스타"가 오고, 그 다음 공백이 있고, 그 다음 ID가 옴
FACEBOOK_ID_REGEX = r"(?:페북|페이스북)[.\s]+(?:인스타[.\s]+)?([a-zA-Z0-9._-]+)|https?://(?:www\.)?facebook\.com/([a-zA-Z0-9._-]+)"
# 유튜브: URL만 (ID만 있는 경우는 드물어서 URL만 처리)
# 예: "https://www.youtube.com/user/hongsool"
YOUTUBE_ID_REGEX = r"https?://(?:www\.)?youtube\.com/(?:user|c|channel)/([a-zA-Z0-9._-]+)"
# 틱톡: URL만
# 예: "https://tiktok.com/@user2165925241150"
TIKTOK_ID_REGEX = r"https?://(?:www\.)?tiktok\.com/([@a-zA-Z0-9._-]+)"
# 네이버 블로그: URL만
# 예: "https://blog.naver.com/blackjackx21"
NBLOG_ID_REGEX = r"https?://blog\.naver\.com/([a-zA-Z0-9._-]+)"

KAKAO_ID_PATTERN = re.compile(KAKAO_ID_REGEX, re.IGNORECASE)
INSTAGRAM_ID_PATTERN = re.compile(INSTAGRAM_ID_REGEX, re.IGNORECASE)
FACEBOOK_ID_PATTERN = re.compile(FACEBOOK_ID_REGEX, re.IGNORECASE)
YOUTUBE_ID_PATTERN = re.compile(YOUTUBE_ID_REGEX, re.IGNORECASE)
TIKTOK_ID_PATTERN = re.compile(TIKTOK_ID_REGEX, re.IGNORECASE)
NBLOG_ID_PATTERN = re.compile(NBLOG_ID_REGEX, re.IGNORECASE)


def extract_user_number(content: str, media_caption: str, name: str) -> Optional[str]:
    """content, media_caption, name에서 user_num 추출 (핸드폰 번호 제외)"""
    if not USER_NUM_REGEX:
        return None

    combined = "\n".join(
        part for part in (name, content, media_caption) if part
    )
    
    # 모든 매치를 찾아서 핸드폰 번호가 아닌 것을 선택
    matches = list(USER_NUM_PATTERN.finditer(combined))
    if not matches:
        return None
    
    # 각 매치가 핸드폰 번호의 일부인지 확인
    for match in matches:
        matched_text = match.group(1) if match.groups() else match.group(0)
        start_pos = match.start()
        end_pos = match.end()
        
        # 앞뒤로 핸드폰 번호 패턴이 있는지 확인
        # 앞 3자리 확인 (010, 011, 016, 017, 018, 019)
        if start_pos >= 3:
            prev_chars = combined[max(0, start_pos - 3):start_pos]
            # 숫자로만 이루어진 경우에만 확인
            if prev_chars.isdigit() and prev_chars in ['010', '011', '016', '017', '018', '019']:
                # 뒤에 추가 숫자가 있는지 확인 (핸드폰 번호일 가능성)
                if end_pos < len(combined) and combined[end_pos:end_pos+4].isdigit():
                    # 핸드폰 번호의 일부로 판단, 스킵
                    continue
        
        # 뒤에 추가 숫자가 많이 있는지 확인 (핸드폰 번호일 가능성)
        if end_pos < len(combined):
            next_chars = combined[end_pos:end_pos+4]
            if next_chars.isdigit() and len(next_chars) >= 3:
                # 핸드폰 번호의 일부일 가능성이 높음, 스킵
                continue
        
        # 유효한 user_num으로 판단
        return matched_text
    
    # 모든 매치가 핸드폰 번호의 일부로 판단됨
    return None


def has_user_pattern(text: str) -> bool:
    """텍스트에 user_num 패턴이 있는지 확인"""
    return bool(text and USER_NUM_PATTERN.search(text))


def find_user_num_by_user_id(posts: List[dict], user_id: str) -> Optional[str]:
    """user_id로 기존 게시물에서 user_num을 찾기"""
    if not user_id:
        return None
    for record in posts:
        if record.get("user_id") == user_id:
            user_num = record.get("user_num")
            if user_num:
                return user_num
    return None


def propagate_user_num(posts: List[dict], target_post: dict, user_num: str) -> int:
    """동일 이름을 가진 다른 게시물에 user_num을 전파"""
    target_name = target_post.get("name")
    if not target_name:
        return 0
    target_shortcode = target_post.get("shortcode")
    updated = 0
    for record in posts:
        if record is target_post:
            continue
        if record.get("name") != target_name:
            continue
        current = record.get("user_num")
        if current and current != user_num:
            continue
        if not current:
            record["user_num"] = user_num
            updated += 1
    return updated


def propagate_user_num_by_user_id(posts: List[dict], target_post: dict, user_num: str) -> int:
    """user_id가 일치하는 다른 게시물에 user_num을 전파"""
    target_user_id = target_post.get("user_id")
    if not target_user_id:
        return 0
    updated = 0
    for record in posts:
        if record is target_post:
            continue
        if record.get("user_id") != target_user_id:
            continue
        current = record.get("user_num")
        if current and current != user_num:
            logger.debug(
                "  → user_id=%s의 기존 user_num(%s)과 다름, 전파 스킵 (새 user_num=%s)",
                target_user_id,
                current,
                user_num,
            )
            continue
        if not current:
            record["user_num"] = user_num
            updated += 1
            logger.debug(
                "  → user_id=%s의 게시물(p_num=%s)에 user_num=%s 전파",
                target_user_id,
                record.get("p_num"),
                user_num,
            )
    return updated


def process_post_user_num(post: dict, all_posts: List[dict], content: str = "", media_caption: str = "", name: str = "", force: bool = False) -> bool:
    """게시물에서 user_num 추출 및 적용 (기존 값 보존)"""
    existing_user_num = post.get("user_num")
    user_id = post.get("user_id")
    updated = False

    # 기존 값이 있고 force가 False이면 스킵
    if existing_user_num and not force:
        logger.debug("  → user_num이 이미 존재하여 스킵: %s", existing_user_num)
        return False

    # user_id로 기존 user_num 찾기 (속도 최적화, 기존 값이 없을 때만)
    if not existing_user_num and user_id:
        found_user_num = find_user_num_by_user_id(all_posts, user_id)
        if found_user_num:
            post["user_num"] = found_user_num
            existing_user_num = found_user_num
            updated = True
            logger.info("  → user_id=%s로 기존 user_num=%s 발견하여 적용", user_id, found_user_num)

    # user_num 추출 시도 (기존 값이 없거나 force가 True일 때)
    if not content:
        content = post.get("content", "")
    if not media_caption:
        media_caption = post.get("media_caption", "")
    if not name:
        name = post.get("name", "")
    
    user_num = extract_user_number(content, media_caption, name)
    if user_num:
        if not existing_user_num:
            post["user_num"] = user_num
            updated = True
            logger.info("  → user_num 추출됨: %s", user_num)
        elif force and user_num != existing_user_num:
            post["user_num"] = user_num
            updated = True
            logger.info("  → user_num 업데이트됨: %s (기존: %s)", user_num, existing_user_num)
    elif existing_user_num and not user_num and not force:
        logger.debug("  → user_num 추출 실패, 기존 값 유지: %s", existing_user_num)

    return updated


def get_unique_users(posts: List[dict]) -> List[dict]:
    """중복 없이 name, user_id 필드를 가진 사용자 목록 반환"""
    seen = set()
    unique_users = []
    
    for post in posts:
        name = post.get("name")
        user_id = post.get("user_id")
        
        # name과 user_id 조합으로 중복 확인
        key = (name, user_id)
        if key not in seen:
            seen.add(key)
            unique_users.append({
                "name": name,
                "user_id": user_id
            })
    
    return unique_users


def extract_phone_number(user_id: str, content: str, media_caption: str, hashtags: List[str]) -> Optional[str]:
    """user_id, content, media_caption, hashtag에서 핸드폰 번호 추출 및 정규화 (11자리 숫자)"""
    if not PHONE_NUM_PATTERN:
        return None
    
    # hashtags를 문자열로 변환
    hashtags_str = " ".join(hashtags) if hashtags else ""
    
    # 모든 필드를 합쳐서 검색
    combined = "\n".join(
        part for part in (user_id or "", content or "", media_caption or "", hashtags_str) if part
    )
    
    # 모든 매치 찾기
    matches = list(PHONE_NUM_PATTERN.finditer(combined))
    if not matches:
        return None
    
    # 첫 번째 매치 사용
    match = matches[0]
    matched_text = match.group(0)
    
    # 숫자만 추출
    digits_only = re.sub(r'\D', '', matched_text)
    
    # 11자리인지 확인 (010으로 시작하는 11자리)
    if len(digits_only) == 11 and digits_only.startswith('010'):
        return digits_only
    elif len(digits_only) == 10 and digits_only.startswith('10'):
        # 010이 빠진 경우 (10XXXXXXXX)
        return '0' + digits_only
    # 11자리를 넘어가는 경우는 잘못된 매치이므로 None 반환
    
    return None


def extract_kakao_id(content: str) -> Optional[str]:
    """content에서 카카오톡 ID 추출 (ID만 또는 URL)"""
    if not KAKAO_ID_PATTERN or not content:
        return None
    
    match = KAKAO_ID_PATTERN.search(content)
    if not match:
        return None
    
    # 첫 번째 그룹(ID만) 또는 두 번째 그룹(URL에서 추출)
    return match.group(1) or match.group(2) if match.groups() else None


def extract_instagram_id(content: str) -> Optional[str]:
    """content에서 인스타그램 ID 추출 (ID만 또는 URL, 게시물 링크 제외)"""
    if not INSTAGRAM_ID_PATTERN or not content:
        return None
    
    # 모든 매치 찾기
    matches = list(INSTAGRAM_ID_PATTERN.finditer(content))
    if not matches:
        return None
    
    for match in matches:
        # URL에서 추출한 경우, 게시물 링크인지 확인
        matched_text = match.group(0)
        if 'instagram.com' in matched_text.lower():
            # 게시물 링크 패턴 제외 (/reel/, /p/, /tv/, /stories/)
            if any(pattern in matched_text.lower() for pattern in ['/reel/', '/p/', '/tv/', '/stories/']):
                continue
        
        # 첫 번째 그룹(ID만) 또는 두 번째 그룹(URL에서 추출)
        # 그룹이 None이 아닌 것을 선택
        instagram_id = None
        if match.groups():
            # 그룹 1 (ID만 있는 경우) 또는 그룹 2 (URL에서 추출)
            instagram_id = match.group(1) if match.group(1) else match.group(2)
        
        if instagram_id:
            return instagram_id
    
    return None


def extract_facebook_id(content: str) -> Optional[str]:
    """content에서 페이스북 ID 추출 (ID만 또는 URL)"""
    if not FACEBOOK_ID_PATTERN or not content:
        return None
    
    match = FACEBOOK_ID_PATTERN.search(content)
    if not match:
        return None
    
    # 첫 번째 그룹(ID만) 또는 두 번째 그룹(URL에서 추출)
    # 그룹이 None이 아닌 것을 선택
    if match.groups():
        # 그룹 1 (ID만 있는 경우) 또는 그룹 2 (URL에서 추출)
        facebook_id = match.group(1) if match.group(1) else match.group(2)
        return facebook_id
    
    return None


def extract_youtube_id(content: str) -> Optional[str]:
    """content에서 유튜브 ID 추출"""
    if not YOUTUBE_ID_PATTERN or not content:
        return None
    
    match = YOUTUBE_ID_PATTERN.search(content)
    if not match:
        return None
    
    return match.group(1) if match.groups() else match.group(0)


def extract_tiktok_id(content: str) -> Optional[str]:
    """content에서 틱톡 ID 추출 (URL에서)"""
    if not TIKTOK_ID_PATTERN or not content:
        return None
    
    match = TIKTOK_ID_PATTERN.search(content)
    if not match:
        return None
    
    return match.group(1) if match.groups() else None


def extract_nblog_id(content: str) -> Optional[str]:
    """content에서 네이버 블로그 ID 추출 (URL에서)"""
    if not NBLOG_ID_PATTERN or not content:
        return None
    
    match = NBLOG_ID_PATTERN.search(content)
    if not match:
        return None
    
    return match.group(1) if match.groups() else None


def process_post_userinfo(post: dict, force: bool = False) -> bool:
    """게시물에서 phone_num 및 SNS ID 추출 및 저장 (기존 값 보존)"""
    updated = False
    
    user_id = post.get("user_id", "")
    content = post.get("content", "")
    media_caption = post.get("media_caption", "")
    hashtags = post.get("hashtags", [])
    if not isinstance(hashtags, list):
        hashtags = []
    
    # 핸드폰 번호 추출 (기존 값이 있고 force가 False이면 스킵)
    existing_phone_num = post.get("phone_num")
    if not existing_phone_num or force:
        phone_num = extract_phone_number(user_id, content, media_caption, hashtags)
        if phone_num:
            if not existing_phone_num:
                post["phone_num"] = phone_num
                updated = True
                logger.debug("  → phone_num 추출됨: %s", phone_num)
            elif force and phone_num != existing_phone_num:
                post["phone_num"] = phone_num
                updated = True
                logger.debug("  → phone_num 업데이트됨: %s (기존: %s)", phone_num, existing_phone_num)
    
    # SNS ID 추출 (content에서만, 기존 값이 있고 force가 False이면 스킵)
    existing_kakao_id = post.get("kakao_id")
    if not existing_kakao_id or force:
        kakao_id = extract_kakao_id(content)
        if kakao_id:
            if not existing_kakao_id:
                post["kakao_id"] = kakao_id
                updated = True
                logger.debug("  → kakao_id 추출됨: %s", kakao_id)
            elif force and kakao_id != existing_kakao_id:
                post["kakao_id"] = kakao_id
                updated = True
                logger.debug("  → kakao_id 업데이트됨: %s (기존: %s)", kakao_id, existing_kakao_id)
    
    existing_instagram_id = post.get("instagram_id")
    if not existing_instagram_id or force:
        instagram_id = extract_instagram_id(content)
        if instagram_id:
            if not existing_instagram_id:
                post["instagram_id"] = instagram_id
                updated = True
                logger.debug("  → instagram_id 추출됨: %s", instagram_id)
            elif force and instagram_id != existing_instagram_id:
                post["instagram_id"] = instagram_id
                updated = True
                logger.debug("  → instagram_id 업데이트됨: %s (기존: %s)", instagram_id, existing_instagram_id)
    
    existing_facebook_id = post.get("facebook_id")
    if not existing_facebook_id or force:
        facebook_id = extract_facebook_id(content)
        if facebook_id:
            if not existing_facebook_id:
                post["facebook_id"] = facebook_id
                updated = True
                logger.debug("  → facebook_id 추출됨: %s", facebook_id)
            elif force and facebook_id != existing_facebook_id:
                post["facebook_id"] = facebook_id
                updated = True
                logger.debug("  → facebook_id 업데이트됨: %s (기존: %s)", facebook_id, existing_facebook_id)
    
    existing_youtube_id = post.get("youtube_id")
    if not existing_youtube_id or force:
        youtube_id = extract_youtube_id(content)
        if youtube_id:
            if not existing_youtube_id:
                post["youtube_id"] = youtube_id
                updated = True
                logger.debug("  → youtube_id 추출됨: %s", youtube_id)
            elif force and youtube_id != existing_youtube_id:
                post["youtube_id"] = youtube_id
                updated = True
                logger.debug("  → youtube_id 업데이트됨: %s (기존: %s)", youtube_id, existing_youtube_id)
    
    existing_tiktok_id = post.get("tiktok_id")
    if not existing_tiktok_id or force:
        tiktok_id = extract_tiktok_id(content)
        if tiktok_id:
            if not existing_tiktok_id:
                post["tiktok_id"] = tiktok_id
                updated = True
                logger.debug("  → tiktok_id 추출됨: %s", tiktok_id)
            elif force and tiktok_id != existing_tiktok_id:
                post["tiktok_id"] = tiktok_id
                updated = True
                logger.debug("  → tiktok_id 업데이트됨: %s (기존: %s)", tiktok_id, existing_tiktok_id)
    
    # 네이버 블로그 ID 추출 (기존 값이 있고 force가 False이면 스킵)
    existing_nblog_id = post.get("nblog_id")
    if not existing_nblog_id or force:
        nblog_id = extract_nblog_id(content)
        if nblog_id:
            if not existing_nblog_id:
                post["nblog_id"] = nblog_id
                updated = True
                logger.debug("  → nblog_id 추출됨: %s", nblog_id)
            elif force and nblog_id != existing_nblog_id:
                post["nblog_id"] = nblog_id
                updated = True
                logger.debug("  → nblog_id 업데이트됨: %s (기존: %s)", nblog_id, existing_nblog_id)
    
    return updated


def process_posts_user_num(posts: List[dict], targets: List[dict]) -> int:
    """게시물들에서 user_num 추출 및 전파"""
    propagated_total = 0

    for post in targets:
        user_num = post.get("user_num")
        if user_num:
            # 이름 기반 전파
            propagated_by_name = propagate_user_num(posts, post, user_num)
            if propagated_by_name:
                logger.info("  → 동일 이름 게시물 %d건에 user_num 전파", propagated_by_name)
                propagated_total += propagated_by_name

            # user_id 기반 전파
            propagated_by_user_id = propagate_user_num_by_user_id(posts, post, user_num)
            if propagated_by_user_id:
                logger.info("  → 동일 user_id 게시물 %d건에 user_num 전파", propagated_by_user_id)
                propagated_total += propagated_by_user_id

    return propagated_total


def load_existing_users() -> tuple[dict, dict]:
    """기존 kakaostory_user.json 파일 로드
    Returns:
        (users_by_id: dict, users_by_name: dict) - user_id를 키로 하는 딕셔너리와 name을 키로 하는 딕셔너리
    """
    if not OUTPUT_PATH.exists():
        return {}, {}
    
    try:
        with open(OUTPUT_PATH, "r", encoding="utf-8") as f:
            users_list = json.load(f)
            if not isinstance(users_list, list):
                logger.warning("kakaostory_user.json 형식이 올바르지 않습니다. 새로 생성합니다.")
                return {}, {}
            
            # user_id를 키로 하는 딕셔너리와 name을 키로 하는 딕셔너리로 변환
            users_by_id = {}
            users_by_name = {}
            
            for user in users_list:
                user_id = user.get("user_id")
                name = user.get("name")
                
                if user_id:
                    users_by_id[user_id] = user
                
                # name만 있고 user_id가 없는 경우도 보존
                if name and not user_id:
                    # 같은 name이 여러 개 있을 수 있으므로 리스트로 저장
                    if name not in users_by_name:
                        users_by_name[name] = []
                    users_by_name[name].append(user)
            
            logger.info(f"기존 사용자 데이터 로드: user_id 있음 {len(users_by_id)}명, name만 있음 {sum(len(v) for v in users_by_name.values())}명")
            return users_by_id, users_by_name
    except json.JSONDecodeError:
        logger.warning("kakaostory_user.json 파일의 JSON 형식이 올바르지 않습니다. 새로 생성합니다.")
        return {}, {}
    except Exception as e:
        logger.warning(f"kakaostory_user.json 로드 실패: {e}. 새로 생성합니다.")
        return {}, {}


def extract_user_info_from_post(post: dict, all_posts: List[dict]) -> Optional[dict]:
    """게시물에서 사용자 정보 추출"""
    user_id = post.get("user_id")
    name = post.get("name")
    
    if not user_id:
        return None
    
    # 사용자 정보 딕셔너리 생성
    user_info = {
        "user_id": user_id,
        "name": name,
    }
    
    # user_num 추출
    content = post.get("content", "")
    media_caption = post.get("media_caption", "")
    user_num = extract_user_number(content, media_caption, name or "")
    if user_num:
        user_info["user_num"] = user_num
    
    # phone_num 추출
    hashtags = post.get("hashtags", [])
    if not isinstance(hashtags, list):
        hashtags = []
    phone_num = extract_phone_number(user_id, content, media_caption, hashtags)
    if phone_num:
        user_info["phone_num"] = phone_num
    
    # SNS ID 추출
    kakao_id = extract_kakao_id(content)
    if kakao_id:
        user_info["kakao_id"] = kakao_id
    
    instagram_id = extract_instagram_id(content)
    if instagram_id:
        user_info["instagram_id"] = instagram_id
    
    facebook_id = extract_facebook_id(content)
    if facebook_id:
        user_info["facebook_id"] = facebook_id
    
    youtube_id = extract_youtube_id(content)
    if youtube_id:
        user_info["youtube_id"] = youtube_id
    
    tiktok_id = extract_tiktok_id(content)
    if tiktok_id:
        user_info["tiktok_id"] = tiktok_id
    
    nblog_id = extract_nblog_id(content)
    if nblog_id:
        user_info["nblog_id"] = nblog_id
    
    return user_info


def merge_user_info(existing: dict, new: dict, force: bool = False) -> dict:
    """기존 사용자 정보와 새 정보를 병합 (기존 값 보존)"""
    merged = existing.copy() if existing else {}
    
    # user_id는 항상 포함 (필수 필드)
    if new.get("user_id"):
        merged["user_id"] = new.get("user_id")
    
    # name은 항상 업데이트 (없으면 추가)
    if new.get("name") and (not merged.get("name") or force):
        merged["name"] = new.get("name")
    
    # 다른 필드들은 기존 값이 없을 때만 추가
    fields = ["user_num", "phone_num", "kakao_id", "instagram_id", "facebook_id", "youtube_id", "tiktok_id", "nblog_id"]
    for field in fields:
        new_value = new.get(field)
        if new_value:
            if not merged.get(field):
                merged[field] = new_value
            elif force and merged.get(field) != new_value:
                merged[field] = new_value
    
    return merged


def main() -> None:
    """메인 함수: 게시물에서 사용자 정보 추출하여 kakaostory_user.json에 누적 저장"""
    logger.info("=" * 80)
    logger.info("프로그램 시작 - 로그 파일: %s", LOG_PATH.absolute())
    logger.info("=" * 80)
    
    # 기존 사용자 데이터 로드
    existing_users_by_id, existing_users_by_name = load_existing_users()
    
    # 게시물 데이터 로드
    posts = json.loads(INPUT_PATH.read_text(encoding="utf-8"))
    logger.info(f"총 {len(posts)}개 게시물 로드 완료")
    
    # user_id별로 게시물 그룹화
    posts_by_user = {}
    # name별로도 게시물 그룹화 (name만 있는 기존 데이터를 위한 매칭)
    posts_by_name = {}
    
    for post in posts:
        user_id = post.get("user_id")
        name = post.get("name")
        
        if user_id:
            if user_id not in posts_by_user:
                posts_by_user[user_id] = []
            posts_by_user[user_id].append(post)
        
        # name으로도 그룹화 (name만 있는 기존 데이터 매칭용)
        if name:
            if name not in posts_by_name:
                posts_by_name[name] = []
            posts_by_name[name].append(post)
    
    logger.info(f"고유 사용자 수 (user_id 기준): {len(posts_by_user)}명")
    
    # 이미 존재하는 user_id 필터링
    if FORCE_REPROCESS:
        target_user_ids = list(posts_by_user.keys())
        logger.info("강제 재처리 모드: 모든 사용자 처리")
    else:
        target_user_ids = [uid for uid in posts_by_user.keys() if uid not in existing_users_by_id]
        skipped_count = len(posts_by_user) - len(target_user_ids)
        if skipped_count > 0:
            logger.info(f"이미 존재하는 사용자 {skipped_count}명 스킵")
    
    logger.info(f"처리할 사용자: {len(target_user_ids)}명")
    
    new_users = {}
    updated_count = 0
    
    # 각 사용자에 대해 정보 추출
    for idx, user_id in enumerate(target_user_ids, start=1):
        user_posts = posts_by_user[user_id]
        name = user_posts[0].get("name") if user_posts else None
        
        if idx % 50 == 0:  # 50명마다 로그 출력
            logger.info(
                "▶ %d번째 사용자 처리 시작 (user_id=%s, name=%s, 게시물 %d개)",
                idx,
                user_id,
                name or "<없음>",
                len(user_posts),
            )
        
        try:
            # 모든 게시물에서 정보 추출 (가장 많은 정보를 가진 것 선택)
            user_info = None
            for post in user_posts:
                extracted = extract_user_info_from_post(post, posts)
                if extracted:
                    if user_info is None:
                        user_info = extracted
                    else:
                        # 정보 병합 (기존 값 보존)
                        user_info = merge_user_info(user_info, extracted, force=False)
            
            if user_info:
                # 기존 사용자 정보와 병합
                existing_user = existing_users_by_id.get(user_id, {})
                merged_user = merge_user_info(existing_user, user_info, force=FORCE_REPROCESS)
                new_users[user_id] = merged_user
                updated_count += 1
                
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("사용자 처리 실패 (user_id=%s): %s", user_id, exc)
            continue
    
    # name만 있는 기존 사용자에 user_id 추가 시도
    name_only_updated = 0
    matched_name_only_users = set()  # user_id가 추가된 name만 있는 사용자 추적
    
    for name, name_only_users in existing_users_by_name.items():
        if name in posts_by_name:
            # 게시물에서 해당 name의 user_id 찾기
            name_posts = posts_by_name[name]
            # 같은 name의 게시물들에서 가장 많이 나타나는 user_id 사용
            user_id_counts = {}
            for post in name_posts:
                user_id = post.get("user_id")
                if user_id:
                    user_id_counts[user_id] = user_id_counts.get(user_id, 0) + 1
            
            if user_id_counts:
                # 가장 많이 나타나는 user_id 선택
                most_common_user_id = max(user_id_counts.items(), key=lambda x: x[1])[0]
                
                # name만 있는 사용자에 user_id 추가
                for name_user in name_only_users:
                    if not name_user.get("user_id"):
                        # 게시물에서 정보 추출
                        user_info = None
                        for post in name_posts:
                            if post.get("user_id") == most_common_user_id:
                                extracted = extract_user_info_from_post(post, posts)
                                if extracted:
                                    if user_info is None:
                                        user_info = extracted
                                    else:
                                        user_info = merge_user_info(user_info, extracted, force=False)
                        
                        if user_info:
                            # 이미 existing_users_by_id에 있으면 병합, 없으면 새로 추가
                            if most_common_user_id in existing_users_by_id:
                                # 기존 사용자 정보와 name만 있는 사용자 정보 병합
                                existing_user = existing_users_by_id[most_common_user_id]
                                merged_user = merge_user_info(existing_user, name_user, force=False)
                                merged_user = merge_user_info(merged_user, user_info, force=False)
                                # 기존 사용자 정보 업데이트
                                existing_users_by_id[most_common_user_id] = merged_user
                                name_only_updated += 1
                                matched_name_only_users.add((name, id(name_user)))  # 추적용
                                logger.info(f"  → name만 있던 사용자 '{name}'에 user_id={most_common_user_id} 추가됨 (기존 사용자와 병합)")
                            elif most_common_user_id not in new_users:
                                # 새로 추가
                                merged_user = merge_user_info(name_user, user_info, force=False)
                                new_users[most_common_user_id] = merged_user
                                name_only_updated += 1
                                matched_name_only_users.add((name, id(name_user)))  # 추적용
                                logger.info(f"  → name만 있던 사용자 '{name}'에 user_id={most_common_user_id} 추가됨")
    
    # 기존 사용자와 새 사용자 병합
    all_users = existing_users_by_id.copy()
    all_users.update(new_users)
    
    # name만 있고 user_id가 없는 기존 사용자도 보존 (매칭되지 않은 경우)
    for name, name_only_users in existing_users_by_name.items():
        for name_user in name_only_users:
            if not name_user.get("user_id"):
                # 매칭되지 않은 name만 있는 사용자만 보존
                if (name, id(name_user)) not in matched_name_only_users:
                    # user_id가 없는 항목은 name을 임시 키로 사용하여 보존
                    # (나중에 매칭될 수 있으므로)
                    temp_key = f"_name_only_{name}_{len(all_users)}"
                    all_users[temp_key] = name_user
    
    # 리스트로 변환하여 저장 (중복 제거)
    users_list = []
    name_only_list = []
    seen_user_ids = set()  # 중복 제거용
    seen_name_only = set()  # name만 있는 사용자 중복 제거용
    
    for key, user_info in all_users.items():
        user_id = user_info.get("user_id")
        name = user_info.get("name")
        
        if user_id and not key.startswith("_name_only_"):
            # user_id가 있는 정상 사용자 (중복 제거)
            if user_id not in seen_user_ids:
                user_info["user_id"] = user_id
                users_list.append(user_info)
                seen_user_ids.add(user_id)
            else:
                logger.debug(f"중복 user_id 제거: {user_id} (name: {name})")
        elif key.startswith("_name_only_"):
            # name만 있는 사용자 (임시 키 제거, 중복 제거)
            user_info.pop("user_id", None)  # 혹시 있을 수 있는 빈 user_id 제거
            # 같은 name이 이미 있는지 확인
            name_key = name or ""
            if name_key not in seen_name_only:
                name_only_list.append(user_info)
                seen_name_only.add(name_key)
            else:
                logger.debug(f"중복 name만 있는 사용자 제거: {name}")
    
    # user_id가 있는 사용자 먼저, 그 다음 name만 있는 사용자
    users_list.extend(name_only_list)
    
    # 결과 저장
    if updated_count > 0 or len(new_users) > 0 or name_only_updated > 0:
        OUTPUT_PATH.write_text(json.dumps(users_list, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(
            "kakaostory_user.json 저장 완료 (새 사용자 %d명, name만 있던 사용자에 user_id 추가 %d명, 총 %d명)",
            len(new_users),
            name_only_updated,
            len(users_list),
        )
    else:
        logger.info("추가된 사용자가 없습니다.")


if __name__ == "__main__":
    main()

