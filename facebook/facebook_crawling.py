import json
import time
import re
import logging
import shutil
from pathlib import Path
from datetime import datetime, timedelta
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from dotenv import load_dotenv
import os
import pickle

# .env 파일에서 로그인 정보 불러오기
load_dotenv('/home/pmi/venvs/source_code/.env')
EMAIL = os.getenv("FB_EMAIL")
PASSWORD = os.getenv("FB_PASSWORD")

# 디버깅: 로그인 정보 로드 확인
if not EMAIL:
    print("⚠️ FB_EMAIL이 .env 파일에 없거나 로드되지 않았습니다.")
if not PASSWORD:
    print("⚠️ FB_PASSWORD가 .env 파일에 없거나 로드되지 않았습니다.")

# 파일 경로 (현재 파일 위치 기준)
BASE_DIR = Path(__file__).parent
MEDIA_JSON = BASE_DIR / "facebook_media.json"
COOKIE_PATH = BASE_DIR / "facebook_cookies.pkl"
LOG_FILE = BASE_DIR / "facebook.log"

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# 해시태그 리스트 (테스트용)
HASHTAGS = [
    "#독일피엠",
    # 추가 해시태그는 여기에 추가
]

# 테스트 모드
TEST_MODE = True  # True면 첫 번째 해시태그의 상위 40개 게시물만 처리

# Selenium WebDriver 설정
def setup_driver():
    """Selenium WebDriver 설정 (Chrome 경로 자동 탐지)"""
    # Chrome 브라우저 경로 후보 리스트 (우선순위 순)
    chrome_path_candidates = []
    
    # 1. which 명령어로 PATH에서 찾기 (가장 신뢰할 수 있음)
    for cmd in ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser"]:
        chrome_cmd = shutil.which(cmd)
        if chrome_cmd:
            chrome_path_candidates.append(Path(chrome_cmd))
            logger.info(f"✅ Chrome 경로 발견: {chrome_cmd}")
    
    # 2. 일반적인 설치 경로 확인
    for chrome_path in (
        Path("/opt/google/chrome/chrome"),
        Path("/opt/google/chrome/google-chrome"),
        Path("/usr/bin/google-chrome"),
        Path("/usr/bin/google-chrome-stable"),
        Path("/usr/bin/chromium"),
        Path("/usr/bin/chromium-browser"),
    ):
        if chrome_path.exists() and os.access(chrome_path, os.X_OK):
            if chrome_path not in chrome_path_candidates:
                chrome_path_candidates.append(chrome_path)
                logger.info(f"✅ Chrome 경로 발견: {chrome_path}")
    
    if not chrome_path_candidates:
        error_msg = "실행 가능한 Chrome 브라우저를 찾을 수 없습니다."
        logger.error(f"❌ {error_msg}")
        logger.error("💡 해결 방법:")
        logger.error("   1. Chrome 브라우저가 설치되어 있는지 확인하세요")
        logger.error("   2. 다음 명령어로 Chrome을 설치할 수 있습니다:")
        logger.error("      sudo apt-get update && sudo apt-get install -y google-chrome-stable")
        logger.error("   3. 또는 Chromium을 설치할 수 있습니다:")
        logger.error("      sudo apt-get install -y chromium-browser")
        raise RuntimeError(error_msg)
    
    # 각 경로를 시도하여 실제로 작동하는지 확인
    last_error = None
    for chrome_path in chrome_path_candidates:
        chrome_binary_location = chrome_path.as_posix()
        logger.info(f"🔍 Chrome 경로 시도: {chrome_binary_location}")
        
        chrome_options = Options()
        chrome_options.binary_location = chrome_binary_location
        
        # Headless 모드 설정 (리눅스 환경 대응) - 로그인 확인용으로 주석처리
        # chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--display=:99")  # Xvfb 디스플레이 사용
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_argument("--disable-notifications")  # 알림 권한 팝업 차단
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        # Windows User-Agent로 변경 (더 일반적)
        chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        
        try:
            # ChromeDriver 자동 관리 시도 (webdriver-manager가 설치되어 있는 경우)
            try:
                from webdriver_manager.chrome import ChromeDriverManager
                service = Service(ChromeDriverManager().install())
                logger.info("✅ ChromeDriverManager를 사용하여 ChromeDriver 설정")
            except ImportError:
                # webdriver-manager가 없으면 기본 Service 사용
                service = Service()
                logger.info("ℹ️ ChromeDriverManager 없음, 기본 Service 사용")
        except Exception as e:
            logger.warning(f"⚠️ ChromeDriverManager 설정 실패, 기본 Service 사용: {e}")
            service = Service()
        
        try:
            driver = webdriver.Chrome(service=service, options=chrome_options)
            driver.set_window_size(1920, 1080)
            logger.info(f"✅ Chrome WebDriver 초기화 성공: {chrome_binary_location}")
            
            # WebDriver 속성 제거 (봇 감지 방지)
            driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
                'source': '''
                    Object.defineProperty(navigator, 'webdriver', {
                        get: () => undefined
                    });
                '''
            })
            
            return driver
        except Exception as e:
            last_error = e
            logger.warning(f"⚠️ 경로 실패: {chrome_binary_location}")
            continue

def login_facebook(driver):
    """Facebook 로그인 (쿠키가 없을 경우)"""
    if COOKIE_PATH.exists():
        try:
            logger.info("🍪 저장된 쿠키 로드 중...")
            driver.get("https://www.facebook.com")
            time.sleep(2)
            
            with open(COOKIE_PATH, "rb") as f:
                cookies = pickle.load(f)
            
            for cookie in cookies:
                try:
                    driver.add_cookie(cookie)
                except Exception as e:
                    logger.warning(f"⚠️ 쿠키 추가 실패: {e}")
                    continue
            
            driver.refresh()
            time.sleep(3)
            
            # 로그인 상태 확인
            current_url = driver.current_url
            if "login" not in current_url.lower() and "facebook.com" in current_url:
                logger.info("✅ 쿠키로 로그인 성공")
                return True
        except Exception as e:
            logger.warning(f"⚠️ 쿠키 로드 실패: {e}")
    
    # 쿠키가 없거나 실패한 경우 수동 로그인
    if EMAIL and PASSWORD:
        logger.info("🔐 Facebook 로그인 시도 중...")
        
        # 먼저 Facebook 메인 페이지로 접속 (봇 감지 방지)
        logger.info("📱 Facebook 메인 페이지 접속 중...")
        driver.get("https://www.facebook.com")
        time.sleep(3)
        
        # 현재 URL 확인
        current_url = driver.current_url
        logger.info(f"📎 메인 페이지 URL: {current_url}")
        
        # data: URL 체크
        if current_url.startswith("data:"):
            logger.error("❌ data: URL로 리다이렉트되었습니다.")
            logger.info("🔄 다시 시도 중...")
            time.sleep(2)
            driver.get("https://www.facebook.com")
            time.sleep(5)
            current_url = driver.current_url
            logger.info(f"📎 재시도 후 URL: {current_url}")
            
            if current_url.startswith("data:"):
                logger.error("❌ 여전히 data: URL입니다. Facebook이 봇을 감지했을 수 있습니다.")
                return False
        
        # 로그인 페이지로 이동
        logger.info("📱 로그인 페이지로 이동 중...")
        driver.get("https://www.facebook.com/login/")
        
        # 페이지 로드 대기
        try:
            WebDriverWait(driver, 15).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
            logger.info("✅ 페이지 로드 완료")
        except TimeoutException:
            logger.warning("⚠️ 페이지 로드 타임아웃, 계속 진행...")
        
        # 추가 대기 (JavaScript 실행 대기)
        time.sleep(5)
        
        # 현재 URL 확인 및 디버깅
        current_url = driver.current_url
        logger.info(f"📎 로그인 페이지 URL: {current_url}")
        
        if current_url.startswith("data:"):
            logger.error("❌ 로그인 페이지에서 data: URL로 리다이렉트되었습니다.")
            logger.info("🔍 페이지 소스 일부 확인 중...")
            try:
                page_source_preview = driver.page_source[:500]
                logger.info(f"페이지 소스 (처음 500자): {page_source_preview}")
            except Exception as e:
                logger.warning(f"페이지 소스 확인 실패: {e}")
            return False
        
        # body 태그가 있는지 확인
        try:
            body = driver.find_element(By.TAG_NAME, "body")
            logger.info("✅ body 태그 발견")
        except NoSuchElementException:
            logger.error("❌ body 태그를 찾을 수 없습니다.")
            return False
        
        try:
            # 이메일 입력 필드 찾기 (한국어/영어 모두 지원)
            email_selectors = [
                "input[type='text'][aria-label='이메일 또는 전화번호']",
                "input[type='text'][aria-label='Email or phone number']",
                "input[type='text'][placeholder='이메일 또는 전화번호']",
                "input[type='text'][placeholder='Email or phone number']",
                "input[type='text'][id='email']",
                "input[type='text'][name='email']",
            ]
            
            email_input = None
            for selector in email_selectors:
                try:
                    email_input = WebDriverWait(driver, 5).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                    )
                    logger.info(f"✅ 이메일 입력 필드 발견: '{selector}'")
                    break
                except (TimeoutException, NoSuchElementException):
                    continue
            
            if not email_input:
                logger.error("❌ 이메일 입력 필드를 찾을 수 없습니다.")
                return False
            
            email_input.clear()
            email_input.send_keys(EMAIL)
            logger.info("✅ 이메일 입력 완료")
            time.sleep(1)
            
            # 비밀번호 입력 필드 찾기 (한국어/영어 모두 지원)
            password_selectors = [
                "input[type='password'][aria-label='비밀번호']",
                "input[type='password'][aria-label='Password']",
                "input[type='password'][placeholder='비밀번호']",
                "input[type='password'][placeholder='Password']",
                "input[type='password'][id='pass']",
                "input[type='password'][name='pass']",
            ]
            
            password_input = None
            for selector in password_selectors:
                try:
                    password_input = driver.find_element(By.CSS_SELECTOR, selector)
                    logger.info(f"✅ 비밀번호 입력 필드 발견: '{selector}'")
                    break
                except NoSuchElementException:
                    continue
            
            if not password_input:
                logger.error("❌ 비밀번호 입력 필드를 찾을 수 없습니다.")
                return False
            
            password_input.clear()
            password_input.send_keys(PASSWORD)
            logger.info("✅ 비밀번호 입력 완료")
            time.sleep(1)
            
            # 로그인 버튼 클릭
            login_button_selectors = [
                "button[name='login'][type='submit']",
                "button[type='submit'][name='login']",
                "button[type='submit']",
                "input[type='submit'][name='login']",
            ]
            
            login_button = None
            for selector in login_button_selectors:
                try:
                    login_button = driver.find_element(By.CSS_SELECTOR, selector)
                    logger.info(f"✅ 로그인 버튼 발견: '{selector}'")
                    break
                except NoSuchElementException:
                    continue
            
            if not login_button:
                logger.error("❌ 로그인 버튼을 찾을 수 없습니다.")
                return False
            
            login_button.click()
            logger.info("✅ 로그인 버튼 클릭")
            
            # 로그인 완료 대기
            time.sleep(5)
            
            # 로그인 성공 확인
            current_url = driver.current_url
            if "login" not in current_url.lower() and "facebook.com" in current_url:
                logger.info("✅ 로그인 성공")
            else:
                logger.warning("⚠️ 로그인 실패로 보입니다. 계속 진행합니다...")
            
            # 쿠키 저장
            try:
                cookies = driver.get_cookies()
                with open(COOKIE_PATH, "wb") as f:
                    pickle.dump(cookies, f)
                logger.info("✅ 쿠키 저장 완료")
                return True
            except Exception as e:
                logger.error(f"⚠️ 쿠키 저장 실패: {e}")
                return False
        except TimeoutException:
            logger.error("❌ 로그인 폼 요소를 찾을 수 없습니다. (타임아웃)")
            return False
        except NoSuchElementException as e:
            logger.error(f"❌ 로그인 폼 요소를 찾을 수 없습니다: {e}")
            return False
        except Exception as e:
            logger.error(f"❌ 로그인 실패: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    else:
        logger.warning("⚠️ 로그인 정보가 없습니다. 수동으로 로그인해주세요.")
        logger.info("📱 Facebook 메인 페이지 접속 중...")
        driver.get("https://www.facebook.com")
        time.sleep(3)
        
        # 현재 URL 확인
        current_url = driver.current_url
        logger.info(f"📎 현재 URL: {current_url}")
        
        if current_url.startswith("data:"):
            logger.error("❌ data: URL로 리다이렉트되었습니다.")
            logger.info("🔄 다시 시도 중...")
            time.sleep(2)
            driver.get("https://www.facebook.com")
            time.sleep(5)
            current_url = driver.current_url
            logger.info(f"📎 재시도 후 URL: {current_url}")
        
        logger.info("👤 브라우저에서 수동으로 로그인해주세요.")
        input("로그인 완료 후 Enter를 눌러주세요...")
        
        # 로그인 후 URL 확인
        current_url = driver.current_url
        logger.info(f"📎 로그인 후 URL: {current_url}")
        
        if current_url.startswith("data:"):
            logger.error("❌ 여전히 data: URL입니다.")
            return False
        
        try:
            cookies = driver.get_cookies()
            with open(COOKIE_PATH, "wb") as f:
                pickle.dump(cookies, f)
            logger.info("✅ 쿠키 저장 완료")
            return True
        except Exception as e:
            logger.error(f"⚠️ 쿠키 저장 실패: {e}")
            return False

def extract_post_data(driver, post_element):
    """
    게시물 요소에서 데이터 추출
    
    Args:
        driver: WebDriver 인스턴스
        post_element: 게시물 div 요소 또는 인덱스 (int)
    
    Returns:
        dict: 게시물 데이터
    """
    # post_element가 인덱스인 경우 요소를 다시 찾기
    if isinstance(post_element, int):
        try:
            articles = driver.find_elements(By.CSS_SELECTOR, "div[role='article']")
            if len(articles) > post_element:
                post_element = articles[post_element]
                logger.info(f"  🔄 인덱스로 요소 재찾기 완료 (인덱스: {post_element})")
            else:
                logger.warning(f"  ⚠️ 인덱스로 요소를 찾을 수 없음 (인덱스: {post_element}, 전체 개수: {len(articles)})")
                # None을 반환하지 않고 빈 dict 반환 (audio_caption, media_caption은 초기화하지 않음)
                return {
                    "user_name": None,
                    "datetime": None,
                    "content": None,
                    "hashtags": [],
                    "like_count": 0,
                    "comments_count": 0,
                    "content_count": 0,
                    "hashtag_count": 0,
                    "share_count": 0,
                    "media_urls": [],
                    "media_count": 0,
                    # audio_caption과 media_caption은 초기화하지 않음
                    "user_num": None
                }
        except Exception as e:
            logger.warning(f"  ⚠️ 인덱스로 요소 재찾기 실패: {e}")
            # None을 반환하지 않고 빈 dict 반환 (audio_caption, media_caption은 초기화하지 않음)
            return {
                "user_name": None,
                "datetime": None,
                "content": None,
                "hashtags": [],
                "like_count": 0,
                "comments_count": 0,
                "content_count": 0,
                "hashtag_count": 0,
                "share_count": 0,
                "media_urls": [],
                "media_count": 0,
                # audio_caption과 media_caption은 초기화하지 않음
                "user_num": None
            }
    
    # post_element가 유효한지 확인 (stale element 방지)
    try:
        # 요소가 유효한지 확인하기 위해 간단한 속성 접근 시도
        _ = post_element.tag_name
    except Exception:
        # 요소가 stale한 경우 다시 찾기 시도
        logger.warning("  ⚠️ post_element가 stale 상태, 재찾기 시도...")
        try:
            # 현재 URL이 해시태그 페이지인지 확인
            current_url = driver.current_url
            if "hashtag" in current_url or "search" in current_url:
                articles = driver.find_elements(By.CSS_SELECTOR, "div[role='article']")
                if articles:
                    # 첫 번째 article 사용 (정확한 매칭은 어려우므로)
                    post_element = articles[0]
                    logger.info("  🔄 stale 요소 재찾기 완료 (첫 번째 article 사용)")
                else:
                    logger.warning("  ⚠️ article 요소를 찾을 수 없음")
                    # None을 반환하지 않고 빈 dict 반환 (audio_caption, media_caption은 초기화하지 않음)
                    return {
                        "user_name": None,
                        "datetime": None,
                        "content": None,
                        "hashtags": [],
                        "like_count": 0,
                        "comments_count": 0,
                        "content_count": 0,
                        "hashtag_count": 0,
                        "share_count": 0,
                        "media_urls": [],
                        "media_count": 0,
                        # audio_caption과 media_caption은 초기화하지 않음
                        "user_num": None
                    }
            else:
                logger.warning(f"  ⚠️ 현재 페이지가 해시태그 페이지가 아님: {current_url}")
                # None을 반환하지 않고 빈 dict 반환 (audio_caption, media_caption은 초기화하지 않음)
                return {
                    "user_name": None,
                    "datetime": None,
                    "content": None,
                    "hashtags": [],
                    "like_count": 0,
                    "comments_count": 0,
                    "content_count": 0,
                    "hashtag_count": 0,
                    "share_count": 0,
                    "media_urls": [],
                    "media_count": 0,
                    # audio_caption과 media_caption은 초기화하지 않음
                    "user_num": None
                }
        except Exception as e:
            logger.warning(f"  ⚠️ stale 요소 재찾기 실패: {e}")
            # None을 반환하지 않고 빈 dict 반환 (audio_caption, media_caption은 초기화하지 않음)
            return {
                "user_name": None,
                "datetime": None,
                "content": None,
                "hashtags": [],
                "like_count": 0,
                "comments_count": 0,
                "content_count": 0,
                "hashtag_count": 0,
                "share_count": 0,
                "media_urls": [],
                "media_count": 0,
                # audio_caption과 media_caption은 초기화하지 않음
                "user_num": None
            }
    
    # 가상화된 요소 처리: 콘텐츠가 로드될 때까지 대기
    def wait_for_content_load(element, max_wait=5):
        """요소의 콘텐츠가 로드될 때까지 대기하는 함수"""
        try:
            # 요소를 뷰포트로 스크롤하여 콘텐츠 로드 유도
            driver.execute_script("arguments[0].scrollIntoView({block: 'center', behavior: 'auto'});", element)
            time.sleep(1)  # 스크롤 후 대기
            
            # 콘텐츠가 로드될 때까지 대기
            wait_interval = 0.5
            waited = 0
            
            while waited < max_wait:
                # textContent 길이 확인
                text_content = driver.execute_script("return arguments[0].textContent || arguments[0].innerText || '';", element)
                text_content = text_content.strip()
                
                # 실제 콘텐츠 요소가 있는지 확인 (user_name, content 등)
                has_content = driver.execute_script("""
                    var element = arguments[0];
                    if (!element) return false;
                    
                    // user_name 요소 확인
                    var profileName = element.querySelector('[data-ad-rendering-role="profile_name"]');
                    if (profileName) return true;
                    
                    // content 요소 확인
                    var storyMessage = element.querySelector('[data-ad-comet-preview="message"]');
                    if (storyMessage) return true;
                    
                    // textContent 길이 확인
                    var text = element.textContent || element.innerText || '';
                    text = text.trim();
                    if (text.length > 50) return true;
                    
                    return false;
                """, element)
                
                if has_content:
                    logger.info(f"  ✅ 요소 콘텐츠 로드 완료 (길이: {len(text_content)}자)")
                    return True
                
                time.sleep(wait_interval)
                waited += wait_interval
            
            if waited >= max_wait:
                logger.warning("  ⚠️ 요소 콘텐츠 로드 대기 시간 초과")
            return False
        except Exception as e:
            logger.warning(f"  ⚠️ 콘텐츠 로드 대기 중 오류: {e}")
            return False
    
    try:
        # 가상화 여부 확인 (더 강력한 체크)
        needs_wait = driver.execute_script("""
            var element = arguments[0];
            if (!element) return true; // 요소가 없으면 대기 필요
            
            // data-virtualized 속성 확인
            var virtualized = element.getAttribute('data-virtualized');
            if (virtualized === 'true') {
                return true;
            }
            
            // 자식 요소 중 data-virtualized="true" 확인
            var children = element.querySelectorAll('[data-virtualized="true"]');
            if (children.length > 0) {
                return true;
            }
            
            // textContent가 거의 비어있는지 확인
            var text = element.textContent || element.innerText || '';
            text = text.trim();
            if (text.length < 50) {
                return true; // 콘텐츠가 부족하면 대기 필요
            }
            
            // 실제 콘텐츠 요소가 있는지 확인
            var profileName = element.querySelector('[data-ad-rendering-role="profile_name"]');
            var storyMessage = element.querySelector('[data-ad-comet-preview="message"]');
            if (!profileName && !storyMessage) {
                return true; // 주요 요소가 없으면 대기 필요
            }
            
            return false;
        """, post_element)
        
        if needs_wait:
            logger.info("  ℹ️ 요소 콘텐츠 로드를 위해 뷰포트로 스크롤 및 대기...")
            wait_for_content_load(post_element)
    except Exception as e:
        logger.debug(f"  ℹ️ 가상화된 요소 확인 중 오류 (무시): {e}")
    
    post_data = {
        "user_name": None,
        "datetime": None,
        "content": None,
        "hashtags": [],
        "like_count": 0,
        "comments_count": 0,
        "content_count": 0,
        "hashtag_count": 0,
        "share_count": 0,
        "media_urls": [],
        "media_count": 0,
        # audio_caption과 media_caption은 초기화하지 않음 (기존 분석 결과 보존을 위해)
        # save_to_json에서 기존 항목과 병합할 때 보존됨
        "user_num": None
    }
    
    try:
        # 1. user_name 추출
        # <div data-ad-rendering-role="profile_name"> a[role='link']에서 직접 추출 (우선)
        logger.info("  🔍 user_name 추출 중...")
        try:
            user_name = None
            
            # 방법 1: JavaScript로 직접 텍스트 추출 (가장 확실한 방법)
            try:
                user_name_js = driver.execute_script("""
                    var article = arguments[0];
                    var profileName = article.querySelector('div[data-ad-rendering-role="profile_name"]');
                    if (!profileName) return null;
                    
                    // a[role='link'] 요소 찾기
                    var link = profileName.querySelector('a[role="link"]');
                    if (link) {
                        // textContent로 직접 텍스트 추출
                        var text = link.textContent || link.innerText || '';
                        text = text.trim();
                        // "· 팔로우" 제거
                        text = text.replace(/\\s*·\\s*팔로우.*$/, '');
                        text = text.replace(/\\n/g, ' ').replace(/\\r/g, ' ');
                        text = text.replace(/\\s+/g, ' ').trim();
                        if (text) return text;
                    }
                    
                    // 차선책: profile_name의 첫 번째 텍스트 노드
                    var textNodes = [];
                    var walker = document.createTreeWalker(
                        profileName,
                        NodeFilter.SHOW_TEXT,
                        null,
                        false
                    );
                    var node;
                    while (node = walker.nextNode()) {
                        var text = node.textContent.trim();
                        if (text && !text.match(/^[·\\s]*$/)) {
                            textNodes.push(text);
                        }
                    }
                    if (textNodes.length > 0) {
                        var result = textNodes[0].replace(/\\s*·\\s*팔로우.*$/, '');
                        result = result.replace(/\\n/g, ' ').replace(/\\r/g, ' ');
                        result = result.replace(/\\s+/g, ' ').trim();
                        return result || null;
                    }
                    
                    return null;
                """, post_element)
                
                if user_name_js:
                    user_name = user_name_js
                    logger.info(f"    ✅ user_name (JavaScript): {user_name}")
            except Exception as e:
                logger.debug(f"    ℹ️ JavaScript 추출 실패: {e}")
            
            # 방법 2: CSS 셀렉터로 추출 (JavaScript 실패 시)
            if not user_name:
                user_name_selectors = [
                    "div[data-ad-rendering-role='profile_name'] a[role='link']",  # a 요소에서 직접 추출
                    "div[data-ad-rendering-role='profile_name'] a[role='link'] span",  # span이 있는 경우
                    "div[data-ad-rendering-role='profile_name'] a[role='link'] b span",  # b > span 구조
                    "div[data-ad-rendering-role='profile_name'] span",  # span만 있는 경우
                    "div[data-ad-rendering-role='profile_name']",  # 차선책
                ]
                
                for idx, selector in enumerate(user_name_selectors, 1):
                    try:
                        user_name_element = post_element.find_element(By.CSS_SELECTOR, selector)
                        # textContent를 JavaScript로 직접 가져오기
                        try:
                            user_name = driver.execute_script("return arguments[0].textContent || arguments[0].innerText || '';", user_name_element)
                            user_name = user_name.strip()
                        except:
                            user_name = user_name_element.text.strip()
                        
                        if user_name:
                            # 불필요한 텍스트 제거 ("· 팔로우", 줄바꿈 등)
                            user_name_original = user_name
                            user_name = user_name.replace('\n', ' ').replace('\r', ' ')
                            # "· 팔로우" 패턴 제거
                            user_name = re.sub(r'\s*·\s*팔로우.*$', '', user_name)
                            # 연속된 공백을 하나로 정리
                            user_name = ' '.join(user_name.split())
                            user_name = user_name.strip()
                            if user_name:
                                logger.info(f"    ✅ user_name (셀렉터 #{idx}): {user_name}")
                                break
                            else:
                                logger.warning(f"    ⚠️ 셀렉터 #{idx}에서 찾았지만 텍스트가 비어있음 (원본: '{user_name_original}')")
                    except NoSuchElementException:
                        logger.debug(f"    ℹ️ 셀렉터 #{idx} 실패: {selector}")
                        continue
                    except Exception as e:
                        logger.warning(f"    ⚠️ 셀렉터 #{idx} 오류: {e}")
                        continue
            
            if user_name:
                post_data["user_name"] = user_name
            else:
                # 디버깅: post_element 내부에 profile_name 관련 요소가 있는지 확인
                try:
                    profile_name_elements = post_element.find_elements(By.CSS_SELECTOR, "div[data-ad-rendering-role='profile_name']")
                    if profile_name_elements:
                        logger.warning(f"    ⚠️ user_name을 찾을 수 없습니다. (profile_name 요소는 {len(profile_name_elements)}개 발견됨)")
                        # 첫 번째 요소의 HTML 전체 출력 (디버깅용)
                        try:
                            profile_html = driver.execute_script("return arguments[0].outerHTML;", profile_name_elements[0])
                            logger.warning(f"    📋 profile_name 요소 HTML 전체:")
                            logger.warning(f"       {profile_html}")
                            
                            # a[role='link'] 요소가 있는지 확인
                            try:
                                link_elements = profile_name_elements[0].find_elements(By.CSS_SELECTOR, "a[role='link']")
                                if link_elements:
                                    logger.warning(f"    📋 a[role='link'] 요소 {len(link_elements)}개 발견:")
                                    for idx, link in enumerate(link_elements, 1):
                                        link_text = driver.execute_script("return arguments[0].textContent;", link)
                                        link_html = driver.execute_script("return arguments[0].outerHTML;", link)
                                        logger.warning(f"       {idx}. 텍스트: '{link_text}'")
                                        logger.warning(f"          HTML: {link_html[:200]}")
                                else:
                                    logger.warning(f"    ⚠️ a[role='link'] 요소를 찾을 수 없습니다.")
                            except Exception as e:
                                logger.warning(f"    ⚠️ a[role='link'] 검색 실패: {e}")
                        except:
                            pass
                    else:
                        logger.warning("    ⚠️ user_name을 찾을 수 없습니다. (profile_name 요소도 없음)")
                except Exception as e:
                    logger.warning(f"    ⚠️ user_name을 찾을 수 없습니다. (디버깅 실패: {e})")
        except Exception as e:
            logger.warning(f"    ⚠️ user_name 추출 실패: {e}")
        
        # 2. datetime 추출
        # <a aria-label="XXXX년 X월 XX일">에서 aria-label 값 추출
        logger.info("  🔍 datetime 추출 중...")
        try:
            datetime_str = None
            
            # 방법 1: CSS 셀렉터로 직접 찾기 (더 빠름)
            # 우선: 연도 포함된 날짜 찾기
            try:
                datetime_element = post_element.find_element(By.CSS_SELECTOR, "a[aria-label*='년'][aria-label*='월'][aria-label*='일']")
                datetime_str = datetime_element.get_attribute("aria-label")
                if datetime_str:
                    logger.info(f"    ✅ 셀렉터로 datetime 찾음 (연도 포함): {datetime_str}")
            except NoSuchElementException:
                # 차선책: 연도 없이 월/일만 있는 날짜 찾기
                try:
                    datetime_element = post_element.find_element(By.CSS_SELECTOR, "a[aria-label*='월'][aria-label*='일']")
                    datetime_str = datetime_element.get_attribute("aria-label")
                    if datetime_str and '년' not in datetime_str:
                        logger.info(f"    ✅ 셀렉터로 datetime 찾음 (연도 없음): {datetime_str}")
                    elif datetime_str:
                        # 연도가 포함되어 있으면 이미 위에서 찾았을 것
                        pass
                except NoSuchElementException:
                    pass
            except Exception as e:
                logger.debug(f"    셀렉터 방식 실패: {e}")
            
            # 방법 2: JavaScript로 직접 찾기 (백업) - 연도 포함 또는 연도 없음 모두 찾기
            if not datetime_str:
                try:
                    datetime_str = driver.execute_script("""
                        var article = arguments[0];
                        var elements = article.querySelectorAll('[aria-label]');
                        
                        // 우선: 연도 포함된 날짜 찾기
                        for (var i = 0; i < elements.length; i++) {
                            var ariaLabel = elements[i].getAttribute('aria-label');
                            if (ariaLabel && ariaLabel.includes('년') && ariaLabel.includes('월') && ariaLabel.includes('일')) {
                                return ariaLabel;
                            }
                        }
                        
                        // 차선책: 연도 없이 월/일만 있는 날짜 찾기
                        for (var i = 0; i < elements.length; i++) {
                            var ariaLabel = elements[i].getAttribute('aria-label');
                            if (ariaLabel && ariaLabel.includes('월') && ariaLabel.includes('일') && !ariaLabel.includes('년')) {
                                return ariaLabel;
                            }
                        }
                        
                        return null;
                    """, post_element)
                    if datetime_str:
                        logger.info(f"    ✅ JavaScript로 datetime 찾음: {datetime_str}")
                except Exception as e:
                    logger.debug(f"    JavaScript 방식 실패: {e}")
            
            if datetime_str:
                # 정규식으로 년, 월, 일 추출
                # 패턴 1: 연도 포함 (예: "2024년 6월 24일", "2024년 06월 24일", "2024년 6월 4일")
                date_pattern_with_year = r'(\d{1,4})년\s*(\d{1,2})월\s*(\d{1,2})일'
                match = re.search(date_pattern_with_year, datetime_str)
                
                if match:
                    year = int(match.group(1))
                    month = int(match.group(2))
                    day = int(match.group(3))
                else:
                    # 패턴 2: 연도 없음 (예: "6월 24일", "06월 24일", "6월 4일")
                    date_pattern_without_year = r'(\d{1,2})월\s*(\d{1,2})일'
                    match = re.search(date_pattern_without_year, datetime_str)
                    
                    if match:
                        # 연도가 없으면 현재 연도 사용
                        current_year = datetime.now().year
                        year = current_year
                        month = int(match.group(1))
                        day = int(match.group(2))
                        logger.info(f"    ℹ️ 연도 없음, 현재 연도({year}년) 사용: {datetime_str} → {year}년 {month}월 {day}일")
                    else:
                        logger.warning(f"    ⚠️ 날짜 패턴을 찾을 수 없습니다: {datetime_str}")
                        match = None
                
                if match:
                    # datetime 객체 생성
                    try:
                        post_datetime = datetime(year, month, day)
                        post_data["datetime"] = post_datetime.isoformat()
                        logger.info(f"    ✅ datetime: {post_data['datetime']}")
                    except ValueError as e:
                        logger.warning(f"    ⚠️ datetime 변환 실패: {year}년 {month}월 {day}일 - {e}")
                        # 변환 실패 시 상대 시간 패턴 검색으로 진행
                        datetime_str = None
                else:
                    # 날짜 패턴 파싱 실패 시 상대 시간 패턴 검색으로 진행
                    datetime_str = None
            
            # datetime_str이 없거나 날짜 패턴 파싱 실패한 경우, 상대 시간 패턴 검색
            if not datetime_str or 'datetime' not in post_data or post_data.get('datetime') is None:
                if not datetime_str:
                    logger.warning("    ⚠️ datetime aria-label을 찾을 수 없습니다.")
                else:
                    logger.warning("    ⚠️ 날짜 패턴 파싱 실패, 상대 시간 패턴 검색 시도...")
                
                # 추가 시도: 모든 aria-label에서 날짜 패턴 또는 상대 시간 패턴 찾기
                try:
                    all_aria_labels = driver.execute_script("""
                        var article = arguments[0];
                        var elements = article.querySelectorAll('[aria-label]');
                        var labels = [];
                        for (var i = 0; i < elements.length; i++) {
                            var label = elements[i].getAttribute('aria-label');
                            if (label) {
                                labels.push(label);
                            }
                        }
                        return labels;
                    """, post_element)
                    
                    # 우선: 날짜 패턴이 있는 aria-label 찾기 (월/일 포함, 하지만 이미지 설명 제외)
                    date_labels = []
                    for label in all_aria_labels:
                        # 이미지 설명 제외 (너무 긴 텍스트나 특정 키워드 포함)
                        if len(label) > 100 or '이미지일 수 있음' in label or '문구:' in label:
                            continue
                        if '월' in label and '일' in label:
                            # 실제 날짜 패턴인지 확인 (정규식으로 검증)
                            if re.search(r'\d{1,2}월\s*\d{1,2}일', label):
                                date_labels.append(label)
                    
                    if date_labels:
                        # 첫 번째 날짜 패턴 사용
                        datetime_str = date_labels[0]
                        logger.info(f"    ℹ️ 추가 검색으로 datetime 찾음: {datetime_str}")
                        
                        # 정규식으로 년, 월, 일 추출
                        date_pattern_with_year = r'(\d{1,4})년\s*(\d{1,2})월\s*(\d{1,2})일'
                        match = re.search(date_pattern_with_year, datetime_str)
                        
                        if match:
                            year = int(match.group(1))
                            month = int(match.group(2))
                            day = int(match.group(3))
                        else:
                            date_pattern_without_year = r'(\d{1,2})월\s*(\d{1,2})일'
                            match = re.search(date_pattern_without_year, datetime_str)
                            
                            if match:
                                current_year = datetime.now().year
                                year = current_year
                                month = int(match.group(1))
                                day = int(match.group(2))
                                logger.info(f"    ℹ️ 연도 없음, 현재 연도({year}년) 사용: {datetime_str} → {year}년 {month}월 {day}일")
                            else:
                                match = None
                        
                        if match:
                            try:
                                post_datetime = datetime(year, month, day)
                                post_data["datetime"] = post_datetime.isoformat()
                                logger.info(f"    ✅ datetime: {post_data['datetime']}")
                            except ValueError as e:
                                logger.warning(f"    ⚠️ datetime 변환 실패: {year}년 {month}월 {day}일 - {e}")
                    
                    # 날짜 패턴을 찾지 못했거나 파싱 실패한 경우, 상대 시간 패턴 찾기
                    if 'datetime' not in post_data or post_data.get('datetime') is None:
                        # 차선책: 상대 시간 패턴 찾기 (XX시간, XX분, XX일)
                        # 주의: "XX일"은 "XX월 XX일"과 구분해야 함 (월이 없을 때만 상대 시간)
                        relative_time_labels = []
                        for label in all_aria_labels:
                            # 이미지 설명이나 다른 텍스트 제외 (너무 긴 텍스트는 제외)
                            if len(label) > 100:
                                continue
                            
                            # "XX시간" 패턴 (1~23시간 범위, 또는 24시간 이상도 허용)
                            hours_match = re.search(r'(\d+)\s*시간', label)
                            if hours_match:
                                hours = int(hours_match.group(1))
                                # 합리적인 범위 체크 (1~720시간, 즉 30일 이내)
                                if 1 <= hours <= 720:
                                    relative_time_labels.append((label, 'hours', hours))
                            
                            # "XX분" 패턴
                            minutes_match = re.search(r'(\d+)\s*분', label)
                            if minutes_match:
                                minutes = int(minutes_match.group(1))
                                # 합리적인 범위 체크 (1~1440분, 즉 24시간 이내)
                                if 1 <= minutes <= 1440:
                                    relative_time_labels.append((label, 'minutes', minutes))
                            
                            # "XX일" 패턴 (단, "월"이 포함되지 않은 경우만)
                            if '월' not in label:
                                days_match = re.search(r'(\d+)\s*일', label)
                                if days_match:
                                    days = int(days_match.group(1))
                                    # 합리적인 범위 체크 (1~365일)
                                    if 1 <= days <= 365:
                                        relative_time_labels.append((label, 'days', days))
                        
                        if relative_time_labels:
                            # 가장 짧은 시간 단위 우선 (분 > 시간 > 일)
                            relative_time_labels.sort(key=lambda x: (x[1] == 'days', x[1] == 'hours', x[2]))
                            relative_time_str, time_type, time_value = relative_time_labels[0]
                            logger.info(f"    ℹ️ 상대 시간 패턴 발견: {relative_time_str} ({time_type}: {time_value})")
                            
                            # 상대 시간 계산
                            now = datetime.now()
                            post_datetime = None
                            
                            if time_type == 'hours':
                                post_datetime = now - timedelta(hours=time_value)
                                logger.info(f"    ℹ️ {time_value}시간 전 → {post_datetime.isoformat()}")
                            elif time_type == 'minutes':
                                post_datetime = now - timedelta(minutes=time_value)
                                logger.info(f"    ℹ️ {time_value}분 전 → {post_datetime.isoformat()}")
                            elif time_type == 'days':
                                post_datetime = now - timedelta(days=time_value)
                                logger.info(f"    ℹ️ {time_value}일 전 → {post_datetime.isoformat()}")
                            
                            if post_datetime:
                                post_data["datetime"] = post_datetime.isoformat()
                                logger.info(f"    ✅ datetime (상대 시간): {post_data['datetime']}")
                except Exception as e:
                    logger.debug(f"    추가 검색 실패: {e}")
        except Exception as e:
            logger.warning(f"    ⚠️ datetime 추출 실패: {e}")
        
        # 3. content 추출
        # <div data-ad-rendering-role="story_message">에서 텍스트 추출
        logger.info("  🔍 content 추출 중...")
        try:
            content = None
            
            # 먼저 story_message 요소 찾기
            content_element = None
            content_selectors = [
                "div[data-ad-rendering-role='story_message']",  # 우선: 기본 셀렉터
                "div[data-pagelet='FeedUnit'] div[dir='auto']",  # 차선책 1: 일반적인 텍스트 영역
                "div[data-pagelet='FeedUnit'] span[dir='auto']",  # 차선책 2: span 텍스트
            ]
            
            for idx, selector in enumerate(content_selectors, 1):
                try:
                    content_element = post_element.find_element(By.CSS_SELECTOR, selector)
                    logger.info(f"    ℹ️ content 요소 찾음 (셀렉터 #{idx})")
                    break
                except NoSuchElementException:
                    continue
                except Exception as e:
                    logger.debug(f"    ℹ️ 셀렉터 #{idx} 실패: {e}")
                    continue
            
            # "더 보기" 버튼이 있으면 먼저 클릭
            # <div role="button">더 보기</div> 형태
            # "더 보기" 버튼은 story_message 내부에 있음
            if content_element:
                try:
                    logger.info("    🔍 '더 보기' 버튼 검색 중 (story_message 내부)...")
                    
                    # 먼저 "더 보기" 텍스트가 있는지 확인
                    initial_text = driver.execute_script("return arguments[0].textContent || arguments[0].innerText || '';", content_element)
                    has_more_button = '더 보기' in initial_text or '…' in initial_text
                    
                    if has_more_button:
                        logger.info("    ℹ️ '더 보기' 텍스트 또는 '…' 발견, 버튼 검색 및 클릭 시도...")
                        
                        # 방법 1: JavaScript로 직접 찾아서 클릭 (가장 확실한 방법)
                        more_button_clicked = driver.execute_script("""
                            var storyMessage = arguments[0];
                            if (!storyMessage) return false;
                            
                            // story_message 내부에서 div[role="button"] 요소 중에서 "더 보기" 텍스트가 있는 것 찾기
                            var buttons = storyMessage.querySelectorAll('div[role="button"]');
                            
                            for (var i = 0; i < buttons.length; i++) {
                                var button = buttons[i];
                                var text = (button.textContent || button.innerText || '').trim();
                                
                                // "더 보기" 텍스트가 정확히 포함되어 있는지 확인
                                if (text === '더 보기' || text.includes('더 보기')) {
                                    try {
                                        // 가시성 체크 없이 바로 클릭 시도
                                        button.click();
                                        return true;
                                    } catch (e) {
                                        // 클릭 실패 시 다른 방법 시도
                                        try {
                                            var event = new MouseEvent('click', {
                                                view: window,
                                                bubbles: true,
                                                cancelable: true
                                            });
                                            button.dispatchEvent(event);
                                            return true;
                                        } catch (e2) {
                                            // 무시하고 다음 버튼 시도
                                        }
                                    }
                                }
                            }
                            
                            return false;
                        """, content_element)
                        
                        if more_button_clicked:
                            logger.info("    ✅ '더 보기' 버튼 발견 및 클릭 완료 (JavaScript)")
                            time.sleep(2.5)  # 내용 로드 대기
                            
                            # 클릭 후 요소 다시 찾기
                            try:
                                content_element = post_element.find_element(By.CSS_SELECTOR, content_selectors[0])
                                logger.info("    ✅ '더 보기' 클릭 후 요소 갱신 완료")
                            except:
                                logger.warning("    ⚠️ '더 보기' 클릭 후 요소 재찾기 실패, 기존 요소 사용")
                        else:
                            logger.warning("    ⚠️ JavaScript로 '더 보기' 버튼 클릭 실패, XPath로 재시도...")
                            
                            # 방법 2: XPath로 찾아서 클릭
                            more_button = None
                            try:
                                more_button = content_element.find_element(By.XPATH, ".//div[@role='button' and normalize-space(text())='더 보기']")
                                logger.info("    ✅ '더 보기' 버튼 발견 (XPath - 정확한 매칭)")
                            except NoSuchElementException:
                                try:
                                    more_button = content_element.find_element(By.XPATH, ".//div[@role='button' and contains(text(), '더 보기')]")
                                    logger.info("    ✅ '더 보기' 버튼 발견 (XPath - contains)")
                                except NoSuchElementException:
                                    logger.warning("    ⚠️ XPath로 '더 보기' 버튼을 찾을 수 없음")
                            
                            if more_button:
                                try:
                                    logger.info("    ℹ️ '더 보기' 버튼 클릭 중 (XPath)...")
                                    # JavaScript로 클릭 (가장 확실)
                                    driver.execute_script("arguments[0].click();", more_button)
                                    time.sleep(2.5)  # 내용 로드 대기
                                    
                                    # 클릭 후 요소 다시 찾기
                                    try:
                                        content_element = post_element.find_element(By.CSS_SELECTOR, content_selectors[0])
                                        logger.info("    ✅ '더 보기' 버튼 클릭 완료, 요소 갱신")
                                    except:
                                        logger.warning("    ⚠️ '더 보기' 클릭 후 요소 재찾기 실패, 기존 요소 사용")
                                except Exception as e:
                                    logger.warning(f"    ⚠️ '더 보기' 버튼 클릭 실패: {e}")
                                    import traceback
                                    logger.warning(traceback.format_exc())
                            else:
                                # 디버깅: story_message 내부의 모든 button 요소 확인
                                try:
                                    all_buttons = content_element.find_elements(By.CSS_SELECTOR, "div[role='button']")
                                    logger.warning(f"    📋 story_message 내부의 div[role='button'] 요소 {len(all_buttons)}개 발견:")
                                    for idx, btn in enumerate(all_buttons[:10], 1):  # 처음 10개
                                        try:
                                            btn_text = driver.execute_script("return arguments[0].textContent || arguments[0].innerText || '';", btn)
                                            btn_text = btn_text.strip()
                                            if btn_text:
                                                logger.warning(f"       {idx}. 텍스트: '{btn_text[:100]}'")
                                        except:
                                            pass
                                except:
                                    pass
                                logger.warning("    ⚠️ '더 보기' 버튼을 찾을 수 없음")
                    else:
                        logger.debug("    ℹ️ '더 보기' 텍스트가 없음 (전체 내용일 수 있음)")
                except Exception as e:
                    logger.warning(f"    ⚠️ '더 보기' 버튼 검색 실패: {e}")
                    import traceback
                    logger.warning(traceback.format_exc())
            
            # 이제 텍스트 추출
            if content_element:
                # 방법 1: JavaScript로 직접 텍스트 추출 (가장 확실한 방법)
                try:
                    content_js = driver.execute_script("""
                        var storyMessage = arguments[0];
                        if (!storyMessage) return null;
                        
                        // story_message 내부의 모든 텍스트 노드 수집
                        var textNodes = [];
                        var walker = document.createTreeWalker(
                            storyMessage,
                            NodeFilter.SHOW_TEXT,
                            {
                                acceptNode: function(node) {
                                    // 부모가 script, style, noscript가 아닌 경우만
                                    var parent = node.parentElement;
                                    if (!parent) return NodeFilter.FILTER_REJECT;
                                    var tagName = parent.tagName.toLowerCase();
                                    if (tagName === 'script' || tagName === 'style' || tagName === 'noscript') {
                                        return NodeFilter.FILTER_REJECT;
                                    }
                                    return NodeFilter.FILTER_ACCEPT;
                                }
                            },
                            false
                        );
                        
                        var node;
                        while (node = walker.nextNode()) {
                            var text = node.textContent.trim();
                            // "더 보기", "공유", "댓글" 등의 버튼 텍스트 제외
                            if (text && 
                                text.length > 0 && 
                                !text.match(/^(더 보기|공유|댓글|좋아요|팔로우|·)$/)) {
                                textNodes.push(text);
                            }
                        }
                        
                        if (textNodes.length > 0) {
                            var result = textNodes.join(' ');
                            // 정리
                            result = result.replace(/\\n/g, ' ').replace(/\\r/g, ' ');
                            result = result.replace(/\\s+/g, ' ').trim();
                            return result || null;
                        }
                        
                        // 차선책: textContent 직접 사용
                        var directText = (storyMessage.textContent || storyMessage.innerText || '').trim();
                        if (directText) {
                            directText = directText.replace(/\\n/g, ' ').replace(/\\r/g, ' ');
                            directText = directText.replace(/\\s+/g, ' ').trim();
                            return directText || null;
                        }
                        
                        return null;
                    """, content_element)
                    
                    if content_js:
                        content = content_js
                        logger.info(f"    ✅ content (JavaScript, 길이: {len(content)}자):")
                        logger.info(f"       {content[:200]}...")
                except Exception as e:
                    logger.debug(f"    ℹ️ JavaScript 추출 실패: {e}")
                
                # 방법 2: CSS 셀렉터로 추출 (JavaScript 실패 시)
                if not content:
                    try:
                        content = driver.execute_script("return arguments[0].textContent || arguments[0].innerText || '';", content_element)
                        content = content.strip()
                    except:
                        try:
                            content = content_element.text.strip()
                        except:
                            content = None
                    
                    if content:
                        # \n 같은 개행 문자를 공백으로 치환
                        content = content.replace('\n', ' ').replace('\r', ' ')
                        # 연속된 공백을 하나로 정리
                        content = ' '.join(content.split())
                        logger.info(f"    ✅ content (CSS 셀렉터, 길이: {len(content)}자):")
                        logger.info(f"       {content[:200]}...")
            else:
                # story_message 요소를 찾지 못한 경우: dir='auto' 요소들에서 찾기
                try:
                    auto_elements = post_element.find_elements(By.CSS_SELECTOR, "[dir='auto']")
                    if auto_elements:
                        texts = []
                        for elem in auto_elements:
                            try:
                                text = driver.execute_script("return arguments[0].textContent || arguments[0].innerText || '';", elem)
                                text = text.strip()
                                if text and len(text) > 0:
                                    texts.append(text)
                            except:
                                continue
                        if texts:
                            content = ' '.join(texts)
                            content = content.replace('\n', ' ').replace('\r', ' ')
                            content = ' '.join(content.split())
                            logger.info(f"    ✅ content (dir='auto' 요소들, 길이: {len(content)}자):")
                            logger.info(f"       {content[:200]}...")
                except Exception as e:
                    logger.debug(f"    ℹ️ dir='auto' 요소 검색 실패: {e}")
                
                if not content:
                    logger.warning("    ⚠️ content 요소를 찾을 수 없습니다 (모든 셀렉터 실패)")
            
            # 최종 결과 저장
            if content:
                post_data["content"] = content
                post_data["content_count"] = len(content)
            else:
                post_data["content_count"] = 0
                
        except Exception as e:
            logger.warning(f"    ⚠️ content 추출 실패: {e}")
            import traceback
            logger.warning(traceback.format_exc())
            post_data["content_count"] = 0
        
        # 4. hashtags 추출
        # <div data-ad-rendering-role="story_message"> 내부의 <a role="link">#~~~</a> 형태 찾기
        # 또는 본문 텍스트에서 #으로 시작하는 단어 추출
        logger.info("  🔍 hashtags 추출 중...")
        hashtags = []
        
        try:
            # 방법 1: JavaScript로 본문 텍스트에서 해시태그 추출 (가장 확실)
            try:
                hashtags_js = driver.execute_script("""
                    var storyMessage = arguments[0];
                    if (!storyMessage) return [];
                    
                    var hashtags = [];
                    
                    // 방법 1-1: a[role='link'] 요소에서 해시태그 찾기
                    var links = storyMessage.querySelectorAll('a[role="link"]');
                    for (var i = 0; i < links.length; i++) {
                        var link = links[i];
                        var text = (link.textContent || link.innerText || '').trim();
                        if (text && text.startsWith('#')) {
                            hashtags.push(text);
                        }
                    }
                    
                    // 방법 1-2: 본문 전체 텍스트에서 정규식으로 해시태그 찾기
                    var fullText = (storyMessage.textContent || storyMessage.innerText || '');
                    var hashtagPattern = /#[\w가-힣]+/g;
                    var matches = fullText.match(hashtagPattern);
                    if (matches) {
                        for (var i = 0; i < matches.length; i++) {
                            var tag = matches[i].trim();
                            if (tag && !hashtags.includes(tag)) {
                                hashtags.push(tag);
                            }
                        }
                    }
                    
                    return hashtags;
                """, content_element if content_element else post_element)
                
                if hashtags_js:
                    hashtags.extend(hashtags_js)
                    logger.info(f"    ✅ hashtags (JavaScript): {len(hashtags_js)}개 발견")
            except Exception as e:
                logger.debug(f"    ℹ️ JavaScript 해시태그 추출 실패: {e}")
            
            # 방법 2: CSS 셀렉터로 찾기 (JavaScript 실패 시)
            if not hashtags:
                try:
                    # story_message 내부에서 hashtag 링크 찾기
                    story_message_element = post_element.find_element(By.CSS_SELECTOR, "div[data-ad-rendering-role='story_message']")
                    hashtag_links = story_message_element.find_elements(By.CSS_SELECTOR, "a[role='link']")
                    
                    for link in hashtag_links:
                        try:
                            hashtag_text = link.text.strip()
                            # #으로 시작하는 텍스트만 hashtag로 인식
                            if hashtag_text.startswith("#"):
                                hashtags.append(hashtag_text)
                        except Exception:
                            continue
                    
                    logger.info(f"    ℹ️ hashtags (CSS 셀렉터): {len(hashtags)}개 발견")
                except NoSuchElementException:
                    logger.warning("    ⚠️ story_message 요소를 찾을 수 없음")
                except Exception as e:
                    logger.warning(f"    ⚠️ CSS 셀렉터 해시태그 추출 실패: {e}")
            
            # 방법 3: 본문 텍스트에서 정규식으로 추출 (추가 보완)
            if not hashtags and post_data.get("content"):
                try:
                    content_text = post_data["content"]
                    hashtag_pattern = r'#[\w가-힣]+'
                    matches = re.findall(hashtag_pattern, content_text)
                    if matches:
                        hashtags.extend(matches)
                        logger.info(f"    ℹ️ hashtags (본문 정규식): {len(matches)}개 발견")
                except Exception as e:
                    logger.debug(f"    ℹ️ 본문 정규식 해시태그 추출 실패: {e}")
            
            # 중복 제거 (순서 유지)
            seen = set()
            unique_hashtags = []
            for tag in hashtags:
                tag_clean = tag.strip()
                if tag_clean and tag_clean not in seen:
                    seen.add(tag_clean)
                    unique_hashtags.append(tag_clean)
            
            post_data["hashtags"] = unique_hashtags
            post_data["hashtag_count"] = len(unique_hashtags)
            
            if unique_hashtags:
                logger.info(f"    ✅ hashtags ({len(unique_hashtags)}개):")
                for idx, tag in enumerate(unique_hashtags, 1):
                    logger.info(f"       {idx}. {tag}")
            else:
                logger.warning("    ⚠️ hashtags 없음")
        except Exception as e:
            logger.warning(f"    ⚠️ hashtags 추출 실패: {e}")
            import traceback
            logger.warning(traceback.format_exc())
            post_data["hashtags"] = []
            post_data["hashtag_count"] = 0
        
        # 5. like_count 추출
        # aria-label에서 반응 정보 추출: '좋아요: A명', '최고예요: B명', '멋져요: C명', '힘내요: D명', '웃겨요: E명', '슬퍼요: F명', '화나요: G명'
        logger.info("  🔍 like_count 추출 중...")
        try:
            # 모든 aria-label 속성을 가진 요소 찾기
            all_elements = post_element.find_elements(By.CSS_SELECTOR, "[aria-label]")
            
            # 반응 종류별 패턴
            reaction_patterns = {
                '좋아요': r'좋아요:\s*(\d+)명',
                '최고예요': r'최고예요:\s*(\d+)명',
                '멋져요': r'멋져요:\s*(\d+)명',
                '힘내요': r'힘내요:\s*(\d+)명',
                '웃겨요': r'웃겨요:\s*(\d+)명',
                '슬퍼요': r'슬퍼요:\s*(\d+)명',
                '화나요': r'화나요:\s*(\d+)명',
            }
            
            reaction_counts = {}
            total_like_count = 0
            
            # 각 요소의 aria-label 확인
            for element in all_elements:
                try:
                    aria_label = element.get_attribute("aria-label")
                    if not aria_label:
                        continue
                    
                    # 각 반응 패턴 확인
                    for reaction_name, pattern in reaction_patterns.items():
                        match = re.search(pattern, aria_label)
                        if match:
                            count = int(match.group(1))
                            if reaction_name not in reaction_counts:
                                reaction_counts[reaction_name] = 0
                            reaction_counts[reaction_name] += count
                            total_like_count += count
                except Exception:
                    continue
            
            # 모든 반응 종류 확인 (없으면 0)
            for reaction_name in reaction_patterns.keys():
                if reaction_name not in reaction_counts:
                    reaction_counts[reaction_name] = 0
            
            # 모든 반응이 0이면 "모든 공감"에서 숫자 추출 시도
            if total_like_count == 0:
                logger.info("    ℹ️ 모든 반응이 0명, '모든 공감'에서 숫자 추출 시도...")
                try:
                    # "모든 공감" 텍스트가 있는 요소 찾기
                    all_reactions_element = post_element.find_element(By.XPATH, ".//div[@role='button' and contains(., '모든 공감')]")
                    logger.info("    ℹ️ '모든 공감' 요소 발견")
                    if all_reactions_element:
                        # 요소의 전체 텍스트에서 숫자 추출 시도
                        try:
                            # 방법 1: span에서 숫자 추출 시도
                            count_text = None
                            try:
                                count_span = all_reactions_element.find_element(By.XPATH, ".//span[contains(., '명')]")
                                count_text = count_span.text.strip()
                            except NoSuchElementException:
                                # 방법 2: 모든 span 요소에서 숫자 포함된 것 찾기
                                try:
                                    all_spans = all_reactions_element.find_elements(By.TAG_NAME, "span")
                                    for span in all_spans:
                                        span_text = span.text.strip()
                                        if any(char.isdigit() for char in span_text) or '천' in span_text or '만' in span_text or '억' in span_text:
                                            count_text = span_text
                                            break
                                except Exception:
                                    pass
                            
                            # 방법 3: 요소의 전체 텍스트에서 직접 추출
                            if not count_text:
                                full_text = all_reactions_element.text.strip()
                                # "모든 공감: XXX명" 또는 "XXX명" 패턴 찾기
                                match = re.search(r'(\d+[.,]?\d*\s*(?:천|만|억)?명?)', full_text)
                                if match:
                                    count_text = match.group(1)
                            
                            if not count_text:
                                logger.warning(f"    ⚠️ '모든 공감' 요소에서 숫자를 찾을 수 없음. 전체 텍스트: '{all_reactions_element.text.strip()}'")
                                # 디버깅: 요소의 HTML 출력
                                element_html = driver.execute_script("return arguments[0].outerHTML;", all_reactions_element)
                                logger.info(f"    📋 '모든 공감' 요소 HTML (처음 500자): {element_html[:500]}")
                                raise ValueError("숫자를 찾을 수 없음")
                            
                            # "명" 제거
                            count_text = count_text.replace('명', '').strip()
                            
                            # 숫자 변환 (한국어 단위 처리)
                            # "4.7천명" -> 4700, "1.2만명" -> 12000
                            if '천' in count_text:
                                number_str = count_text.replace('천', '').strip()
                                number = float(number_str) * 1000
                                total_like_count = int(number)
                                logger.info(f"    ℹ️ '모든 공감'에서 추출: {count_text} → {total_like_count}명")
                            elif '만' in count_text:
                                number_str = count_text.replace('만', '').strip()
                                number = float(number_str) * 10000
                                total_like_count = int(number)
                                logger.info(f"    ℹ️ '모든 공감'에서 추출: {count_text} → {total_like_count}명")
                            elif '억' in count_text:
                                number_str = count_text.replace('억', '').strip()
                                number = float(number_str) * 100000000
                                total_like_count = int(number)
                                logger.info(f"    ℹ️ '모든 공감'에서 추출: {count_text} → {total_like_count}명")
                            else:
                                # 일반 숫자만 있는 경우
                                total_like_count = int(float(count_text.replace(',', '')))
                                logger.info(f"    ℹ️ '모든 공감'에서 추출: {count_text} → {total_like_count}명")
                        except (NoSuchElementException, ValueError) as e:
                            logger.warning(f"    ⚠️ '모든 공감' 숫자 추출 실패: {e}")
                except NoSuchElementException:
                    logger.info("    ℹ️ '모든 공감' 요소를 찾을 수 없음")
                except Exception as e:
                    logger.warning(f"    ⚠️ '모든 공감' 추출 중 오류: {e}")
            
            post_data["like_count"] = total_like_count
            
            # 터미널에 출력
            logger.info(f"    ✅ like_count 계산 결과:")
            logger.info(f"       총 좋아요 수: {total_like_count}개")
            logger.info(f"       반응별 상세:")
            for reaction_name in ['좋아요', '최고예요', '멋져요', '힘내요', '웃겨요', '슬퍼요', '화나요']:
                count = reaction_counts.get(reaction_name, 0)
                logger.info(f"         - {reaction_name}: {count}명")
            
        except Exception as e:
            logger.warning(f"    ⚠️ like_count 추출 실패: {e}")
            post_data["like_count"] = 0
        
        # 6. comments_count 추출
        # <div id="_r_dl_", role="button"><span><span>댓글 X개</span></span></div> 형태에서 숫자 추출
        logger.info("  🔍 comments_count 추출 중...")
        try:
            comments_count = 0
            
            # post_element는 이미 extract_post_data 함수 시작 부분에서 WebElement로 변환됨
            # 따라서 여기서는 post_element를 직접 사용
            # 하지만 stale element 방지를 위해 요소 유효성 확인
            current_post_element = post_element
            
            # 요소 유효성 확인 (stale element 방지)
            try:
                _ = current_post_element.tag_name
            except Exception:
                # stale element인 경우 재찾기 시도
                logger.warning("    ⚠️ comments_count 추출 전 요소가 stale 상태, 재찾기 시도...")
                try:
                    articles = driver.find_elements(By.CSS_SELECTOR, "div[role='article']")
                    if articles:
                        # 현재 post_element의 위치를 추정하기 어려우므로, 
                        # 모든 article에서 "댓글 X개" 패턴을 찾는 방식으로 변경
                        current_post_element = None
                    else:
                        raise Exception("article 요소를 찾을 수 없음")
                except Exception as e:
                    logger.warning(f"    ⚠️ 요소 재찾기 실패: {e}")
                    current_post_element = None
            
            # comments_count 추출 전에도 콘텐츠 로드 확인 및 대기
            if current_post_element:
                try:
                    # 댓글 요소가 있는지 확인
                    has_comments = driver.execute_script("""
                        var element = arguments[0];
                        if (!element) return false;
                        
                        // "댓글" 텍스트가 포함된 요소 찾기
                        var text = element.textContent || element.innerText || '';
                        if (text.indexOf('댓글') === -1) {
                            return false; // 댓글 관련 텍스트가 없음
                        }
                        
                        // 댓글 버튼이나 요소가 있는지 확인
                        var commentButtons = element.querySelectorAll('div[role="button"]');
                        for (var i = 0; i < commentButtons.length; i++) {
                            var btnText = commentButtons[i].textContent || commentButtons[i].innerText || '';
                            if (btnText.match(/댓글\\s*\\d+\\s*개/) && btnText.indexOf('남기기') === -1 && btnText.indexOf('달기') === -1) {
                                return true; // 댓글 수가 있는 버튼 발견
                            }
                        }
                        
                        return false;
                    """, current_post_element)
                    
                    if not has_comments:
                        # 댓글 요소가 없으면 콘텐츠 로드를 위해 스크롤 및 대기
                        logger.info("    ℹ️ comments_count 추출 전 콘텐츠 로드 확인 및 대기...")
                        driver.execute_script("arguments[0].scrollIntoView({block: 'center', behavior: 'auto'});", current_post_element)
                        time.sleep(1.5)  # 스크롤 후 대기
                        
                        # 댓글 요소가 나타날 때까지 대기 (최대 3초)
                        max_wait = 3
                        wait_interval = 0.5
                        waited = 0
                        
                        while waited < max_wait:
                            has_comments = driver.execute_script("""
                                var element = arguments[0];
                                if (!element) return false;
                                var text = element.textContent || element.innerText || '';
                                if (text.indexOf('댓글') === -1) return false;
                                var commentButtons = element.querySelectorAll('div[role="button"]');
                                for (var i = 0; i < commentButtons.length; i++) {
                                    var btnText = commentButtons[i].textContent || commentButtons[i].innerText || '';
                                    if (btnText.match(/댓글\\s*\\d+\\s*개/) && btnText.indexOf('남기기') === -1 && btnText.indexOf('달기') === -1) {
                                        return true;
                                    }
                                }
                                return false;
                            """, current_post_element)
                            
                            if has_comments:
                                logger.info("    ✅ 댓글 요소 로드 완료")
                                break
                            
                            time.sleep(wait_interval)
                            waited += wait_interval
                except Exception as e:
                    logger.debug(f"    ℹ️ comments_count 추출 전 콘텐츠 로드 확인 중 오류 (무시): {e}")
            
            # JavaScript로 직접 DOM을 탐색하여 "댓글 X개" 패턴 찾기 (개발자 도구에서 보이는 구조 그대로 사용)
            try:
                if current_post_element is None:
                    # 요소를 찾을 수 없는 경우, 모든 article에서 검색
                    logger.info("    ℹ️ 특정 요소를 찾을 수 없어 모든 article에서 검색...")
                    articles = driver.find_elements(By.CSS_SELECTOR, "div[role='article']")
                    for article in articles:
                        try:
                            comments_count_js = driver.execute_script("""
                                var postElement = arguments[0];
                                var commentCount = 0;
                                
                                // 모든 요소를 재귀적으로 탐색하는 함수
                                function searchElement(element) {
                                    if (!element) return false;
                                    
                                    try {
                                        // textContent 또는 innerText 가져오기
                                        var text = element.textContent || element.innerText || '';
                                        text = text.trim();
                                        
                                        // "댓글 X개" 패턴 찾기 (정규식)
                                        var match = text.match(/댓글\\s*(\\d+)\\s*개/);
                                        if (match) {
                                            // "댓글 남기기", "댓글 달기" 제외
                                            if (text.indexOf('남기기') === -1 && text.indexOf('달기') === -1) {
                                                commentCount = parseInt(match[1]);
                                                return true; // 찾았으면 중단
                                            }
                                        }
                                        
                                        // "댓글 X" 패턴 (개 없이) 찾기
                                        match = text.match(/댓글\\s*(\\d+)/);
                                        if (match) {
                                            if (text.indexOf('남기기') === -1 && text.indexOf('달기') === -1) {
                                                commentCount = parseInt(match[1]);
                                                return true;
                                            }
                                        }
                                        
                                        // 자식 요소들 재귀적으로 탐색
                                        var children = element.children || element.childNodes;
                                        for (var i = 0; i < children.length; i++) {
                                            if (searchElement(children[i])) {
                                                return true; // 찾았으면 중단
                                            }
                                        }
                                    } catch (e) {
                                        // 요소 접근 오류 무시
                                    }
                                    
                                    return false;
                                }
                                
                                // 탐색 시작
                                try {
                                    searchElement(postElement);
                                } catch (e) {
                                    // 요소 탐색 오류 무시
                                }
                                
                                return commentCount;
                            """, article)
                            
                            if comments_count_js and comments_count_js > 0:
                                comments_count = comments_count_js
                                post_data["comments_count"] = comments_count
                                logger.info(f"    ✅ comments_count (JavaScript DOM 탐색, 전체 검색): {comments_count}개")
                                break
                        except:
                            continue
                else:
                    # JavaScript로 post_element 내부의 모든 요소를 탐색하고 "댓글 X개" 패턴 찾기
                    comments_count_js = driver.execute_script("""
                        var postElement = arguments[0];
                        var commentCount = 0;
                        
                        // 요소 유효성 확인
                        if (!postElement) {
                            return 0;
                        }
                        
                        // 모든 요소를 재귀적으로 탐색하는 함수
                        function searchElement(element) {
                            if (!element) return false;
                            
                            try {
                                // textContent 또는 innerText 가져오기
                                var text = element.textContent || element.innerText || '';
                                text = text.trim();
                                
                                // "댓글 X개" 패턴 찾기 (정규식)
                                var match = text.match(/댓글\\s*(\\d+)\\s*개/);
                                if (match) {
                                    // "댓글 남기기", "댓글 달기" 제외
                                    if (text.indexOf('남기기') === -1 && text.indexOf('달기') === -1) {
                                        commentCount = parseInt(match[1]);
                                        return true; // 찾았으면 중단
                                    }
                                }
                                
                                // "댓글 X" 패턴 (개 없이) 찾기
                                match = text.match(/댓글\\s*(\\d+)/);
                                if (match) {
                                    if (text.indexOf('남기기') === -1 && text.indexOf('달기') === -1) {
                                        commentCount = parseInt(match[1]);
                                        return true;
                                    }
                                }
                                
                                // 자식 요소들 재귀적으로 탐색
                                var children = element.children || element.childNodes;
                                for (var i = 0; i < children.length; i++) {
                                    if (searchElement(children[i])) {
                                        return true; // 찾았으면 중단
                                    }
                                }
                            } catch (e) {
                                // 요소 접근 오류 무시
                            }
                            
                            return false;
                        }
                        
                        // 탐색 시작
                        try {
                            searchElement(postElement);
                        } catch (e) {
                            // 요소 탐색 오류 무시
                        }
                        
                        return commentCount;
                    """, current_post_element)
                
                if comments_count_js and comments_count_js > 0:
                    comments_count = comments_count_js
                    post_data["comments_count"] = comments_count
                    logger.info(f"    ✅ comments_count (JavaScript DOM 탐색): {comments_count}개")
                else:
                    # JavaScript로 찾지 못한 경우, CSS 셀렉터로 시도
                    logger.debug("    ℹ️ JavaScript 탐색으로 찾지 못함, CSS 셀렉터로 시도...")
                    
                    # 방법 1: id가 "_r_dl_"로 시작하는 요소 찾기
                    try:
                        comments_element = current_post_element.find_element(By.CSS_SELECTOR, "div[id^='_r_dl_'][role='button']")
                        btn_text = driver.execute_script("return arguments[0].textContent || arguments[0].innerText || '';", comments_element)
                        btn_text = btn_text.strip()
                        match = re.search(r'댓글\s*(\d+)\s*개', btn_text)
                        if match:
                            comments_count = int(match.group(1))
                            post_data["comments_count"] = comments_count
                            logger.info(f"    ✅ comments_count (_r_dl_ 셀렉터): {comments_count}개")
                        else:
                            match = re.search(r'댓글\s*(\d+)', btn_text)
                            if match and '남기기' not in btn_text and '달기' not in btn_text:
                                comments_count = int(match.group(1))
                                post_data["comments_count"] = comments_count
                                logger.info(f"    ✅ comments_count (_r_dl_ 셀렉터, 패턴 2): {comments_count}개")
                            else:
                                raise Exception("패턴 없음")
                    except:
                        # 방법 2: 특정 클래스 조합 찾기
                        try:
                            specific_buttons = current_post_element.find_elements(By.CSS_SELECTOR, "div[role='button'].x1i10hfl.x1qjc9v5.xjbqb8w")
                            for btn in specific_buttons:
                                btn_text = driver.execute_script("return arguments[0].textContent || arguments[0].innerText || '';", btn)
                                btn_text = btn_text.strip()
                                match = re.search(r'댓글\s*(\d+)\s*개', btn_text)
                                if match and '남기기' not in btn_text and '달기' not in btn_text:
                                    comments_count = int(match.group(1))
                                    post_data["comments_count"] = comments_count
                                    logger.info(f"    ✅ comments_count (특정 클래스): {comments_count}개")
                                    break
                        except:
                            pass
                    
                    # 여전히 찾지 못한 경우
                    if comments_count == 0:
                        # 디버깅: post_element의 HTML 일부 출력
                        try:
                            post_html = driver.execute_script("return arguments[0].outerHTML;", current_post_element)
                            logger.warning(f"    📋 post_element HTML (처음 1000자): {post_html[:1000]}")
                        except:
                            pass
                        post_data["comments_count"] = 0
                        logger.warning("    ⚠️ 댓글 요소를 찾을 수 없음, 0으로 처리")
                        
            except Exception as e:
                logger.warning(f"    ⚠️ comments_count 추출 실패: {e}")
                import traceback
                logger.debug(traceback.format_exc())
                post_data["comments_count"] = 0
            
        except Exception as e:
            logger.warning(f"    ⚠️ comments_count 추출 실패: {e}")
            import traceback
            logger.warning(traceback.format_exc())
            post_data["comments_count"] = 0
        
        # 7. share_count 추출
        # <div role="button">공유 XX회</div> 형태에서 숫자 추출
        logger.info("  🔍 share_count 추출 중...")
        try:
            # role="button"과 "공유" 텍스트로 찾기
            share_element = None
            try:
                share_element = post_element.find_element(By.XPATH, ".//div[@role='button' and contains(., '공유')]")
            except NoSuchElementException:
                pass
            
            if share_element:
                share_text = share_element.text.strip()
                # "공유 XX회" 패턴에서 숫자 추출
                match = re.search(r'공유\s*(\d+)\s*회', share_text)
                if match:
                    share_count = int(match.group(1))
                    post_data["share_count"] = share_count
                    logger.info(f"    ✅ share_count: {share_count}회")
                else:
                    # "공유 XX회" 패턴이 없으면 0
                    post_data["share_count"] = 0
                    logger.info(f"    ℹ️ '공유 XX회' 패턴을 찾을 수 없음 (텍스트: '{share_text}'), 0으로 처리")
            else:
                # 공유 요소를 찾을 수 없으면 0
                post_data["share_count"] = 0
                logger.info("    ℹ️ 공유 요소를 찾을 수 없음, 0으로 처리")
        except Exception as e:
            logger.warning(f"    ⚠️ share_count 추출 실패: {e}")
            post_data["share_count"] = 0
        
        # content_count와 hashtag_count는 각각 추출 시점에 이미 설정됨
        
    except Exception as e:
        logger.error(f"  ⚠️ 게시물 데이터 추출 중 오류: {e}")
        import traceback
        logger.error(traceback.format_exc())
    
    return post_data

def is_profile_url(url):
    """
    URL이 프로필 페이지인지 확인
    
    Args:
        url: 확인할 URL 문자열
    
    Returns:
        bool: 프로필 페이지이면 True, 아니면 False
    """
    if not url:
        return False
    
    # 명시적인 프로필 URL 패턴
    if "/profile.php" in url or "/people/" in url or "/user/" in url:
        return True
    
    # 사용자명만 있는 URL 패턴 체크 (예: facebook.com/jiyeon.cho.46332)
    # 미디어 관련 키워드가 없고, 사용자명 패턴인 경우
    media_keywords = ["/photo", "/video", "/reel", "/watch", "/posts", "/story", "/hashtag", "/groups", "/pages", "/events", "/marketplace"]
    if any(keyword in url for keyword in media_keywords):
        return False
    
    # facebook.com/사용자명 패턴 체크
    # facebook.com/ 또는 m.facebook.com/ 뒤에 사용자명이 오는 패턴
    profile_pattern = r'(?:www\.|m\.)?facebook\.com/([^/?]+)'
    match = re.search(profile_pattern, url)
    if match:
        username = match.group(1)
        # 사용자명이 있고, 숫자만이 아니며, 특수 경로가 아닌 경우
        if username and not username.isdigit() and username not in ["home", "login", "register", "recover", "help"]:
            # 사용자명 패턴 (알파벳, 숫자, 점, 언더스코어, 하이픈 포함 가능)
            if re.match(r'^[a-zA-Z0-9._-]+$', username):
                return True
    
    return False

def extract_media_urls(driver, post_element):
    """
    게시물의 미디어 URL 수집
    1. aria-label="사진 설명이 없습니다" 클릭
    2. 주소창 URL 수집
    3. aria-label="다음 사진" 클릭하여 반복
    4. 중복 URL 발견 시 aria-label="닫기" 클릭하여 종료
    
    Args:
        driver: WebDriver 인스턴스
        post_element: 게시물 div 요소
    
    Returns:
        list: 미디어 URL 리스트
    """
    media_urls = []
    
    try:
        # 1. 첫 번째 미디어 클릭
        logger.info("  🔍 미디어 URL 수집 시작...")
        try:
            # 방법 1: aria-label="사진 설명이 없습니다" 요소 찾기 (프로필 영역 제외)
            first_media = None
            try:
                # 모든 "사진 설명이 없습니다" 요소 찾기
                all_media_candidates = post_element.find_elements(By.CSS_SELECTOR, "a[aria-label='사진 설명이 없습니다.']")
                
                # 프로필 영역이 아닌 것만 필터링
                for candidate in all_media_candidates:
                    # 프로필 영역 내에 있는지 확인
                    try:
                        # data-ad-rendering-role='profile_name' 영역 내에 있는지 확인
                        profile_name_area = candidate.find_element(By.XPATH, ".//ancestor::div[@data-ad-rendering-role='profile_name']")
                        if profile_name_area:
                            # 프로필 영역 내의 요소이므로 스킵
                            logger.debug("    ℹ️ 프로필 영역 내 '사진 설명이 없습니다' 요소 발견, 스킵")
                            continue
                    except NoSuchElementException:
                        # 프로필 영역이 아니면 게시물 본문 미디어로 간주
                        pass
                    
                    # 추가 확인: href가 프로필 페이지인지 체크
                    try:
                        href = candidate.get_attribute("href")
                        if href and is_profile_url(href):
                            # 프로필 링크이므로 스킵
                            logger.debug(f"    ℹ️ 프로필 링크 발견, 스킵: {href}")
                            continue
                    except:
                        pass
                    
                    # 프로필 영역이 아닌 것으로 판단되면 사용
                    first_media = candidate
                    break
                
                if first_media:
                    logger.info("    ℹ️ '사진 설명이 없습니다' 요소 발견 (프로필 영역 제외)")
                    # 클릭할 요소의 상세 정보 로그 출력
                    try:
                        aria_label = first_media.get_attribute("aria-label")
                        href = first_media.get_attribute("href")
                        tag_name = first_media.tag_name
                        element_html = driver.execute_script("return arguments[0].outerHTML;", first_media)
                        logger.info(f"    🖱️ 클릭할 요소 정보:")
                        logger.info(f"       - 태그: {tag_name}")
                        logger.info(f"       - aria-label: {aria_label}")
                        logger.info(f"       - href: {href}")
                        logger.info(f"       - HTML (처음 500자): {element_html[:500]}")
                    except Exception as e:
                        logger.warning(f"    ⚠️ 요소 정보 가져오기 실패: {e}")
                    # 요소를 뷰포트 중앙으로 스크롤 (주석처리 - 스크롤 액션 제거)
                    # driver.execute_script("arguments[0].scrollIntoView({block: 'center', behavior: 'smooth'});", first_media)
                    # time.sleep(0.5)  # 스크롤 완료 대기
                    # 클릭
                    logger.info("    🖱️ 첫 번째 미디어 클릭 중...")
                    driver.execute_script("arguments[0].click();", first_media)
                    time.sleep(1.5)  # 미디어 뷰어 로드 대기
                    # 주소창 URL 수집
                    current_url = driver.current_url
                    
                    # 프로필 페이지 URL인지 확인
                    if current_url and is_profile_url(current_url):
                        logger.warning(f"    ⚠️ 프로필 페이지로 이동됨: {current_url}")
                        logger.info("    ℹ️ 뒤로 가기 시도...")
                        driver.back()
                        time.sleep(1)
                        logger.info("    ℹ️ 미디어 요소를 찾을 수 없음 (프로필 링크만 존재)")
                        return media_urls
                else:
                    # 프로필 영역만 발견된 경우
                    logger.debug("    ℹ️ '사진 설명이 없습니다' 요소는 있지만 모두 프로필 영역 내부")
                    raise NoSuchElementException("프로필 영역이 아닌 미디어 요소 없음")
                
                if current_url and current_url not in media_urls:
                    media_urls.append(current_url)
                    logger.info(f"    ✅ 미디어 URL #1: {current_url}")
                else:
                    logger.warning(f"    ⚠️ 첫 번째 미디어 URL을 가져올 수 없음")
                    return media_urls
            except NoSuchElementException:
                # 방법 1-2: aria-label="릴스 뷰어에서 릴스 열기" 요소 찾기 (비디오/릴스, 프로필 영역 제외)
                try:
                    # 모든 "릴스 뷰어에서 릴스 열기" 요소 찾기
                    all_reels_candidates = post_element.find_elements(By.CSS_SELECTOR, "a[aria-label='릴스 뷰어에서 릴스 열기']")
                    
                    # 프로필 영역이 아닌 것만 필터링
                    for candidate in all_reels_candidates:
                        # 프로필 영역 내에 있는지 확인
                        try:
                            # data-ad-rendering-role='profile_name' 영역 내에 있는지 확인
                            profile_name_area = candidate.find_element(By.XPATH, ".//ancestor::div[@data-ad-rendering-role='profile_name']")
                            if profile_name_area:
                                # 프로필 영역 내의 요소이므로 스킵
                                logger.debug("    ℹ️ 프로필 영역 내 '릴스 뷰어에서 릴스 열기' 요소 발견, 스킵")
                                continue
                        except NoSuchElementException:
                            # 프로필 영역이 아니면 게시물 본문 미디어로 간주
                            pass
                        
                        # 추가 확인: href가 프로필 페이지인지 체크
                        try:
                            href = candidate.get_attribute("href")
                            if href and is_profile_url(href):
                                # 프로필 링크이므로 스킵
                                logger.debug(f"    ℹ️ 프로필 링크 발견, 스킵: {href}")
                                continue
                        except:
                            pass
                        
                        # 프로필 영역이 아닌 것으로 판단되면 사용
                        first_media = candidate
                        break
                    
                    if first_media:
                        logger.info("    ℹ️ '릴스 뷰어에서 릴스 열기' 요소 발견 (프로필 영역 제외)")
                        # 클릭할 요소의 상세 정보 로그 출력
                        try:
                            aria_label = first_media.get_attribute("aria-label")
                            href = first_media.get_attribute("href")
                            tag_name = first_media.tag_name
                            element_html = driver.execute_script("return arguments[0].outerHTML;", first_media)
                            logger.info(f"    🖱️ 클릭할 요소 정보:")
                            logger.info(f"       - 태그: {tag_name}")
                            logger.info(f"       - aria-label: {aria_label}")
                            logger.info(f"       - href: {href}")
                            logger.info(f"       - HTML (처음 500자): {element_html[:500]}")
                        except Exception as e:
                            logger.warning(f"    ⚠️ 요소 정보 가져오기 실패: {e}")
                        # 요소를 뷰포트 중앙으로 스크롤 (주석처리 - 스크롤 액션 제거)
                        # driver.execute_script("arguments[0].scrollIntoView({block: 'center', behavior: 'smooth'});", first_media)
                        # time.sleep(0.5)  # 스크롤 완료 대기
                        # 클릭
                        logger.info("    🖱️ 첫 번째 미디어 (릴스) 클릭 중...")
                        driver.execute_script("arguments[0].click();", first_media)
                        time.sleep(1.5)  # 미디어 뷰어 로드 대기
                        # 주소창 URL 수집
                        current_url = driver.current_url
                        
                        # 프로필 페이지 URL인지 확인
                        if current_url and is_profile_url(current_url):
                            logger.warning(f"    ⚠️ 프로필 페이지로 이동됨: {current_url}")
                            logger.info("    ℹ️ 뒤로 가기 시도...")
                            driver.back()
                            time.sleep(1)
                            logger.info("    ℹ️ 미디어 요소를 찾을 수 없음 (프로필 링크만 존재)")
                            return media_urls
                    else:
                        # 프로필 영역만 발견된 경우
                        logger.debug("    ℹ️ '릴스 뷰어에서 릴스 열기' 요소는 있지만 모두 프로필 영역 내부")
                        raise NoSuchElementException("프로필 영역이 아닌 미디어 요소 없음")
                    
                    if current_url and current_url not in media_urls:
                        media_urls.append(current_url)
                        logger.info(f"    ✅ 미디어 URL #1: {current_url}")
                    else:
                        logger.warning(f"    ⚠️ 첫 번째 미디어 URL을 가져올 수 없음")
                        return media_urls
                except NoSuchElementException:
                    pass
            
            # 방법 1에서 찾지 못한 경우 방법 2 시도
            if not first_media:
                # 방법 2: div[data-visualcompletion="ignore"] 또는 "ignore-dynamic" 찾기 (프로필 링크 제외)
                try:
                    # 게시물 본문 영역 내에서만 찾기 (프로필 영역 제외)
                    # 우선: story_message 영역 내에서 찾기
                    media_candidates = []
                    try:
                        story_message = post_element.find_element(By.CSS_SELECTOR, "div[data-ad-rendering-role='story_message']")
                        # story_message의 부모나 형제 요소에서 미디어 찾기
                        # data-visualcompletion='ignore' 또는 'ignore-dynamic' 모두 찾기
                        media_candidates = post_element.find_elements(By.CSS_SELECTOR, "div[data-visualcompletion='ignore'], div[data-visualcompletion='ignore-dynamic']")
                    except NoSuchElementException:
                        # story_message가 없으면 전체 post_element에서 찾기
                        media_candidates = post_element.find_elements(By.CSS_SELECTOR, "div[data-visualcompletion='ignore'], div[data-visualcompletion='ignore-dynamic']")
                    
                    # 프로필 링크가 아닌 것만 필터링
                    first_media = None
                    for candidate in media_candidates:
                        # 프로필 영역 내에 있는지 확인
                        try:
                            # data-ad-rendering-role='profile_name' 영역 내에 있는지 확인
                            profile_name_area = candidate.find_element(By.XPATH, ".//ancestor::div[@data-ad-rendering-role='profile_name']")
                            if profile_name_area:
                                # 프로필 영역 내의 요소이므로 스킵
                                continue
                        except NoSuchElementException:
                            # 프로필 영역이 아니면 게시물 본문 미디어로 간주
                            pass
                        
                        # 추가 확인: a 태그인지 확인하고 href가 프로필 페이지인지 체크
                        try:
                            # 조상에 a 태그가 있는지 확인
                            parent_link = candidate.find_element(By.XPATH, ".//ancestor::a[1]")
                            if parent_link:
                                href = parent_link.get_attribute("href")
                                # 프로필 페이지 URL인지 확인
                                if href and is_profile_url(href):
                                    # 프로필 링크이므로 스킵
                                    logger.debug(f"    ℹ️ 프로필 링크 발견 (부모 a 태그), 스킵: {href}")
                                    continue
                                # aria-label이 있는 a 태그인지 확인
                                aria_label = parent_link.get_attribute("aria-label")
                                if aria_label:
                                    # aria-label이 있으면 프로필 링크일 가능성 높음
                                    # 하지만 확실하지 않으므로 일단 스킵하지 않음
                                    pass
                        except NoSuchElementException:
                            pass
                        
                        # "이 게시물에 대한 옵션" 버튼 제외
                        try:
                            # candidate 자체나 조상 요소의 aria-label 확인
                            candidate_aria_label = candidate.get_attribute("aria-label")
                            if candidate_aria_label and "이 게시물에 대한 옵션" in candidate_aria_label:
                                # 옵션 버튼이므로 스킵
                                continue
                            # 조상 요소 중에 "이 게시물에 대한 옵션"이 있는지 확인
                            option_button = candidate.find_element(By.XPATH, ".//ancestor::div[@aria-label='이 게시물에 대한 옵션']")
                            if option_button:
                                # 옵션 버튼 영역 내의 요소이므로 스킵
                                continue
                        except (NoSuchElementException, AttributeError):
                            pass
                        
                        # 프로필 영역이 아닌 것으로 판단되면 사용
                        # 내부에 "릴스 뷰어에서 릴스 열기" 또는 "사진 설명이 없습니다" 요소가 있는지 확인
                        try:
                            inner_media = candidate.find_element(By.CSS_SELECTOR, "div[aria-label='릴스 뷰어에서 릴스 열기'], a[aria-label='릴스 뷰어에서 릴스 열기'], a[aria-label='사진 설명이 없습니다.']")
                            # 내부 요소가 있으면 그것을 사용
                            first_media = inner_media
                            logger.info("    ℹ️ 내부 미디어 요소 발견 (릴스/사진)")
                        except NoSuchElementException:
                            # 내부 요소가 없으면 외부 div 사용
                            # 하지만 프로필 링크인지 더 엄격하게 확인
                            
                            # 1. candidate의 부모 a 태그 확인 (가장 중요)
                            is_profile_link = False
                            try:
                                parent_a = candidate.find_element(By.XPATH, "./ancestor::a[1]")
                                if parent_a:
                                    href = parent_a.get_attribute("href")
                                    if href:
                                        # 프로필 페이지 URL인지 확인
                                        if is_profile_url(href):
                                            is_profile_link = True
                                            logger.warning(f"    ⚠️ candidate의 부모에 프로필 링크 발견: {href}")
                            except NoSuchElementException:
                                pass
                            
                            # 2. candidate 내부의 모든 a 태그 확인
                            if not is_profile_link:
                                try:
                                    all_links = candidate.find_elements(By.TAG_NAME, "a")
                                    for link in all_links:
                                        try:
                                            href = link.get_attribute("href")
                                            if href:
                                                # 프로필 페이지 URL인지 확인
                                                if is_profile_url(href):
                                                    is_profile_link = True
                                                    logger.warning(f"    ⚠️ candidate 내부에 프로필 링크 발견: {href}")
                                                    break
                                        except:
                                            pass
                                except:
                                    pass
                            
                            # 프로필 링크이면 스킵
                            if is_profile_link:
                                logger.warning("    ⚠️ candidate가 프로필 링크와 연결되어 있음, 스킵")
                                continue
                            
                            # 프로필 링크가 아니면 candidate 사용
                            first_media = candidate
                            logger.info("    ℹ️ candidate 사용 (프로필 링크 아님 확인됨)")
                        break
                    
                    if first_media:
                        logger.info("    ℹ️ 'data-visualcompletion=ignore' 요소 발견 (프로필 링크 제외)")
                    else:
                        logger.info("    ℹ️ 미디어 요소를 찾을 수 없음 (미디어 없음 또는 프로필 링크만 존재)")
                        return media_urls
                except NoSuchElementException:
                    logger.info("    ℹ️ 미디어 요소를 찾을 수 없음 (미디어 없음)")
                    return media_urls
            
            # 방법 2에서 찾은 경우에만 클릭 및 URL 수집 (방법 1/1-2에서는 이미 처리됨)
            if first_media and len(media_urls) == 0:
                # 클릭할 요소의 상세 정보 로그 출력
                try:
                    aria_label = first_media.get_attribute("aria-label")
                    href = first_media.get_attribute("href")
                    tag_name = first_media.tag_name
                    element_html = driver.execute_script("return arguments[0].outerHTML;", first_media)
                    logger.info(f"    🖱️ 클릭할 요소 정보 (방법 2):")
                    logger.info(f"       - 태그: {tag_name}")
                    logger.info(f"       - aria-label: {aria_label}")
                    logger.info(f"       - href: {href}")
                    logger.info(f"       - HTML (처음 500자): {element_html[:500]}")
                except Exception as e:
                    logger.warning(f"    ⚠️ 요소 정보 가져오기 실패: {e}")
                # 미디어 요소를 뷰포트 중앙으로 스크롤 (주석처리 - 스크롤 액션 제거)
                # driver.execute_script("arguments[0].scrollIntoView({block: 'center', behavior: 'smooth'});", first_media)
                # time.sleep(0.5)  # 스크롤 완료 대기
                logger.info("    🖱️ 첫 번째 미디어 (방법 2) 클릭 중...")
                driver.execute_script("arguments[0].click();", first_media)
                time.sleep(1.5)  # 미디어 뷰어 로드 대기
                
                # 주소창 URL 수집
                current_url = driver.current_url
                
                # 프로필 페이지 URL인지 확인
                if current_url and is_profile_url(current_url):
                    logger.warning(f"    ⚠️ 프로필 페이지로 이동됨: {current_url}")
                    logger.info("    ℹ️ 뒤로 가기 시도...")
                    driver.back()
                    time.sleep(1)
                    logger.info("    ℹ️ 미디어 요소를 찾을 수 없음 (프로필 링크만 존재)")
                    return media_urls
                
                if current_url and current_url not in media_urls:
                    media_urls.append(current_url)
                    logger.info(f"    ✅ 미디어 URL #1: {current_url}")
                else:
                    logger.warning(f"    ⚠️ 첫 번째 미디어 URL을 가져올 수 없음")
                    return media_urls
            elif not first_media:
                return media_urls
        except Exception as e:
            logger.warning(f"    ⚠️ 첫 번째 미디어 클릭 실패: {e}")
            return media_urls
        
        # 2. 다음 사진 버튼 클릭하여 반복
        max_iterations = 50  # 무한 루프 방지
        for i in range(2, max_iterations + 1):
            try:
                # aria-label="다음 사진" 버튼 찾기
                next_button = WebDriverWait(driver, 3).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "div[aria-label='다음 사진']"))
                )
                # 클릭할 요소의 상세 정보 로그 출력
                try:
                    aria_label = next_button.get_attribute("aria-label")
                    tag_name = next_button.tag_name
                    element_html = driver.execute_script("return arguments[0].outerHTML;", next_button)
                    logger.info(f"    🖱️ '다음 사진' 버튼 클릭 중 (#{i}):")
                    logger.info(f"       - 태그: {tag_name}")
                    logger.info(f"       - aria-label: {aria_label}")
                    logger.info(f"       - HTML (처음 300자): {element_html[:300]}")
                except Exception as e:
                    logger.warning(f"    ⚠️ 요소 정보 가져오기 실패: {e}")
                driver.execute_script("arguments[0].click();", next_button)
                time.sleep(1.5)  # 다음 미디어 로드 대기
                
                # 주소창 URL 수집
                current_url = driver.current_url
                
                # 중복 체크
                if current_url in media_urls:
                    logger.info(f"    ℹ️ 중복 URL 발견 (#{i}): {current_url}")
                    logger.info(f"    ✅ 총 {len(media_urls)}개 미디어 URL 수집 완료")
                    break
                
                media_urls.append(current_url)
                logger.info(f"    ✅ 미디어 URL #{i}: {current_url}")
                
            except TimeoutException:
                logger.info(f"    ℹ️ '다음 사진' 버튼을 찾을 수 없음 (마지막 미디어)")
                break
            except Exception as e:
                logger.warning(f"    ⚠️ 다음 사진 클릭 실패: {e}")
                break
        
        # 3. 닫기 버튼 클릭
        try:
            close_button = WebDriverWait(driver, 3).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "div[aria-label='닫기']"))
            )
            # 클릭할 요소의 상세 정보 로그 출력
            try:
                aria_label = close_button.get_attribute("aria-label")
                tag_name = close_button.tag_name
                element_html = driver.execute_script("return arguments[0].outerHTML;", close_button)
                logger.info(f"    🖱️ '닫기' 버튼 클릭 중:")
                logger.info(f"       - 태그: {tag_name}")
                logger.info(f"       - aria-label: {aria_label}")
                logger.info(f"       - HTML (처음 300자): {element_html[:300]}")
            except Exception as e:
                logger.warning(f"    ⚠️ 요소 정보 가져오기 실패: {e}")
            driver.execute_script("arguments[0].click();", close_button)
            time.sleep(1.5)  # 뷰어 닫힘 대기
            logger.info("    ✅ 미디어 뷰어 닫기 완료")
        except TimeoutException:
            logger.warning("    ⚠️ '닫기' 버튼을 찾을 수 없음")
        except Exception as e:
            logger.warning(f"    ⚠️ 닫기 버튼 클릭 실패: {e}")
        
        # 페이지 복구 확인 및 대기 (미디어 URL 수집 중 페이지 이동으로 인한 요소 참조 무효화 방지)
        time.sleep(1)
        try:
            # 해시태그 페이지인지 확인
            current_url = driver.current_url
            if "hashtag" not in current_url:
                logger.warning(f"    ⚠️ 해시태그 페이지가 아님: {current_url}")
                # 해시태그 페이지로 돌아가기 시도는 하지 않음 (이미 처리 중인 게시물이 있을 수 있음)
        except Exception as e:
            logger.warning(f"    ⚠️ 페이지 상태 확인 실패: {e}")
        
    except Exception as e:
        logger.error(f"  ⚠️ 미디어 URL 수집 중 오류: {e}")
        import traceback
        logger.error(traceback.format_exc())
    
    return media_urls

def crawl_hashtag_posts(driver, hashtag, test_mode=True):
    """
    해시태그 페이지에서 게시물 수집
    
    Args:
        driver: WebDriver 인스턴스
        hashtag: 해시태그 (예: "테스트" 또는 "#테스트")
        test_mode: 테스트 모드 (True면 상위 40개 게시물만 처리)
    
    Returns:
        list: 게시물 데이터 리스트
    """
    # 해시태그에서 # 제거
    hashtag_clean = hashtag.replace("#", "").strip()
    hashtag_url = f"https://www.facebook.com/hashtag/{hashtag_clean}"
    
    logger.info("=" * 60)
    logger.info(f"📱 해시태그 페이지 접속: {hashtag_url}")
    logger.info("=" * 60)
    
    try:
        # 해시태그 페이지 접속
        driver.get(hashtag_url)
        time.sleep(5)
        
        # 페이지 로드 대기
        try:
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            logger.info("✅ 페이지 로드 완료")
        except TimeoutException:
            logger.warning("⚠️ 페이지 로드 타임아웃, 계속 진행...")
        
        # 추가 대기
        time.sleep(3)
        
        # 스크롤 이벤트 추가 (최대치로 3번 반복하며 article 개수 확인) - 테스트용으로 주석처리
        # logger.info("📜 스크롤 이벤트 시작 (최대치로 3번 반복)...")
        # previous_article_count = 0
        # 
        # for scroll_round in range(1, 4):  # 3번 반복
        #     logger.info(f"\n📜 스크롤 라운드 #{scroll_round}/3")
        #     
        #     # 현재 article 개수 확인 (스크롤 전)
        #     try:
        #         current_articles = driver.find_elements(By.CSS_SELECTOR, "div[role='article']")
        #         current_count = len(current_articles)
        #         logger.info(f"   📊 스크롤 전 article 개수: {current_count}개")
        #     except Exception as e:
        #         logger.warning(f"   ⚠️ article 개수 확인 실패: {e}")
        #         current_count = 0
        #     
        #     # 최대치로 스크롤 다운
        #     logger.info("   ⬇️ 최대치로 스크롤 다운 중...")
        #     driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        #     time.sleep(2)  # 초기 대기
        #     
        #     # 동적 콘텐츠 로드 대기 (article 개수가 변하지 않을 때까지 또는 최대 대기 시간)
        #     logger.info("   ⏳ 콘텐츠 로드 대기 중...")
        #     max_wait_time = 10  # 최대 10초 대기
        #     wait_interval = 1  # 1초마다 확인
        #     stable_count = 0
        #     stable_threshold = 2  # 2번 연속 같은 개수면 로드 완료로 간주
        #     previous_check_count = None  # 초기화
        #     
        #     for wait_attempt in range(max_wait_time):
        #         try:
        #             check_articles = driver.find_elements(By.CSS_SELECTOR, "div[role='article']")
        #             check_count = len(check_articles)
        #             
        #             if wait_attempt == 0:
        #                 logger.info(f"      초기 article 개수: {check_count}개")
        #                 previous_check_count = check_count
        #             elif check_count != previous_check_count:
        #                 logger.info(f"      {wait_attempt}초 후 article 개수: {check_count}개 (변화 있음)")
        #                 stable_count = 0
        #                 previous_check_count = check_count
        #             else:
        #                 stable_count += 1
        #                 if stable_count >= stable_threshold:
        #                     logger.info(f"      {wait_attempt}초 후 article 개수: {check_count}개 (안정화됨, 로드 완료)")
        #                     break
        #             
        #             time.sleep(wait_interval)
        #         except Exception as e:
        #             logger.debug(f"      대기 중 article 확인 실패: {e}")
        #             time.sleep(wait_interval)
        #     
        #     # 스크롤 후 최종 article 개수 확인
        #     try:
        #         after_scroll_articles = driver.find_elements(By.CSS_SELECTOR, "div[role='article']")
        #         after_count = len(after_scroll_articles)
        #         logger.info(f"   📊 스크롤 후 최종 article 개수: {after_count}개")
        #         
        #         if after_count > current_count:
        #             added_count = after_count - current_count
        #             logger.info(f"   ✅ article 추가됨: +{added_count}개 (총 {after_count}개)")
        #         elif after_count == current_count:
        #             logger.info(f"   ℹ️ article 개수 변화 없음 (총 {after_count}개)")
        #         else:
        #             logger.warning(f"   ⚠️ article 개수 감소: {current_count} → {after_count}")
        #         
        #         previous_article_count = after_count
        #     except Exception as e:
        #         logger.warning(f"   ⚠️ 스크롤 후 article 개수 확인 실패: {e}")
        #     
        #     # 추가 대기 (lazy loading 트리거)
        #     time.sleep(2)
        #     
        #     # 약간 위로 스크롤 후 다시 아래로 (로딩 트리거)
        #     if scroll_round < 3:  # 마지막 라운드가 아니면
        #         driver.execute_script("window.scrollBy(0, -200);")
        #         time.sleep(1)
        #         driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        #         time.sleep(2)
        # 
        # logger.info(f"\n📊 최종 스크롤 완료: 총 {previous_article_count}개 article 발견")
        # 
        # # 스크롤 완료 후 최종 article 개수 재확인
        # logger.info("🔍 스크롤 완료 후 최종 article 개수 재확인 중...")
        # try:
        #     final_articles = driver.find_elements(By.CSS_SELECTOR, "div[role='article']")
        #     final_article_count = len(final_articles)
        #     logger.info(f"📊 최종 확인된 article 개수: {final_article_count}개")
        #     if final_article_count != previous_article_count:
        #         logger.info(f"   ℹ️ 스크롤 중 확인한 개수({previous_article_count}개)와 다름")
        # except Exception as e:
        #     logger.warning(f"⚠️ 최종 article 개수 확인 실패: {e}")
        #     final_article_count = previous_article_count
        
        # 게시물 컨테이너 찾기 (더 구체적인 경로 사용)
        logger.info("🔍 게시물 컨테이너 찾기 중...")
        post_container = None
        
        # 방법 1: 구체적인 경로로 찾기
        container_selectors = [
            # 최종 컨테이너 (가장 구체적)
            "div.x9f619.x1n2onr6.x1ja2u2z.xeuugli.xs83m0k.xjl7jj.x1xmf6yo.x1xegmmw.x1e56ztr.x13fj5qh.x19h7ccj.xu9j1y6.x7ep2pv",
            # 중간 경로를 거쳐서 찾기
            "div.x9f619.x1ja2u2z.x2lah0s.x1n2onr6.x1qjc9v5.x78zum5.x1q0g3np.x1a02dak.xl56j7k.x9otpla.x1w5wx5t.x1wsgfga.x1qfufaz > div.x9f619.x1n2onr6.x1ja2u2z.xeuugli.xs83m0k.xjl7jj.x1xmf6yo.x1xegmmw.x1e56ztr.x13fj5qh.x19h7ccj.xu9j1y6.x7ep2pv",
            # 부분 매칭
            "div[class*='x9f619'][class*='x1n2onr6'][class*='x1ja2u2z'][class*='xeuugli'][class*='xs83m0k']",
        ]
        
        for selector in container_selectors:
            try:
                post_container = driver.find_element(By.CSS_SELECTOR, selector)
                logger.info(f"✅ 게시물 컨테이너 발견: '{selector[:100]}...'")
                break
            except NoSuchElementException:
                continue
        
        # 방법 2: 여러 단계를 거쳐서 찾기 (방법 1이 실패한 경우)
        if not post_container:
            logger.info("🔍 방법 1 실패, 여러 단계를 거쳐서 찾기 시도...")
            try:
                # 최상위 컨테이너 찾기
                top_container = driver.find_element(By.CSS_SELECTOR, "div.x78zum5.xdt5ytf.x1iyjqo2")
                logger.info("✅ 최상위 컨테이너 발견")
                
                # 중간 단계들을 거쳐서 최종 컨테이너 찾기
                # div.x1n2onr6.x1ja2u2z.x9f619.x78zum5.xdt5ytf.x2lah0s.x193iq5w.xyamay9.x1l90r2v
                # > div.x9f619.x1n2onr6.x1ja2u2z.x78zum5.xdt5ytf.x1iyjqo2.x2lwn1j
                # > div.x9f619.x1n2onr6.x1ja2u2z.x78zum5.xdt5ytf.x2lah0s.x193iq5w.x6s0dn4
                # > div.x9f619.x193iq5w.x1talbiv.x1sltb1f.x3fxtfs.xf7dkkf.xv54qhq
                # > div.x9f619.x1ja2u2z.x2lah0s.x1n2onr6.x1qjc9v5.x78zum5.x1q0g3np.x1a02dak.xl56j7k.x9otpla.x1w5wx5t.x1wsgfga.x1qfufaz
                # > div.x9f619.x1n2onr6.x1ja2u2z.xeuugli.xs83m0k.xjl7jj.x1xmf6yo.x1xegmmw.x1e56ztr.x13fj5qh.x19h7ccj.xu9j1y6.x7ep2pv
                
                # JavaScript로 중첩된 구조를 따라가며 찾기
                post_container = driver.execute_script("""
                    var topContainer = arguments[0];
                    var targetClass = 'x9f619 x1n2onr6 x1ja2u2z xeuugli xs83m0k xjl7jj x1xmf6yo x1xegmmw x1e56ztr x13fj5qh x19h7ccj xu9j1y6 x7ep2pv';
                    
                    // 재귀적으로 찾기
                    function findContainer(element) {
                        if (element.className && element.className.trim() === targetClass) {
                            return element;
                        }
                        
                        var children = element.children;
                        for (var i = 0; i < children.length; i++) {
                            var result = findContainer(children[i]);
                            if (result) {
                                return result;
                            }
                        }
                        return null;
                    }
                    
                    return findContainer(topContainer);
                """, top_container)
                
                if post_container:
                    logger.info("✅ 중첩 구조를 통해 게시물 컨테이너 발견")
            except Exception as e:
                logger.warning(f"⚠️ 방법 2도 실패: {e}")
        
        if not post_container:
            logger.warning("⚠️ 게시물 컨테이너를 찾을 수 없습니다.")
            return []
        
        # 전체 페이지에서 <div role="article"> 찾기
        logger.info("🔍 전체 페이지에서 <div role='article'> 찾기 중...")
        all_article_divs = []
        try:
            all_article_divs = driver.find_elements(By.CSS_SELECTOR, "div[role='article']")
            logger.info(f"📊 전체 페이지 <div role='article'> 개수: {len(all_article_divs)}개")
        except Exception as e:
            logger.warning(f"⚠️ 전체 페이지 article 찾기 중 오류: {e}")
        
        # 컨테이너 내부에서 <div role="article"> 찾기
        logger.info("🔍 컨테이너 내부에서 <div role='article'> 찾기 중...")
        article_divs = []
        try:
            article_divs = post_container.find_elements(By.CSS_SELECTOR, "div[role='article']")
            logger.info(f"📊 컨테이너 내부 <div role='article'> 개수: {len(article_divs)}개")
        except Exception as e:
            logger.warning(f"⚠️ 컨테이너 내부 article 찾기 중 오류: {e}")
        
        # JavaScript로 더 정확하게 세기 (중첩 구조 고려)
        logger.info("🔍 JavaScript로 전체 페이지 <div role='article'> 재확인 중...")
        try:
            js_article_count = driver.execute_script("""
                var articles = document.querySelectorAll('div[role="article"]');
                var count = 0;
                var articleInfo = [];
                
                for (var i = 0; i < articles.length; i++) {
                    var article = articles[i];
                    // 중복 체크: 부모-자식 관계가 아닌 독립적인 article만 카운트
                    var isIndependent = true;
                    for (var j = 0; j < articles.length; j++) {
                        if (i !== j && articles[j].contains(article)) {
                            isIndependent = false;
                            break;
                        }
                    }
                    if (isIndependent) {
                        count++;
                        // 첫 3개의 article 정보 저장
                        if (articleInfo.length < 3) {
                            articleInfo.push({
                                index: i,
                                className: article.className || '',
                                id: article.id || '',
                                hasChildren: article.children.length > 0
                            });
                        }
                    }
                }
                
                return { count: count, info: articleInfo };
            """)
            
            logger.info(f"📊 JavaScript로 확인한 독립적인 <div role='article'> 개수: {js_article_count['count']}개")
            if js_article_count['info']:
                logger.info("   - 첫 3개 article 정보:")
                for info in js_article_count['info']:
                    logger.info(f"     Article #{info['index']}: className={info['className'][:50]}..., children={info['hasChildren']}")
        except Exception as e:
            logger.warning(f"⚠️ JavaScript article 카운트 중 오류: {e}")
        
        # 컨테이너 내부에서도 JavaScript로 재확인
        logger.info("🔍 JavaScript로 컨테이너 내부 <div role='article'> 재확인 중...")
        try:
            js_container_article_count = driver.execute_script("""
                var container = arguments[0];
                var articles = container.querySelectorAll('div[role="article"]');
                var count = 0;
                
                for (var i = 0; i < articles.length; i++) {
                    var article = articles[i];
                    // 중복 체크: 부모-자식 관계가 아닌 독립적인 article만 카운트
                    var isIndependent = true;
                    for (var j = 0; j < articles.length; j++) {
                        if (i !== j && articles[j].contains(article)) {
                            isIndependent = false;
                            break;
                        }
                    }
                    if (isIndependent) {
                        count++;
                    }
                }
                
                return count;
            """, post_container)
            
            logger.info(f"📊 JavaScript로 확인한 컨테이너 내부 독립적인 <div role='article'> 개수: {js_container_article_count}개")
        except Exception as e:
            logger.warning(f"⚠️ JavaScript 컨테이너 article 카운트 중 오류: {e}")
        
        # 최종적으로 사용할 article_divs 결정 (전체 페이지에서 찾은 것 사용)
        if all_article_divs:
            article_divs = all_article_divs
            logger.info(f"✅ 최종 사용: 전체 페이지에서 찾은 <div role='article'> {len(article_divs)}개")
        elif not article_divs:
            logger.warning("⚠️ 게시물을 찾을 수 없습니다.")
            return []
        
        # 테스트 모드: 개수만 출력하고 종료
        if test_mode:
            logger.info("=" * 60)
            logger.info("🧪 테스트 모드: 게시물 개수 확인 완료")
            logger.info(f"   - 컨테이너: 발견됨")
            logger.info(f"   - 전체 페이지 <div role='article'> 개수: {len(all_article_divs)}개")
            logger.info(f"   - 컨테이너 내부 <div role='article'> 개수: {len(article_divs) if article_divs else 0}개 (컨테이너 내부만)")
            logger.info(f"   - 최종 사용할 게시물 개수: {len(article_divs)}개")
            logger.info("=" * 60)
            
            # 상위 40개 article 처리 (테스트 모드)
            test_posts = []
            current_articles = article_divs
            target_count = 40
            test_idx = 0
            
            while test_idx < len(current_articles) and len(test_posts) < target_count:
                # article이 부족하고 더 필요하면 스크롤하여 추가 로드 (5개 남았을 때)
                if test_idx >= len(current_articles) - 5 and len(test_posts) < target_count:
                    logger.info(f"   📜 article이 부족함 (현재: {len(current_articles)}개, 수집: {len(test_posts)}/{target_count}개, 남은 article: {len(current_articles) - test_idx}개), 스크롤하여 추가 로드 시도...")
                    
                    # 페이지 하단으로 스크롤 (5번 반복)
                    try:
                        for scroll_round in range(1, 6):  # 5번 반복
                            logger.info(f"   ⬇️ 스크롤 라운드 #{scroll_round}/5")
                            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                            if scroll_round == 5:
                                # 마지막 스크롤 후 10초 대기
                                logger.info("   ⏳ 마지막 스크롤 후 콘텐츠 로드 대기 중... (10초)")
                                time.sleep(10)
                            else:
                                # 나머지 스크롤 후 3초 대기
                                time.sleep(3)
                        
                        # 스크롤 후 post_container가 stale element가 될 수 있으므로 다시 찾기
                        try:
                            # post_container 재찾기
                            container_selectors = [
                                "div.x9f619.x1n2onr6.x1ja2u2z.xeuugli.xs83m0k.xjl7jj.x1xmf6yo.x1xegmmw.x1e56ztr.x13fj5qh.x19h7ccj.xu9j1y6.x7ep2pv",
                                "div[class*='x9f619'][class*='x1n2onr6'][class*='x1ja2u2z'][class*='xeuugli'][class*='xs83m0k']",
                            ]
                            post_container = None
                            for selector in container_selectors:
                                try:
                                    post_container = driver.find_element(By.CSS_SELECTOR, selector)
                                    logger.info("   🔄 post_container 재찾기 완료")
                                    break
                                except NoSuchElementException:
                                    continue
                        except Exception as e:
                            logger.debug(f"   ℹ️ post_container 재찾기 실패 (무시): {e}")
                            post_container = None
                        
                        # 컨테이너 내부에서 새로운 article_div 확인
                        try:
                            # post_container가 있으면 컨테이너 내부에서 찾기
                            if post_container:
                                try:
                                    new_article_divs = post_container.find_elements(By.CSS_SELECTOR, "div[role='article']")
                                    logger.info(f"   🔍 컨테이너 내부 article 확인: {len(new_article_divs)}개")
                                except Exception as e:
                                    logger.warning(f"   ⚠️ 컨테이너 내부 article 찾기 실패 (전체 페이지에서 찾기): {e}")
                                    new_article_divs = driver.find_elements(By.CSS_SELECTOR, "div[role='article']")
                                    logger.info(f"   🔍 전체 페이지 article 확인: {len(new_article_divs)}개")
                            else:
                                # post_container가 없으면 전체 페이지에서 찾기
                                new_article_divs = driver.find_elements(By.CSS_SELECTOR, "div[role='article']")
                                logger.info(f"   🔍 전체 페이지 article 확인: {len(new_article_divs)}개")
                            
                            if len(new_article_divs) > len(current_articles):
                                added_count = len(new_article_divs) - len(current_articles)
                                logger.info(f"   ✅ 새로운 article 로드됨: {len(current_articles)}개 → {len(new_article_divs)}개 (+{added_count}개)")
                                current_articles = new_article_divs
                            else:
                                logger.info(f"   ℹ️ 새로운 article 없음 (현재: {len(new_article_divs)}개)")
                                # 더 이상 로드할 article이 없으면 종료
                                if test_idx >= len(current_articles) - 1:
                                    logger.info("   ℹ️ 더 이상 로드할 article이 없습니다. 수집 종료.")
                                    break
                        except Exception as e:
                            logger.warning(f"   ⚠️ 새로운 article 확인 중 오류: {e}")
                            # 오류 발생 시에도 전체 페이지에서 확인 시도
                            try:
                                new_articles = driver.find_elements(By.CSS_SELECTOR, "div[role='article']")
                                if len(new_articles) > len(current_articles):
                                    logger.info(f"   ✅ 새로운 article 로드됨 (전체 페이지 확인): {len(current_articles)}개 → {len(new_articles)}개")
                                    current_articles = new_articles
                            except:
                                pass
                    except Exception as e:
                        logger.warning(f"   ⚠️ 스크롤 중 오류: {e}")
                
                # 현재 article 처리
                article = current_articles[test_idx]
                test_idx += 1
                logger.info(f"\n   📋 테스트 모드 - 게시물 #{test_idx} 처리 중... (전체 article: {len(current_articles)}개)")
                try:
                    # 게시물 상단이 뷰포트 상단에 오도록 스크롤 (주석처리 - 스크롤 액션으로 인한 문제 방지)
                    # try:
                    #     driver.execute_script("arguments[0].scrollIntoView({block: 'start', behavior: 'smooth'});", article)
                    #     time.sleep(1)  # 스크롤 완료 대기
                    # except Exception as e:
                    #     logger.warning(f"   ⚠️ 스크롤 실패: {e}")
                    
                    # 첫 번째 article만 디버깅 정보 출력
                    if test_idx == 1:
                        article_html = driver.execute_script("return arguments[0].outerHTML;", article)
                        logger.info(f"   - 첫 번째 article div 샘플 (처음 500자): {article_html[:500]}...")
                        
                        # 첫 번째 article에서 user_name과 datetime 셀렉터 테스트
                        logger.info("   - 첫 번째 article에서 셀렉터 테스트 중...")
                        
                        # user_name 셀렉터 테스트 (우선: 구체적인 셀렉터)
                        logger.info("     🔍 user_name 셀렉터 테스트:")
                        
                        user_name_selectors_test = [
                            "div[data-ad-rendering-role='profile_name'] a[role='link']",  # a 요소에서 직접 추출
                            "div[data-ad-rendering-role='profile_name'] a[role='link'] span",  # span이 있는 경우
                            "div[data-ad-rendering-role='profile_name'] a[role='link'] b span",  # b > span 구조
                            "div[data-ad-rendering-role='profile_name'] span",
                            "div[data-ad-rendering-role='profile_name']",  # 차선책
                        ]
                        
                        for idx, selector in enumerate(user_name_selectors_test, 1):
                            try:
                                element = article.find_element(By.CSS_SELECTOR, selector)
                                text = element.text.strip()
                                priority = "우선" if idx == 1 else "차선책"
                                logger.info(f"       ✅ ({priority}) '{selector}': '{text}'")
                            except NoSuchElementException:
                                priority = "우선" if idx == 1 else "차선책"
                                logger.info(f"       ❌ ({priority}) '{selector}': 요소 없음")
                            except Exception as e:
                                priority = "우선" if idx == 1 else "차선책"
                                logger.info(f"       ⚠️ ({priority}) '{selector}': {e}")
                    
                    # 실제 extract_post_data 함수 호출하여 테스트
                    logger.info(f"     🔍 게시물 #{test_idx} - extract_post_data 함수 호출 테스트:")
                    try:
                        # 요소 참조 갱신 (이전 게시물 처리 중 페이지 이동으로 인한 요소 참조 무효화 방지)
                        try:
                            refreshed_articles = driver.find_elements(By.CSS_SELECTOR, "div[role='article']")
                            if len(refreshed_articles) > test_idx - 1:
                                article = refreshed_articles[test_idx - 1]
                                logger.info(f"     🔄 게시물 #{test_idx} 요소 참조 갱신 완료")
                                # current_articles도 갱신
                                if len(refreshed_articles) > len(current_articles):
                                    current_articles = refreshed_articles
                            else:
                                logger.warning(f"     ⚠️ 게시물 #{test_idx} 요소를 다시 찾을 수 없음 (인덱스: {test_idx - 1}, 전체 개수: {len(refreshed_articles)})")
                                logger.warning(f"     ⚠️ 게시물 #{test_idx} 스킵합니다.")
                                continue
                        except Exception as e:
                            logger.warning(f"     ⚠️ 요소 갱신 실패, 기존 요소 사용: {e}")
                        
                        # article 요소를 직접 전달 (인덱스 대신)
                        # extract_post_data는 인덱스 또는 WebElement를 받을 수 있음
                        post_data = extract_post_data(driver, article)
                        
                        # post_data가 None인지 체크
                        if post_data is None:
                            logger.warning(f"       ⚠️ 게시물 #{test_idx} - extract_post_data가 None을 반환했습니다. 빈 dict로 초기화합니다.")
                            post_data = {
                                "user_name": None,
                                "datetime": None,
                                "content": None,
                                "hashtags": [],
                                "like_count": 0,
                                "comments_count": 0,
                                "content_count": 0,
                                "hashtag_count": 0,
                                "share_count": 0,
                                "media_urls": [],
                                "media_count": 0,
                                # audio_caption과 media_caption은 초기화하지 않음
                                "user_num": None
                            }
                        
                        logger.info(f"       ✅ 게시물 #{test_idx} - extract_post_data 실행 완료")
                        
                        # 미디어 URL 수집 테스트
                        logger.info(f"     🔍 게시물 #{test_idx} - extract_media_urls 함수 호출 테스트:")
                        try:
                            # article이 유효한지 확인
                            if article is None:
                                logger.warning(f"       ⚠️ 게시물 #{test_idx} - article이 None입니다. 미디어 URL 수집을 건너뜁니다.")
                                if post_data is not None:
                                    post_data["media_urls"] = []
                                    post_data["media_count"] = 0
                            else:
                                # article 요소 재찾기 (stale element 방지)
                                try:
                                    refreshed_articles = driver.find_elements(By.CSS_SELECTOR, "div[role='article']")
                                    if len(refreshed_articles) > test_idx - 1:
                                        article = refreshed_articles[test_idx - 1]
                                    else:
                                        logger.warning(f"       ⚠️ 게시물 #{test_idx} - 미디어 수집을 위한 요소를 찾을 수 없음")
                                        if post_data is not None:
                                            post_data["media_urls"] = []
                                            post_data["media_count"] = 0
                                        raise Exception("요소를 찾을 수 없음")
                                except Exception as e:
                                    logger.warning(f"       ⚠️ 요소 재찾기 실패: {e}")
                                
                                media_urls = extract_media_urls(driver, article)
                                if post_data is not None:
                                    post_data["media_urls"] = media_urls
                                    post_data["media_count"] = len(media_urls)
                                    logger.info(f"       ✅ 게시물 #{test_idx} - extract_media_urls 실행 완료: {len(media_urls)}개 미디어 URL 수집")
                                else:
                                    logger.warning(f"       ⚠️ 게시물 #{test_idx} - post_data가 None입니다.")
                        except Exception as e:
                            logger.warning(f"       ⚠️ 게시물 #{test_idx} - extract_media_urls 실행 실패: {e}")
                            if post_data is not None:
                                post_data["media_urls"] = []
                                post_data["media_count"] = 0
                        
                        logger.info("=" * 60)
                        logger.info(f"       📋 테스트 모드 - 게시물 #{test_idx} post_data (JSON 형식):")
                        logger.info("=" * 60)
                        # post_data를 JSON 형식으로 예쁘게 출력
                        post_data_json = json.dumps(post_data, ensure_ascii=False, indent=2)
                        logger.info(post_data_json)
                        logger.info("=" * 60)
                        
                        # 빈 데이터 체크: datetime이나 media_urls가 있으면 저장, 모두 없으면 스킵
                        has_datetime = post_data.get("datetime") is not None
                        has_media = len(post_data.get("media_urls", [])) > 0
                        
                        # datetime이나 media_urls가 있으면 저장 (user_name이나 content가 null이어도 저장)
                        if not has_datetime and not has_media:
                            logger.warning(f"   ⚠️ 게시물 #{test_idx} - 빈 데이터 감지 (datetime과 media_urls 모두 없음), 스킵합니다")
                            continue
                        
                        test_posts.append(post_data)
                        
                        # 게시물 하나씩 바로 JSON에 저장
                        save_to_json([post_data], test_mode=test_mode)
                        logger.info(f"   💾 게시물 #{test_idx} JSON 파일에 저장 완료")
                    except Exception as e:
                        logger.warning(f"       ⚠️ 게시물 #{test_idx} - extract_post_data 실행 실패: {e}")
                        import traceback
                        logger.warning(traceback.format_exc())
                        
                except Exception as e:
                    logger.warning(f"   - 게시물 #{test_idx} 처리 실패: {e}")
            
            return test_posts
        
        # 실제 모드: article_divs를 post_elements로 사용 (테스트 모드와 동일)
        collected_posts = []
        
        # article_divs 사용 (테스트 모드와 동일한 소스)
        logger.info(f"📊 사용할 article 개수: {len(article_divs)}개")
        
        if len(article_divs) == 0:
            logger.info("ℹ️ 처리할 article이 없습니다.")
            return []
        
        # 필요한 article 개수 (테스트 모드: 40개, 일반 모드: 무제한이지만 스크롤로 계속 로드)
        target_count = 40 if test_mode else float('inf')
        current_articles = article_divs
        article_idx = 0
        
        # 각 게시물 처리
        while article_idx < len(current_articles):
            # 필요한 개수만큼 수집했으면 종료 (테스트 모드)
            if test_mode and len(collected_posts) >= target_count:
                logger.info(f"🧪 테스트 모드: {target_count}개 게시물 수집 완료, 종료")
                break
            
            # 현재 article이 부족하고 더 필요하면 스크롤하여 추가 로드 (5개 남았을 때)
            if article_idx >= len(current_articles) - 5:  # 마지막 5개 남았을 때 미리 스크롤
                logger.info(f"📜 article이 부족함 (현재: {len(current_articles)}개, 처리 중: {article_idx + 1}번째, 남은 article: {len(current_articles) - article_idx}개), 스크롤하여 추가 로드 시도...")
                
                # 페이지 하단으로 스크롤 (5번 반복)
                try:
                    for scroll_round in range(1, 6):  # 5번 반복
                        logger.info(f"⬇️ 스크롤 라운드 #{scroll_round}/5")
                        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                        if scroll_round == 5:
                            # 마지막 스크롤 후 10초 대기
                            logger.info("⏳ 마지막 스크롤 후 콘텐츠 로드 대기 중... (10초)")
                            time.sleep(10)
                        else:
                            # 나머지 스크롤 후 3초 대기
                            time.sleep(3)
                    
                    # 스크롤 후 post_container가 stale element가 될 수 있으므로 다시 찾기
                    try:
                        # post_container 재찾기
                        container_selectors = [
                            "div.x9f619.x1n2onr6.x1ja2u2z.xeuugli.xs83m0k.xjl7jj.x1xmf6yo.x1xegmmw.x1e56ztr.x13fj5qh.x19h7ccj.xu9j1y6.x7ep2pv",
                            "div[class*='x9f619'][class*='x1n2onr6'][class*='x1ja2u2z'][class*='xeuugli'][class*='xs83m0k']",
                        ]
                        post_container = None
                        for selector in container_selectors:
                            try:
                                post_container = driver.find_element(By.CSS_SELECTOR, selector)
                                logger.info("🔄 post_container 재찾기 완료")
                                break
                            except NoSuchElementException:
                                continue
                    except Exception as e:
                        logger.debug(f"ℹ️ post_container 재찾기 실패 (무시): {e}")
                        post_container = None
                    
                    # 컨테이너 내부에서 새로운 article_div 확인
                    try:
                        # post_container가 있으면 컨테이너 내부에서 찾기
                        if post_container:
                            try:
                                new_article_divs = post_container.find_elements(By.CSS_SELECTOR, "div[role='article']")
                                logger.info(f"🔍 컨테이너 내부 article 확인: {len(new_article_divs)}개")
                            except Exception as e:
                                logger.warning(f"⚠️ 컨테이너 내부 article 찾기 실패 (전체 페이지에서 찾기): {e}")
                                new_article_divs = driver.find_elements(By.CSS_SELECTOR, "div[role='article']")
                                logger.info(f"🔍 전체 페이지 article 확인: {len(new_article_divs)}개")
                        else:
                            # post_container가 없으면 전체 페이지에서 찾기
                            new_article_divs = driver.find_elements(By.CSS_SELECTOR, "div[role='article']")
                            logger.info(f"🔍 전체 페이지 article 확인: {len(new_article_divs)}개")
                        
                        if len(new_article_divs) > len(current_articles):
                            added_count = len(new_article_divs) - len(current_articles)
                            logger.info(f"✅ 새로운 article 로드됨: {len(current_articles)}개 → {len(new_article_divs)}개 (+{added_count}개)")
                            current_articles = new_article_divs
                        else:
                            logger.info(f"ℹ️ 새로운 article 없음 (현재: {len(new_article_divs)}개)")
                            # 더 이상 로드할 article이 없으면 종료
                            if article_idx >= len(current_articles) - 1:
                                logger.info("ℹ️ 더 이상 로드할 article이 없습니다. 수집 종료.")
                                break
                    except Exception as e:
                        logger.warning(f"⚠️ 새로운 article 확인 중 오류: {e}")
                        # 오류 발생 시에도 전체 페이지에서 확인 시도
                        try:
                            new_articles = driver.find_elements(By.CSS_SELECTOR, "div[role='article']")
                            if len(new_articles) > len(current_articles):
                                logger.info(f"✅ 새로운 article 로드됨 (전체 페이지 확인): {len(current_articles)}개 → {len(new_articles)}개")
                                current_articles = new_articles
                        except:
                            pass
                except Exception as e:
                    logger.warning(f"⚠️ 스크롤 중 오류: {e}")
            
            # 현재 article 처리
            post_element = current_articles[article_idx]
            global_idx = article_idx + 1
            logger.info(f"\n[{global_idx}] 게시물 처리 중... (전체 article: {len(current_articles)}개)")
            
            try:
                # 미디어 URL 수집 중 페이지 이동으로 인한 요소 참조 무효화 방지: 매번 요소를 다시 찾기
                try:
                    # 현재 페이지의 article 요소들 다시 찾기
                    refreshed_articles = driver.find_elements(By.CSS_SELECTOR, "div[role='article']")
                    if len(refreshed_articles) > global_idx - 1:
                        post_element = refreshed_articles[global_idx - 1]
                        logger.info(f"  🔄 요소 참조 갱신 완료 (인덱스: {global_idx - 1})")
                    else:
                        logger.warning(f"  ⚠️ 요소를 다시 찾을 수 없음 (인덱스: {global_idx - 1}, 전체 개수: {len(refreshed_articles)})")
                except Exception as e:
                    logger.warning(f"  ⚠️ 요소 갱신 실패, 기존 요소 사용: {e}")
                
                # 게시물 데이터 추출 (요소 참조를 안전하게 전달)
                # post_element가 stale할 수 있으므로 인덱스를 전달하여 함수 내에서 재찾기
                post_data = extract_post_data(driver, global_idx - 1)
                
                # post_data가 None인지 체크
                if post_data is None:
                    logger.warning(f"  ⚠️ 게시물 #{global_idx} - extract_post_data가 None을 반환했습니다. 빈 dict로 초기화합니다.")
                    post_data = {
                        "user_name": None,
                        "datetime": None,
                        "content": None,
                        "hashtags": [],
                        "like_count": 0,
                        "comments_count": 0,
                        "content_count": 0,
                        "hashtag_count": 0,
                        "share_count": 0,
                        "media_urls": [],
                        "media_count": 0,
                        # audio_caption과 media_caption은 초기화하지 않음
                        "user_num": None
                    }
                
                # 빈 데이터 체크: datetime이나 media_urls가 있으면 저장, 모두 없으면 스킵
                has_datetime = post_data.get("datetime") is not None
                has_media = len(post_data.get("media_urls", [])) > 0
                has_user_name = post_data.get("user_name") is not None
                has_content = post_data.get("content") is not None
                
                # datetime이나 media_urls가 있으면 저장 (user_name이나 content가 null이어도 저장)
                if not has_datetime and not has_media:
                    logger.warning(f"  ⚠️ 게시물 #{global_idx} - 빈 데이터 감지 (datetime과 media_urls 모두 없음), 스킵합니다")
                    continue
                
                # 미디어 URL 수집 (페이지 이동 가능하므로 요소 참조 무효화 주의)
                try:
                    media_urls = extract_media_urls(driver, post_element)
                    if post_data is not None:
                        post_data["media_urls"] = media_urls
                        post_data["media_count"] = len(media_urls)
                except Exception as e:
                    logger.warning(f"  ⚠️ 게시물 #{global_idx} - extract_media_urls 실행 실패: {e}")
                    if post_data is not None:
                        post_data["media_urls"] = []
                        post_data["media_count"] = 0
                
                # 미디어 URL 수집 후 요소 참조 갱신 (driver.back() 등으로 인한 페이지 변경 대비)
                try:
                    refreshed_articles_after_media = driver.find_elements(By.CSS_SELECTOR, "div[role='article']")
                    if len(refreshed_articles_after_media) > global_idx - 1:
                        post_element = refreshed_articles_after_media[global_idx - 1]
                        logger.info(f"  🔄 미디어 수집 후 요소 참조 갱신 완료")
                    time.sleep(0.5)  # 페이지 상태 안정화 대기
                except Exception as e:
                    logger.warning(f"  ⚠️ 미디어 수집 후 요소 갱신 실패: {e}")
                
                # 해시태그 정보 추가
                post_data["hashtag"] = hashtag_clean
                post_data["hashtag_url"] = hashtag_url
                
                # 수집 시간 추가
                post_data["collected_at"] = datetime.now().isoformat()
                
                collected_posts.append(post_data)
                
                logger.info(f"✅ 게시물 #{global_idx} 수집 완료")
                logger.info("=" * 60)
                logger.info(f"📋 게시물 #{global_idx} post_data:")
                logger.info("=" * 60)
                # post_data를 JSON 형식으로 예쁘게 출력
                post_data_json = json.dumps(post_data, ensure_ascii=False, indent=2)
                logger.info(post_data_json)
                logger.info("=" * 60)
                logger.info(f"📊 현재까지 수집된 데이터: {len(collected_posts)}개")
                
                # 게시물 하나씩 바로 JSON에 저장 (강제 종료 대비)
                save_to_json([post_data], test_mode=test_mode)
                logger.info(f"💾 게시물 #{global_idx} JSON 파일에 저장 완료")
                
                # 테스트 모드면 상위 40개 게시물만 처리하고 종료
                if test_mode and len(collected_posts) >= 40:
                    logger.info("🧪 테스트 모드: 상위 40개 게시물 처리 완료, 종료")
                    return collected_posts
                
                # 요청 간 딜레이
                time.sleep(2)
                
            except Exception as e:
                logger.error(f"  ❌ 게시물 처리 중 오류: {e}")
                import traceback
                logger.error(traceback.format_exc())
            
            # article_idx 증가 (오류 발생 여부와 관계없이 증가)
            article_idx += 1
        
        logger.info(f"✅ 해시태그 '{hashtag_clean}' 수집 완료: 총 {len(collected_posts)}개 게시물")
        return collected_posts
        
    except Exception as e:
        logger.error(f"❌ 해시태그 페이지 처리 중 오류: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return []

def is_duplicate_post(new_post, existing_post):
    """
    두 게시물이 중복인지 확인
    
    Args:
        new_post: 새 게시물 데이터
        existing_post: 기존 게시물 데이터
    
    Returns:
        bool: 중복이면 True, 아니면 False
    """
    # 방법 1: media_urls의 첫 번째 요소 비교
    new_first_media = new_post.get("media_urls", [None])[0] if new_post.get("media_urls") else None
    existing_first_media = existing_post.get("media_urls", [None])[0] if existing_post.get("media_urls") else None
    
    if new_first_media and existing_first_media:
        if new_first_media == existing_first_media:
            return True
    
    # 방법 2: user_name + content + hashtags 비교
    new_user_name = new_post.get("user_name", "").strip()
    new_content = new_post.get("content", "").strip()
    new_hashtags = sorted(new_post.get("hashtags", []))
    
    existing_user_name = existing_post.get("user_name", "").strip()
    existing_content = existing_post.get("content", "").strip()
    existing_hashtags = sorted(existing_post.get("hashtags", []))
    
    if (new_user_name and existing_user_name and 
        new_user_name == existing_user_name and
        new_content and existing_content and
        new_content == existing_content and
        new_hashtags == existing_hashtags):
        return True
    
    return False

def save_to_json(posts_data, test_mode=False):
    """
    수집한 데이터를 JSON 파일에 저장 (중복 제거 포함)
    
    Args:
        posts_data: 게시물 데이터 리스트
        test_mode: 테스트 모드 여부 (현재는 중복 제거에 영향 없음)
    """
    try:
        # 기존 데이터 로드
        existing_data = []
        if MEDIA_JSON.exists():
            try:
                with open(MEDIA_JSON, "r", encoding="utf-8") as f:
                    existing_data = json.load(f)
            except json.JSONDecodeError:
                logger.warning(f"⚠️ {MEDIA_JSON} 파일의 JSON 형식이 올바르지 않습니다. 새로 생성합니다.")
        
        # 중복 제거 수행 (테스트 모드 포함)
        logger.info("🔍 중복 게시물 체크 중...")
        new_posts = []
        duplicate_count = 0
        updated_count = 0
        
        for new_post in posts_data:
            is_duplicate = False
            existing_post_index = None
            
            # 기존 데이터와 비교
            for idx, existing_post in enumerate(existing_data):
                if is_duplicate_post(new_post, existing_post):
                    is_duplicate = True
                    existing_post_index = idx
                    duplicate_count += 1
                    
                    # 기존 항목의 audio_caption과 media_caption 보존
                    existing_audio_caption = existing_post.get("audio_caption")
                    existing_media_caption = existing_post.get("media_caption")
                    
                    # 새 항목의 데이터로 기존 항목 업데이트 (단, audio_caption과 media_caption은 보존)
                    for key, value in new_post.items():
                        if key not in ["audio_caption", "media_caption"]:
                            existing_post[key] = value
                    
                    # audio_caption과 media_caption이 기존에 있고 유효한 경우 보존
                    if existing_audio_caption:
                        # 리스트인 경우 내용이 있는지 확인
                        if isinstance(existing_audio_caption, list):
                            has_content = any(str(cap).strip() for cap in existing_audio_caption if cap)
                            if has_content:
                                existing_post["audio_caption"] = existing_audio_caption
                                logger.info(f"   ✅ 기존 audio_caption 보존 ({len(existing_audio_caption)}개 항목)")
                        # 문자열인 경우
                        elif isinstance(existing_audio_caption, str) and existing_audio_caption.strip():
                            existing_post["audio_caption"] = existing_audio_caption
                            logger.info(f"   ✅ 기존 audio_caption 보존 (문자열)")
                    
                    if existing_media_caption:
                        # 리스트인 경우 내용이 있는지 확인
                        if isinstance(existing_media_caption, list):
                            has_content = any(str(cap).strip() for cap in existing_media_caption if cap)
                            if has_content:
                                existing_post["media_caption"] = existing_media_caption
                                logger.info(f"   ✅ 기존 media_caption 보존 ({len(existing_media_caption)}개 항목)")
                        # 문자열인 경우
                        elif isinstance(existing_media_caption, str) and existing_media_caption.strip():
                            existing_post["media_caption"] = existing_media_caption
                            logger.info(f"   ✅ 기존 media_caption 보존 (문자열)")
                    
                    # 중복 검사에 사용된 필드로 로그 표시 (datetime 제외)
                    new_first_media = new_post.get("media_urls", [None])[0] if new_post.get("media_urls") else None
                    if new_first_media:
                        logger.info(f"   ⚠️ 중복 게시물 발견 (업데이트): media_url='{new_first_media[:80]}...', user_name='{new_post.get('user_name', 'N/A')}'")
                    else:
                        # media_url이 없으면 user_name, content, hashtags로 표시
                        content_preview = new_post.get('content', 'N/A')[:50] if new_post.get('content') else 'N/A'
                        hashtags_str = ', '.join(new_post.get('hashtags', []))[:50] if new_post.get('hashtags') else 'N/A'
                        logger.info(f"   ⚠️ 중복 게시물 발견 (업데이트): user_name='{new_post.get('user_name', 'N/A')}', content='{content_preview}...', hashtags='{hashtags_str}'")
                    
                    updated_count += 1
                    break
            
            if not is_duplicate:
                new_posts.append(new_post)
        
        if duplicate_count > 0:
            logger.info(f"   ℹ️ 총 {duplicate_count}개 중복 게시물 발견 (기존 항목 업데이트)")
            if updated_count > 0:
                logger.info(f"   ✅ {updated_count}개 기존 항목 업데이트됨 (audio_caption/media_caption 보존)")
            logger.info(f"   ✅ {len(new_posts)}개 새 게시물 저장됩니다")
        
        # 중복 제거된 새 데이터만 추가
        existing_data.extend(new_posts)
        posts_to_save = new_posts
        
        # JSON 파일에 저장
        with open(MEDIA_JSON, "w", encoding="utf-8") as f:
            json.dump(existing_data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"✅ {MEDIA_JSON} 파일에 {len(posts_to_save)}개 게시물 저장 완료 (총 {len(existing_data)}개)")
        
    except Exception as e:
        logger.error(f"❌ JSON 저장 실패: {e}")
        import traceback
        logger.error(traceback.format_exc())

def main():
    """메인 함수"""
    logger.info("=" * 60)
    logger.info("🚀 Facebook 크롤링 시작")
    logger.info("=" * 60)
    
    # Selenium WebDriver 초기화
    driver = setup_driver()
    
    try:
        # Facebook 로그인
        if not login_facebook(driver):
            logger.error("❌ 로그인 실패. 크롤링을 종료합니다.")
            return
        
        all_posts = []
        
        # 해시태그 리스트 반복
        for hashtag_idx, hashtag in enumerate(HASHTAGS, 1):
            logger.info(f"\n{'='*60}")
            logger.info(f"해시태그 #{hashtag_idx}/{len(HASHTAGS)}: {hashtag}")
            logger.info(f"{'='*60}")
            
            # 해시태그 페이지에서 게시물 수집
            posts = crawl_hashtag_posts(driver, hashtag, test_mode=TEST_MODE)
            
            if posts:
                all_posts.extend(posts)
                logger.info(f"✅ {hashtag}에서 {len(posts)}개 게시물 수집 완료")
            else:
                logger.warning(f"⚠️ {hashtag}에서 게시물을 찾을 수 없습니다.")
            
            # 해시태그 간 딜레이
            if hashtag_idx < len(HASHTAGS):
                time.sleep(3)
        
        # JSON 파일에 저장 (각 게시물은 이미 개별적으로 저장됨)
        if all_posts:
            logger.info(f"\n✅ 총 {len(all_posts)}개 게시물 수집 완료 (각 게시물은 이미 JSON 파일에 저장됨)")
        else:
            logger.warning("⚠️ 수집된 게시물이 없습니다.")
        
    except Exception as e:
        logger.error(f"❌ 크롤링 중 오류 발생: {e}")
        import traceback
        logger.error(traceback.format_exc())
    
    finally:
        driver.quit()
        logger.info("\n🔒 브라우저 종료")
        logger.info("=" * 60)
        logger.info("✅ 모든 작업 완료")
        logger.info("=" * 60)

if __name__ == "__main__":
    main()

