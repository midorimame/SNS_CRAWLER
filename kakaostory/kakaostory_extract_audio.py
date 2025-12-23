from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path
from typing import List, Optional

import requests
import whisper

try:
    import librosa
    import numpy as np
    HAS_LIBROSA = True
except ImportError:
    HAS_LIBROSA = False


# 파일 경로 (현재 파일 위치 기준)
BASE_DIR = Path(__file__).parent
INPUT_PATH = BASE_DIR / "kakaostory_popup_posts.json"
OUTPUT_PATH = INPUT_PATH
LOG_PATH = BASE_DIR / "kakaostory.log"
REQUEST_TIMEOUT = 300  # 비디오 다운로드는 시간이 걸릴 수 있음
WHISPER_MODEL = "base"  # tiny, base, small, medium, large 중 선택
FORCE_REPROCESS = False  # 이미 audio_caption이 있어도 재처리할지 여부
TEST_LIMIT = 0  # 테스트용: 양수로 설정하면 해당 개수만 처리, 0이면 전체 처리


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


def download_video(url: str) -> bytes:
    """비디오 URL에서 비디오 파일 다운로드"""
    logging.info(f"비디오 다운로드 시작: {url}")
    response = requests.get(url, timeout=REQUEST_TIMEOUT, stream=True)
    response.raise_for_status()
    
    content = b""
    total_size = int(response.headers.get('content-length', 0))
    downloaded = 0
    
    for chunk in response.iter_content(chunk_size=8192):
        if chunk:
            content += chunk
            downloaded += len(chunk)
            if total_size > 0:
                percent = (downloaded / total_size) * 100
                if downloaded % (1024 * 1024) == 0:  # 1MB마다 로그
                    logging.debug(f"다운로드 진행률: {percent:.1f}% ({downloaded}/{total_size} bytes)")
    
    logging.info(f"비디오 다운로드 완료: {len(content)} bytes")
    return content


def find_mp4_url(media_urls: List[str]) -> Optional[str]:
    """media_url 리스트에서 .mp4가 포함된 URL 찾기"""
    for url in media_urls:
        if ".mp4" in url.lower():
            return url
    return None


def calculate_audio_db(video_path: str) -> Optional[float]:
    """비디오 파일에서 오디오의 평균 데시벨 계산
    
    Returns:
        Optional[float]: 평균 데시벨 값 (dB), 계산 실패 시 None
    """
    if not HAS_LIBROSA:
        return None
    
    try:
        # 오디오 로드 (librosa는 자동으로 오디오만 추출)
        y, sr = librosa.load(video_path, sr=None)
        
        if len(y) == 0:
            return None
        
        # RMS (Root Mean Square) 계산
        rms = librosa.feature.rms(y=y)[0]
        
        # 데시벨로 변환 (reference=1.0)
        db = librosa.amplitude_to_db(rms, ref=1.0)
        
        # 평균 데시벨 반환
        avg_db = float(np.mean(db))
        return avg_db
    except Exception as exc:
        logging.debug(f"데시벨 계산 실패: {exc}")
        return None


def transcribe_video(video_bytes: bytes, model) -> tuple[str, Optional[float]]:
    """Whisper를 사용하여 비디오에서 음성 인식 및 데시벨 계산 (임시 파일 자동 삭제)
    
    Returns:
        tuple: (transcribed_text, average_db)
        
    Raises:
        RuntimeError: 오디오 스트림이 없는 경우 또는 기타 오디오 로드 실패
    """
    # NamedTemporaryFile: delete=True로 설정하면 컨텍스트 종료 시 자동 삭제
    # 메모리에서 직접 처리할 수 없으므로 임시 파일 사용하되, 자동으로 정리됨
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=True) as tmp_file:
        tmp_file.write(video_bytes)
        tmp_file.flush()  # 디스크에 쓰기 보장
        
        logging.info("Whisper 음성 인식 시작...")
        try:
            result = model.transcribe(tmp_file.name, language="ko")
            text = result["text"].strip()
                
            # 오디오 데시벨 계산
            avg_db = calculate_audio_db(tmp_file.name)
                
            db_info = f", 평균 데시벨: {avg_db:.1f} dB" if avg_db is not None else ""
            logging.info(f"음성 인식 완료: {len(text)}자{db_info}")
                
            return text, avg_db
        except RuntimeError as e:
            error_msg = str(e)
            # 오디오 스트림이 없는 경우를 감지
            if "does not contain any stream" in error_msg or "no audio stream" in error_msg.lower():
                raise RuntimeError("비디오에 오디오 스트림이 없습니다") from e
            raise
        # 컨텍스트 종료 시 자동으로 파일 삭제됨


def process_posts(posts: List[dict], model) -> int:
    """비디오 게시물들을 처리하여 audio_caption 추출"""
    updated_count = 0
    
    # media_type="video"인 게시물 필터링
    video_posts = [
        post for post in posts
        if post.get("media_type") == "video"
    ]
    
    # audio_caption이 이미 있는 경우 스킵 (FORCE_REPROCESS가 False인 경우)
    if not FORCE_REPROCESS:
        video_posts = [
            post for post in video_posts
            if not post.get("audio_caption") or not post.get("audio_caption").strip()
        ]
    
    # 테스트 제한 적용
    if TEST_LIMIT > 0:
        video_posts = video_posts[:TEST_LIMIT]
        logging.info(f"테스트 모드: 상위 {len(video_posts)}건만 처리")
    
    total = len(video_posts)
    logging.info(f"처리할 비디오 게시물: {total}건")
    
    for idx, post in enumerate(video_posts, start=1):
        p_num = post.get("p_num")
        shortcode = post.get("shortcode")
        media_urls = post.get("media_url", [])
        
        logging.info(
            f"[{idx}/{total}] 게시물 처리 시작 (p_num={p_num}, shortcode={shortcode})"
        )
        
        # .mp4 URL 찾기
        mp4_url = find_mp4_url(media_urls)
        if not mp4_url:
            logging.warning(f"  → .mp4 URL을 찾을 수 없습니다. media_urls: {media_urls}")
            continue
        
        try:
            # 비디오 다운로드
            video_bytes = download_video(mp4_url)
            
            # Whisper로 음성 인식 및 데시벨 계산
            audio_caption, avg_db = transcribe_video(video_bytes, model)
            
            if audio_caption:
                post["audio_caption"] = audio_caption
                updated_count += 1
                db_info = f", 평균 데시벨: {avg_db:.1f} dB" if avg_db is not None else ""
                logging.info(f"  → audio_caption 저장 완료: {len(audio_caption)}자{db_info}")
            else:
                logging.warning("  → 음성 인식 결과가 비어있습니다.")
                
        except RuntimeError as exc:
            # 오디오 스트림이 없는 경우 등 특정 오류 처리
            error_msg = str(exc)
            if "오디오 스트림이 없습니다" in error_msg:
                logging.warning(f"  → 스킵: {error_msg}")
            else:
                logging.error(f"  → 처리 실패: {error_msg}")
            continue
        except Exception as exc:
            # 기타 예외는 안전하게 로깅 (UnicodeDecodeError 등 방지)
            try:
                error_msg = str(exc)
                logging.error(f"  → 처리 실패: {error_msg}")
            except Exception:
                logging.error("  → 처리 실패: 알 수 없는 오류 발생")
            continue
    
    return updated_count


def main() -> None:
    setup_logging(str(LOG_PATH))
    
    logging.info("=" * 80)
    logging.info("프로그램 시작 - 로그 파일: %s", LOG_PATH.absolute())
    logging.info("=" * 80)
    
    # JSON 파일 로드
    logging.info(f"JSON 파일 로드: {INPUT_PATH}")
    posts = json.loads(INPUT_PATH.read_text(encoding="utf-8"))
    logging.info(f"총 {len(posts)}개 게시물 로드 완료")
    
    # Whisper 모델 로드
    logging.info(f"Whisper 모델 로드 중: {WHISPER_MODEL} (처음 실행 시 다운로드됩니다)")
    model = whisper.load_model(WHISPER_MODEL)
    logging.info("Whisper 모델 로드 완료")
    
    # 게시물 처리
    try:
        updated_count = process_posts(posts, model)
        
        # 결과 저장
        if updated_count > 0:
            logging.info(f"JSON 파일 저장 중: {OUTPUT_PATH}")
            OUTPUT_PATH.write_text(
                json.dumps(posts, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            logging.info(f"✅ 저장 완료: {updated_count}개 게시물의 audio_caption이 업데이트되었습니다.")
        else:
            logging.info("변경된 게시물이 없습니다.")
            
    except KeyboardInterrupt:
        logging.warning("\n⚠️  사용자에 의해 중단되었습니다. 처리 완료된 데이터를 저장합니다...")
        OUTPUT_PATH.write_text(
            json.dumps(posts, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        logging.info("✅ 중간 저장 완료")
        raise


if __name__ == "__main__":
    main()

