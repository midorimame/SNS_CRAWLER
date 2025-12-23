#! /bin/bash
# 가상환경 호출
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$(dirname "$SCRIPT_DIR")/.env"
source "$VENV_PATH"

# 페이스북 해시태그별 크롤링 수행
python ./facebook_crawling.py
# facebook_media.json에서 이미지와 영상링크를 모아서 OCR 분석
python ./facebook_imgocr.py
# facebook_media.json에서 영상 미디어에서 음성분석
python ./facebook_audio_whisper.py

# 가상환경 종료
deactivate