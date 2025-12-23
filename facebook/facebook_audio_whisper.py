"""
Facebook 게시물의 비디오에서 오디오 추출 및 Whisper 음성 인식
facebook_imgocr.py의 비디오 불러들이는 로직과 instagram_extract_audio_from_json.py의 Whisper 사용 방법 참고
"""

import base64
import io
import json
import logging
import os
import pickle
import subprocess
import tempfile
import time
from pathlib import Path
from typing import List, Optional

import whisper
from dotenv import load_dotenv

# Selenium Wire 사용 시도 (없으면 일반 Selenium 사용)
# 주의: selenium-wire는 선택적 의존성입니다. 설치되지 않아도 정상 작동합니다.
# selenium-wire는 selenium의 Options를 그대로 사용합니다.
try:
    from seleniumwire import webdriver  # type: ignore # noqa: F401
    # selenium-wire는 일반 selenium의 Options를 사용
    from selenium.webdriver.chrome.options import Options
    SELENIUM_WIRE_AVAILABLE = True
    _SELENIUM_WIRE_ERROR = None
except ImportError as e:
    # 디버깅: import 실패 이유 저장 (나중에 로그로 출력)
    _SELENIUM_WIRE_ERROR = str(e)
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    SELENIUM_WIRE_AVAILABLE = False
except Exception as e:
    # ImportError 외의 다른 예외도 처리
    _SELENIUM_WIRE_ERROR = f"{type(e).__name__}: {str(e)}"
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    SELENIUM_WIRE_AVAILABLE = False

from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException

# .env 파일에서 로그인 정보 불러오기
load_dotenv('/home/pmi/venvs/source_code/.env')
EMAIL = os.getenv("FB_EMAIL")
PASSWORD = os.getenv("FB_PASSWORD")

# 파일 경로
# 파일 경로 (현재 파일 위치 기준)
BASE_DIR = Path(__file__).parent
DATA_FILE = BASE_DIR / "facebook_media.json"
COOKIE_PATH = BASE_DIR / "facebook_cookies.pkl"
LOG_PATH = BASE_DIR / "facebook.log"

# 로깅 설정
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


def setup_driver(use_selenium_wire: bool = True) -> webdriver.Chrome:
    """Chrome WebDriver 설정 (Selenium Wire 지원) - 리눅스 환경용 Chrome binary 자동 탐지"""
    import shutil
    from pathlib import Path
    
    # Chrome/Chromium binary 경로 찾기
    chrome_path_candidates = []
    seen_paths = set()  # 중복 제거용
    
    # 1. 작동하는 경로를 우선 추가 (테스트로 확인됨)
    priority_paths = [
        Path("/usr/bin/chromium-browser"),  # 우선 (테스트로 작동 확인됨)
    ]
    
    for path in priority_paths:
        if path.exists():
            resolved = path.resolve()
            if resolved.exists() and resolved.is_file():
                resolved_str = resolved.as_posix()
                if resolved_str not in seen_paths:
                    chrome_path_candidates.append(resolved)
                    seen_paths.add(resolved_str)
    
    # 2. PATH에서 찾기
    for cmd in ['chromium-browser', 'google-chrome', 'google-chrome-stable', 'chromium', 'chrome']:
        chrome_path = shutil.which(cmd)
        if chrome_path:
            path_obj = Path(chrome_path)
            resolved = path_obj.resolve()
            resolved_str = resolved.as_posix()
            if resolved_str not in seen_paths:
                chrome_path_candidates.append(resolved)
                seen_paths.add(resolved_str)
    
    # 3. 일반적인 설치 경로 확인
    common_paths = [
        Path("/usr/bin/google-chrome-stable"),
        Path("/usr/bin/google-chrome"),
        Path("/opt/google/chrome/google-chrome"),
        Path("/opt/google/chrome/chrome"),
    ]
    
    for path in common_paths:
        if path.exists():
            # 심볼릭 링크나 래퍼 스크립트인 경우 실제 파일 찾기
            resolved = path.resolve()
            if resolved.exists() and resolved.is_file():
                resolved_str = resolved.as_posix()
                if resolved_str not in seen_paths:
                    chrome_path_candidates.append(resolved)
                    seen_paths.add(resolved_str)
    
    if not chrome_path_candidates:
        error_msg = "Chrome/Chromium을 찾을 수 없습니다."
        logger.error(error_msg)
        print(f"❌ {error_msg}")
        print("💡 해결 방법:")
        print("   1. Chrome 브라우저가 올바르게 설치되어 있는지 확인하세요")
        print("   2. 다음 명령어로 Chrome을 설치할 수 있습니다:")
        print("      sudo apt-get update && sudo apt-get install -y google-chrome-stable")
        print("   3. 또는 Chromium을 설치할 수 있습니다:")
        print("      sudo apt-get install -y chromium-browser")
        raise RuntimeError(error_msg)
    
    # 각 경로를 시도하여 실제로 작동하는지 확인
    logger.info(f"🔍 총 {len(chrome_path_candidates)}개 Chrome 경로 발견, 순서대로 시도합니다:")
    for idx, cp in enumerate(chrome_path_candidates[:5], 1):
        logger.info(f"   {idx}. {cp.as_posix()}")
    
    last_error = None
    for chrome_path in chrome_path_candidates:
        chrome_binary_location = chrome_path.as_posix()
        logger.info(f"Chrome 경로 시도: {chrome_binary_location}")
        
        options = Options()
        options.binary_location = chrome_binary_location
        
        # Headless 모드 활성화 (리눅스 환경용)
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        options.add_argument("user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        # 자동 재생 정책 우회
        options.add_argument("--autoplay-policy=no-user-gesture-required")
        
        # Selenium Wire 사용 (네트워크 요청 가로채기)
        if use_selenium_wire and SELENIUM_WIRE_AVAILABLE:
            # Selenium Wire 옵션 설정
            seleniumwire_options = {
                'suppress_connection_errors': False,  # 연결 오류 표시
            }
            
            # Selenium Wire의 로깅 비활성화 (과도한 로그 방지)
            import logging as std_logging
            seleniumwire_logger = std_logging.getLogger('seleniumwire')
            seleniumwire_logger.setLevel(std_logging.WARNING)  # WARNING 이상만 출력
            
            service = Service()
            try:
                driver = webdriver.Chrome(service=service, options=options, seleniumwire_options=seleniumwire_options)
                logger.info(f"✅ Selenium Wire로 네트워크 요청 모니터링 활성화 (Chrome: {chrome_binary_location})")
                # 스크립트 타임아웃을 5분으로 설정 (비디오 재생 시간 고려)
                driver.set_script_timeout(300)  # 5분
                return driver
            except Exception as e:
                error_str = str(e)
                logger.warning(f"⚠️ Selenium Wire 초기화 실패 ({chrome_binary_location}): {error_str}")
                logger.info(f"   💡 일반 Selenium으로 폴백...")
                
                # 일반 Selenium으로 폴백
                try:
                    from selenium import webdriver as selenium_webdriver
                    driver = selenium_webdriver.Chrome(service=service, options=options)
                    logger.info(f"✅ 일반 Selenium으로 초기화 성공 (Chrome: {chrome_binary_location})")
                    driver.set_script_timeout(300)
                    return driver
                except Exception as e2:
                    logger.warning(f"⚠️ 일반 Selenium도 실패 ({chrome_binary_location}): {str(e2)}")
                    last_error = e2
                    continue
        else:
            if use_selenium_wire:
                logger.warning("⚠️ Selenium Wire를 사용하려고 했지만 설치되지 않았습니다. 일반 Selenium을 사용합니다.")
                logger.warning(f"   SELENIUM_WIRE_AVAILABLE={SELENIUM_WIRE_AVAILABLE}, use_selenium_wire={use_selenium_wire}")
                # import 실패 이유 출력
                if '_SELENIUM_WIRE_ERROR' in globals() and _SELENIUM_WIRE_ERROR:
                    logger.warning(f"   Import 실패 이유: {_SELENIUM_WIRE_ERROR}")
                    
                    # blinker._saferef 에러인 경우 특별 안내
                    if 'blinker._saferef' in _SELENIUM_WIRE_ERROR or 'blinker' in _SELENIUM_WIRE_ERROR.lower():
                        logger.warning("   💡 blinker 버전 호환성 문제입니다.")
                        logger.warning("   해결 방법: pip install \"blinker<1.7\"")
                        logger.warning("   또는: pip install --upgrade selenium-wire")
                    else:
                        logger.warning("   해결 방법: pip install selenium-wire (또는 pip install --upgrade selenium-wire)")
            
            service = Service()
            try:
                # Selenium Wire가 없을 때는 일반 selenium 사용
                if SELENIUM_WIRE_AVAILABLE:
                    from selenium import webdriver as selenium_webdriver
                    driver = selenium_webdriver.Chrome(service=service, options=options)
                else:
                    driver = webdriver.Chrome(service=service, options=options)
                logger.info(f"✅ Chrome WebDriver 초기화 성공: {chrome_binary_location}")
                driver.set_script_timeout(300)
                return driver
            except Exception as e:
                last_error = e
                logger.warning(f"⚠️ Chrome 경로 실패 ({chrome_binary_location}): {str(e)}")
                continue
    
    # 모든 경로가 실패한 경우
    error_msg = f"모든 Chrome 경로 시도 실패. 마지막 오류: {str(last_error)}"
    logger.error(error_msg, exc_info=True)
    print(f"❌ {error_msg}")
    print("💡 해결 방법:")
    print("   1. Chrome 브라우저가 올바르게 설치되어 있는지 확인하세요")
    print("   2. 다음 명령어로 Chrome을 설치할 수 있습니다:")
    print("      sudo apt-get update && sudo apt-get install -y google-chrome-stable")
    print("   3. 또는 Chromium을 설치할 수 있습니다:")
    print("      sudo apt-get install -y chromium-browser")
    raise RuntimeError(error_msg) from last_error


def login_facebook(driver: webdriver.Chrome) -> bool:
    """Facebook 로그인 (쿠키 사용)"""
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
    
    # 쿠키가 없거나 실패한 경우
    if EMAIL and PASSWORD:
        logger.warning("⚠️ 쿠키가 없거나 만료되었습니다. 수동 로그인이 필요합니다.")
        logger.info("📱 Facebook 페이지를 열어 로그인해주세요...")
        driver.get("https://www.facebook.com")
        time.sleep(5)
        
        # 로그인 완료 대기
        input("로그인 완료 후 Enter를 눌러주세요...")
        
        # 쿠키 저장
        try:
            cookies = driver.get_cookies()
            with open(COOKIE_PATH, "wb") as f:
                pickle.dump(cookies, f)
            logger.info("✅ 쿠키 저장 완료")
            return True
        except Exception as e:
            logger.warning(f"⚠️ 쿠키 저장 실패: {e}")
    
    return False


def find_ffmpeg() -> Optional[str]:
    """ffmpeg 실행 파일 경로 찾기"""
    import shutil
    ffmpeg_exe = shutil.which("ffmpeg")
    if ffmpeg_exe:
        return ffmpeg_exe
    
    # Windows에서 일반적인 경로 확인
    if os.name == 'nt':
        common_paths = [
            r"C:\ffmpeg\bin\ffmpeg.exe",
            r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
            r"C:\Program Files (x86)\ffmpeg\bin\ffmpeg.exe",
        ]
        for path in common_paths:
            if os.path.exists(path):
                return path
    
    logger.warning("⚠️ ffmpeg를 찾을 수 없습니다. PATH에 ffmpeg가 있는지 확인하세요.")
    return None


def extract_video_blob_to_base64(driver: webdriver.Chrome, video_element) -> Optional[str]:
    """
    JavaScript를 사용하여 video 요소의 blob URL을 가져와서 Base64로 변환
    instagram_extract_voice.py의 extract_video_blob_to_base64 함수 참고
    """
    try:
        # 비디오 상태 및 실제 URL 확인
        logger.debug("   🔍 비디오 상태 및 실제 URL 확인 중...")
        video_info = driver.execute_script("""
            var video = arguments[0];
            var info = {
                readyState: video.readyState,
                networkState: video.networkState,
                src: video.src,
                currentSrc: video.currentSrc,
                duration: video.duration,
                videoWidth: video.videoWidth,
                videoHeight: video.videoHeight,
                poster: video.poster,  // poster 속성 추가
                sources: [],
                parentAttributes: {},
                dataAttributes: {},
                videoAttributes: {}
            };
            
            // video 요소의 모든 속성 확인
            for (var attr of video.attributes) {
                if (attr.name.startsWith('data-')) {
                    info.dataAttributes[attr.name] = attr.value;
                } else {
                    info.videoAttributes[attr.name] = attr.value;
                }
            }
            
            // source 태그들 확인
            var sources = video.querySelectorAll('source');
            for (var i = 0; i < sources.length; i++) {
                info.sources.push({
                    src: sources[i].src,
                    type: sources[i].type
                });
            }
            
            // 부모 요소의 속성 확인
            var parent = video.parentElement;
            if (parent) {
                for (var attr of parent.attributes) {
                    if (attr.name.includes('src') || attr.name.includes('url') || attr.name.includes('video')) {
                        info.parentAttributes[attr.name] = attr.value;
                    }
                }
            }
            
            return info;
        """, video_element)
        
        logger.debug(f"   📊 비디오 상태: readyState={video_info['readyState']}, duration={video_info.get('duration', 'N/A')}")
        logger.debug(f"   📹 video.src: {video_info['src'][:80] if video_info['src'] else 'None'}...")
        logger.debug(f"   📹 video.currentSrc: {video_info['currentSrc'][:80] if video_info['currentSrc'] else 'None'}...")
        logger.debug(f"   🖼️ video.poster: {video_info.get('poster', 'None')[:80] if video_info.get('poster') else 'None'}...")
        
        # poster가 있으면 비디오가 존재한다는 신호
        if video_info.get('poster'):
            logger.debug(f"   ✅ poster 속성 발견 - 비디오 존재 확인됨")
            # poster URL에서 실제 비디오 URL 패턴 유추 시도
            poster_url = video_info.get('poster', '')
            # poster URL 패턴: scontent-ssn1-1.xx.fbcdn.net/v/t51.71878-15/...
            # 실제 비디오 URL 패턴: scontent-ssn1-1.xx.fbcdn.net/v/t51.71878-15/... (동일한 경로 구조일 수 있음)
            logger.debug(f"   💡 poster URL을 기반으로 비디오 URL 패턴 분석...")
        
        # 실제 비디오 URL 찾기 (blob이 아닌 경우)
        actual_video_url = None
        
        # 1. currentSrc 확인
        if video_info['currentSrc'] and not video_info['currentSrc'].startswith('blob:'):
            actual_video_url = video_info['currentSrc']
            logger.info(f"   ✅ 실제 비디오 URL 발견 (currentSrc): {actual_video_url[:80]}...")
        # 2. src 확인
        elif video_info['src'] and not video_info['src'].startswith('blob:'):
            actual_video_url = video_info['src']
            logger.info(f"   ✅ 실제 비디오 URL 발견 (src): {actual_video_url[:80]}...")
        # 3. source 태그 확인
        elif video_info['sources']:
            for source in video_info['sources']:
                if source['src'] and not source['src'].startswith('blob:'):
                    actual_video_url = source['src']
                    logger.info(f"   ✅ source 태그에서 실제 비디오 URL 발견: {actual_video_url[:80]}...")
                    break
        
        # 4. 부모 요소의 속성에서 URL 찾기
        if not actual_video_url and video_info.get('parentAttributes'):
            for attr_name, attr_value in video_info['parentAttributes'].items():
                if attr_value and isinstance(attr_value, str):
                    # URL 패턴 확인
                    if (attr_value.startswith('http://') or attr_value.startswith('https://')) and \
                       ('.mp4' in attr_value or '.webm' in attr_value or 'video' in attr_value.lower()):
                        actual_video_url = attr_value
                        logger.info(f"   ✅ 부모 요소 속성에서 실제 비디오 URL 발견 ({attr_name}): {actual_video_url[:80]}...")
                        break
        
        # 5. video 요소의 모든 속성에서 URL 찾기 (data-video-src 등)
        if not actual_video_url and video_info.get('videoAttributes'):
            for attr_name, attr_value in video_info['videoAttributes'].items():
                if attr_value and isinstance(attr_value, str):
                    # URL 패턴 확인 (poster는 제외)
                    if attr_name != 'poster' and (attr_value.startswith('http://') or attr_value.startswith('https://')):
                        if ('.mp4' in attr_value or '.webm' in attr_value or 'video' in attr_value.lower() or 
                            ('fbcdn' in attr_value and 'video' in attr_value.lower())):
                            actual_video_url = attr_value
                            logger.info(f"   ✅ video 요소 속성에서 실제 비디오 URL 발견 ({attr_name}): {actual_video_url[:80]}...")
                            break
        
        # 6. data 속성에서 URL 찾기
        if not actual_video_url and video_info.get('dataAttributes'):
            for attr_name, attr_value in video_info['dataAttributes'].items():
                if attr_value and isinstance(attr_value, str):
                    # URL 패턴 확인
                    if (attr_value.startswith('http://') or attr_value.startswith('https://')) and \
                       ('.mp4' in attr_value or '.webm' in attr_value or 'video' in attr_value.lower()):
                        actual_video_url = attr_value
                        logger.info(f"   ✅ data 속성에서 실제 비디오 URL 발견 ({attr_name}): {actual_video_url[:80]}...")
                        break
        
        # 7. JavaScript 변수나 window 객체에서 비디오 URL 찾기
        if not actual_video_url:
            logger.debug("   🔍 JavaScript 변수/객체에서 비디오 URL 검색 중...")
            try:
                js_video_url = driver.execute_script("""
                    // window 객체와 전역 변수에서 비디오 URL 찾기
                    var videoUrls = [];
                    
                    // window 객체의 모든 속성 검사
                    for (var key in window) {
                        try {
                            var value = window[key];
                            if (typeof value === 'string' && value.includes('http') && 
                                (value.includes('.mp4') || value.includes('.webm') || 
                                 value.includes('fbcdn') || value.includes('scontent'))) {
                                if (!value.includes('poster') && !value.includes('.jpg')) {
                                    videoUrls.push(value);
                                }
                            }
                        } catch(e) {}
                    }
                    
                    // React나 다른 프레임워크의 상태에서 찾기
                    if (window.__REACT_DEVTOOLS_GLOBAL_HOOK__) {
                        try {
                            var reactInstances = window.__REACT_DEVTOOLS_GLOBAL_HOOK__.renderers;
                            // React 컴포넌트 트리에서 비디오 URL 찾기 (간단한 시도)
                        } catch(e) {}
                    }
                    
                    // document에서 data 속성이나 script 태그에서 찾기
                    var scripts = document.querySelectorAll('script');
                    for (var i = 0; i < scripts.length; i++) {
                        var scriptText = scripts[i].innerText || scripts[i].textContent || '';
                        // URL 패턴 찾기 (정규식)
                        var urlPattern = /https?:\/\/[^"'\s]+\.(mp4|webm|m3u8)/gi;
                        var matches = scriptText.match(urlPattern);
                        if (matches) {
                            for (var j = 0; j < matches.length; j++) {
                                if (!matches[j].includes('poster') && !matches[j].includes('.jpg')) {
                                    videoUrls.push(matches[j]);
                                }
                            }
                        }
                    }
                    
                    return videoUrls.length > 0 ? videoUrls[0] : null;
                """)
                
                if js_video_url:
                    actual_video_url = js_video_url
                    logger.info(f"   ✅ JavaScript 변수에서 실제 비디오 URL 발견: {actual_video_url[:80]}...")
            except Exception as e:
                logger.debug(f"   ℹ️ JavaScript 변수 검색 실패: {e}")
        
        # 8. 비디오 재생 후 네트워크 로그에서 비디오 URL 찾기 시도
        if not actual_video_url:
            logger.debug("   🔍 비디오 재생 후 네트워크 로그에서 비디오 URL 검색 중...")
            try:
                # 비디오 재생 시도 (실제 URL이 나타날 수 있음)
                driver.execute_script("""
                    var video = arguments[0];
                    if (video) {
                        video.load();
                        video.play().catch(function(e) {
                            console.log('Auto-play blocked:', e);
                        });
                    }
                """, video_element)
                
                import time
                time.sleep(3)  # 네트워크 요청이 발생할 시간 대기
                
                # 네트워크 로그 다시 확인
                logs = driver.get_log('performance')
                video_urls = []
                for log in logs:
                    try:
                        log_data = json.loads(log.get('message', '{}'))
                        message = log_data.get('message', {})
                        method = message.get('method', '')
                        
                        if method in ['Network.responseReceived', 'Network.requestWillBeSent']:
                            params = message.get('params', {})
                            request = params.get('request', {})
                            response = params.get('response', {})
                            url = request.get('url') or response.get('url', '')
                            mime_type = response.get('mimeType', '').lower()
                            
                            # 비디오 URL 패턴 확인 (poster 이미지 제외)
                            if url and ('.mp4' in url or '.webm' in url or 'video' in mime_type or 
                                       ('fbcdn' in url and ('video' in url.lower() or 'v/t' in url)) or 
                                       ('scontent' in url and ('video' in url.lower() or 'v/t' in url))):
                                if not url.startswith('blob:') and url not in video_urls and 'poster' not in url.lower() and '.jpg' not in url.lower():
                                    video_urls.append(url)
                    except:
                        continue
                
                if video_urls:
                    # 가장 최근 URL 사용
                    actual_video_url = video_urls[-1]
                    logger.info(f"   ✅ 비디오 재생 후 네트워크 로그에서 실제 비디오 URL 발견: {actual_video_url[:80]}...")
            except Exception as e:
                logger.debug(f"   ℹ️ 비디오 재생 후 네트워크 로그 확인 실패: {e}")
        
        # 9. 페이지 소스에서 비디오 URL 패턴 찾기 (정규식)
        if not actual_video_url:
            logger.debug("   🔍 페이지 소스에서 비디오 URL 패턴 검색 중...")
            try:
                import re
                page_source = driver.page_source
                
                # Facebook CDN 비디오 URL 패턴
                patterns = [
                    r'https?://[^"\'\\s]*scontent[^"\'\\s]*\.(?:mp4|webm)',
                    r'https?://[^"\'\\s]*fbcdn[^"\'\\s]*\.(?:mp4|webm)',
                    r'https?://[^"\'\\s]*scontent[^"\'\\s]*v/t[^"\'\\s]*',
                    r'https?://[^"\'\\s]*fbcdn[^"\'\\s]*v/t[^"\'\\s]*',
                    r'https?://[^"\'\\s]*scontent[^"\'\\s]*video[^"\'\\s]*',
                    r'https?://[^"\'\\s]*fbcdn[^"\'\\s]*video[^"\'\\s]*',
                ]
                
                found_urls = []
                for pattern in patterns:
                    matches = re.finditer(pattern, page_source, re.IGNORECASE)
                    for match in matches:
                        url = match.group(0)
                        # URL 유효성 검사
                        if url and len(url) > 20 and 'poster' not in url.lower() and '.jpg' not in url.lower() and '.png' not in url.lower():
                            found_urls.append(url)
                
                if found_urls:
                    # 가장 긴 URL 선택 (일반적으로 실제 비디오 URL이 더 길다)
                    actual_video_url = max(found_urls, key=len)
                    logger.info(f"   ✅ 페이지 소스에서 실제 비디오 URL 발견: {actual_video_url[:80]}...")
            except Exception as e:
                logger.debug(f"   ℹ️ 페이지 소스 검색 실패: {e}")
        
        # 실제 URL이 있으면 requests로 다운로드
        if actual_video_url:
            logger.info("   🔄 실제 비디오 URL에서 다운로드 중...")
            try:
                import requests
                
                # Selenium의 쿠키를 requests 세션에 전달
                selenium_cookies = driver.get_cookies()
                session = requests.Session()
                
                # 쿠키 추가
                for cookie in selenium_cookies:
                    session.cookies.set(cookie['name'], cookie['value'], domain=cookie.get('domain', ''))
                
                # 헤더 추가
                user_agent = driver.execute_script("return navigator.userAgent;")
                headers = {
                    'User-Agent': user_agent,
                    'Referer': driver.current_url,
                    'Accept': 'video/webm,video/ogg,video/*;q=0.9,application/ogg;q=0.7,audio/*;q=0.6,*/*;q=0.5',
                    'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
                    'Accept-Encoding': 'identity',
                    'Range': 'bytes=0-',
                    'Connection': 'keep-alive',
                }
                
                logger.info(f"   📥 다운로드 시도 중... (쿠키 {len(selenium_cookies)}개 사용)")
                response = session.get(actual_video_url, headers=headers, timeout=60, stream=True)
                
                if response.status_code == 200 or response.status_code == 206:
                    # 스트림으로 다운로드
                    video_bytes = b''
                    total_size = 0
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            video_bytes += chunk
                            total_size += len(chunk)
                            if total_size % (1024 * 1024) == 0:
                                logger.info(f"   📥 다운로드 중... {total_size / (1024 * 1024):.1f} MB")
                    
                    logger.info(f"   ✅ 다운로드 완료 (크기: {len(video_bytes)} bytes)")
                    
                    # base64로 인코딩
                    base64_data = base64.b64encode(video_bytes).decode('utf-8')
                    logger.info(f"   ✅ base64 변환 완료 (크기: {len(base64_data)} bytes)")
                    return base64_data
                else:
                    logger.warning(f"   ⚠️ 다운로드 실패: HTTP {response.status_code}")
            except Exception as e:
                logger.warning(f"   ⚠️ 다운로드 중 오류: {e}")
                import traceback
                logger.debug(traceback.format_exc())
        
        # blob URL인 경우 - JavaScript로 직접 추출 시도
        if video_info['src'] and video_info['src'].startswith('blob:'):
            logger.info("   🔄 JavaScript로 blob URL에서 비디오 데이터 직접 추출 중...")
            try:
                # 비디오 재생 시도 (자동 재생 정책 우회)
                driver.execute_script("arguments[0].play().catch(function(e) { console.log('재생 실패:', e); });", video_element)
                time.sleep(2)
                
                # blob URL을 fetch로 가져와서 base64로 변환
                base64_data = driver.execute_async_script("""
                    var video = arguments[0];
                    var callback = arguments[arguments.length - 1];
                    
                    try {
                        var blobUrl = video.src || video.currentSrc;
                        if (!blobUrl || !blobUrl.startsWith('blob:')) {
                            callback(null);
                            return;
                        }
                        
                        fetch(blobUrl)
                            .then(function(response) {
                                return response.blob();
                            })
                            .then(function(blob) {
                                var reader = new FileReader();
                                reader.onloadend = function() {
                                    var base64 = reader.result.split(',')[1];
                                    callback(base64);
                                };
                                reader.onerror = function() {
                                    callback(null);
                                };
                                reader.readAsDataURL(blob);
                            })
                            .catch(function(e) {
                                console.log('blob fetch 실패:', e);
                                callback(null);
                            });
                    } catch (e) {
                        console.log('오류:', e);
                        callback(null);
                    }
                """, video_element)
                
                if base64_data:
                    logger.info(f"   ✅ blob URL에서 base64 변환 완료 (크기: {len(base64_data)} bytes)")
                    return base64_data
                else:
                    logger.warning(f"   ⚠️ blob URL에서 base64 변환 실패")
            except Exception as e:
                logger.warning(f"   ⚠️ blob URL 처리 중 오류: {e}")
                import traceback
                logger.debug(traceback.format_exc())
        
        logger.warning(f"   ⚠️ 비디오 데이터 추출 실패")
        return None
        
    except Exception as e:
        logger.warning(f"   ⚠️ base64 변환 실패: {e}")
        import traceback
        logger.debug(traceback.format_exc())
        return None


def process_video_with_ffmpeg_whisper(video_bytes: bytes) -> Optional[str]:
    """
    비디오 바이트 데이터를 ffmpeg/Whisper로 처리
    instagram_extract_voice.py의 process_video_with_ffmpeg_whisper 함수 참고
    """
    # 파일 크기 검증
    if len(video_bytes) < 1024:  # 1KB 미만이면 오류
        logger.warning(f"  ⚠️ 비디오 데이터가 너무 작습니다: {len(video_bytes)} bytes")
        return None
    
    # 파일 헤더 검증
    if len(video_bytes) >= 8:
        file_header = video_bytes[:8]
        # MP4 파일 시그니처 확인
        if file_header[4:8] != b'ftyp' and file_header[:4] not in [b'\x00\x00\x00\x20', b'\x00\x00\x00\x18']:
            logger.warning(f"  ⚠️ 유효하지 않은 비디오 파일 형식: {file_header.hex()[:16]}")
            # 경고만 하고 계속 진행 (일부 스트림은 다른 형식일 수 있음)
    
    logger.info(f"📹 비디오 데이터 크기: {len(video_bytes)} bytes ({len(video_bytes) / (1024 * 1024):.2f} MB)")
    
    # 임시 파일로 비디오 저장
    with tempfile.NamedTemporaryFile(delete=False, suffix='.mp4') as video_file:
        video_path = video_file.name
        video_file.write(video_bytes)
    
    try:
        # ffmpeg 경로 찾기
        ffmpeg_exe = find_ffmpeg()
        if not ffmpeg_exe:
            logger.error("❌ ffmpeg를 찾을 수 없습니다.")
            return None
        
        # ffmpeg로 비디오에서 오디오 추출
        logger.info("🔄 ffmpeg로 오디오 추출 중...")
        with tempfile.NamedTemporaryFile(delete=False, suffix='.wav') as audio_file:
            audio_path = audio_file.name
        
        # ffmpeg 명령어 실행 (DASH 스트림 등 불완전한 파일도 처리 가능하도록 옵션 추가)
        ffmpeg_cmd = [
            ffmpeg_exe,
            '-i', video_path,
            '-vn',  # 비디오 스트림 제거
            '-acodec', 'pcm_s16le',  # PCM 16-bit
            '-ar', '16000',  # 샘플링 레이트 16kHz (Whisper 권장)
            '-ac', '1',  # 모노
            '-y',  # 덮어쓰기
            '-err_detect', 'ignore_err',  # 오류 무시하고 계속 진행
            '-fflags', '+genpts',  # 타임스탬프 재생성
            audio_path
        ]
        
        logger.info(f"   🔧 ffmpeg 명령어 실행 중...")
        use_shell = os.name == 'nt'  # Windows인 경우
        result = subprocess.run(
            ffmpeg_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=use_shell,
            timeout=300  # 5분 타임아웃
        )
        
        if result.returncode != 0:
            logger.warning(f"⚠️ ffmpeg 오류 (returncode={result.returncode}): {result.stderr[-500:]}")  # 마지막 500자만 출력
            # 파일이 손상되었을 수 있으므로 파일 크기 확인
            if os.path.exists(video_path):
                file_size = os.path.getsize(video_path)
                logger.warning(f"⚠️ 다운로드한 파일 크기: {file_size} bytes")
            return None
        
        logger.info(f"✅ 오디오 추출 완료: {audio_path}")
        
        # 무음 여부 확인
        logger.info("🔍 무음 여부 확인 중...")
        volume_check_cmd = [
            ffmpeg_exe,
            '-i', audio_path,
            '-af', 'volumedetect',
            '-f', 'null',
            '-'
        ]
        
        use_shell = os.name == 'nt'
        volume_result = subprocess.run(
            volume_check_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=use_shell
        )
        
        # 볼륨 레벨 파싱
        is_silent = False
        if volume_result.returncode == 0:
            stderr_output = volume_result.stderr
            mean_volume = None
            max_volume = None
            
            for line in stderr_output.split('\n'):
                if 'mean_volume:' in line:
                    try:
                        mean_volume = float(line.split('mean_volume:')[1].split('dB')[0].strip())
                    except:
                        pass
                if 'max_volume:' in line:
                    try:
                        max_volume = float(line.split('max_volume:')[1].split('dB')[0].strip())
                    except:
                        pass
            
            if mean_volume is not None and max_volume is not None:
                if mean_volume < -60 and max_volume < -50:
                    is_silent = True
                    logger.info(f"🔇 무음 비디오로 판단됨 (평균: {mean_volume:.2f} dB, 최대: {max_volume:.2f} dB)")
                else:
                    logger.info(f"🔊 음성이 있는 비디오 (평균: {mean_volume:.2f} dB, 최대: {max_volume:.2f} dB)")
            elif mean_volume is not None:
                if mean_volume < -60:
                    is_silent = True
                    logger.info(f"🔇 무음 비디오로 판단됨 (평균 볼륨: {mean_volume:.2f} dB)")
                else:
                    logger.info(f"🔊 음성이 있는 비디오 (평균 볼륨: {mean_volume:.2f} dB)")
        
        # 무음이면 Whisper 처리 생략
        if is_silent:
            logger.info("⏭️ 무음 비디오이므로 Whisper 처리를 건너뜁니다.")
            return None
        
        # Whisper로 오디오를 텍스트로 변환
        logger.info("🔄 Whisper로 음성 인식 중...")
        try:
            if not os.path.exists(audio_path):
                logger.warning(f"⚠️ 오디오 파일을 찾을 수 없습니다: {audio_path}")
                return None
            
            audio_path_abs = os.path.abspath(audio_path)
            logger.info(f"   📁 오디오 파일 경로: {audio_path_abs}")
            
            # ffmpeg 경로 설정
            ffmpeg_path = find_ffmpeg()
            if ffmpeg_path:
                if os.path.isfile(ffmpeg_path):
                    ffmpeg_dir = os.path.dirname(ffmpeg_path)
                else:
                    ffmpeg_dir = ffmpeg_path
                
                current_path = os.environ.get('PATH', '')
                if ffmpeg_dir not in current_path.split(os.pathsep):
                    os.environ['PATH'] = ffmpeg_dir + os.pathsep + current_path
                    logger.info(f"   🔧 PATH에 ffmpeg 디렉토리 추가: {ffmpeg_dir}")
            
            # Whisper 모델 로드 (base 모델 사용)
            model = whisper.load_model("base")
            
            # 오디오 파일에서 텍스트 추출
            result = model.transcribe(audio_path_abs, language="ko")  # 한국어 지정
            
            transcribed_text = result["text"].strip()
            logger.info(f"✅ 음성 인식 완료: {len(transcribed_text)}자")
            
            return transcribed_text if transcribed_text else None
            
        except Exception as e:
            logger.warning(f"⚠️ Whisper 처리 실패: {e}")
            import traceback
            logger.warning(traceback.format_exc())
            return None
    
    finally:
        # 임시 파일 삭제
        try:
            if os.path.exists(video_path):
                os.unlink(video_path)
            if os.path.exists(audio_path):
                os.unlink(audio_path)
        except Exception as e:
            logger.warning(f"⚠️ 임시 파일 삭제 실패: {e}")


def extract_audio_from_video_url(driver: webdriver.Chrome, url: str) -> Optional[str]:
    """
    Facebook 비디오 URL에서 오디오 추출
    facebook_imgocr.py의 process_media_url_with_selenium 로직 참고
    """
    try:
        logger.info(f"  📱 Facebook 페이지 로딩 중: {url[:80]}...")
        driver.get(url)
        
        # 페이지 로드 대기
        try:
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            logger.info("  ✅ 페이지 로드 완료")
        except TimeoutException:
            logger.warning("  ⚠️ 페이지 로드 타임아웃, 계속 진행...")
        
        # 추가 대기 및 스크롤 (미디어 로드를 위해)
        time.sleep(5)
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)
        driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(2)
        
        # 비디오 찾기
        try:
            video_elements = driver.find_elements(By.CSS_SELECTOR, "video")
            logger.info(f"  🔍 비디오 요소 개수: {len(video_elements)}")
            
            for video_idx, video in enumerate(video_elements, 1):
                # "소리 켜기" 버튼 클릭 (오디오 활성화)
                try:
                    logger.info(f"  🔊 '소리 켜기' 버튼 찾는 중...")
                    audio_button = driver.find_elements(By.XPATH, "//div[@aria-label='소리 켜기']")
                    
                    if audio_button:
                        logger.info(f"  ✅ '소리 켜기' 버튼 발견. 클릭 중...")
                        try:
                            # Selenium으로 클릭 시도
                            audio_button[0].click()
                            logger.info(f"  ✅ '소리 켜기' 버튼 클릭 완료 (Selenium)")
                            time.sleep(2)  # 오디오 활성화 대기 시간 증가
                        except Exception as e:
                            logger.debug(f"  ℹ️ Selenium 클릭 실패, JavaScript로 시도: {e}")
                            # JavaScript로 클릭 시도
                            driver.execute_script("""
                                var buttons = document.querySelectorAll('div[aria-label="소리 켜기"]');
                                if (buttons.length > 0) {
                                    buttons[0].click();
                                    console.log('소리 켜기 버튼 클릭 완료 (JavaScript)');
                                }
                            """)
                            time.sleep(2)  # 오디오 활성화 대기 시간 증가
                    else:
                        logger.info(f"  ℹ️ '소리 켜기' 버튼을 찾을 수 없습니다. (이미 켜져있거나 다른 패턴일 수 있음)")
                except Exception as e:
                    logger.debug(f"  ℹ️ 오디오 버튼 찾기 중 오류 (무시): {e}")
                
                # 비디오를 강제로 로드하고 재생 시도 (src가 설정되도록)
                # 오디오 스트림이 캡처되도록 충분한 시간 확보
                try:
                    logger.info(f"  📹 비디오 #{video_idx} 로드 및 재생 시도 중...")
                    driver.execute_script("""
                        var video = arguments[0];
                        // 비디오 로드
                        video.load();
                        // 재생 시도 (자동 재생 정책 우회)
                        video.play().catch(function(e) {
                            console.log('자동 재생 실패, 사용자 상호작용 시뮬레이션:', e);
                            // 클릭 이벤트로 재생 시도
                            var clickEvent = new MouseEvent('click', {
                                bubbles: true,
                                cancelable: true,
                                view: window
                            });
                            video.dispatchEvent(clickEvent);
                            video.play().catch(function(e2) {
                                console.log('재생 실패:', e2);
                            });
                        });
                    """, video)
                    time.sleep(5)  # 비디오 로드 및 재생 대기 (오디오 스트림 캡처를 위해 시간 증가)
                except Exception as e:
                    logger.debug(f"  ℹ️ 비디오 재생 시도 중 오류 (무시): {e}")
                
                # src 속성 확인 (여러 번 시도)
                video_src = None
                for attempt in range(3):
                    video_src = video.get_attribute("src")
                    if not video_src:
                        video_src = video.get_attribute("data-src")
                    if not video_src:
                        # JavaScript로 직접 확인
                        video_src = driver.execute_script("""
                            var video = arguments[0];
                            return video.src || video.currentSrc || null;
                        """, video)
                    
                    if video_src:
                        break
                    else:
                        logger.info(f"  ⏳ src 속성 확인 시도 {attempt + 1}/3... (대기 중)")
                        time.sleep(2)
                
                logger.info(f"  📹 비디오 #{video_idx} src: {video_src[:80] if video_src else 'None'}...")
                
                # src가 None이면 네트워크 요청에서 비디오 URL 찾기
                if not video_src:
                    # 방법 1: Selenium Wire로 네트워크 요청 가로채기 (우선)
                    if SELENIUM_WIRE_AVAILABLE and hasattr(driver, 'requests'):
                        logger.info(f"  🔍 Selenium Wire로 네트워크 요청 모니터링 중...")
                        try:
                            audio_stream_urls = []  # 오디오 전용 스트림
                            video_stream_urls = []   # 일반 비디오 스트림
                            
                            # 최근 요청들 확인 (비디오 재생 후 발생한 요청)
                            for request in driver.requests:
                                url = request.url
                                path = request.path
                                
                                # 실제 비디오/오디오 파일만 필터링 (더 엄격한 조건)
                                if url and not url.startswith('blob:'):
                                    # Facebook CDN 도메인 확인
                                    is_fbcdn = 'fbcdn' in url.lower() or 'scontent' in url.lower()
                                    
                                    # 실제 미디어 파일 확장자 확인
                                    is_media_file = (
                                        '.mp4' in url.lower() or 
                                        '.webm' in url.lower() or 
                                        '.m3u8' in url.lower()
                                    )
                                    
                                    # CSS, JS, 이미지 파일 제외
                                    is_excluded = (
                                        '.css' in url.lower() or 
                                        '.js' in url.lower() or 
                                        '.svg' in url.lower() or
                                        '.jpg' in url.lower() or 
                                        '.jpeg' in url.lower() or
                                        '.png' in url.lower() or
                                        '.gif' in url.lower() or
                                        '.ico' in url.lower() or
                                        'poster' in url.lower() or
                                        'static.xx.fbcdn.net/rsrc.php' in url.lower()  # 정적 리소스 제외
                                    )
                                    
                                    # 실제 비디오/오디오 스트림만 포함
                                    if is_fbcdn and is_media_file and not is_excluded:
                                        # 오디오 전용 스트림 확인 (strext=1, dash_ln_heaac_vbr3_audio 등)
                                        if 'strext=1' in url or 'dash_ln_heaac' in url.lower() or 'dash_ln_heaac_vbr3_audio' in url.lower():
                                            if url not in audio_stream_urls:
                                                audio_stream_urls.append(url)
                                                logger.debug(f"  🎵 오디오 전용 스트림 발견: {url[:100]}...")
                                        else:
                                            # 일반 비디오 스트림 (비디오+오디오 포함)
                                            if url not in video_stream_urls:
                                                video_stream_urls.append(url)
                                                logger.debug(f"  📹 비디오 스트림 발견: {url[:100]}...")
                            
                            # 발견된 스트림 개수만 로그로 출력
                            if audio_stream_urls or video_stream_urls:
                                logger.info(f"  📊 발견된 스트림: 오디오 전용 {len(audio_stream_urls)}개, 비디오 {len(video_stream_urls)}개")
                            
                            # 오디오 전용 스트림 우선 사용 (Whisper 처리에 효율적)
                            if audio_stream_urls:
                                video_src = audio_stream_urls[-1]  # 가장 최근 오디오 스트림
                                logger.info(f"  ✅ 오디오 전용 스트림 선택: {video_src[:80]}...")
                            elif video_stream_urls:
                                video_src = video_stream_urls[-1]  # 일반 비디오 스트림
                                logger.info(f"  ✅ 비디오 스트림 선택: {video_src[:80]}...")
                        except Exception as e:
                            logger.debug(f"  ℹ️ Selenium Wire 확인 실패: {e}")
                    
                    # 방법 2: Performance 로그 확인 (Selenium Wire 실패 시)
                    if not video_src:
                        logger.info(f"  🔍 Performance 로그에서 비디오 URL 검색 중...")
                        try:
                            logs = driver.get_log('performance')
                            video_urls = []
                            for log in logs:
                                try:
                                    log_data = json.loads(log.get('message', '{}'))
                                    message = log_data.get('message', {})
                                    method = message.get('method', '')
                                    
                                    if method in ['Network.responseReceived', 'Network.requestWillBeSent']:
                                        params = message.get('params', {})
                                        request = params.get('request', {})
                                        response = params.get('response', {})
                                        url = request.get('url') or response.get('url', '')
                                        mime_type = response.get('mimeType', '').lower()
                                        
                                        if url and (
                                            '.mp4' in url or 
                                            '.webm' in url or 
                                            '.m3u8' in url or
                                            'video' in mime_type or 
                                            ('fbcdn' in url and ('video' in url.lower() or 'v/t' in url)) or 
                                            ('scontent' in url and ('video' in url.lower() or 'v/t' in url)) or
                                            'playable_url' in url.lower()
                                        ):
                                            if not url.startswith('blob:') and url not in video_urls and 'poster' not in url.lower() and '.jpg' not in url.lower():
                                                video_urls.append(url)
                                except:
                                    continue
                            
                            if video_urls:
                                video_src = video_urls[-1]
                                logger.info(f"  ✅ Performance 로그에서 비디오 URL 발견: {video_src[:80]}...")
                        except Exception as e:
                            logger.debug(f"  ℹ️ Performance 로그 확인 실패: {e}")
                
                # 실제 URL을 찾은 경우 바로 다운로드 및 분석
                if video_src and not video_src.startswith('blob:'):
                    try:
                        # URL에서 bytestart와 byteend 파라미터 제거 (전체 파일 다운로드를 위해)
                        from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
                        parsed_url = urlparse(video_src)
                        query_params = parse_qs(parsed_url.query)
                        
                        # bytestart와 byteend 제거
                        if 'bytestart' in query_params:
                            del query_params['bytestart']
                        if 'byteend' in query_params:
                            del query_params['byteend']
                        
                        # URL 재구성
                        clean_url = urlunparse((
                            parsed_url.scheme,
                            parsed_url.netloc,
                            parsed_url.path,
                            parsed_url.params,
                            urlencode(query_params, doseq=True),
                            parsed_url.fragment
                        ))
                        
                        logger.info(f"  📥 발견된 URL로 비디오 다운로드 중: {clean_url[:100]}...")
                        import requests
                        
                        # Selenium 쿠키 가져오기
                        cookies = driver.get_cookies()
                        cookie_dict = {cookie['name']: cookie['value'] for cookie in cookies}
                        
                        # User-Agent 설정
                        headers = {
                            'User-Agent': driver.execute_script("return navigator.userAgent;"),
                            'Referer': url,
                            'Accept': 'video/webm,video/ogg,video/*;q=0.9,application/ogg;q=0.7,audio/*;q=0.6,*/*;q=0.5',
                            'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
                            'Accept-Encoding': 'identity',  # 압축 해제 방지
                            'Range': 'bytes=0-',  # 전체 파일 요청
                            'Connection': 'keep-alive',
                        }
                        
                        # clean_url 사용
                        video_src = clean_url
                        
                        # 비디오 다운로드
                        response = requests.get(video_src, cookies=cookie_dict, headers=headers, timeout=120, stream=True)
                        
                        # HTTP 상태 코드 확인
                        if response.status_code not in [200, 206]:
                            logger.warning(f"  ⚠️ 다운로드 실패: HTTP {response.status_code}")
                            raise Exception(f"HTTP {response.status_code}")
                        
                        # Content-Length 확인
                        content_length = response.headers.get('Content-Length')
                        if content_length:
                            logger.info(f"  📊 예상 파일 크기: {int(content_length) / (1024 * 1024):.2f} MB")
                        
                        # 스트림으로 다운로드 (메모리 효율적)
                        video_bytes = b''
                        total_size = 0
                        for chunk in response.iter_content(chunk_size=8192):
                            if chunk:
                                video_bytes += chunk
                                total_size += len(chunk)
                                # 10MB마다 진행 상황 로그
                                if total_size % (10 * 1024 * 1024) == 0:
                                    logger.info(f"  📥 다운로드 중... {total_size / (1024 * 1024):.1f} MB")
                        
                        logger.info(f"  ✅ 비디오 다운로드 완료: {len(video_bytes)} bytes ({len(video_bytes) / (1024 * 1024):.2f} MB)")
                        
                        # 파일 크기 검증
                        if len(video_bytes) < 1024:  # 1KB 미만이면 오류
                            logger.warning(f"  ⚠️ 다운로드한 파일이 너무 작습니다: {len(video_bytes)} bytes")
                            raise Exception("다운로드한 파일이 너무 작습니다")
                        
                        # Content-Length와 실제 크기 비교
                        if content_length and int(content_length) > 0:
                            expected_size = int(content_length)
                            if abs(len(video_bytes) - expected_size) > 1024:  # 1KB 이상 차이나면 경고
                                logger.warning(f"  ⚠️ 파일 크기 불일치: 예상 {expected_size} bytes, 실제 {len(video_bytes)} bytes")
                        
                        # 파일 헤더 검증 (MP4 파일인지 확인)
                        if len(video_bytes) >= 8:
                            file_header = video_bytes[:8]
                            # MP4 파일 시그니처 확인 (ftyp box)
                            if file_header[4:8] == b'ftyp':
                                logger.info(f"  ✅ MP4 파일 형식 확인됨")
                            elif file_header[:4] == b'\x00\x00\x00\x20' or file_header[:4] == b'\x00\x00\x00\x18':
                                # DASH 스트림일 수 있음
                                logger.info(f"  ℹ️ DASH 스트림 형식일 수 있음")
                            else:
                                logger.warning(f"  ⚠️ 알 수 없는 파일 형식: {file_header.hex()[:16]}")
                        
                        # ffmpeg/Whisper 처리
                        logger.info(f"  🔄 ffmpeg/Whisper 처리 중...")
                        audio_text = process_video_with_ffmpeg_whisper(video_bytes)
                        
                        if audio_text:
                            logger.info(f"  ✅ 음성 텍스트 추출 완료: {len(audio_text)}자")
                            return audio_text
                        else:
                            logger.info(f"  ℹ️ 음성 텍스트 추출 실패 또는 무음")
                            return None
                            
                    except Exception as e:
                        logger.warning(f"  ⚠️ URL 다운로드 중 오류: {e}")
                        import traceback
                        logger.warning(traceback.format_exc())
                        # 실패 시 blob URL 처리로 폴백
                
                # blob URL이거나 src가 없는 경우
                if not video_src or video_src.startswith('blob:'):
                    if video_src:
                        logger.info(f"  📹 blob URL 발견: {video_src[:50]}...")
                    else:
                        logger.info(f"  📹 src 속성이 없음. 비디오 요소에서 직접 데이터 추출 시도...")
                    
                    try:
                        # 비디오 메타데이터 로드
                        driver.execute_script("arguments[0].load();", video)
                        
                        # 비디오가 로드될 때까지 대기
                        driver.execute_script("""
                            var video = arguments[0];
                            return new Promise(function(resolve) {
                                if (video.readyState >= 1) {
                                    resolve(video.duration);
                                } else {
                                    video.addEventListener('loadedmetadata', function() {
                                        resolve(video.duration);
                                    }, { once: true });
                                    video.addEventListener('error', function() {
                                        resolve(0);
                                    }, { once: true });
                                    setTimeout(function() {
                                        resolve(0);
                                    }, 5000);
                                }
                            });
                        """, video)
                        
                        time.sleep(2)
                        
                        # 비디오 duration 확인
                        duration = driver.execute_script("""
                            var v = arguments[0];
                            if (v.readyState >= 1 && v.duration && v.duration > 0) {
                                return v.duration;
                            }
                            return 0;
                        """, video)
                        
                        ready_state = driver.execute_script("return arguments[0].readyState;", video)
                        logger.info(f"  📹 비디오 상태: readyState={ready_state}, duration={duration}초")
                        
                        if ready_state < 2:
                            logger.warning(f"  ⚠️ 비디오가 아직 로드되지 않았습니다.")
                            continue
                        
                        # blob URL을 base64로 변환
                        base64_data = extract_video_blob_to_base64(driver, video)
                        
                        if not base64_data:
                            logger.warning(f"  ⚠️ base64 변환 실패")
                            continue
                        
                        # base64가 URL인 경우 다운로드
                        if base64_data.startswith('http'):
                            logger.info(f"  📥 비디오 다운로드 중: {base64_data[:80]}...")
                            import requests
                            response = requests.get(base64_data, timeout=60)
                            response.raise_for_status()
                            video_bytes = response.content
                        else:
                            # base64 디코딩
                            logger.info(f"  🔄 base64 디코딩 중...")
                            video_bytes = base64.b64decode(base64_data)
                        
                        logger.info(f"  ✅ 비디오 데이터 추출 완료: {len(video_bytes)} bytes")
                        
                        # ffmpeg/Whisper 처리
                        logger.info(f"  🔄 ffmpeg/Whisper 처리 중...")
                        audio_text = process_video_with_ffmpeg_whisper(video_bytes)
                        
                        if audio_text:
                            logger.info(f"  ✅ 음성 텍스트 추출 완료: {len(audio_text)}자")
                            return audio_text
                        else:
                            logger.info(f"  ℹ️ 음성 텍스트 추출 실패 또는 무음")
                        
                    except Exception as e:
                        logger.warning(f"  ⚠️ 비디오 처리 중 오류: {e}")
                        import traceback
                        logger.warning(traceback.format_exc())
                    
                    break  # 첫 번째 비디오만 처리
                
        except Exception as e:
            logger.warning(f"  ⚠️ 비디오 찾기 중 오류: {e}")
            import traceback
            logger.warning(traceback.format_exc())
        
    except Exception as e:
        logger.error(f"  ❌ Selenium 처리 실패: {e}")
        import traceback
        logger.error(traceback.format_exc())
    
    return None


def load_media_data() -> List[dict]:
    """facebook_media.json 파일을 로드"""
    if not DATA_FILE.exists():
        logger.error(f"❌ {DATA_FILE} 파일을 찾을 수 없습니다.")
        return []
    
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
            if isinstance(data, list):
                return data
            else:
                logger.error("❌ JSON 파일 형식이 올바르지 않습니다. 리스트 형식이어야 합니다.")
                return []
        except json.JSONDecodeError as e:
            logger.error(f"❌ JSON 파일을 읽는 중 오류 발생: {e}")
            return []


def save_media_data(data: List[dict]) -> None:
    """facebook_media.json 파일에 저장"""
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info(f"✅ {DATA_FILE} 파일에 저장 완료")


def filter_video_and_reel_posts(media_list: List[dict]) -> List[dict]:
    """media_urls에 /reel/이나 /video/가 포함된 게시물만 필터링"""
    filtered = []
    for item in media_list:
        media_urls = item.get("media_urls", [])
        if not media_urls:
            continue
        
        # media_urls 중 하나라도 /reel/이나 /video/가 포함되어 있으면 포함
        for url in media_urls:
            if "/reel/" in url or "/video/" in url:
                filtered.append(item)
                break
    
    return filtered


def main():
    """메인 함수"""
    logger.info("=" * 80)
    logger.info("📹 Facebook 비디오 오디오 추출 시작")
    logger.info("=" * 80)
    
    # 데이터 로드
    logger.info("\n📂 데이터 파일 로드 중...")
    media_list = load_media_data()
    if not media_list:
        logger.error("❌ 로드할 데이터가 없습니다.")
        return
    
    logger.info(f"✅ 총 {len(media_list)}개의 게시물 로드 완료")
    
    # /reel/이나 /video/가 포함된 게시물 필터링
    logger.info("\n🔍 /reel/이나 /video/가 포함된 게시물 필터링 중...")
    filtered_media = filter_video_and_reel_posts(media_list)
    logger.info(f"📊 필터링 결과: {len(filtered_media)}개")
    
    if not filtered_media:
        logger.warning("❌ 처리할 게시물이 없습니다.")
        return
    
    # audio_caption이 이미 있는 항목 제외
    logger.info("\n🔍 audio_caption이 이미 있는 항목 필터링 중...")
    media_without_audio = []
    media_with_audio = []
    for item in filtered_media:
        audio_caption = item.get("audio_caption", "")
        # 리스트인 경우 모든 항목이 비어있지 않은지 확인
        if isinstance(audio_caption, list):
            # 리스트의 모든 항목이 비어있지 않은지 확인
            has_content = any(str(cap).strip() for cap in audio_caption if cap)
            if has_content:
                media_with_audio.append(item)
            else:
                media_without_audio.append(item)
        else:
            # 문자열인 경우
            audio_caption = str(audio_caption).strip() if audio_caption else ""
            if not audio_caption:
                media_without_audio.append(item)
            else:
                media_with_audio.append(item)
    
    logger.info(f"📊 필터링 결과:")
    logger.info(f"   - audio_caption 있음 (스킵): {len(media_with_audio)}개")
    logger.info(f"   - audio_caption 없음 (처리): {len(media_without_audio)}개")
    
    # 처리할 미디어로 교체
    filtered_media = media_without_audio
    
    # Selenium WebDriver 설정
    logger.info("\n🌐 브라우저 설정 중...")
    driver = setup_driver(use_selenium_wire=True)  # Selenium Wire로 네트워크 요청 모니터링
    
    try:
        # Facebook 로그인
        logger.info("\n🔐 Facebook 로그인 중...")
        login_facebook(driver)
        time.sleep(3)
        
        # 각 게시물 처리
        logger.info(f"\n🎬 {len(filtered_media)}개의 게시물 처리 시작...")
        processed_count = 0
        success_count = 0
        
        for idx, media_item in enumerate(filtered_media, 1):
            user_name = media_item.get("user_name", "N/A")
            media_urls = media_item.get("media_urls", [])
            
            # audio_caption이 이미 있는지 다시 확인 (스킵)
            existing_audio = media_item.get("audio_caption", "")
            has_existing_audio = False
            if isinstance(existing_audio, list):
                # 리스트인 경우 모든 항목이 비어있지 않은지 확인
                has_existing_audio = any(str(cap).strip() for cap in existing_audio if cap)
            else:
                # 문자열인 경우
                existing_audio_str = str(existing_audio).strip() if existing_audio else ""
                has_existing_audio = bool(existing_audio_str)
            
            if has_existing_audio:
                logger.info(f"\n[{idx}/{len(filtered_media)}] ⏭️  스킵 (이미 오디오 추출됨): {user_name}")
                if isinstance(existing_audio, list):
                    logger.info(f"   📝 기존 audio_caption: {len(existing_audio)}개 항목 (리스트)")
                else:
                    logger.info(f"   📝 기존 audio_caption: {str(existing_audio)[:50]}...")
                continue
            
            if not media_urls:
                logger.info(f"\n[{idx}/{len(filtered_media)}] ⚠️  스킵 (media_urls 없음): {user_name}")
                continue
            
            # /reel/이나 /video/가 포함된 모든 URL 찾기
            video_urls = []
            for url in media_urls:
                if "/reel/" in url or "/video/" in url:
                    video_urls.append(url)
            
            if not video_urls:
                logger.info(f"\n[{idx}/{len(filtered_media)}] ⚠️  스킵 (비디오 URL 없음): {user_name}")
                continue
            
            logger.info(f"\n[{idx}/{len(filtered_media)}] 🎥 처리 중: {user_name}")
            logger.info(f"   📹 발견된 비디오 URL 개수: {len(video_urls)}개")
            
            # 원본 media_list에서 해당 항목 찾기 (user_name, datetime, content로 매칭)
            original_item = None
            for item in media_list:
                if (item.get("user_name") == user_name and 
                    item.get("datetime") == media_item.get("datetime") and
                    item.get("content") == media_item.get("content")):
                    original_item = item
                    break
            
            # 원본 항목을 찾지 못하면 media_item의 인덱스로 찾기
            if not original_item:
                # filtered_media의 인덱스를 media_list에서 찾기
                try:
                    original_item = media_list[media_list.index(media_item)]
                except (ValueError, IndexError):
                    # 매칭 실패 시 media_item을 직접 사용 (참조일 수 있음)
                    original_item = media_item
            
            # 기존 audio_caption 확인 (리스트 또는 문자열)
            existing_audio_list = []
            existing_audio = original_item.get("audio_caption", "")
            if isinstance(existing_audio, list):
                existing_audio_list = existing_audio
            elif existing_audio and existing_audio.strip():
                existing_audio_list = [existing_audio.strip()]
            
            # 각 비디오 URL에 대해 오디오 추출
            audio_captions = existing_audio_list.copy()  # 기존 결과 유지
            processed_count += 1
            video_success_count = 0
            
            for video_idx, video_url in enumerate(video_urls, 1):
                logger.info(f"   🎬 비디오 {video_idx}/{len(video_urls)} 처리 중: {video_url[:80]}...")
                audio_caption = None
                
                try:
                    # 비디오에서 오디오 추출
                    audio_caption = extract_audio_from_video_url(driver, video_url)
                    
                    if audio_caption:
                        audio_captions.append(audio_caption)
                        video_success_count += 1
                        logger.info(f"      ✅ 오디오 추출 성공: {len(audio_caption)}자")
                    else:
                        logger.info(f"      ⚠️  오디오 추출 실패 또는 무음")
                        # 실패한 경우 빈 문자열 추가하지 않음 (누적만 함)
                    
                except Exception as e:
                    logger.error(f"      ❌ 처리 중 오류: {e}")
                    import traceback
                    logger.error(traceback.format_exc())
                    # 오류 시에도 계속 진행 (다음 비디오 처리)
            
            # 결과 저장 (원본 media_list에 반영)
            if audio_captions:
                # 리스트에 결과가 있으면 리스트로 저장, 단일 결과면 문자열로 저장 (호환성)
                if len(audio_captions) == 1 and not existing_audio_list:
                    original_item["audio_caption"] = audio_captions[0]
                else:
                    original_item["audio_caption"] = audio_captions
                success_count += 1
                logger.info(f"   ✅ 총 {video_success_count}/{len(video_urls)}개 비디오 오디오 추출 성공")
                logger.info(f"   📝 저장된 audio_caption: {len(audio_captions)}개 (리스트: {isinstance(original_item['audio_caption'], list)})")
            else:
                logger.info(f"   ⚠️  모든 비디오 오디오 추출 실패 또는 무음")
                original_item["audio_caption"] = ""  # 빈 문자열로 표시
            
            # 중간 저장 (10개마다)
            if processed_count % 10 == 0:
                logger.info(f"\n💾 중간 저장 중... ({processed_count}개 처리됨)")
                save_media_data(media_list)
        
        # 최종 저장
        logger.info(f"\n💾 최종 저장 중...")
        save_media_data(media_list)
        
        logger.info(f"\n✅ 처리 완료!")
        logger.info(f"   - 총 처리: {processed_count}개")
        logger.info(f"   - 성공: {success_count}개")
        logger.info(f"   - 실패: {processed_count - success_count}개")
        
    finally:
        logger.info("\n🔚 브라우저 종료 중...")
        driver.quit()
        logger.info("✅ 완료")


if __name__ == "__main__":
    main()

