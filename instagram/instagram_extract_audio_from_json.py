"""
instagram_media.json에서 VIDEO와 CAROUSEL_ALBUM 타입의 미디어를 찾아서
오디오를 추출하고 audio_caption으로 저장하는 스크립트
"""

import json
import time
from pathlib import Path
from typing import List, Dict, Optional
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
import requests
import logging
from instagram_extract_voice import (
    setup_driver,
    login_instagram,
    extract_video_blob_to_base64,
    process_video_with_ffmpeg_whisper
)

# 파일 경로 (현재 파일 위치 기준)
BASE_DIR = Path(__file__).parent
DATA_FILE = BASE_DIR / "instagram_media.json"
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


def load_media_data() -> List[Dict]:
    """instagram_media.json 파일을 로드"""
    if not DATA_FILE.exists():
        print(f"❌ {DATA_FILE} 파일을 찾을 수 없습니다.")
        return []
    
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
            if isinstance(data, list):
                return data
            else:
                print("❌ JSON 파일 형식이 올바르지 않습니다. 리스트 형식이어야 합니다.")
                return []
        except json.JSONDecodeError as e:
            print(f"❌ JSON 파일을 읽는 중 오류 발생: {e}")
            return []


def save_media_data(data: List[Dict]) -> None:
    """instagram_media.json 파일에 저장"""
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"✅ {DATA_FILE} 파일에 저장 완료")


def filter_video_and_carousel_media(media_list: List[Dict]) -> List[Dict]:
    """VIDEO와 CAROUSEL_ALBUM 타입의 미디어만 필터링"""
    filtered = []
    for item in media_list:
        media_type = item.get("media_type", "").upper()
        if media_type in ["VIDEO", "CAROUSEL_ALBUM"]:
            filtered.append(item)
    return filtered


def extract_audio_from_carousel(driver, post_url: str) -> tuple:
    """
    캐러셀 앨범에서 비디오 요소를 찾아서 오디오를 추출
    instagram_extract_voice.py의 extract_voice_from_instagram_post 로직 참고
    
    Returns:
        tuple: (audio_captions: List[str], is_video: str)
            - audio_captions: 각 비디오에서 추출한 오디오 텍스트 리스트
            - is_video: "Y" (비디오가 하나라도 있음) 또는 "N" (비디오가 없음)
    """
    from instagram_extract_voice import extract_voice_from_instagram_post
    
    audio_captions = []
    has_video = False
    
    try:
        print(f"   📖 캐러셀 앨범 페이지 로딩: {post_url}")
        
        # instagram_extract_voice.py의 함수를 재사용 (캐러셀 앨범임을 명시)
        results = extract_voice_from_instagram_post(driver, post_url, is_carousel=True)
        
        # 결과에서 오디오 텍스트 추출 및 is_video 확인
        for result in results:
            if isinstance(result, dict):
                # is_video 필드 확인
                is_video = result.get("is_video")
                if is_video == "Y":
                    has_video = True
                
                # voice_text 필드 확인 (extract_voice_from_instagram_post가 반환하는 형식)
                audio_text = result.get("voice_text") or result.get("audio_text") or result.get("transcription")
                if audio_text:
                    audio_captions.append(audio_text)
            elif isinstance(result, str):
                audio_captions.append(result)
        
        # is_video 결정: 비디오가 하나라도 있으면 "Y", 없으면 "N"
        is_video_value = "Y" if has_video else "N"
        print(f"   📊 총 {len(audio_captions)}개의 오디오를 추출했습니다.")
        print(f"   📊 is_video: {is_video_value}")
        
    except Exception as e:
        print(f"   ❌ 캐러셀 앨범 처리 중 오류: {e}")
        import traceback
        traceback.print_exc()
        is_video_value = "N"
    
    return audio_captions, is_video_value


def extract_audio_from_video_element(driver, video_element) -> Optional[str]:
    """
    video 요소에서 오디오를 추출
    
    Returns:
        str: 추출한 오디오 텍스트 (실패 시 None)
    """
    try:
        # blob URL을 base64로 변환
        base64_data = extract_video_blob_to_base64(driver, video_element)
        if not base64_data:
            print("   ⚠️ base64 변환 실패")
            return None
        
        # base64 디코딩
        import base64
        video_bytes = base64.b64decode(base64_data)
        
        # ffmpeg/Whisper로 처리
        audio_text = process_video_with_ffmpeg_whisper(video_bytes)
        return audio_text
        
    except Exception as e:
        print(f"   ❌ 오디오 추출 중 오류: {e}")
        import traceback
        traceback.print_exc()
        return None


def extract_audio_from_single_video(driver, post_url: str) -> Optional[str]:
    """
    단일 비디오 포스트에서 오디오 추출
    instagram_extract_voice.py의 extract_voice_from_instagram_post 로직 재사용
    
    Returns:
        str: 추출한 오디오 텍스트 (실패 시 None)
    """
    from instagram_extract_voice import extract_voice_from_instagram_post
    
    try:
        print(f"   📖 비디오 페이지 로딩: {post_url}")
        
        # instagram_extract_voice.py의 함수를 재사용 (단일 비디오임을 명시)
        results = extract_voice_from_instagram_post(driver, post_url, is_carousel=False)
        
        # 결과에서 첫 번째 오디오 텍스트 추출
        for result in results:
            if isinstance(result, dict):
                # voice_text 필드 확인 (extract_voice_from_instagram_post가 반환하는 형식)
                audio_text = result.get("voice_text") or result.get("audio_text") or result.get("transcription")
                if audio_text:
                    return audio_text
            elif isinstance(result, str):
                return result
        
        return None
            
    except Exception as e:
        print(f"   ❌ 비디오 처리 중 오류: {e}")
        import traceback
        traceback.print_exc()
        return None


def main():
    """메인 함수"""
    print("=" * 60)
    print("📹 Instagram 미디어 오디오 추출 시작")
    print("=" * 60)
    
    # 데이터 로드
    print("\n📂 데이터 파일 로드 중...")
    media_list = load_media_data()
    if not media_list:
        print("❌ 로드할 데이터가 없습니다.")
        return
    
    print(f"✅ 총 {len(media_list)}개의 미디어 항목 로드 완료")
    
    # VIDEO와 CAROUSEL_ALBUM 필터링
    print("\n🔍 VIDEO와 CAROUSEL_ALBUM 타입 필터링 중...")
    filtered_media = filter_video_and_carousel_media(media_list)
    
    video_count = sum(1 for item in filtered_media if item.get("media_type", "").upper() == "VIDEO")
    carousel_count = sum(1 for item in filtered_media if item.get("media_type", "").upper() == "CAROUSEL_ALBUM")
    
    print(f"📊 필터링 결과:")
    print(f"   - VIDEO: {video_count}개")
    print(f"   - CAROUSEL_ALBUM: {carousel_count}개")
    print(f"   - 총계: {len(filtered_media)}개")
    
    if not filtered_media:
        print("❌ 처리할 미디어가 없습니다.")
        return
    
    # audio_caption이 이미 있는 항목과 is_video="N"인 캐러셀은 제외
    print("\n🔍 audio_caption이 이미 있는 항목 및 비디오가 없는 캐러셀 필터링 중...")
    media_without_audio = []
    media_with_audio = []
    media_without_video = []
    for item in filtered_media:
        audio_caption = item.get("audio_caption")
        media_type = item.get("media_type", "").upper()
        is_video = item.get("is_video")
        
        # 캐러셀 앨범이고 is_video="N"이면 스킵
        if media_type == "CAROUSEL_ALBUM" and is_video == "N":
            media_without_video.append(item)
            continue
        
        # audio_caption이 없거나 빈 문자열이면 처리 대상
        if not audio_caption or (isinstance(audio_caption, str) and not audio_caption.strip()):
            media_without_audio.append(item)
        else:
            media_with_audio.append(item)
    
    print(f"📊 필터링 결과:")
    print(f"   - audio_caption 있음 (스킵): {len(media_with_audio)}개")
    print(f"   - is_video='N' (스킵): {len(media_without_video)}개")
    print(f"   - audio_caption 없음 (처리): {len(media_without_audio)}개")
    
    # 처리할 미디어로 교체
    filtered_media = media_without_audio
    
    # Selenium WebDriver 설정
    print("\n🌐 브라우저 설정 중...")
    driver = setup_driver()
    
    try:
        # Instagram 로그인
        print("\n🔐 Instagram 로그인 중...")
        login_instagram(driver)
        time.sleep(3)
        
        # 각 미디어 처리
        print(f"\n🎬 {len(filtered_media)}개의 미디어 처리 시작...")
        processed_count = 0
        success_count = 0
        
        for idx, media_item in enumerate(filtered_media, 1):
            media_id = media_item.get("id", "unknown")
            media_type = media_item.get("media_type", "").upper()
            permalink = media_item.get("permalink", "")
            
            # audio_caption이 이미 있는지 다시 확인 (이중 체크)
            existing_audio = media_item.get("audio_caption")
            if existing_audio and (isinstance(existing_audio, str) and existing_audio.strip()):
                print(f"\n[{idx}/{len(filtered_media)}] ⏭️  스킵 (이미 오디오 추출됨): {media_id}")
                continue
            
            if not permalink:
                print(f"\n[{idx}/{len(filtered_media)}] ⚠️  스킵 (permalink 없음): {media_id}")
                continue
            
            print(f"\n[{idx}/{len(filtered_media)}] 🎥 처리 중: {media_id} ({media_type})")
            print(f"   🔗 URL: {permalink}")
            
            processed_count += 1
            audio_caption = None
            
            try:
                if media_type == "VIDEO":
                    # 단일 비디오 처리
                    audio_caption = extract_audio_from_single_video(driver, permalink)
                    
                elif media_type == "CAROUSEL_ALBUM":
                    # 캐러셀 앨범 처리
                    audio_captions, is_video = extract_audio_from_carousel(driver, permalink)
                    
                    # is_video 필드 저장
                    media_item["is_video"] = is_video
                    
                    # is_video="N"이면 스킵 (비디오가 없는 캐러셀)
                    if is_video == "N":
                        print(f"   ⏭️  스킵 (비디오가 없는 캐러셀): {media_id}")
                        media_item["audio_caption"] = ""  # 빈 문자열로 표시
                        continue
                    
                    if audio_captions:
                        # 여러 비디오의 오디오를 합침
                        audio_caption = "\n".join(audio_captions)
                
                # 결과 저장
                if audio_caption:
                    media_item["audio_caption"] = audio_caption
                    success_count += 1
                    print(f"   ✅ 오디오 추출 성공: {len(audio_caption)}자")
                else:
                    print(f"   ⚠️  오디오 추출 실패 또는 무음")
                    media_item["audio_caption"] = ""  # 빈 문자열로 표시
                
            except Exception as e:
                print(f"   ❌ 처리 중 오류: {e}")
                media_item["audio_caption"] = ""  # 오류 시 빈 문자열
                import traceback
                traceback.print_exc()
            
            # 중간 저장 (10개마다)
            if processed_count % 10 == 0:
                print(f"\n💾 중간 저장 중... ({processed_count}개 처리됨)")
                save_media_data(media_list)
        
        # 최종 저장
        print(f"\n💾 최종 저장 중...")
        save_media_data(media_list)
        
        print(f"\n✅ 처리 완료!")
        print(f"   - 총 처리: {processed_count}개")
        print(f"   - 성공: {success_count}개")
        print(f"   - 실패: {processed_count - success_count}개")
        
    finally:
        print("\n🔚 브라우저 종료 중...")
        driver.quit()
        print("✅ 완료")


if __name__ == "__main__":
    # 로깅 초기화
    setup_logging(str(LOG_PATH))
    logging.info("=" * 80)
    logging.info("프로그램 시작 - instagram_extract_audio_from_json.py")
    logging.info("=" * 80)
    
    main()

