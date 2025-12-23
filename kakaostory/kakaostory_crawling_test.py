from __future__ import annotations
import json
import logging
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import quote, urlparse

from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.selenium_manager import SeleniumManager

# --------------------
# 환경 설정
# --------------------
HASHTAG_URL_TEMPLATE = "https://story.kakao.com/hashtag/{tag}"
HASHTAG_LIST = [
    "#독일피엠",
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
    "#피엠다이어트",
]
MAX_POSTS_PER_TAG: Optional[int] = None
HEADLESS_MODE = True
REFRESH_WINDOW_DAYS: Optional[int] = 3


def setup_logging(log_file: str = "kakaostory.log") -> None:
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


def build_driver() -> webdriver.Chrome:
    chrome_options = webdriver.ChromeOptions()
    chrome_binary_location: Optional[str] = None
    for chrome_path in (
        Path("/opt/google/chrome/chrome"),
        Path("/opt/google/chrome/google-chrome"),
        Path("/usr/bin/google-chrome"),
    ):
        if chrome_path.exists():
            chrome_binary_location = chrome_path.as_posix()
            chrome_options.binary_location = chrome_binary_location
            break
    chrome_options.add_argument("--disable-notifications")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_experimental_option(
        "prefs",
        {
            "profile.managed_default_content_settings.images": 2,
            "profile.default_content_setting_values.notifications": 2,
        },
    )
    if HEADLESS_MODE:
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--disable-gpu")

    manager_args = ["--browser", "chrome", "--skip-driver-in-path"]
    if chrome_binary_location:
        manager_args.extend(["--browser-path", chrome_binary_location])
    manager_result = SeleniumManager().binary_paths(manager_args)
    driver_path = manager_result.get("driver_path")
    if not driver_path:
        raise RuntimeError("Selenium Manager failed to locate a ChromeDriver binary.")

    service = Service(
        executable_path=driver_path,
        log_output="chromedriver.log",
        service_args=["--verbose"],
    )
    driver = webdriver.Chrome(service=service, options=chrome_options)
    driver.set_window_size(1280, 960)
    return driver


# --------------------
# 유틸 함수
# --------------------
def extract_shortcode(url: str) -> str:
    path_parts = urlparse(url).path.strip("/").split("/")
    return path_parts[-1] if path_parts else ""


def extract_user_id(url: str) -> str:
    path_parts = urlparse(url).path.strip("/").split("/")
    if len(path_parts) >= 2:
        return path_parts[-2]
    return ""


def parse_counts_from_thumbnail(item) -> Dict[str, int]:
    like_count = 0
    comment_count = 0

    try:
        empathy_container = item.find_element(By.CSS_SELECTOR, "span.cont_empathy")
        empathy_spans = empathy_container.find_elements(By.CSS_SELECTOR, "span.txt_empathy")
        if len(empathy_spans) >= 1:
            like_digits = re.findall(r"\d+", empathy_spans[0].text)
            like_count = int(like_digits[0]) if like_digits else 0
        if len(empathy_spans) >= 2:
            comment_digits = re.findall(r"\d+", empathy_spans[1].text)
            comment_count = int(comment_digits[0]) if comment_digits else 0
    except Exception:
        pass

    return {"like_count": like_count, "comment_count": comment_count}


def parse_datetime(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    raw = raw.strip()
    if not raw or raw.lower() in {"null", "true", "false"}:
        return None
    raw = raw.replace("오전", "AM").replace("오후", "PM")
    patterns = [
        "%Y년 %m월 %d일 %p %I:%M",
        "%Y년 %m월 %d일 %H:%M",
        "%m월 %d일 %p %I:%M",
        "%m월 %d일 %H:%M",
    ]
    for pattern in patterns:
        try:
            dt = datetime.strptime(raw, pattern)
            if "%Y" not in pattern:
                dt = dt.replace(year=datetime.now().year)
            return dt.isoformat()
        except ValueError:
            continue
    return raw


def clean_content(html_text: str, hashtags: List[str]) -> str:
    cleaned = html_text.replace("\xa0", " ")
    cleaned = cleaned.replace("&nbsp;", " ")
    cleaned = re.sub(r"<br\s*/?>", " ", cleaned)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    for tag in hashtags:
        cleaned = cleaned.replace(tag, " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def extract_video_urls_from_container(container) -> tuple[List[str], bool]:
    urls: List[str] = []
    include_thumbnail = False

    try:
        thumb_elem = container.find_element(By.CSS_SELECTOR, "img")
        thumbnail_url = thumb_elem.get_attribute("src") or thumb_elem.get_attribute("data-src")
        if thumbnail_url:
            urls.append(thumbnail_url)
            include_thumbnail = True
    except Exception:
        pass

    try:
        anchor_elem = container.find_element(By.CSS_SELECTOR, "a")
        video_url = anchor_elem.get_attribute("data-url") or anchor_elem.get_attribute("href")
        if video_url:
            urls.append(video_url)
    except Exception:
        pass

    return urls, include_thumbnail


def find_video_media(popup) -> tuple[List[str], bool]:
    video_urls: List[str] = []
    has_thumbnail = False

    containers = popup.find_elements(By.CSS_SELECTOR, "div._videoContainer")
    for container in containers:
        urls, include_thumbnail = extract_video_urls_from_container(container)
        if urls:
            video_urls.extend(urls)
            has_thumbnail = has_thumbnail or include_thumbnail

    if video_urls:
        return video_urls, has_thumbnail

    fallback_elements = popup.find_elements(By.CSS_SELECTOR, "div._videoContainer video, div._videoContainer source")
    fallback_urls = [
        elem.get_attribute("src")
        for elem in fallback_elements
        if elem.get_attribute("src")
    ]
    if fallback_urls:
        return fallback_urls, False

    return [], False


FIELD_ORDER = [
    "name",
    "user_id",
    "shortcode",
    "date",
    "media_type",
    "media_url",
    "media_count",
    "content",
    "content_count",
    "hashtag",
    "hashtag_count",
    "like_count",
    "comment_count",
]


def order_post_fields(post: Dict) -> Dict:
    ordered = {"p_num": post["p_num"]}
    # FIELD_ORDER에 정의된 필드를 우선순위대로 추가
    for key in FIELD_ORDER:
        if key in post:
            ordered[key] = post[key]
    # FIELD_ORDER에 없는 필드도 보존 (media_caption, user_num 등)
    for key, value in post.items():
        if key not in ordered and key != "p_num":
            ordered[key] = value
    return ordered


def should_refresh(record: Dict) -> bool:
    if REFRESH_WINDOW_DAYS is None:
        return True
    date_str = record.get("date")
    if not date_str:
        return True
    try:
        post_dt = datetime.fromisoformat(date_str)
    except ValueError:
        return True
    return datetime.now() - post_dt <= timedelta(days=REFRESH_WINDOW_DAYS)


def load_existing_posts(path: Path) -> tuple[Dict[str, Dict], int]:
    if not path.exists():
        return {}, 0

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logging.warning("⚠️ 기존 JSON을 읽는 중 오류가 발생했습니다. 새 파일을 생성합니다.")
        return {}, 0

    records: Dict[str, Dict] = {}
    max_p_num = 0

    for entry in data:
        shortcode = entry.get("shortcode")
        if not shortcode:
            continue
        p_num = entry.get("p_num")
        if isinstance(p_num, int):
            max_p_num = max(max_p_num, p_num)
        else:
            max_p_num += 1
            entry["p_num"] = max_p_num
        records[shortcode] = order_post_fields(entry)

    return records, max_p_num


def wait_for_popup(driver: webdriver.Chrome) -> Optional[webdriver.remote.webelement.WebElement]:
    popup_selectors = [
        "div.cover_wrapper",
        "div.cover",
        "div.layer_panel",
        "div.layer_cover",
    ]
    deadline = time.time() + 10
    while time.time() < deadline:
        for selector in popup_selectors:
            try:
                popup = driver.find_element(By.CSS_SELECTOR, selector)
                if popup.is_displayed():
                    return popup
            except Exception:
                continue
        time.sleep(0.2)
    return None


def close_popup(driver: webdriver.Chrome) -> None:
    close_selectors = [
        "div.cover_wrapper button.btn_close",
        "div.cover button.btn_close",
        "div.layer_panel button.btn_close",
        "button.btn_cover_close",
    ]
    for selector in close_selectors:
        try:
            close_btn = driver.find_element(By.CSS_SELECTOR, selector)
            driver.execute_script("arguments[0].click();", close_btn)
            WebDriverWait(driver, 5).until(
                EC.invisibility_of_element_located((By.CSS_SELECTOR, selector.split()[0]))
            )
            return
        except Exception:
            continue
    driver.execute_script(
        "const btn=document.querySelector('div.cover_wrapper button.btn_close')||document.querySelector('div.cover button.btn_close');"
        "btn?.click();"
    )
    time.sleep(0.5)


# --------------------
# 팝업 파싱
# --------------------
def extract_post_from_popup(
    driver: webdriver.Chrome,
    counts: Dict[str, int],
) -> Optional[Dict]:
    popup = wait_for_popup(driver)
    if popup is None:
        logging.warning("  → 팝업을 찾지 못했습니다. 건너뜁니다.")
        return None

    name = ""
    user_id = ""
    name_selectors = [
        "a.pf_name",
        "span.pf_name",
        "div.profile_area a",
        "div.profile_area span.txt_name",
        "div.profile_area strong.name",
        "div.cover_header a",
    ]
    for selector in name_selectors:
        try:
            WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, selector))
            )
            name_elem = popup.find_element(By.CSS_SELECTOR, selector)
            name_text = name_elem.get_attribute("innerText") or name_elem.text
            name_text = name_text.strip()
            if not name_text:
                continue
            name = name_text
            break
        except Exception:
            continue
    if not name:
        try:
            profile_block = popup.find_element(By.CSS_SELECTOR, "div.profile_area")
            profile_text = profile_block.text.strip()
            if profile_text:
                name = profile_text.splitlines()[0].strip()
        except Exception:
            pass

    try:
        time_elem = popup.find_element(By.CSS_SELECTOR, "span.time")
        timestamp_raw = (
            time_elem.get_attribute("title")
            or time_elem.get_attribute("data-tooltip")
            or time_elem.text
        )
    except Exception:
        timestamp_raw = ""

    date_value = parse_datetime(timestamp_raw)

    content_selectors = [
        "div._content",
        "div.txt_wrap div.txt_detail",
        "div.txt_wrap div.txt_inner",
    ]
    content_element = None
    content_html = ""
    for selector in content_selectors:
        try:
            WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, selector))
            )
            content_element = popup.find_element(By.CSS_SELECTOR, selector)
            content_html = content_element.get_attribute("innerHTML") or ""
            break
        except Exception:
            continue
    if content_element is None:
        logging.warning("  → 본문 요소를 찾지 못했습니다. 건너뜁니다.")
        return None
    hashtag_elements = popup.find_elements(By.CSS_SELECTOR, "a._decoratedHashtag")
    raw_hashtags = [elem.text.strip() for elem in hashtag_elements if elem.text.strip()]
    hashtags = sorted(set(raw_hashtags), key=raw_hashtags.index)
    hashtag_count = len(hashtags)

    content = clean_content(content_html, raw_hashtags)
    content_count = len(content)

    image_elements = popup.find_elements(By.CSS_SELECTOR, "div.img img")
    image_urls = [elem.get_attribute("src") for elem in image_elements if elem.get_attribute("src")]

    video_urls, has_video_thumbnail = find_video_media(popup)

    if video_urls:
        media_type = "video"
        media_urls = video_urls
    elif len(image_urls) > 1:
        media_type = "multi_image"
        media_urls = image_urls
    elif len(image_urls) == 1:
        media_type = "image"
        media_urls = image_urls
    else:
        media_type = "none"
        media_urls = []

    media_count = len(media_urls)
    if media_type == "video" and has_video_thumbnail:
        media_count = max(media_count - 1, 0)

    current_url = driver.current_url
    shortcode = extract_shortcode(current_url)
    user_id_from_url = extract_user_id(current_url)
    if user_id_from_url:
        user_id = user_id_from_url

    like_count = counts.get("like_count", 0)
    comment_count = counts.get("comment_count", 0)
    try:
        like_elem = popup.find_element(By.CSS_SELECTOR, "strong._likeCount")
        like_digits = re.findall(r"\d+", like_elem.text)
        like_count = int(like_digits[0]) if like_digits else like_count
    except Exception:
        pass
    try:
        comment_elem = popup.find_element(By.CSS_SELECTOR, "strong._commentCount")
        comment_digits = re.findall(r"\d+", comment_elem.text)
        comment_count = int(comment_digits[0]) if comment_digits else comment_count
    except Exception:
        pass

    return {
        "name": name,
        "user_id": user_id,
        "shortcode": shortcode,
        "date": date_value,
        "media_type": media_type,
        "media_url": media_urls,
        "media_count": media_count,
        "content": content,
        "content_count": content_count,
        "hashtag": hashtags,
        "hashtag_count": hashtag_count,
        "like_count": like_count,
        "comment_count": comment_count,
    }


# --------------------
# 메인 크롤링 루틴
# --------------------
def crawl_tag(
    driver: webdriver.Chrome,
    tag: str,
    limit: Optional[int],
    existing_shortcodes: set[str],
    processed_shortcodes: set[str],
) -> List[Dict]:
    encoded_tag = quote(tag)
    url = HASHTAG_URL_TEMPLATE.format(tag=encoded_tag)
    driver.get(url)

    try:
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.img_item")))
    except TimeoutException:
        logging.warning(f"[{tag}] 썸네일을 찾지 못했습니다. 건너뜁니다.")
        return []

    collected: List[Dict] = []
    seen_in_tag: set[str] = set()
    index = 0

    while limit is None or len(collected) < limit:
        items = driver.find_elements(By.CSS_SELECTOR, "div.img_item")

        if index >= len(items):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1)
            items = driver.find_elements(By.CSS_SELECTOR, "div.img_item")
            if index >= len(items):
                logging.info(f"[{tag}] 더 이상 항목이 없습니다.")
                break

        item = items[index]
        counts = parse_counts_from_thumbnail(item)

        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", item)

        click_target = None
        try:
            click_target = item.find_element(By.CSS_SELECTOR, "a, button")
        except Exception:
            click_target = item

        try:
            driver.execute_script("arguments[0].click();", click_target)
        except Exception:
            try:
                click_target.click()
            except Exception:
                ActionChains(driver).move_to_element(click_target).click().perform()

        post = extract_post_from_popup(driver, counts)
        if post:
            sc = post.get("shortcode")
            if not sc:
                logging.warning("  → shortcode를 확인하지 못했습니다.")
            elif sc in processed_shortcodes or sc in seen_in_tag:
                logging.info(f"  → 이미 처리한 shortcode {sc}입니다. 건너뜁니다.")
            else:
                seen_in_tag.add(sc)
                processed_shortcodes.add(sc)
                collected.append(post)
                limit_display = limit if limit is not None else "∞"
                status = "기존" if sc in existing_shortcodes else "신규"
                logging.info(
                    f"[{tag}] 수집 {len(collected)}/{limit_display} ({status}) → "
                    f"{post['shortcode']} (좋아요 {post['like_count']} / 댓글 {post['comment_count']})"
                )
        close_popup(driver)

        index += 1
        time.sleep(0.2)

    return collected


def main() -> None:
    # 파일 경로 (현재 파일 위치 기준)
    BASE_DIR = Path(__file__).parent
    setup_logging(str(BASE_DIR / "kakaostory.log"))
    driver = build_driver()

    output_path = BASE_DIR / "kakaostory_popup_posts.json"
    existing_records, max_p_num = load_existing_posts(output_path)
    existing_shortcodes = set(existing_records.keys())
    processed_shortcodes: set[str] = set()
    new_posts: List[Dict] = []
    updated_posts: List[Dict] = []

    try:
        for tag in HASHTAG_LIST:
            logging.info(f"\n===== 해시태그 '{tag}' 처리 시작 =====")
            posts = crawl_tag(
                driver,
                tag,
                MAX_POSTS_PER_TAG,
                existing_shortcodes,
                processed_shortcodes,
            )
            added = 0
            refreshed = 0
            for post in posts:
                shortcode = post.get("shortcode")
                if not shortcode:
                    continue

                if shortcode in existing_records:
                    current_record = dict(existing_records[shortcode])
                    if not should_refresh(current_record):
                        continue
                    changed = False

                    if post["like_count"] != current_record.get("like_count"):
                        current_record["like_count"] = post["like_count"]
                        changed = True
                    if post["comment_count"] != current_record.get("comment_count"):
                        current_record["comment_count"] = post["comment_count"]
                        changed = True

                    if changed:
                        updated_record = order_post_fields(current_record)
                        existing_records[shortcode] = updated_record
                        updated_posts.append(updated_record)
                        refreshed += 1
                else:
                    max_p_num += 1
                    post["p_num"] = max_p_num
                    ordered_post = order_post_fields(post)
                    existing_records[shortcode] = ordered_post
                    existing_shortcodes.add(shortcode)
                    new_posts.append(ordered_post)
                    added += 1
            logging.info(
                f"===== 해시태그 '{tag}' 처리 종료 (신규 {added}건, 갱신 {refreshed}건) ====="
            )
    finally:
        driver.quit()

    final_records = sorted(
        existing_records.values(), key=lambda record: record["p_num"]
    )

    output_path.write_text(
        json.dumps(final_records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    logging.info(
        f"\n신규 게시물 {len(new_posts)}건, 좋아요/댓글 갱신 {len(updated_posts)}건 반영 "
        f"(총 {len(final_records)}건)"
    )
    if new_posts:
        logging.info("\n추가된 게시물 미리보기:")
        logging.info(json.dumps(new_posts, ensure_ascii=False, indent=2))
    if updated_posts:
        logging.info("\n갱신된 게시물 미리보기:")
        logging.info(json.dumps(updated_posts, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()