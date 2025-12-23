#! /bin/bash
# 가상환경 호출
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$(dirname "$SCRIPT_DIR")/.env"
source "$VENV_PATH"

# 카카오스토리 해시태그 별로 게시글 수집
python ./kakaostory_crawling_test.py
# 수집한 게시글의 이미지, 비디오 OCR(비디오는 처음과 끝 프레임 추출해서 OCR)
python ./kakaostory_postprocess.py
# 비디오 미디어에 대해서 whisper로 오디오분석
python ./kakaostory_extract_audio.py
# 수집한 데이터에서 게시글 작성자 정보 추출
python ./kakaostory_extract_userinfo.py

# 가상환경 종료
deactivate