import json
import os
import time
import base64
import io
import pickle
import requests
import shutil
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from dotenv import load_dotenv
import easyocr
import numpy as np
from PIL import Image
import logging

# .env 파일에서 로그인 정보 불러오기
load_dotenv('/home/pmi/venvs/source_code/.env')
USERNAME = os.getenv("IG_USERNAME")
PASSWORD = os.getenv("IG_PASSWORD")

# 파일 경로 (현재 파일 위치 기준)
BASE_DIR = Path(__file__).parent
LOG_PATH = BASE_DIR / "instagram.log"

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

# 로깅 초기화
setup_logging(str(LOG_PATH))
logging.info("=" * 80)
logging.info("프로그램 시작 - instagram_extract_single_media_ocr.py")
logging.info("=" * 80)

# JSON 파일 불러오기
MEDIA_JSON = BASE_DIR / "instagram_media.json"
print("📂 instagram_media.json 파일 로딩 중...")
with open(MEDIA_JSON, "r", encoding="utf-8") as f:
    media_data = json.load(f)

# IMAGE와 VIDEO 타입만 필터링 (원본 인덱스와 함께 저장)
single_media_posts = []
for idx, item in enumerate(media_data):
    media_type = item.get("media_type", "").upper()
    if media_type in ["IMAGE", "VIDEO"]:
        single_media_posts.append({"index": idx, "data": item})

image_count = sum(1 for item in single_media_posts if item["data"].get("media_type", "").upper() == "IMAGE")
video_count = sum(1 for item in single_media_posts if item["data"].get("media_type", "").upper() == "VIDEO")

print(f"✅ IMAGE 타입 게시글 {image_count}개 발견")
print(f"✅ VIDEO 타입 게시글 {video_count}개 발견")
print(f"✅ 총 {len(single_media_posts)}개 게시글 처리 예정\n")

# EasyOCR 리더 초기화 (전역 변수로 한 번만 초기화)
_easyocr_reader = None
def get_easyocr_reader():
    global _easyocr_reader
    if _easyocr_reader is None:
        try:
            _easyocr_reader = easyocr.Reader(["ko", "en"], gpu=True)
        except Exception:
            _easyocr_reader = easyocr.Reader(["ko", "en"], gpu=False)
    return _easyocr_reader

# 이미지 URL에서 OCR 수행 함수
def ocr_image_url(url: str) -> list:
    """이미지 URL에서 OCR을 수행하여 텍스트 리스트 반환"""
    try:
        # 이미지 다운로드
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        image_data = response.content
        
        # 이미지 열기
        image = Image.open(io.BytesIO(image_data))
        if image.mode != "RGB":
            image = image.convert("RGB")
        
        # EasyOCR로 텍스트 추출
        array = np.array(image)
        reader = get_easyocr_reader()
        results = reader.readtext(array)
        
        # 신뢰도 0.5 이상인 텍스트만 추출하여 리스트로 반환
        texts = [text.strip() for _, text, conf in results if text and conf >= 0.5]
        return texts
        
    except Exception as e:
        print(f"  ⚠️ 이미지 OCR 실패 ({url[:50]}...): {e}")
        return []

# 비디오 프레임에서 OCR 수행 함수
def ocr_video_frame_from_blob(driver, video_element, frame_time):
    """비디오 요소에서 특정 시점의 프레임을 추출하여 OCR 수행 (리스트 반환)"""
    try:
        # 비디오 상태 확인
        ready_state = driver.execute_script("return arguments[0].readyState;", video_element)
        video_width = driver.execute_script("return arguments[0].videoWidth || 0;", video_element)
        video_height = driver.execute_script("return arguments[0].videoHeight || 0;", video_element)
        
        print(f"  📹 비디오 상태: readyState={ready_state}, size={video_width}x{video_height}")
        
        if ready_state < 2:
            print(f"  ⚠️ 비디오가 아직 로드되지 않았습니다. 로드 중...")
            # 비디오 로드 강제
            driver.execute_script("arguments[0].load();", video_element)
            time.sleep(2)
            ready_state = driver.execute_script("return arguments[0].readyState;", video_element)
            print(f"  📹 로드 후 readyState={ready_state}")
        
        if video_width == 0 or video_height == 0:
            print(f"  ⚠️ 비디오 크기를 가져올 수 없습니다.")
            return []
        
        # 비디오 시간 설정
        driver.execute_script("arguments[0].currentTime = arguments[1];", video_element, frame_time)
        time.sleep(0.5)  # seek 완료 대기
        
        # 프레임 추출 (여러 번 시도)
        base64_image = None
        for attempt in range(3):
            try:
                base64_image = driver.execute_script("""
                    var video = arguments[0];
                    var canvas = document.createElement('canvas');
                    var ctx = canvas.getContext('2d');
                    
                    // 비디오 크기 확인
                    if (video.videoWidth === 0 || video.videoHeight === 0) {
                        return null;
                    }
                    
                    // canvas 크기 설정
                    canvas.width = video.videoWidth;
                    canvas.height = video.videoHeight;
                    
                    // 비디오 프레임을 canvas에 그리기
                    try {
                        ctx.drawImage(video, 0, 0);
                    } catch (e) {
                        return null;
                    }
                    
                    // base64로 변환
                    try {
                        var dataURL = canvas.toDataURL('image/png');
                        return dataURL.split(',')[1]; // base64 부분만 반환
                    } catch (e) {
                        return null;
                    }
                """, video_element)
                
                if base64_image:
                    break
                else:
                    print(f"  ⚠️ 프레임 추출 시도 {attempt + 1}/3 실패, 재시도...")
                    time.sleep(0.5)
            except Exception as e:
                print(f"  ⚠️ 프레임 추출 시도 {attempt + 1}/3 중 오류: {e}")
                time.sleep(0.5)
        
        if not base64_image:
            print(f"  ⚠️ 프레임 추출 실패 (time={frame_time})")
            return []
        
        print(f"  ✅ 프레임 추출 성공 (time={frame_time}, base64 길이={len(base64_image)})")
        
        # base64를 이미지로 변환
        try:
            image_data = base64.b64decode(base64_image)
            image = Image.open(io.BytesIO(image_data))
            
            if image.mode != "RGB":
                image = image.convert("RGB")
            
            print(f"  📸 이미지 크기: {image.size}")
        except Exception as e:
            print(f"  ⚠️ 이미지 변환 실패: {e}")
            return []
        
        # EasyOCR로 텍스트 추출
        try:
            array = np.array(image)
            reader = get_easyocr_reader()
            results = reader.readtext(array)
            
            # 신뢰도 0.5 이상인 텍스트만 추출하여 리스트로 반환
            texts = [text.strip() for _, text, conf in results if text and conf >= 0.5]
            
            if texts:
                print(f"  ✅ OCR 완료: {len(texts)}개 텍스트 추출")
            else:
                print(f"  ℹ️ OCR 결과 없음")
            
            return texts  # 리스트 반환
        except Exception as e:
            print(f"  ⚠️ OCR 처리 실패: {e}")
            return []
        
    except Exception as e:
        print(f"  ⚠️ 프레임 OCR 실패 (time={frame_time}): {e}")
        import traceback
        print(traceback.format_exc())
        return []

# 쿠키 파일 경로
COOKIE_PATH = BASE_DIR / "instagram_cookies.pkl"

def setup_chrome_driver():
    """Chrome WebDriver 설정 (instagram_extract_imgurl.py와 동일한 로직)"""
    # Chrome 브라우저 경로 후보 리스트 (우선순위 순)
    chrome_path_candidates = []
    
    # 1. which 명령어로 PATH에서 찾기 (가장 신뢰할 수 있음)
    for cmd in ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser"]:
        chrome_cmd = shutil.which(cmd)
        if chrome_cmd:
            chrome_path_candidates.append(Path(chrome_cmd))
            print(f"✅ Chrome 경로 발견: {chrome_cmd}")
    
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
                print(f"✅ Chrome 경로 발견: {chrome_path}")
    
    if not chrome_path_candidates:
        error_msg = "실행 가능한 Chrome 브라우저를 찾을 수 없습니다."
        print(f"❌ {error_msg}")
        print("💡 해결 방법:")
        print("   1. Chrome 브라우저가 설치되어 있는지 확인하세요")
        print("   2. 다음 명령어로 Chrome을 설치할 수 있습니다:")
        print("      sudo apt-get update && sudo apt-get install -y google-chrome-stable")
        print("   3. 또는 Chromium을 설치할 수 있습니다:")
        print("      sudo apt-get install -y chromium-browser")
        raise RuntimeError(error_msg)
    
    # 각 경로를 시도하여 실제로 작동하는지 확인
    last_error = None
    for chrome_path in chrome_path_candidates:
        chrome_binary_location = chrome_path.as_posix()
        print(f"🔍 Chrome 경로 시도: {chrome_binary_location}")
        
        options = Options()
        options.binary_location = chrome_binary_location
        
        # Headless 모드 설정 (리눅스 환경 대응)
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--display=:99")  # Xvfb 디스플레이 사용
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        options.add_argument("user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        
        try:
            service = Service()
            driver = webdriver.Chrome(service=service, options=options)
            driver.set_window_size(1920, 1080)
            print(f"✅ Chrome WebDriver 초기화 성공: {chrome_binary_location}")
            return driver
        except Exception as e:
            last_error = e
            print(f"⚠️ 경로 실패: {chrome_binary_location}")
            continue
    
    # 모든 경로 실패
    error_msg = f"모든 Chrome 경로 시도 실패. 마지막 오류: {last_error}"
    print(f"❌ {error_msg}")
    raise RuntimeError(error_msg)

# 크롬 드라이버 초기화
print("🚀 Chrome WebDriver 초기화 중...")
driver = setup_chrome_driver()

# 쿠키 로드 시도
logged_in = False
if COOKIE_PATH.exists():
    try:
        print("🍪 저장된 쿠키 로드 중...")
        driver.get("https://www.instagram.com")
        time.sleep(2)
        
        with open(COOKIE_PATH, "rb") as f:
            cookies = pickle.load(f)
        
        for cookie in cookies:
            try:
                driver.add_cookie(cookie)
            except Exception as e:
                print(f"⚠️ 쿠키 추가 실패: {e}")
                continue
        
        # 쿠키 로드 후 페이지 새로고침하여 로그인 상태 확인
        driver.refresh()
        time.sleep(3)
        
        # 로그인 상태 확인 (로그인 페이지가 아니면 로그인 성공)
        current_url = driver.current_url
        if "accounts/login" not in current_url:
            print("✅ 쿠키로 로그인 성공!")
            logged_in = True
        else:
            print("⚠️ 쿠키가 만료되었습니다. 새로 로그인합니다.")
    except Exception as e:
        print(f"⚠️ 쿠키 로드 실패: {e}")
        print("⚠️ 새로 로그인합니다.")

# 쿠키가 없거나 만료된 경우 로그인
if not logged_in:
    print("🔐 인스타그램 로그인 중...")
    driver.get("https://www.instagram.com")
    time.sleep(3)

    try:
        # 로그인 과정
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.NAME, "username"))).send_keys(USERNAME)
        driver.find_element(By.NAME, "password").send_keys(PASSWORD)
        driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
        print("✅ 로그인 버튼 클릭")
        
        # 로그인 완료 대기
        time.sleep(5)
        
        # 로그인 성공 확인
        current_url = driver.current_url
        if "accounts/login" in current_url:
            print("⚠️ 로그인 실패로 보입니다. 계속 진행합니다...")
        else:
            print("✅ 로그인 성공!")
        
        # 팝업 닫기 시도
        try:
            not_now_button = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), '나중에 하기') or contains(text(), '지금은 안함') or contains(text(), 'Not Now')]"))
            )
            not_now_button.click()
            print("✅ 팝업 닫기 성공")
            time.sleep(2)
        except:
            print("ℹ️ 팝업 없음 또는 이미 닫힘")
        
        # 알림 팝업 닫기
        try:
            not_now_button = WebDriverWait(driver, 3).until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), '나중에 하기') or contains(text(), '지금은 안함') or contains(text(), 'Not Now')]"))
            )
            not_now_button.click()
            print("✅ 알림 팝업 닫기 성공")
            time.sleep(2)
        except:
            print("ℹ️ 알림 팝업 없음")
        
        # 쿠키 저장
        try:
            cookies = driver.get_cookies()
            with open(COOKIE_PATH, "wb") as f:
                pickle.dump(cookies, f)
            print("✅ 쿠키 저장 완료!")
        except Exception as e:
            print(f"⚠️ 쿠키 저장 실패: {e}")
            
    except Exception as e:
        print(f"⚠️ 로그인 중 오류 발생: {e}")
        print("⚠️ 로그인 없이 진행합니다...")

try:
    # 각 IMAGE/VIDEO 게시글에 대해 순차적으로 처리
    for idx, post_info in enumerate(single_media_posts, 1):
        post = post_info["data"]
        original_index = post_info["index"]
        url = post.get("permalink")
        media_type = post.get("media_type", "").upper()
        
        if not url:
            print(f"⚠️ 게시글 #{idx}: permalink가 없어 스킵합니다.")
            continue
        
        # 이미 media_caption이 있고 리스트에 항목이 있으면 스킵
        existing_caption = post.get("media_caption", [])
        if isinstance(existing_caption, str):
            existing_caption = [line.strip() for line in existing_caption.split("\n") if line.strip()]
        elif not isinstance(existing_caption, list):
            existing_caption = []
        
        if existing_caption:
            print(f"\n⏭️ 게시글 #{idx}: 이미 OCR 완료 (media_caption 항목 {len(existing_caption)}개) - 스킵합니다.")
            continue
        
        print("\n" + "="*60)
        print(f"📱 게시글 #{idx}/{len(single_media_posts)} 처리 중 ({media_type})")
        print(f"URL: {url}")
        print("="*60)
        
        # URL로 이동
        print(f"📱 인스타그램 게시글 로딩 중...")
        driver.get(url)
        
        # 페이지 로드 대기
        try:
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.TAG_NAME, "article"))
            )
            print("✅ 게시글 페이지 로드 완료")
        except TimeoutException:
            print("⚠️ 게시글 페이지 로드 타임아웃, 계속 진행...")
        
        # 추가 대기 및 스크롤 (미디어 로드를 위해)
        time.sleep(5)
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)
        driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(2)
        
        ocr_texts = []
        
        if media_type == "IMAGE":
            # IMAGE 타입 처리
            print("🖼️ 이미지 포스트 처리 중...")
            
            try:
                # article 내에서 이미지 찾기 (article이 없을 수 있으므로 예외 처리)
                article = None
                try:
                    article = driver.find_element(By.TAG_NAME, "article")
                    img_elements = article.find_elements(By.CSS_SELECTOR, "img")
                except NoSuchElementException:
                    print("⚠️ article 요소를 찾을 수 없습니다. 전체 페이지에서 검색합니다.")
                    img_elements = []
                
                if not img_elements:
                    # 전체 페이지에서 이미지 찾기
                    img_elements = driver.find_elements(By.CSS_SELECTOR, "img")
                
                print(f"🔍 이미지 요소 개수: {len(img_elements)}")
                
                for img in img_elements:
                    img_src = img.get_attribute("src")
                    if not img_src:
                        img_src = img.get_attribute("data-src")
                    
                    # scontent가 포함된 URL만 (인스타그램 CDN 이미지)
                    if img_src and ("scontent" in img_src or "cdninstagram" in img_src) and not img_src.startswith('blob:'):
                        print(f"✅ 이미지 URL 발견: {img_src[:80]}...")
                        
                        # 이미지 URL에서 OCR 수행
                        print(f"  📸 이미지 OCR 수행 중...")
                        image_ocr_texts = ocr_image_url(img_src)
                        if image_ocr_texts:
                            ocr_texts.extend(image_ocr_texts)
                            print(f"  ✅ 이미지 OCR 완료: {len(image_ocr_texts)}개 텍스트 추출")
                        else:
                            print(f"  ℹ️ 이미지 OCR 결과 없음")
                        break  # 첫 번째 유효한 이미지만 처리
                        
            except Exception as e:
                print(f"⚠️ 이미지 처리 중 오류: {e}")
                import traceback
                traceback.print_exc()
        
        elif media_type == "VIDEO":
            # VIDEO 타입 처리
            print("📹 비디오 포스트 처리 중...")
            
            try:
                # article 내에서 비디오 찾기 (article이 없을 수 있으므로 예외 처리)
                article = None
                try:
                    article = driver.find_element(By.TAG_NAME, "article")
                    video_elements = article.find_elements(By.CSS_SELECTOR, "video")
                except NoSuchElementException:
                    print("⚠️ article 요소를 찾을 수 없습니다. 전체 페이지에서 검색합니다.")
                    video_elements = []
                
                if not video_elements:
                    # 전체 페이지에서 비디오 찾기
                    video_elements = driver.find_elements(By.CSS_SELECTOR, "video")
                
                print(f"🔍 비디오 요소 개수: {len(video_elements)}")
                
                for video in video_elements:
                    video_src = video.get_attribute("src")
                    if not video_src:
                        video_src = video.get_attribute("data-src")
                    
                    # blob URL인 경우 프레임 추출하여 OCR 수행
                    if video_src and video_src.startswith('blob:'):
                        print(f"📹 blob URL 발견: {video_src[:50]}...")
                        print(f"📹 프레임 추출 및 OCR 수행 중...")
                        try:
                            # 비디오 메타데이터 로드
                            driver.execute_script("arguments[0].load();", video)
                            
                            # 비디오가 로드될 때까지 대기 (loadedmetadata 이벤트)
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
                            
                            time.sleep(1)  # 추가 대기
                            
                            # 비디오 duration 확인
                            duration = driver.execute_script("""
                                var v = arguments[0];
                                if (v.readyState >= 1 && v.duration && v.duration > 0) {
                                    return v.duration;
                                }
                                return 0;
                            """, video)
                            
                            print(f"📹 비디오 duration: {duration}초")
                            
                            if duration == 0 or not duration:
                                print(f"⚠️ 비디오 duration을 가져올 수 없습니다. readyState: {driver.execute_script('return arguments[0].readyState;', video)}")
                            else:
                                # 첫 프레임 (0초)
                                print(f"📸 첫 프레임 추출 중...")
                                first_frame_texts = ocr_video_frame_from_blob(driver, video, 0)
                                if first_frame_texts:
                                    ocr_texts.extend(first_frame_texts)
                                    print(f"✅ 첫 프레임 OCR 완료: {len(first_frame_texts)}개 텍스트 추출")
                                else:
                                    print(f"⚠️ 첫 프레임 OCR 실패")
                                
                                # 마지막 프레임 (duration - 0.1초, 최소 0초)
                                if duration > 0.1:
                                    last_frame_time = max(0, duration - 0.1)
                                    print(f"📸 마지막 프레임 추출 중 (time={last_frame_time:.2f}s)...")
                                    last_frame_texts = ocr_video_frame_from_blob(driver, video, last_frame_time)
                                    if last_frame_texts:
                                        ocr_texts.extend(last_frame_texts)
                                        print(f"✅ 마지막 프레임 OCR 완료: {len(last_frame_texts)}개 텍스트 추출")
                                    else:
                                        print(f"⚠️ 마지막 프레임 OCR 실패")
                                
                        except Exception as e:
                            print(f"⚠️ blob URL 프레임 OCR 실패: {e}")
                            import traceback
                            traceback.print_exc()
                        
                        break  # 첫 번째 비디오만 처리
                    
            except Exception as e:
                print(f"⚠️ 비디오 처리 중 오류: {e}")
                import traceback
                traceback.print_exc()
        
        # OCR 결과를 media_caption에 저장 (리스트 형식)
        if ocr_texts:
            # 기존 media_caption이 있으면 병합 (중복 제거)
            existing_caption = media_data[original_index].get("media_caption", [])
            
            # 기존 media_caption이 문자열이면 리스트로 변환
            if isinstance(existing_caption, str):
                existing_caption = [line.strip() for line in existing_caption.split("\n") if line.strip()]
            elif not isinstance(existing_caption, list):
                existing_caption = []
            
            # 새 OCR 결과와 기존 내용 병합 (중복 제거)
            seen_texts = set(existing_caption)
            combined_caption = list(existing_caption)
            
            for ocr_text in ocr_texts:
                if ocr_text and ocr_text not in seen_texts:
                    seen_texts.add(ocr_text)
                    combined_caption.append(ocr_text)
            
            # audio_caption과 is_video 보존
            existing_audio_caption = media_data[original_index].get("audio_caption")
            existing_is_video = media_data[original_index].get("is_video")
            
            media_data[original_index]["media_caption"] = combined_caption
            total_chars = sum(len(text) for text in combined_caption)
            print(f"✅ media_caption 업데이트 완료 (항목 {len(combined_caption)}개, 총 {total_chars}자)")
            
            # audio_caption 보존
            if existing_audio_caption:
                media_data[original_index]["audio_caption"] = existing_audio_caption
            
            # is_video 보존
            if existing_is_video:
                media_data[original_index]["is_video"] = existing_is_video
            
            # media_caption 업데이트 후 즉시 JSON 파일에 저장 (강제 중단 시에도 보존)
            try:
                with open(MEDIA_JSON, "w", encoding="utf-8") as f:
                    json.dump(media_data, f, ensure_ascii=False, indent=2)
                print(f"💾 media_caption JSON 저장 완료")
            except Exception as e:
                print(f"⚠️ media_caption JSON 저장 실패: {e}")
        else:
            print(f"⚠️ OCR 결과가 없습니다.")
            # OCR 결과가 없어도 audio_caption과 is_video는 보존
            existing_audio_caption = media_data[original_index].get("audio_caption")
            existing_is_video = media_data[original_index].get("is_video")
            
            if existing_audio_caption:
                media_data[original_index]["audio_caption"] = existing_audio_caption
            if existing_is_video:
                media_data[original_index]["is_video"] = existing_is_video

finally:
    driver.quit()
    
    # 최종 JSON 파일 저장 (안전장치)
    try:
        print("\n📝 최종 JSON 파일 저장 중...")
        with open(MEDIA_JSON, "w", encoding="utf-8") as f:
            json.dump(media_data, f, ensure_ascii=False, indent=2)
        print("✅ 최종 JSON 파일 저장 완료")
    except Exception as e:
        print(f"⚠️ 최종 JSON 파일 저장 실패: {e}")
    
    print("✅ 모든 작업 완료")

