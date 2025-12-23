'''
기존 전처리 로직은 테스트 실행을 위해 임시로 비활성화했습니다.
필요 시 이 주석 블록을 제거하고 원본 코드를 복원하세요.
'''

from __future__ import annotations

import copy
import io
import json
import logging
import re
import tempfile
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

import cv2  # type: ignore
import easyocr  # type: ignore
import numpy as np  # type: ignore
import requests
from PIL import Image

# 파일 경로 (현재 파일 위치 기준)
BASE_DIR = Path(__file__).parent
INPUT_PATH = BASE_DIR / "kakaostory_popup_posts.json"
OUTPUT_PATH = INPUT_PATH
LOG_PATH = BASE_DIR / "kakaostory.log"
TARGET_P_NUM = -1  # 특정 p_num을 테스트하려면 양수로 설정
TEST_LIMIT = 0  # 샘플 테스트: 20같은 양수로 설정 / 전체 데이터: 0으로 설정
FORCE_REPROCESS = False
MIN_CAPTION_LENGTH = 20
REQUEST_TIMEOUT = 30
EASYOCR_LANGS = ["ko", "en"]

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

# user_num 관련 함수는 kakaostory_extract_userinfo에서 import
try:
    from kakaostory_extract_userinfo import has_user_pattern
except ImportError:
    # import 실패 시 빈 함수로 대체
    def has_user_pattern(text: str) -> bool:
        return False


class OCRProcessingError(Exception):
    """테스트용 OCR 예외"""


def download_bytes(url: str) -> bytes:
    response = requests.get(url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.content


def preprocess_image_bytes(data: bytes) -> Optional[Image.Image]:
    try:
        np_array = np.frombuffer(data, dtype=np.uint8)
        frame = cv2.imdecode(np_array, cv2.IMREAD_COLOR)
        if frame is None:
            return None

        frame = cv2.resize(frame, None, fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC)
        frame = cv2.medianBlur(frame, 3)

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)
        thresh = cv2.adaptiveThreshold(
            enhanced,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            31,
            2,
        )
        return Image.fromarray(thresh)
    except Exception:  # pylint: disable=broad-except
        return None


_easyocr_reader: Optional[easyocr.Reader] = None


def get_easyocr_reader() -> easyocr.Reader:
    global _easyocr_reader  # pylint: disable=global-statement
    if _easyocr_reader is None:
        try:
            _easyocr_reader = easyocr.Reader(EASYOCR_LANGS, gpu=True)
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("EasyOCR GPU 초기화 실패, CPU로 재시도합니다: %s", exc)
            _easyocr_reader = easyocr.Reader(EASYOCR_LANGS, gpu=False)
    return _easyocr_reader


def ocr_image_from_bytes(data: bytes) -> str:
    image = preprocess_image_bytes(data)
    if image is None:
        image = Image.open(io.BytesIO(data))
    if image.mode != "RGB":
        image = image.convert("RGB")

    array = np.array(image)
    try:
        reader = get_easyocr_reader()
        results = reader.readtext(array)
    except Exception as exc:  # pylint: disable=broad-except
        logger.debug("EasyOCR 실패: %s", exc)
        return ""

    texts = [text.strip() for _, text, conf in results if text and conf >= 0.5]
    return "\n".join(texts)


def ocr_image_url(url: str) -> str:
    try:
        return ocr_image_from_bytes(download_bytes(url))
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("이미지 OCR 실패 (%s): %s", url, exc)
        return ""


def sample_video_frames(video_path: Path) -> Iterable[bytes]:
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise OCRProcessingError("영상 열기 실패")

    try:
        frames: List[np.ndarray] = []

        ok, first_frame = capture.read()
        if ok and first_frame is not None:
            frames.append(first_frame)

        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
        if frame_count > 1:
            capture.set(cv2.CAP_PROP_POS_FRAMES, frame_count - 1)
            ok, last_frame = capture.read()
            if ok and last_frame is not None:
                if not frames or not np.array_equal(frames[0], last_frame):
                    frames.append(last_frame)

        if not frames:
            raise OCRProcessingError("프레임 추출에 실패했습니다")

        for frame in frames:
            ok, encoded = cv2.imencode(".png", frame)
            if ok:
                yield encoded.tobytes()
    finally:
        capture.release()


def ocr_video(url: str) -> List[str]:
    try:
        data = download_bytes(url)
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("영상 다운로드 실패 (%s): %s", url, exc)
        return []

    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp_file:
        tmp_file.write(data)
        video_path = Path(tmp_file.name)

    texts: List[str] = []
    try:
        for frame_bytes in sample_video_frames(video_path):
            try:
                text = ocr_image_from_bytes(frame_bytes)
            except Exception as exc:  # pylint: disable=broad-except
                logger.debug("프레임 OCR 실패: %s", exc)
                continue
            if text:
                texts.append(text)
    finally:
        try:
            video_path.unlink(missing_ok=True)
        except OSError:
            pass

    return texts


def should_run_ocr(
    existing_caption: str,
    existing_user_num: Optional[str],
    media_urls: List[str],
    force: bool = FORCE_REPROCESS,
) -> bool:
    if force:
        return True
    if not media_urls:
        return False
    # media_caption이 이미 존재하면 OCR 스킵 (속도 최적화)
    if existing_caption and existing_caption.strip():
        logger.debug("  → media_caption이 이미 존재하여 OCR 스킵")
        return False
    if not existing_caption:
        return True
    if len(existing_caption) < MIN_CAPTION_LENGTH:
        return True
    if not existing_user_num and not has_user_pattern(existing_caption):
        return True
    return False


def choose_media_caption(existing: str, candidate: str) -> Tuple[str, bool]:
    existing = (existing or "").strip()
    candidate = (candidate or "").strip()

    if not existing and candidate:
        return candidate, True
    if existing and not candidate:
        return existing, False
    if not existing and not candidate:
        return "", False

    candidate_has_pattern = has_user_pattern(candidate)
    existing_has_pattern = has_user_pattern(existing)
    if candidate_has_pattern and not existing_has_pattern:
        return candidate, True
    if existing_has_pattern and not candidate_has_pattern:
        return existing, False

    if len(candidate) > len(existing):
        return candidate, True

    return existing, False


def generate_media_caption(post: dict) -> str:
    media_type = post.get("media_type")
    media_urls: List[str] = post.get("media_url") or []
    ocr_chunks: List[str] = []

    if media_type in {"image", "multi_image"}:
        for url in media_urls:
            text = ocr_image_url(url)
            if text:
                ocr_chunks.append(text)
    elif media_type == "video" and len(media_urls) >= 2:
        thumb_text = ocr_image_url(media_urls[0])
        if thumb_text:
            ocr_chunks.append(thumb_text)
        ocr_chunks.extend(ocr_video(media_urls[1]))

    return "\n".join(chunk for chunk in ocr_chunks if chunk).strip()


def process_target_post(post: dict, all_posts: List[dict]) -> bool:
    existing_caption = (post.get("media_caption") or "").strip()
    existing_user_num = post.get("user_num")
    media_urls: List[str] = post.get("media_url") or []

    updated = False

    need_ocr = should_run_ocr(existing_caption, existing_user_num, media_urls)
    if need_ocr:
        logger.debug("  → OCR 실행 필요")
    candidate_caption = generate_media_caption(post) if need_ocr else ""

    chosen_caption, caption_updated = choose_media_caption(existing_caption, candidate_caption)
    if not need_ocr and not caption_updated:
        logger.debug("  → 기존 media_caption 유지 (재분석 조건 미충족)")

    if caption_updated:
        post["media_caption"] = chosen_caption
        updated = True
        logger.debug("  → media_caption 업데이트됨")
    elif not existing_caption and chosen_caption:
        post["media_caption"] = chosen_caption
        updated = True
        logger.debug("  → media_caption 신규 추가됨")

    return updated


def process_posts(posts: List[dict], targets: Iterable[dict]) -> int:
    updated_posts = 0
    index = 0

    for index, post in enumerate(targets, start=1):
        shortcode = post.get("shortcode")
        p_num = post.get("p_num")
        user_id = post.get("user_id")
        logger.info(
            "▶ %d번째 게시물 처리 시작 (p_num=%s, shortcode=%s, user_id=%s)",
            index,
            p_num,
            shortcode,
            user_id or "<없음>",
        )
        try:
            if process_target_post(post, posts):
                updated_posts += 1
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("게시물 처리 실패 (p_num=%s, shortcode=%s): %s", p_num, shortcode, exc)
            continue

    return updated_posts


def save_posts(posts: List[dict], updated_posts: int) -> None:
    """게시물 데이터를 파일에 저장"""
    OUTPUT_PATH.write_text(json.dumps(posts, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(
        "JSON 업데이트 완료 (media_caption 갱신 %d건)",
        updated_posts,
    )


def main() -> None:
    logger.info("=" * 80)
    logger.info("프로그램 시작 - 로그 파일: %s", LOG_PATH.absolute())
    logger.info("=" * 80)
    
    posts = json.loads(INPUT_PATH.read_text(encoding="utf-8"))
    # 초기 상태 백업 (실제 변경사항 확인용)
    initial_posts_state = copy.deepcopy(posts)

    if TARGET_P_NUM > 0:
        target_post = next((post for post in posts if post.get("p_num") == TARGET_P_NUM), None)
        if target_post is None:
            raise ValueError(f"p_num={TARGET_P_NUM}에 해당하는 게시물을 찾을 수 없습니다.")
        targets: List[dict] = [target_post]
        logger.info("단일 게시물 테스트 모드 (p_num=%s)", TARGET_P_NUM)
    else:
        # media_caption이 없거나 비어있는 게시물만 필터링 (재시작 시 이미 처리된 것은 스킵)
        if FORCE_REPROCESS:
            # 강제 재처리 모드: 모든 게시물 처리
            candidate_targets = posts
            logger.info("강제 재처리 모드: 모든 게시물 처리")
        else:
            # 일반 모드: media_caption이 없는 게시물만 처리
            candidate_targets = [
                post
                for post in posts
                if not (post.get("media_caption") or "").strip()
                or should_run_ocr(
                    (post.get("media_caption") or "").strip(),
                    post.get("user_num"),
                    post.get("media_url") or [],
                    False,
                )
            ]
            skipped_count = len(posts) - len(candidate_targets)
            if skipped_count > 0:
                logger.info(
                    "이미 처리된 게시물 %d건 스킵 (media_caption 있음)", skipped_count
                )

        if TEST_LIMIT > 0:
            targets = candidate_targets[:TEST_LIMIT]
            logger.info("샘플 테스트 모드: 상위 %d건 처리", len(targets))
        else:
            targets = candidate_targets
            logger.info("전체 데이터 처리 모드: 총 %d건 처리", len(targets))

    updated_posts = 0

    try:
        updated_posts = process_posts(posts, targets)
    except KeyboardInterrupt:
        logger.warning("\n⚠️  사용자에 의해 중단되었습니다. 처리 완료된 데이터를 저장합니다...")
        # 실제 변경사항 확인 (초기 상태와 비교)
        # 빠른 비교: JSON 직렬화로 비교 (더 정확함)
        initial_json = json.dumps(initial_posts_state, sort_keys=True, ensure_ascii=False)
        current_json = json.dumps(posts, sort_keys=True, ensure_ascii=False)
        has_changes = initial_json != current_json
        
        if has_changes or updated_posts > 0:
            # 실제 변경사항이 있거나 카운터에 변경이 있으면 무조건 저장
            save_posts(posts, updated_posts)
            logger.info("✅ 중간 저장 완료 (처리된 데이터 보존됨)")
        else:
            logger.info("변경된 내용이 없어 저장하지 않습니다.")
        raise

    if updated_posts > 0:
        save_posts(posts, updated_posts)
    else:
        logger.info("변경된 게시물이 없습니다.")

    if targets:
        sample_post = targets[0]
        logger.info("첫 게시물 media_caption 미리보기:\n%s", sample_post.get("media_caption", "<없음>"))


if __name__ == "__main__":
    main()
