# 카카오스토리 크롤링 시스템 인수인계 문서

## 📋 목차
1. [시스템 개요](#시스템-개요)
2. [파일 구조 및 역할](#파일-구조-및-역할)
3. [데이터 흐름도](#데이터-흐름도)
4. [각 스크립트 상세 설명](#각-스크립트-상세-설명)
5. [실행 순서](#실행-순서)
6. [입출력 파일](#입출력-파일)

---

## 시스템 개요

카카오스토리 해시태그 기반 게시물 수집 및 분석 시스템입니다. 
해시태그별로 게시물을 크롤링하고, 이미지/비디오 OCR, 오디오 추출, 사용자 정보 추출 등의 후처리를 수행합니다.

---

## 파일 구조 및 역할

### 1. `kakaostory_crawling_test.py` (1단계: 크롤링)
**역할**: 카카오스토리 해시태그별 게시물 수집

**주요 기능**:
- 해시태그 목록을 순회하며 게시물 수집
- Selenium을 사용한 웹 크롤링
- 팝업에서 게시물 정보 추출 (작성자, 내용, 미디어 URL 등)
- 중복 게시물 체크 및 좋아요/댓글 수 갱신

**입력**: 해시태그 리스트 (코드 내 정의)
**출력**: `kakaostory_popup_posts.json`

---

### 2. `kakaostory_postprocess.py` (2단계: OCR 처리)
**역할**: 이미지 및 비디오에서 텍스트 추출 (OCR)

**주요 기능**:
- 이미지 URL에서 EasyOCR을 사용한 텍스트 추출
- 비디오의 첫 프레임과 마지막 프레임에서 OCR 수행
- `media_caption` 필드에 OCR 결과 저장
- 이미 처리된 게시물은 스킵 (중복 처리 방지)

**입력**: `kakaostory_popup_posts.json`
**출력**: `kakaostory_popup_posts.json` (업데이트)

---

### 3. `kakaostory_extract_audio.py` (3단계: 오디오 추출)
**역할**: 비디오 게시물에서 오디오 추출 및 음성 인식

**주요 기능**:
- 비디오 게시물 필터링 (`media_type="video"`)
- `.mp4` URL에서 비디오 다운로드
- Whisper 모델을 사용한 음성 인식 (STT)
- 평균 데시벨 계산
- `audio_caption` 필드에 음성 인식 결과 저장

**입력**: `kakaostory_popup_posts.json`
**출력**: `kakaostory_popup_posts.json` (업데이트)

---

### 4. `kakaostory_extract_userinfo.py` (4단계: 사용자 정보 추출)
**역할**: 게시물에서 사용자 정보 추출 및 정리

**주요 기능**:
- 게시물 내용에서 사용자 번호(`user_num`) 추출
- 전화번호 추출
- SNS ID 추출 (카카오톡, 인스타그램, 페이스북, 유튜브, 틱톡, 네이버 블로그)
- 사용자별 정보 병합 및 중복 제거
- `kakaostory_user.json`에 사용자 정보 저장

**입력**: `kakaostory_popup_posts.json`
**출력**: `kakaostory_user.json`

---

## 데이터 흐름도

```
┌─────────────────────────────────────────────────────────────┐
│ 1. kakaostory_crawling_test.py                              │
│    - 해시태그 리스트 순회                                    │
│    - Selenium으로 카카오스토리 크롤링                        │
│    - 게시물 정보 추출 (작성자, 내용, 미디어 URL 등)          │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
         ┌───────────────────────────┐
         │ kakaostory_popup_posts.json │
         │ (초기 크롤링 데이터)        │
         └───────────┬───────────────┘
                     │
         ┌───────────┴───────────────┐
         │                            │
         ▼                            ▼
┌──────────────────────┐   ┌──────────────────────┐
│ 2. postprocess.py    │   │ 3. extract_audio.py  │
│    - 이미지 OCR       │   │    - 비디오 다운로드  │
│    - 비디오 프레임 OCR│   │    - Whisper STT      │
│    - media_caption   │   │    - audio_caption    │
└──────────┬───────────┘   └──────────┬───────────┘
           │                          │
           └──────────┬───────────────┘
                     │
                     ▼
         ┌───────────────────────────┐
         │ kakaostory_popup_posts.json │
         │ (OCR + 오디오 처리 완료)    │
         └───────────┬───────────────┘
                     │
                     ▼
┌──────────────────────────────────────┐
│ 4. extract_userinfo.py               │
│    - 사용자 번호 추출                 │
│    - 전화번호 추출                    │
│    - SNS ID 추출                      │
│    - 사용자 정보 병합                  │
└──────────────────┬───────────────────┘
                   │
                   ▼
         ┌───────────────────────────┐
         │ kakaostory_user.json      │
         │ (사용자 정보 집계)         │
         └───────────────────────────┘
```

---

## 각 스크립트 상세 설명

### 1. kakaostory_crawling_test.py

#### 주요 함수
- `build_driver()`: Chrome WebDriver 설정
- `crawl_tag()`: 특정 해시태그의 게시물 크롤링
- `extract_post_from_popup()`: 팝업에서 게시물 정보 추출
- `load_existing_posts()`: 기존 게시물 데이터 로드
- `should_refresh()`: 게시물 갱신 필요 여부 판단

#### 처리 과정
1. 해시태그 URL 생성 (`https://story.kakao.com/hashtag/{tag}`)
2. 해시태그 페이지 접속
3. 썸네일 클릭하여 팝업 열기
4. 팝업에서 게시물 정보 추출:
   - 작성자 정보 (name, user_id)
   - 게시 시간
   - 내용 (content)
   - 해시태그 (hashtags)
   - 미디어 URL (media_url)
   - 좋아요/댓글 수
5. 중복 체크 (shortcode 기준)
6. 신규 게시물 추가 또는 기존 게시물 갱신

#### 설정 변수
- `HASHTAG_LIST`: 처리할 해시태그 목록
- `MAX_POSTS_PER_TAG`: 해시태그당 최대 게시물 수 (None이면 제한 없음)
- `HEADLESS_MODE`: 헤드리스 모드 사용 여부
- `REFRESH_WINDOW_DAYS`: 게시물 갱신 기간 (일)

---

### 2. kakaostory_postprocess.py

#### 주요 함수
- `ocr_image_url()`: 이미지 URL에서 OCR 수행
- `ocr_video()`: 비디오의 첫/마지막 프레임에서 OCR 수행
- `generate_media_caption()`: 게시물의 모든 미디어에서 OCR 결과 생성
- `should_run_ocr()`: OCR 실행 필요 여부 판단
- `process_target_post()`: 단일 게시물 처리

#### 처리 과정
1. `kakaostory_popup_posts.json` 로드
2. `media_caption`이 없는 게시물 필터링
3. 각 게시물에 대해:
   - 이미지: EasyOCR로 텍스트 추출
   - 비디오: 첫 프레임과 마지막 프레임에서 OCR
4. OCR 결과를 `media_caption` 필드에 저장
5. JSON 파일 업데이트

#### 설정 변수
- `FORCE_REPROCESS`: 강제 재처리 모드 (기본값: False)
- `TEST_LIMIT`: 테스트 모드 제한 (0이면 전체 처리)
- `TARGET_P_NUM`: 특정 게시물만 처리 (0이면 전체)

---

### 3. kakaostory_extract_audio.py

#### 주요 함수
- `download_video()`: 비디오 URL에서 비디오 다운로드
- `find_mp4_url()`: 미디어 URL 목록에서 .mp4 URL 찾기
- `transcribe_video()`: Whisper 모델로 음성 인식
- `calculate_audio_db()`: 평균 데시벨 계산
- `process_posts()`: 비디오 게시물 일괄 처리

#### 처리 과정
1. `kakaostory_popup_posts.json` 로드
2. Whisper 모델 로드
3. `media_type="video"`인 게시물 필터링
4. 각 비디오 게시물에 대해:
   - `.mp4` URL 찾기
   - 비디오 다운로드
   - Whisper로 음성 인식
   - 평균 데시벨 계산
   - `audio_caption` 필드에 결과 저장
5. JSON 파일 업데이트

#### 설정 변수
- `WHISPER_MODEL`: Whisper 모델 크기 (기본값: "base")
- `FORCE_REPROCESS`: 강제 재처리 모드
- `TEST_LIMIT`: 테스트 모드 제한

---

### 4. kakaostory_extract_userinfo.py

#### 주요 함수
- `extract_user_number()`: 게시물에서 사용자 번호 추출
- `extract_phone_number()`: 전화번호 추출
- `extract_kakao_id()`, `extract_instagram_id()` 등: SNS ID 추출
- `extract_user_info_from_post()`: 게시물에서 모든 사용자 정보 추출
- `merge_user_info()`: 사용자 정보 병합
- `process_posts_user_num()`: 사용자 번호 전파 처리

#### 처리 과정
1. 기존 `kakaostory_user.json` 로드
2. `kakaostory_popup_posts.json` 로드
3. 게시물을 `user_id`별로 그룹화
4. 각 사용자에 대해:
   - 모든 게시물에서 정보 추출
   - 사용자 번호, 전화번호, SNS ID 추출
   - 기존 사용자 정보와 병합
5. `name`만 있는 기존 사용자에 `user_id` 추가 시도
6. `kakaostory_user.json` 저장

#### 추출 정보
- `user_num`: 사용자 번호 (숫자 패턴)
- `phone_num`: 전화번호
- `kakao_id`: 카카오톡 ID
- `instagram_id`: 인스타그램 ID
- `facebook_id`: 페이스북 ID
- `youtube_id`: 유튜브 ID
- `tiktok_id`: 틱톡 ID
- `nblog_id`: 네이버 블로그 ID

#### 설정 변수
- `FORCE_REPROCESS`: 강제 재처리 모드

---

## 실행 순서

### 환경 설정

프로젝트 루트 디렉터리에 `.env` 파일을 생성하고 가상환경 경로를 설정하세요:

```bash
VENV_PATH=/path/to/your/venv/bin/activate
```

### 자동 실행 (권장)
```bash
bash kakaostory.sh
```

### 수동 실행
```bash
# 1단계: 크롤링
python kakaostory_crawling_test.py

# 2단계: OCR 처리
python kakaostory_postprocess.py

# 3단계: 오디오 추출
python kakaostory_extract_audio.py

# 4단계: 사용자 정보 추출
python kakaostory_extract_userinfo.py
```

---

## 입출력 파일

### 입력 파일
- 없음 (해시태그는 코드 내 정의)

### 중간 파일
- `kakaostory_popup_posts.json`: 크롤링된 게시물 데이터
  - 각 스크립트가 순차적으로 업데이트
  - 필드: `p_num`, `shortcode`, `user_id`, `name`, `content`, `hashtags`, `media_url`, `media_type`, `like_count`, `comment_count`, `media_caption`, `audio_caption` 등

### 출력 파일
- `kakaostory_user.json`: 추출된 사용자 정보
  - 필드: `user_id`, `name`, `user_num`, `phone_num`, `kakao_id`, `instagram_id` 등

### 로그 파일
- `kakaostory.log`: 전체 프로세스 로그
- `chromedriver.log`: ChromeDriver 로그

---

## 주요 데이터 구조

### 게시물 (kakaostory_popup_posts.json)
```json
{
  "p_num": 1,
  "shortcode": "ABC123",
  "user_id": "user123",
  "name": "홍길동",
  "content": "게시물 내용...",
  "hashtags": ["#독일피엠"],
  "media_url": ["https://..."],
  "media_type": "video",
  "like_count": 10,
  "comment_count": 5,
  "media_caption": "OCR 결과 텍스트",
  "audio_caption": "음성 인식 결과"
}
```

### 사용자 정보 (kakaostory_user.json)
```json
{
  "user_id": "user123",
  "name": "홍길동",
  "user_num": "010-1234-5678",
  "phone_num": "010-1234-5678",
  "kakao_id": "kakao_id",
  "instagram_id": "instagram_id"
}
```

---

## 주의사항

1. **실행 순서 준수**: 스크립트는 반드시 순서대로 실행해야 합니다.
2. **중복 처리 방지**: 각 스크립트는 이미 처리된 데이터를 스킵하므로, 중간에 중단되어도 재실행 가능합니다.
3. **리소스 사용**: Whisper 모델 로드 및 OCR 처리 시 메모리와 시간이 소요됩니다.
4. **ChromeDriver**: Chrome 브라우저와 ChromeDriver 버전 호환성 확인 필요
5. **네트워크**: 비디오 다운로드 및 크롤링 시 안정적인 네트워크 연결 필요

---

## 문제 해결

### ChromeDriver 오류
- Chrome 브라우저와 ChromeDriver 버전 확인
- `build_driver()` 함수에서 Chrome 경로 확인

### OCR 실패
- EasyOCR 모델이 제대로 로드되었는지 확인
- 이미지/비디오 URL 접근 가능 여부 확인

### Whisper 오류
- Whisper 모델 다운로드 확인
- 비디오 파일 형식 확인 (.mp4)

### 메모리 부족
- `TEST_LIMIT` 설정으로 처리량 제한
- 배치 단위로 나누어 처리

---

## 업데이트 이력

- 2025-12-12: 인수인계 문서 작성

