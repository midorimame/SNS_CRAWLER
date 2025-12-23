# SNS 크롤링 시스템

SNS 플랫폼(카카오스토리, Instagram, Facebook)의 해시태그 기반 게시물 수집 및 분석 시스템입니다.

## 📋 목차

1. [프로젝트 개요](#프로젝트-개요)
2. [프로젝트 구조](#프로젝트-구조)
3. [기술 스택](#기술-스택)
4. [설치 및 환경 설정](#설치-및-환경-설정)
5. [사용 방법](#사용-방법)
6. [각 플랫폼별 상세 문서](#각-플랫폼별-상세-문서)
7. [주의사항](#주의사항)

---

## 프로젝트 개요

이 프로젝트는 세 가지 SNS 플랫폼에서 해시태그 기반 게시물을 크롤링하고, 다음과 같은 분석을 수행합니다:

- **게시물 크롤링**: 해시태그별 게시물 수집
- **OCR 분석**: 이미지 및 비디오에서 텍스트 추출 (EasyOCR)
- **오디오 분석**: 비디오에서 오디오 추출 및 음성 인식 (Whisper)
- **사용자 정보 추출**: 게시물 작성자 정보 수집 및 정리

### 지원 플랫폼

- **카카오스토리**: 해시태그 기반 게시물 크롤링 및 분석
- **Instagram**: Graph API 및 Selenium을 사용한 크롤링 및 분석
- **Facebook**: 해시태그 기반 게시물 크롤링 및 분석

---

## 프로젝트 구조

```
SNS_CRAWLER/
├── kakaostory/          # 카카오스토리 크롤링 시스템
│   ├── kakaostory_README.md
│   ├── kakaostory.sh
│   └── *.py             # 크롤링 스크립트들
│
├── instagram/           # Instagram 크롤링 시스템
│   ├── instagram_README.md
│   ├── instagram.sh
│   └── *.py             # 크롤링 스크립트들
│
├── facebook/            # Facebook 크롤링 시스템
│   ├── facebook_README.md
│   ├── facebook.sh
│   └── *.py             # 크롤링 스크립트들
│
├── .env                 # 환경 변수 파일 (직접 생성 필요)
├── .gitignore
└── README.md            # 이 파일
```

---

## 기술 스택

### 주요 라이브러리

- **Selenium**: 웹 크롤링 및 자동화
- **EasyOCR**: 이미지 및 비디오 OCR 처리
- **Whisper (OpenAI)**: 음성 인식 (STT)
- **FFmpeg**: 비디오에서 오디오 추출 (Whisper와 함께 사용)
- **requests**: HTTP 요청
- **PIL/Pillow**: 이미지 처리
- **python-dotenv**: 환경 변수 관리

### Python 버전

- Python 3.11 권장

---

## 설치 및 환경 설정

### 1. 필수 패키지 설치

```bash
pip install selenium easyocr openai-whisper requests pillow python-dotenv
```

### 2. 환경 변수 설정

프로젝트 루트 디렉터리에 `.env` 파일을 생성하고 다음 내용을 추가하세요:

```bash
VENV_PATH=/path/to/your/venv/bin/activate
```

**예시:**
```bash
VENV_PATH=/home/user/venvs/py311/bin/activate
```

### 3. ChromeDriver 설치

Selenium을 사용하므로 Chrome 브라우저와 호환되는 ChromeDriver가 필요합니다.

### 4. FFmpeg 설치

비디오에서 오디오 추출 및 Whisper 음성 인식을 위해 FFmpeg가 필요합니다.

#### Windows
1. [FFmpeg 공식 웹사이트](https://ffmpeg.org/download.html)에서 다운로드
2. 압축 해제 후 `bin` 폴더를 PATH 환경 변수에 추가
3. 또는 `C:\ffmpeg\bin\ffmpeg.exe` 경로에 설치

#### Linux/macOS
```bash
# Ubuntu/Debian
sudo apt update && sudo apt install ffmpeg

# macOS
brew install ffmpeg
```

설치 확인:
```bash
ffmpeg -version
```

### 5. 추가 설정 (Instagram만 해당)

Instagram Graph API를 사용하는 경우, `.env` 파일에 Access Token을 추가하세요:

```bash
INSTAGRAM_ACCESS_TOKEN=your_access_token_here
```

---

## 사용 방법

### 전체 프로세스 실행

각 플랫폼별 디렉터리에서 shell 스크립트를 실행합니다:

```bash
# 카카오스토리
cd kakaostory
bash kakaostory.sh

# Instagram
cd instagram
bash instagram.sh

# Facebook
cd facebook
bash facebook.sh
```

### 개별 스크립트 실행

각 플랫폼의 README 문서를 참고하여 개별 스크립트를 실행할 수 있습니다.

---

## 각 플랫폼별 상세 문서

각 플랫폼의 상세한 사용 방법, 데이터 흐름, 문제 해결 방법은 다음 문서를 참고하세요:

- **[카카오스토리 크롤링 시스템](kakaostory/kakaostory_README.md)**
  - 해시태그별 게시물 수집
  - 이미지/비디오 OCR
  - 오디오 추출 및 음성 인식
  - 사용자 정보 추출

- **[Instagram 크롤링 시스템](instagram/instagram_README.md)**
  - Graph API를 사용한 게시물 수집
  - 사용자 정보 추출
  - Carousel Album 처리
  - 이미지/비디오 OCR 및 오디오 추출

- **[Facebook 크롤링 시스템](facebook/facebook_README.md)**
  - 해시태그별 게시물 수집
  - 이미지/비디오 OCR
  - 비디오 오디오 추출

---

## 주의사항

### 공통 주의사항

1. **실행 순서 준수**: 각 플랫폼의 스크립트는 반드시 순서대로 실행해야 합니다.
2. **중복 처리 방지**: 각 스크립트는 이미 처리된 데이터를 스킵하므로, 중간에 중단되어도 재실행 가능합니다.
3. **ChromeDriver 버전**: Chrome 브라우저와 ChromeDriver 버전 호환성을 확인하세요.
4. **네트워크 연결**: 안정적인 네트워크 연결이 필요합니다.
5. **리소스 사용**: Whisper 모델 로드 및 OCR 처리 시 메모리와 시간이 소요됩니다.

### 플랫폼별 주의사항

#### Instagram
- Instagram Graph API Access Token이 필요합니다.
- API 토큰 만료 시 메타 개발자 계정에서 장기 토큰을 발급받아야 합니다.
- 대부분의 스크립트는 Instagram 로그인이 필요합니다.

#### Facebook
- Facebook 로그인이 필요한 스크립트가 있습니다.
- Selenium Wire가 필요한 경우 추가 설치가 필요합니다: `pip install selenium-wire`

#### 카카오스토리
- Selenium을 사용한 웹 크롤링을 수행합니다.

### 데이터 파일

크롤링된 데이터 파일들은 `.gitignore`에 포함되어 있어 Git에 커밋되지 않습니다:
- `*.json`: 크롤링된 게시물 및 사용자 데이터
- `*.log`: 로그 파일
- `*.pkl`: 쿠키 및 세션 파일

---

## 문제 해결

각 플랫폼별 README 문서의 "문제 해결" 섹션을 참고하세요:
- [카카오스토리 문제 해결](kakaostory/kakaostory_README.md#문제-해결)
- [Instagram 문제 해결](instagram/instagram_README.md#문제-해결)
- [Facebook 문제 해결](facebook/facebook_README.md#문제-해결)

---

## 라이선스

이 프로젝트의 라이선스 정보를 여기에 추가하세요.

---

## 업데이트 이력

- 2025-12-12: 프로젝트 백업
- 2025-12-23: 프로젝트 github에 추가

