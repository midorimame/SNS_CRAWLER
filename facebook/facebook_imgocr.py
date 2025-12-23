"""
Facebook 게시물의 이미지와 영상에 대한 OCR 분석
Instagram 처리 방식을 참고하여 Selenium 기반으로 작성
"""

from __future__ import annotations

import base64
import io
import json
import logging
import os
import pickle
import re
import tempfile
import time
from pathlib import Path
from typing import List, Optional

import cv2  # type: ignore
import easyocr  # type: ignore
import numpy as np  # type: ignore
import requests
from dotenv import load_dotenv
from PIL import Image
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import NoSuchElementException, TimeoutException

# .env 파일에서 로그인 정보 불러오기
load_dotenv('/home/pmi/venvs/source_code/.env')
EMAIL = os.getenv("FB_EMAIL")
PASSWORD = os.getenv("FB_PASSWORD")

# 파일 경로 (현재 파일 위치 기준)
BASE_DIR = Path(__file__).parent
COOKIE_PATH = BASE_DIR / "facebook_cookies.pkl"
LOG_PATH = BASE_DIR / "facebook.log"  # facebook.log에 누적 저장

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

# 설정
REQUEST_TIMEOUT = 30
EASYOCR_LANGS = ["ko", "en"]
MIN_CAPTION_LENGTH = 20

# EasyOCR Reader (전역 변수로 한 번만 초기화)
_easyocr_reader: Optional[easyocr.Reader] = None


def get_easyocr_reader() -> easyocr.Reader:
    """EasyOCR Reader 싱글톤 패턴으로 초기화"""
    global _easyocr_reader  # pylint: disable=global-statement
    if _easyocr_reader is None:
        try:
            _easyocr_reader = easyocr.Reader(EASYOCR_LANGS, gpu=True)
            logger.info("✅ EasyOCR GPU 모드로 초기화 완료")
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("⚠️ EasyOCR GPU 초기화 실패, CPU로 재시도합니다: %s", exc)
            _easyocr_reader = easyocr.Reader(EASYOCR_LANGS, gpu=False)
            logger.info("✅ EasyOCR CPU 모드로 초기화 완료")
    return _easyocr_reader


def setup_driver() -> webdriver.Chrome:
    """Chrome WebDriver 설정 (Headless 모드) - 리눅스 환경용 Chrome binary 자동 탐지"""
    import shutil
    from pathlib import Path
    
    # Chrome/Chromium binary 경로 찾기
    chrome_path_candidates = []
    
    # 1. PATH에서 찾기
    for cmd in ['chromium-browser', 'google-chrome', 'google-chrome-stable', 'chromium', 'chrome']:
        chrome_path = shutil.which(cmd)
        if chrome_path:
            chrome_path_candidates.append(Path(chrome_path))
    
    # 2. 일반적인 설치 경로 확인
    common_paths = [
        Path("/usr/bin/chromium-browser"),
        Path("/usr/bin/google-chrome"),
        Path("/usr/bin/google-chrome-stable"),
        Path("/opt/google/chrome/chrome"),
        Path("/opt/google/chrome/google-chrome"),
    ]
    
    for path in common_paths:
        if path.exists():
            # 심볼릭 링크나 래퍼 스크립트인 경우 실제 파일 찾기
            resolved = path.resolve()
            if resolved.exists() and resolved.is_file():
                chrome_path_candidates.append(resolved)
    
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
        
        try:
            service = Service()
            driver = webdriver.Chrome(service=service, options=options)
            logger.info(f"✅ Chrome WebDriver 초기화 성공: {chrome_binary_location}")
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


def preprocess_image_bytes(data: bytes) -> Optional[Image.Image]:
    """이미지 전처리 (크기 조정, 블러, CLAHE, adaptive threshold)"""
    try:
        np_array = np.frombuffer(data, dtype=np.uint8)
        frame = cv2.imdecode(np_array, cv2.IMREAD_COLOR)
        if frame is None:
            return None

        # 이미지 크기 3배 확대
        frame = cv2.resize(frame, None, fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC)
        # 중간값 블러 적용
        frame = cv2.medianBlur(frame, 3)

        # 그레이스케일 변환
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        # CLAHE (Contrast Limited Adaptive Histogram Equalization) 적용
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)
        # Adaptive Threshold 적용
        thresh = cv2.adaptiveThreshold(
            enhanced,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            31,
            2,
        )
        return Image.fromarray(thresh)
    except Exception as exc:  # pylint: disable=broad-except
        logger.debug("이미지 전처리 실패: %s", exc)
        return None


def ocr_image_from_bytes(data: bytes) -> List[str]:
    """바이너리 이미지 데이터에서 OCR 수행 (리스트 반환)"""
    if not data or len(data) == 0:
        logger.debug("빈 이미지 데이터")
        return []
    
    # 전처리 시도
    preprocessed_image = preprocess_image_bytes(data)
    
    if preprocessed_image is None:
        # 전처리 실패 시 원본 이미지 사용
        try:
            image = Image.open(io.BytesIO(data))
            # 이미지가 실제로 로드되었는지 확인
            image.verify()  # 이미지 무결성 검증
            image = Image.open(io.BytesIO(data))  # verify 후에는 다시 열어야 함
        except Exception as exc:
            logger.debug("이미지 열기 실패 (데이터 크기: %d bytes): %s", len(data), exc)
            # HTML이나 다른 형식일 수 있으므로 조용히 실패 처리
            return []
    else:
        image = preprocessed_image
    
    # RGB 모드로 변환
    if image.mode != "RGB":
        image = image.convert("RGB")
    
    try:
        array = np.array(image)
        reader = get_easyocr_reader()
        results = reader.readtext(array)
        
        # 신뢰도 0.3 이상인 텍스트만 추출 (임계값 낮춤)
        texts = [text.strip() for _, text, conf in results if text and conf >= 0.3]
        
        if texts:
            logger.info(f"  ✅ OCR 성공: {len(texts)}개 텍스트 추출 (신뢰도 0.3 이상)")
            # 디버깅: 추출된 텍스트 일부 출력
            for idx, text in enumerate(texts[:3], 1):
                logger.info(f"     {idx}. {text[:50]}")
        else:
            logger.info(f"  ℹ️ OCR 결과 없음 (신뢰도 0.3 이상 텍스트 없음)")
            # 디버깅: 모든 결과 출력 (신뢰도 낮은 것도)
            all_texts = [text.strip() for _, text, conf in results if text]
            if all_texts:
                logger.info(f"  📋 전체 OCR 결과 ({len(all_texts)}개, 신뢰도 무관):")
                for idx, (_, text, conf) in enumerate(results[:5], 1):
                    logger.info(f"     {idx}. {text[:50]} (신뢰도: {conf:.2f})")
        
        return texts
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("이미지 OCR 실패: %s", exc)
        import traceback
        logger.debug(traceback.format_exc())
        return []


def ocr_image_url(url: str) -> List[str]:
    """이미지 URL에서 OCR 수행 (리스트 반환)"""
    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        
        # Content-Type 확인
        content_type = response.headers.get('Content-Type', '').lower()
        if not content_type.startswith('image/'):
            logger.warning(f"⚠️ URL이 이미지가 아닙니다 (Content-Type: {content_type}): {url[:80]}...")
            return []
        
        image_data = response.content
        
        # 데이터 크기 확인
        if len(image_data) == 0:
            logger.warning(f"⚠️ 빈 이미지 데이터: {url[:80]}...")
            return []
        
        # 이미지 데이터인지 간단히 확인 (매직 넘버 체크)
        if not (image_data.startswith(b'\xff\xd8\xff') or  # JPEG
                image_data.startswith(b'\x89PNG\r\n\x1a\n') or  # PNG
                image_data.startswith(b'GIF87a') or  # GIF87a
                image_data.startswith(b'GIF89a') or  # GIF89a
                image_data.startswith(b'RIFF') or  # WebP (RIFF...WEBP)
                image_data.startswith(b'\x00\x00\x01\x00')):  # ICO
            logger.debug(f"⚠️ 알 수 없는 이미지 형식 (첫 바이트: {image_data[:10]}): {url[:80]}...")
            # 일단 시도는 해봄 (일부 이미지 형식은 매직 넘버가 다를 수 있음)
        
        return ocr_image_from_bytes(image_data)
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("이미지 OCR 실패 (%s): %s", url[:80] if url else "N/A", exc)
        return []


def ocr_video_frame_from_blob(driver: webdriver.Chrome, video_element, frame_time: float) -> List[str]:
    """비디오 요소에서 특정 시점의 프레임을 추출하여 OCR 수행 (리스트 반환)"""
    try:
        # 비디오 상태 확인
        ready_state = driver.execute_script("return arguments[0].readyState;", video_element)
        video_width = driver.execute_script("return arguments[0].videoWidth || 0;", video_element)
        video_height = driver.execute_script("return arguments[0].videoHeight || 0;", video_element)
        
        logger.info(f"  📹 비디오 상태: readyState={ready_state}, size={video_width}x{video_height}")
        
        if ready_state < 2:
            logger.info(f"  ⚠️ 비디오가 아직 로드되지 않았습니다. 로드 중...")
            driver.execute_script("arguments[0].load();", video_element)
            time.sleep(2)
            ready_state = driver.execute_script("return arguments[0].readyState;", video_element)
            logger.info(f"  📹 로드 후 readyState={ready_state}")
        
        if video_width == 0 or video_height == 0:
            logger.warning(f"  ⚠️ 비디오 크기를 가져올 수 없습니다.")
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
                    
                    if (video.videoWidth === 0 || video.videoHeight === 0) {
                        return null;
                    }
                    
                    canvas.width = video.videoWidth;
                    canvas.height = video.videoHeight;
                    
                    try {
                        ctx.drawImage(video, 0, 0);
                    } catch (e) {
                        return null;
                    }
                    
                    try {
                        var dataURL = canvas.toDataURL('image/png');
                        return dataURL.split(',')[1];
                    } catch (e) {
                        return null;
                    }
                """, video_element)
                
                if base64_image:
                    break
                else:
                    logger.warning(f"  ⚠️ 프레임 추출 시도 {attempt + 1}/3 실패, 재시도...")
                    time.sleep(0.5)
            except Exception as e:
                logger.warning(f"  ⚠️ 프레임 추출 시도 {attempt + 1}/3 중 오류: {e}")
                time.sleep(0.5)
        
        if not base64_image:
            logger.warning(f"  ⚠️ 프레임 추출 실패 (time={frame_time})")
            return []
        
        logger.info(f"  ✅ 프레임 추출 성공 (time={frame_time}, base64 길이={len(base64_image)})")
        
        # base64를 이미지로 변환
        try:
            image_data = base64.b64decode(base64_image)
            image = Image.open(io.BytesIO(image_data))
            
            if image.mode != "RGB":
                image = image.convert("RGB")
            
            logger.info(f"  📸 이미지 크기: {image.size}")
        except Exception as e:
            logger.warning(f"  ⚠️ 이미지 변환 실패: {e}")
            return []
        
        # EasyOCR로 텍스트 추출
        try:
            array = np.array(image)
            reader = get_easyocr_reader()
            results = reader.readtext(array)
            
            # 신뢰도 0.3 이상인 텍스트만 추출 (이미지와 동일하게)
            texts = [text.strip() for _, text, conf in results if text and conf >= 0.3]
            
            if texts:
                logger.info(f"  ✅ OCR 완료: {len(texts)}개 텍스트 추출 (신뢰도 0.3 이상)")
                # 디버깅: 추출된 텍스트 일부 출력
                for idx, text in enumerate(texts[:3], 1):
                    logger.info(f"     {idx}. {text[:50]}")
            else:
                logger.info(f"  ℹ️ OCR 결과 없음 (신뢰도 0.3 이상 텍스트 없음)")
                # 디버깅: 모든 결과 출력 (신뢰도 낮은 것도)
                all_texts = [text.strip() for _, text, conf in results if text]
                if all_texts:
                    logger.info(f"  📋 전체 OCR 결과 ({len(all_texts)}개, 신뢰도 무관):")
                    for idx, (_, text, conf) in enumerate(results[:5], 1):
                        logger.info(f"     {idx}. {text[:50]} (신뢰도: {conf:.2f})")
            
            return texts
        except Exception as e:
            logger.warning(f"  ⚠️ OCR 처리 실패: {e}")
            return []
        
    except Exception as e:
        logger.warning(f"  ⚠️ 프레임 OCR 실패 (time={frame_time}): {e}")
        import traceback
        logger.warning(traceback.format_exc())
        return []


def process_media_url_with_selenium(driver: webdriver.Chrome, url: str) -> List[str]:
    """Selenium을 사용하여 Facebook 페이지에서 실제 미디어 파일을 찾아 OCR 수행"""
    ocr_texts: List[str] = []
    
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
        
        # 이미지 찾기
        try:
            img_elements = driver.find_elements(By.CSS_SELECTOR, "img")
            logger.info(f"  🔍 이미지 요소 개수: {len(img_elements)}")
            
            for img in img_elements:
                img_src = img.get_attribute("src")
                if not img_src:
                    img_src = img.get_attribute("data-src")
                
                # Facebook CDN 이미지 URL 확인 (scontent, fbcdn 등)
                if img_src and ("scontent" in img_src or "fbcdn" in img_src or "cdninstagram" in img_src) and not img_src.startswith('blob:'):
                    logger.info(f"  ✅ 이미지 URL 발견: {img_src[:80]}...")
                    
                    # 이미지 URL에서 OCR 수행
                    logger.info(f"  📸 이미지 OCR 수행 중...")
                    image_ocr_texts = ocr_image_url(img_src)
                    if image_ocr_texts:
                        ocr_texts.extend(image_ocr_texts)
                        logger.info(f"  ✅ 이미지 OCR 완료: {len(image_ocr_texts)}개 텍스트 추출")
                    else:
                        logger.info(f"  ℹ️ 이미지 OCR 결과 없음")
                    break  # 첫 번째 유효한 이미지만 처리
        except Exception as e:
            logger.warning(f"  ⚠️ 이미지 처리 중 오류: {e}")
        
        # 비디오 찾기
        try:
            video_elements = driver.find_elements(By.CSS_SELECTOR, "video")
            logger.info(f"  🔍 비디오 요소 개수: {len(video_elements)}")
            
            for video_idx, video in enumerate(video_elements, 1):
                video_src = video.get_attribute("src")
                if not video_src:
                    video_src = video.get_attribute("data-src")
                
                logger.info(f"  📹 비디오 #{video_idx} src: {video_src[:80] if video_src else 'None'}...")
                
                # blob URL이거나 src가 없는 경우 (비디오 요소 자체에서 프레임 추출 시도)
                if not video_src or video_src.startswith('blob:'):
                    if video_src:
                        logger.info(f"  📹 blob URL 발견: {video_src[:50]}...")
                    else:
                        logger.info(f"  📹 src 속성이 없음. 비디오 요소에서 직접 프레임 추출 시도...")
                    
                    logger.info(f"  📹 프레임 추출 및 OCR 수행 중...")
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
                        
                        time.sleep(2)  # 추가 대기 시간 증가
                        
                        # 비디오 duration 확인
                        duration = driver.execute_script("""
                            var v = arguments[0];
                            if (v.readyState >= 1 && v.duration && v.duration > 0) {
                                return v.duration;
                            }
                            return 0;
                        """, video)
                        
                        ready_state = driver.execute_script("return arguments[0].readyState;", video)
                        video_width = driver.execute_script("return arguments[0].videoWidth || 0;", video)
                        video_height = driver.execute_script("return arguments[0].videoHeight || 0;", video)
                        
                        logger.info(f"  📹 비디오 상태: readyState={ready_state}, duration={duration}초, size={video_width}x{video_height}")
                        
                        if duration == 0 or not duration:
                            logger.warning(f"  ⚠️ 비디오 duration을 가져올 수 없습니다. readyState={ready_state}")
                            # duration이 없어도 첫 프레임은 시도
                            if ready_state >= 2 and video_width > 0 and video_height > 0:
                                logger.info(f"  📸 첫 프레임 추출 시도 (duration 없음)...")
                                first_frame_texts = ocr_video_frame_from_blob(driver, video, 0)
                                if first_frame_texts:
                                    ocr_texts.extend(first_frame_texts)
                                    logger.info(f"  ✅ 첫 프레임 OCR 완료: {len(first_frame_texts)}개 텍스트 추출")
                        else:
                            # 첫 프레임 (0초)
                            logger.info(f"  📸 첫 프레임 추출 중...")
                            first_frame_texts = ocr_video_frame_from_blob(driver, video, 0)
                            if first_frame_texts:
                                ocr_texts.extend(first_frame_texts)
                                logger.info(f"  ✅ 첫 프레임 OCR 완료: {len(first_frame_texts)}개 텍스트 추출")
                            
                            # 마지막 프레임 (duration - 0.1초, 최소 0초)
                            if duration > 0.1:
                                last_frame_time = max(0, duration - 0.1)
                                logger.info(f"  📸 마지막 프레임 추출 중 (time={last_frame_time:.2f}s)...")
                                last_frame_texts = ocr_video_frame_from_blob(driver, video, last_frame_time)
                                if last_frame_texts:
                                    ocr_texts.extend(last_frame_texts)
                                    logger.info(f"  ✅ 마지막 프레임 OCR 완료: {len(last_frame_texts)}개 텍스트 추출")
                        
                    except Exception as e:
                        logger.warning(f"  ⚠️ 비디오 프레임 OCR 실패: {e}")
                        import traceback
                        logger.warning(traceback.format_exc())
                    
                    break  # 첫 번째 비디오만 처리
                else:
                    logger.info(f"  ℹ️ 비디오 #{video_idx}는 blob URL이 아닙니다. src={video_src[:80]}...")
                
        except Exception as e:
            logger.warning(f"  ⚠️ 비디오 처리 중 오류: {e}")
            import traceback
            logger.warning(traceback.format_exc())
        
    except Exception as e:
        logger.error(f"  ❌ Selenium 처리 실패: {e}")
        import traceback
        logger.error(traceback.format_exc())
    
    return ocr_texts


def process_media_urls(media_urls: List[str], driver: Optional[webdriver.Chrome] = None) -> List[str]:
    """미디어 URL 리스트를 처리하여 OCR 텍스트 리스트 반환"""
    if not media_urls:
        return []
    
    ocr_texts: List[str] = []
    
    for idx, url in enumerate(media_urls, 1):
        logger.info("  🔍 미디어 #%d/%d 처리 중...", idx, len(media_urls))
        
        # Facebook 페이지 URL인 경우 Selenium 사용
        if "facebook.com" in url and ("/reel/" in url or "/video/" in url or "/watch/" in url or "/photo/" in url):
            if driver:
                texts = process_media_url_with_selenium(driver, url)
                if texts:
                    ocr_texts.extend(texts)
                    logger.info("  ✅ 미디어 #%d OCR 완료 (텍스트 %d개)", idx, len(texts))
                else:
                    logger.info("  ℹ️ 미디어 #%d OCR 결과 없음", idx)
            else:
                logger.warning("  ⚠️ Selenium driver가 없어 처리할 수 없습니다.")
        else:
            # 직접 이미지/비디오 URL인 경우
            try:
                texts = ocr_image_url(url)
                if texts:
                    ocr_texts.extend(texts)
                    logger.info("  ✅ 미디어 #%d OCR 완료 (텍스트 %d개)", idx, len(texts))
                else:
                    logger.info("  ℹ️ 미디어 #%d OCR 결과 없음", idx)
            except Exception as exc:
                logger.warning("  ⚠️ 미디어 #%d 처리 실패: %s", idx, exc)
                continue
    
    return ocr_texts


def process_single_post(post: dict, driver: Optional[webdriver.Chrome] = None) -> dict:
    """단일 게시물의 media_urls를 처리하여 media_caption 업데이트"""
    media_urls: List[str] = post.get("media_urls", [])
    
    if not media_urls:
        logger.info("  ℹ️ media_urls가 없어 OCR 스킵")
        return post
    
    # 기존 media_caption 확인
    existing_caption = post.get("media_caption", "")
    if isinstance(existing_caption, list):
        existing_caption = "\n".join(existing_caption)
    existing_caption = existing_caption.strip()
    
    if existing_caption and len(existing_caption) >= MIN_CAPTION_LENGTH:
        logger.info("  ℹ️ 기존 media_caption이 이미 존재하여 OCR 스킵")
        return post
    
    # OCR 수행
    logger.info("  🔍 OCR 시작 (media_urls: %d개)", len(media_urls))
    ocr_texts = process_media_urls(media_urls, driver)
    
    # 결과 업데이트 (리스트로 저장)
    if ocr_texts:
        post["media_caption"] = ocr_texts
        logger.info("  ✅ media_caption 업데이트 완료 (%d개 텍스트)", len(ocr_texts))
    else:
        logger.info("  ℹ️ OCR 결과 없음, media_caption 업데이트 안 함")
    
    return post


def main():
    """메인 함수 - facebook_media.json 파일의 게시물들에 OCR 수행"""
    import sys
    
    # JSON 파일 경로 (현재 파일 위치 기준)
    BASE_DIR = Path(__file__).parent
    MEDIA_JSON = BASE_DIR / "facebook_media.json"
    
    if not MEDIA_JSON.exists():
        logger.error(f"❌ {MEDIA_JSON} 파일을 찾을 수 없습니다.")
        sys.exit(1)
    
    # JSON 파일 로드
    logger.info(f"📂 {MEDIA_JSON} 파일 로드 중...")
    try:
        with open(MEDIA_JSON, "r", encoding="utf-8") as f:
            posts = json.load(f)
        logger.info(f"✅ {len(posts)}개의 게시물 로드 완료")
    except Exception as e:
        logger.error(f"❌ JSON 파일 로드 실패: {e}")
        sys.exit(1)
    
    # WebDriver 초기화
    logger.info("🚀 WebDriver 초기화 중...")
    driver = None
    try:
        driver = setup_driver()
        logger.info("✅ WebDriver 초기화 완료")
        
        # Facebook 로그인
        logger.info("🔐 Facebook 로그인 중...")
        if not login_facebook(driver):
            logger.error("❌ Facebook 로그인 실패")
            sys.exit(1)
        
        # 각 게시물 처리
        logger.info(f"\n{'='*60}")
        logger.info(f"📋 총 {len(posts)}개의 게시물 처리 시작")
        logger.info(f"{'='*60}\n")
        
        processed_count = 0
        skipped_count = 0
        error_count = 0
        
        for idx, post in enumerate(posts, 1):
            logger.info(f"\n[{idx}/{len(posts)}] 게시물 처리 중...")
            logger.info(f"  📌 permalink: {post.get('permalink', 'N/A')[:80]}...")
            
            # media_caption이 이미 존재하는지 확인
            existing_caption = post.get("media_caption", "")
            if isinstance(existing_caption, list):
                existing_caption = "\n".join(existing_caption)
            existing_caption = existing_caption.strip()
            
            if existing_caption and len(existing_caption) >= MIN_CAPTION_LENGTH:
                skipped_count += 1
                logger.info(f"  ⏭️ 게시물 #{idx} 스킵 (이미 media_caption 존재, 길이: {len(existing_caption)}자)")
                continue
            
            try:
                # 게시물 처리
                updated_post = process_single_post(post, driver)
                
                # 업데이트된 게시물로 교체
                posts[idx - 1] = updated_post
                
                # JSON 파일 저장 (매번 저장하여 중단 시에도 진행 상황 보존)
                try:
                    with open(MEDIA_JSON, "w", encoding="utf-8") as f:
                        json.dump(posts, f, ensure_ascii=False, indent=2)
                    
                    # media_caption이 업데이트되었는지 확인
                    existing_caption = updated_post.get("media_caption", "")
                    if isinstance(existing_caption, list):
                        existing_caption = "\n".join(existing_caption)
                    existing_caption = existing_caption.strip()
                    
                    if existing_caption and len(existing_caption) >= MIN_CAPTION_LENGTH:
                        processed_count += 1
                        logger.info(f"  ✅ 게시물 #{idx} 처리 완료 및 저장 완료")
                    else:
                        skipped_count += 1
                        logger.info(f"  ⏭️ 게시물 #{idx} 스킵 (OCR 결과 없음 또는 기존 caption 존재)")
                        
                except Exception as e:
                    logger.error(f"  ❌ JSON 저장 실패: {e}")
                    error_count += 1
                
                # 요청 간 딜레이 (Facebook 차단 방지)
                time.sleep(2)
                
            except Exception as e:
                error_count += 1
                logger.error(f"  ❌ 게시물 #{idx} 처리 중 오류: {e}")
                import traceback
                logger.error(traceback.format_exc())
                continue
        
        # 최종 통계
        logger.info(f"\n{'='*60}")
        logger.info(f"✅ OCR 처리 완료!")
        logger.info(f"   총 게시물: {len(posts)}개")
        logger.info(f"   처리 완료: {processed_count}개")
        logger.info(f"   스킵됨: {skipped_count}개")
        logger.info(f"   오류 발생: {error_count}개")
        logger.info(f"{'='*60}")
        
    except Exception as e:
        logger.error(f"❌ 프로그램 실행 중 오류: {e}")
        import traceback
        logger.error(traceback.format_exc())
        sys.exit(1)
    finally:
        if driver:
            try:
                driver.quit()
                logger.info("🔒 브라우저 종료")
            except Exception as e:
                logger.warning(f"⚠️ 브라우저 종료 중 오류: {e}")


if __name__ == "__main__":
    main()
