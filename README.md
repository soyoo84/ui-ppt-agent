# 🎨 UI-PPT 자동 생성 에이전트 (HDS 기반)

이 프로젝트는 사용자가 업로드한 AS-IS(기존) 화면 캡쳐본을 SK하이닉스 내부망 LLM(Qwen)으로 분석하여, 사내 표준 디자인 시스템(HDS, Ant Design + AG Grid 기반)이 적용된 **수정 가능한 PPT 기획서**와 **프론트엔드 HTML/React 코드**로 자동 변환해 주는 AI 에이전트입니다.

---

## 🌟 주요 기능 (Key Features)

1. **비전(Vision) AI 기반 UI 분석**
   * AS-IS 화면 이미지를 분석하여 버튼, 입력창, 체크박스, 라디오 버튼, 모달, AG Grid 등 다양한 컴포넌트의 위치와 크기(X, Y 좌표)를 정확히 추출합니다.
2. **수정 가능한 PPT(Native Shape) 생성**
   * 단순 이미지 붙여넣기가 아닌 `python-pptx`를 활용하여 파워포인트의 네이티브 도형(Shape)으로 화면을 다시 그립니다.
   * 생성된 PPT 파일은 기획자가 직접 도형의 크기, 위치, 텍스트, 색상을 수정할 수 있습니다.
   * 컴포넌트 간의 가로/세로 좌표 오차(3% 이내)를 자동으로 보정하여 자를 대고 그린 듯한 깔끔한 정렬(Snapping)을 제공합니다.
3. **HDS (Ant Design + AG Grid) 스타일 자동 매핑**
   * 사내 UI 표준에 맞추어 Ant Design의 기본 클래스(`ant-btn`, `ant-input` 등)와 AG Grid 패턴을 HTML/PPT에 일관되게 적용합니다.
4. **프론트엔드 HTML/CSS/React 코드 생성**
   * 화면 구성뿐만 아니라 프론트엔드 개발자가 즉시 활용할 수 있는 HTML DOM 구조 또는 React(JSX) 코드를 함께 생성하여 제공합니다. (웹에서 미리보기 지원)
5. **피드백 루프 (Revision 반영 기능)**
   * 생성된 결과물이 마음에 들지 않을 경우, 텍스트로 피드백(예: "로그인 버튼을 파란색으로 변경해줘")을 입력하면 이전 JSON 결과를 바탕으로 내용만 수정하여 다시 생성합니다.

---

## 🛠 기술 스택 (Tech Stack)

* **Frontend:** Streamlit (`app.py`)
* **AI / LLM:** SK하이닉스 내부망 HCP API (Qwen-3.5 / Qwen-2.5-VL), OpenAI Python SDK
* **PPT Generation:** `python-pptx`
* **Data Validation:** Pydantic

---

## 📂 디렉토리 구조 및 파일 명세

```text
e:\workspace\UI-PPT\
├── app.py                   # Streamlit 웹 프론트엔드 (이미지 업로드, 미리보기, 다운로드 UI)
├── local_llm_service.py     # HCP API 통신, 로직 제어 및 JSON 파싱
├── ppt_service.py           # 추출된 JSON 데이터를 기반으로 PPT 슬라이드 렌더링
├── schemas.py               # Pydantic 데이터 스키마 정의
├── prompts.py               # 목적별 시스템 프롬프트(HTML, React 등) 템플릿 통합 관리
├── config.py                # 환경 변수를 로드하고 파이썬 상수로 제공하는 중앙 설정 파일
├── .env                     # API 키, 모델명, 타임아웃, PPT 크기 등 환경 변수 설정 파일
├── .gitignore               # Git 버전 관리 제외 목록 (보안 및 캐시 파일 제외)
├── hds.css                  # HDS 스타일(Ant Design 기반) 샘플 CSS
├── master.pptx              # (선택) 사내 PPT 템플릿 (배경, 로고, 폰트 설정용)
└── requirements.txt         # 프로젝트 실행에 필요한 Python 라이브러리
```

---

## 🚀 설치 및 실행 방법 (Installation & Usage)

## 🏢 사내 내부망 로컬 세팅 필수 체크리스트

사내(폐쇄망) 로컬 PC 환경에서 작업을 시작하기 전에 다음 항목들을 반드시 세팅해 주세요.

1. **진짜 HDS CSS 파일 교체**
   * 프로젝트 루트의 `hds.css` 파일을 실제 사내 NPM 패키지나 가이드 사이트에서 추출한 진짜 HDS CSS 파일로 덮어쓰기 합니다.
2. **사내 표준 PPT 템플릿(`master.pptx`) 적용**
   * 사내 기획서 표준 양식 파일을 `master.pptx`라는 이름으로 프로젝트 루트에 넣습니다.
   * `.env` 파일의 `TARGET_LAYOUT_NAME`을 해당 템플릿의 실제 빈 화면 레이아웃 이름으로 변경합니다.

---

### 0. 환경 변수 설정 (.env)
프로젝트를 실행하기 전, 루트 경로에 `.env` 파일을 생성하고 필요한 설정값을 기입합니다.
```env
HCP_API_URL=https://hcp.skhynix.com/llm/v1
HCP_API_KEY=your_api_key_here
HCP_VISION_MODEL=qwen-2.5-vl
HCP_TEXT_MODEL=qwen-3.5
```

### 1. 패키지 설치
Python 3.9 이상의 환경에서 아래 명령어를 통해 필요한 라이브러리를 설치합니다.
```bash
pip install -r requirements.txt
```

### 2. Streamlit 웹 실행 (단독 구동)
새로운 터미널을 열고 사용자 인터페이스를 실행합니다.
```bash
streamlit run app.py
```
*(브라우저에서 `http://localhost:8501`로 접속)*

---

## 📖 시스템 워크플로우 (Workflow)

1. **요청 단계**: 사용자가 `app.py`에서 캡쳐 이미지와 시스템 프롬프트(HTML or React)를 선택하고 전송합니다.
2. **LLM 분석**: Streamlit 앱이 LLM을 직접 호출하여, 화면을 분석하고 `schemas.py`의 구조에 맞는 JSON 데이터를 받아옵니다. (재시도 및 타임아웃 방어 적용)
3. **메모리 렌더링**: 추출된 JSON 데이터로 PPT 슬라이드와 HTML, 코드를 디스크 기록 없이 100% 로컬 메모리(RAM)에 직접 생성합니다.
4. **결과 확인**: 화면에 CSS가 적용된 HTML 미리보기와 코드가 렌더링되며, 즉시 다운로드 버튼이 제공됩니다.

---

## 💡 커스터마이징 가이드 (Customizing)

* **PPT 템플릿 변경**: 프로젝트 루트 경로에 `master.pptx` 파일을 배치하고 슬라이드 마스터(배경, 로고, 폰트)를 수정하면 생성되는 PPT에 즉시 반영됩니다.
* **CSS 스타일 변경**: `hds.css` 파일 내의 속성을 사내 HDS 스펙에 맞게 수정하면 HTML 다운로드 파일 및 화면 미리보기에 즉시 적용됩니다.
* **프롬프트 튜닝**: `prompts.py`에 정의된 `DEFAULT_PROMPT` 및 `REACT_PROMPT`를 수정하거나 새로운 템플릿을 추가하여 LLM의 인식 규칙을 유연하게 변경할 수 있습니다.
* **환경 설정 튜닝**: `.env` 파일을 통해 슬라이드 비율, 정렬 오차율, API 타임아웃, 하이퍼파라미터 등 코드를 수정하지 않고도 시스템 전반의 수치를 제어할 수 있습니다.