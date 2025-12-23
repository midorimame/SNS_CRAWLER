#! /bin/bash
# 가상환경 호출
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$(dirname "$SCRIPT_DIR")/.env"
source "$VENV_PATH"

# Graph API로 인스타그램 해시태그별 최근 게시물 최대 50개씩 불러옴.(carousel_album 미디어 타입은 썸네일 하나만 가져옴.)
python ./instagram_use_api.py
# instagram_media.json에 모인 permalink를 토대로 작성자의 handle과 닉네임을 중복없이 수집해 instagram_user.json에 저장
python ./instagram_extract_user.py
# instagram_user.json에 모인 작성자들의 프로필로 들어가서 링크된 페이지, 소개글, 팔로워 수, 소개글에 명시된 핸드폰번호나 PM 회원번호 수집
python ./instagram_save_userinfo.py
# instagram_user.json에 있는 작성자의 과거 게시물 permalink 전부 수집
python ./instagram_crawling_postpermalink.py
# 위에서 수집된 permalink로 들어가 게시물에 지정한 해시태그가 있다면 게시물 수집
python ./instagram_filter_userposts.py
# 모인 데이터에서 Carousel_Album의 미디어 개수 정확히 세기 + OCR 분석
python ./instagram_extract_imgurl.py
# 모인 데이터에서 Image, Video가 media_type인 것들에 대해 OCR 분석
python ./instagram_extract_single_media_ocr.py
# 이미지 OCR 끝난 후 video가 들어간 carousel_album과 video 타입에 대해 openai-whisper 오디오 분석
python ./instagram_extract_audio_from_json.py

# 가상환경 종료
deactivate