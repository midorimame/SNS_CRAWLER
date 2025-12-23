# Facebook 크롤링 시스템 인수인계 문서

## 📋 목차
1. [시스템 개요](#시스템-개요)
2. [파일 구조 및 역할](#파일-구조-및-역할)
3. [데이터 흐름도](#데이터-흐름도)
4. [각 스크립트 상세 설명](#각-스크립트-상세-설명)
5. [실행 순서](#실행-순서)
6. [입출력 파일](#입출력-파일)

---

## 시스템 개요

Facebook 해시태그 기반 게시물 수집 및 분석 시스템입니다.
해시태그별로 게시물을 크롤링하고, 이미지/비디오 OCR, 오디오 추출 등의 후처리를 수행합니다.

---

## 파일 구조 및 역할

### 1. `facebook_crawling.py` (1단계: 크롤링)
**역할**: Facebook 해시태그별 게시물 수집

**주요 기능**:
- 해시태그 목록을 순회하며 게시물 수집
- Selenium을 사용한 웹 크롤링
- 게시물 정보 추출 (작성자, 내용, 미디어 URL, 좋아요/댓글 수 등)
- 중복 게시물 체크 및 업데이트
- `audio_caption`과 `media_caption` 보존 (기존 데이터 유지)

**입력**: 해시태그 리스트 (코드 내 정의)
**출력**: `facebook_media.json`

---

### 2. `facebook_imgocr.py` (2단계: OCR 처리)
**역할**: 이미지 및 비디오에서 텍스트 추출 (OCR)

**주요 기능**:
- 이미지 URL에서 EasyOCR을 사용한 텍스트 추출
- 비디오의 첫 프레임과 마지막 프레임에서 OCR 수행
- `media_caption` 필드에 OCR 결과 저장
- 이미 처리된 게시물은 스킵 (중복 처리 방지)
- Facebook 로그인 필요 (미디어 접근을 위해)

**입력**: `facebook_media.json`
**출력**: `facebook_media.json` (업데이트)

---

### 3. `facebook_audio_whisper.py` (3단계: 오디오 추출)
**역할**: 비디오 게시물에서 오디오 추출 및 음성 인식

**주요 기능**:
- `/reel/` 또는 `/video/`가 포함된 게시물 필터링
- Selenium Wire를 사용한 네트워크 요청 모니터링
- 비디오 URL에서 오디오 추출
- Web Audio API를 사용한 오디오 데이터 수집
- `audio_caption` 필드에 오디오 추출 결과 저장
- 이미 처리된 게시물은 스킵

**입력**: `facebook_media.json`
**출력**: `facebook_media.json` (업데이트)

---

## 데이터 흐름도

```
┌─────────────────────────────────────────────────────────────┐
│ 1. facebook_crawling.py                                     │
│    - 해시태그 리스트 순회                                    │
│    - Selenium으로 Facebook 크롤링                           │
│    - 게시물 정보 추출                                        │
│    - 중복 체크 및 업데이트                                   │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
         ┌───────────────────────────┐
         │ facebook_media.json        │
         │ (초기 크롤링 데이터)        │
         └───────────┬───────────────┘
                     │
         ┌───────────┴───────────────┐
         │                            │
         ▼                            ▼
┌──────────────────────┐   ┌──────────────────────┐
│ 2. imgocr.py         │   │ 3. audio_whisper.py  │
│    - 이미지 OCR       │   │    - 비디오 필터링    │
│    - 비디오 프레임 OCR│   │    - 오디오 추출      │
│    - media_caption   │   │    - audio_caption    │
└──────────┬───────────┘   └──────────┬───────────┘
           │                          │
           └──────────┬───────────────┘
                     │
                     ▼
         ┌───────────────────────────┐
         │ facebook_media.json        │
         │ (OCR + 오디오 처리 완료)    │
         └───────────────────────────┘
```

---

## 각 스크립트 상세 설명

### 1. facebook_crawling.py

#### 주요 함수
- `setup_driver()`: Chrome WebDriver 설정 (Chrome 경로 자동 탐지)
- `login_facebook()`: Facebook 로그인 (쿠키 사용 또는 새로 로그인)
- `crawl_hashtag_posts()`: 특정 해시태그의 게시물 크롤링
- `save_to_json()`: JSON 파일에 저장 (중복 체크 포함)

#### 처리 과정
1. 해시태그 페이지 접속 (`https://www.facebook.com/hashtag/{hashtag}`)
2. 게시물 목록 스크롤 및 로드
3. 각 게시물에서 정보 추출:
   - 작성자 정보 (user_name)
   - 게시 시간 (datetime)
   - 내용 (content)
   - 해시태그 (hashtags)
   - 미디어 URL (media_urls)
   - 좋아요/댓글 수
4. 중복 체크 (media_urls, user_name, content, hashtags 기준)
5. 신규 게시물 추가 또는 기존 게시물 업데이트
6. `audio_caption`과 `media_caption` 보존 (기존 데이터 유지)

#### 설정 변수
- `HASHTAGS`: 처리할 해시태그 목록
- `TEST_MODE`: 테스트 모드 (True면 첫 번째 해시태그의 상위 40개만 처리)

---

### 2. facebook_imgocr.py

#### 주요 함수
- `setup_driver()`: Chrome WebDriver 설정 (Chrome 경로 자동 탐지)
- `login_facebook()`: Facebook 로그인
- `ocr_image_url()`: 이미지 URL에서 OCR 수행
- `ocr_video_frame_from_blob()`: 비디오 프레임에서 OCR 수행
- `process_single_post()`: 단일 게시물 처리

#### 처리 과정
1. `facebook_media.json` 로드
2. Facebook 로그인
3. 각 게시물에 대해:
   - `media_caption`이 이미 있으면 스킵
   - 이미지 URL에서 EasyOCR로 텍스트 추출
   - 비디오의 첫/마지막 프레임에서 OCR
   - OCR 결과를 `media_caption` 필드에 저장
4. JSON 파일 업데이트 (매 게시물마다 저장)

#### 설정 변수
- `MIN_CAPTION_LENGTH`: 최소 caption 길이 (기본값: 10)

---

### 3. facebook_audio_whisper.py

#### 주요 함수
- `setup_driver()`: Chrome WebDriver 설정 (Selenium Wire 지원)
- `login_facebook()`: Facebook 로그인
- `extract_audio_from_video_url()`: 비디오 URL에서 오디오 추출
- `filter_video_and_reel_posts()`: 비디오 게시물 필터링
- `load_media_data()`, `save_media_data()`: 데이터 로드/저장

#### 처리 과정
1. `facebook_media.json` 로드
2. `/reel/` 또는 `/video/`가 포함된 게시물 필터링
3. `audio_caption`이 이미 있는 항목 제외
4. Facebook 로그인
5. 각 비디오 게시물에 대해:
   - Selenium Wire로 네트워크 요청 모니터링
   - 비디오 URL 접속
   - Web Audio API로 오디오 데이터 수집
   - 오디오 추출 및 텍스트 변환
   - `audio_caption` 필드에 결과 저장
6. JSON 파일 업데이트 (10개마다 중간 저장)

#### 특징
- Selenium Wire를 사용하여 네트워크 요청 모니터링
- Web Audio API로 오디오 데이터 수집
- 여러 비디오가 있는 경우 리스트로 저장

---

## 실행 순서

### 환경 설정

프로젝트 루트 디렉터리에 `.env` 파일을 생성하고 가상환경 경로를 설정하세요:

```bash
VENV_PATH=/path/to/your/venv/bin/activate
```

### 자동 실행 (권장)
```bash
bash facebook.sh
```

### 수동 실행
```bash
# 1단계: 크롤링
python facebook_crawling.py

# 2단계: OCR 처리
python facebook_imgocr.py

# 3단계: 오디오 추출
python facebook_audio_whisper.py
```

---

## 입출력 파일

### 입력 파일
- 없음 (해시태그는 코드 내 정의)

### 중간 파일
- `facebook_media.json`: 크롤링된 게시물 데이터
  - 각 스크립트가 순차적으로 업데이트
  - 필드: `user_name`, `datetime`, `content`, `hashtags`, `media_urls`, `like_count`, `comment_count`, `media_caption`, `audio_caption` 등

### 로그 파일
- `facebook.log`: 전체 프로세스 로그
- `facebook_imgocr.log`: OCR 처리 로그

---

## 주요 데이터 구조

### 게시물 (facebook_media.json)
```json
{
  "user_name": "홍길동",
  "datetime": "2025-12-11T12:00:00",
  "content": "게시물 내용...",
  "hashtags": ["#독일피엠"],
  "media_urls": ["https://..."],
  "like_count": 10,
  "comment_count": 5,
  "media_caption": "OCR 결과 텍스트",
  "audio_caption": "오디오 추출 결과"
}
```

---

## 주의사항

1. **실행 순서 준수**: 스크립트는 반드시 순서대로 실행해야 합니다.
2. **중복 처리 방지**: 각 스크립트는 이미 처리된 데이터를 스킵하므로, 중간에 중단되어도 재실행 가능합니다.
3. **Facebook 로그인**: `facebook_imgocr.py`와 `facebook_audio_whisper.py`는 Facebook 로그인이 필요합니다.
4. **ChromeDriver**: Chrome 브라우저와 ChromeDriver 버전 호환성 확인 필요
5. **네트워크**: 비디오 다운로드 및 크롤링 시 안정적인 네트워크 연결 필요
6. **Selenium Wire**: `facebook_audio_whisper.py`는 Selenium Wire를 사용하므로 추가 설치 필요 (`pip install selenium-wire`)

---

## 문제 해결

### ChromeDriver 오류
- Chrome 브라우저와 ChromeDriver 버전 확인
- `setup_driver()` 함수에서 Chrome 경로 확인

### OCR 실패
- EasyOCR 모델이 제대로 로드되었는지 확인
- 이미지/비디오 URL 접근 가능 여부 확인
- Facebook 로그인 상태 확인

### 오디오 추출 실패
- Selenium Wire 설치 확인
- 비디오 URL 접근 가능 여부 확인
- Web Audio API 지원 브라우저 사용

### 메모리 부족
- 배치 단위로 나누어 처리
- 테스트 모드로 처리량 제한

---
## 해결해야할 과제
**페이스북 게시글 작성자 정보 저장**
데이터를 가져오는데 다른 플랫폼보다 휴대폰 번호나 추천인번호(회원번호)같은 내용이 많이 발견되지 않았고, 인스타그램처럼 핸들을 추출하기도 어려워 프로젝트트 기간에는 관련 코드를 작성하지 못함. 추후에 페이스북 게시물 작성자 추출하는 파일 생성 필요.

**쿠키 파일 생성**
앞서 언급하였듯이, 인스타그램과 페이스북 같은 경우 로그인을 하지 않으면 작성자 개인 페이지에 접근하거나 검색 화면을 보지 못하는 등 크롤링할 때 어려운 점이 많이 생김.
쿠키가 만료되고 리눅스 환경에서 코드를 돌리는 경우, .pkl을 가져오는 파일을 하나를 윈도우 환경(GUI)으로 복사한 뒤에 코드 실행 시, 로그인하면 .pkl파일을 생성하므로, 생성된 .pkl 파일을 해당 코드가 있던 폴더에 넣어야 함.

**유지보수 필요**
인스타그램과 페이스북은 html css 셀렉터에 동적태그를 사용하므로 주기적으로 바뀌는 편이라고 함. 만약 데이터가 제대로 수집이 안 된다면 개발자 도구를 통해 css 셀렉터를 확인하는 것을 권장.


## 업데이트 이력

- 2025-12-12: 인수인계 문서 작성

