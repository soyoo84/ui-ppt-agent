# 🎨 UI-PPT 자동 생성 에이전트 (HDS 기반)

AS-IS 화면 캡쳐본을 분석하여 실무에서 즉시 활용 가능한 **사내 표준 UI 정의서(PPT)**와 **프론트엔드 코드(HTML/React)**로 자동 변환하는 AI 에이전트입니다.

---

## 🌟 주요 기능 (Key Features)

1. **비전(Vision) AI 기반 UI 분석**
   * AS-IS 화면 이미지를 분석하여 버튼, 입력창, 체크박스, 라디오 버튼, 모달, AG Grid 등 다양한 컴포넌트의 위치와 크기(X, Y 좌표)를 정확히 추출합니다.
2. **디자이너/퍼블리셔 맞춤형 UI 정의서(PPT) 생성**
   * 단순 이미지 붙여넣기가 아닌 `python-pptx`를 활용하여 파워포인트의 네이티브 도형(Shape)으로 화면을 다시 그립니다.
   * 생성된 PPT 파일은 기획자가 직접 도형의 크기, 위치, 텍스트, 색상을 수정할 수 있습니다.
   * 컴포넌트 간의 가로/세로 좌표 오차(3% 이내)를 자동으로 보정하여 자를 대고 그린 듯한 깔끔한 정렬(Snapping)을 제공합니다.
3. **HDS (Ant Design + AG Grid) 스타일 자동 매핑**
   * 사내 UI 표준에 맞추어 Ant Design의 기본 클래스(`ant-btn`, `ant-input` 등)와 AG Grid 패턴을 HTML/PPT에 일관되게 적용합니다.
4. **프론트엔드 코드 및 엑셀(CSV) 명세서 추출**
   * 프론트엔드 개발자가 즉시 활용할 수 있는 HTML/React(JSX) 코드를 생성하며, 기획자를 위해 엑셀과 호환되는 CSV 파일 형태의 컴포넌트 명세서를 제공합니다.
5. **채팅형(Chat UI) 피드백 및 클립보드 붙여넣기 지원**
   * 클립보드 복사/붙여넣기(Ctrl+V)를 완벽 지원하며, 좌측 사이드바의 채팅창에 피드백을 입력하면 무거운 이미지 분석을 건너뛰는 **초고속(Fast-Track)** 방식으로 결과물을 실시간 갱신합니다.

---

## 🛠 기술 스택

* **Frontend:** Streamlit (`app.py`)
* **AI / LLM:** SK하이닉스 내부망 HCP API (Qwen-3.5 / Qwen-2.5-VL), OpenAI Python SDK
* **PPT Generation:** `python-pptx`
* **Data Validation:** Pydantic

---

## 🚀 설치 및 실행

### 1. 사전 준비
루트 폴더에 `.env` 파일을 생성하고 사내 환경에 맞게 세팅합니다.
```env
HCP_API_URL=https://hcp.skhynix.com/llm/v1
HCP_API_KEY=your_api_key_here
HCP_VISION_MODEL=qwen-2.5-vl
HCP_TEXT_MODEL=qwen-3.5
```
* **사내 PPT 템플릿:** `master/` 폴더에 `.pptx` 파일 추가
* **사내 HDS CSS:** 루트의 `hds.css` 파일 덮어쓰기

### 2. 설치 및 실행
```bash
pip install -r requirements.txt  # python-pptx, streamlit, openai, pydantic, pillow 등
streamlit run app.py
```
*(브라우저에서 `http://localhost:8501`로 접속)*

---
## 📖 상세 사용자 가이드 (User Guide)

### Step 1. 이미지 업로드 & 설정
* 화면에 캡처본을 **`Ctrl+V`**로 붙여넣고, **프롬프트** 및 **PPT 템플릿(레이아웃)**을 선택합니다.

### Step 2. 결과 생성 및 탭(Tab) 확인
* `🚀 PPT 생성 시작` 버튼을 클릭합니다. 완료 후 **4개의 탭**(미리보기, 코드, JSON, CSS)에서 결과물을 확인합니다.

### Step 3. 다운로드 및 실시간 피드백
* 하단 버튼을 통해 PPT, 코드, JSON, CSV 등을 다운로드합니다.
* 수정이 필요하면 **사이드바 채팅창**에 피드백(예: "검색 버튼 파란색으로")을 입력해 초고속으로 갱신합니다.

---

## ⚙️ 관리자 커스터마이징 가이드 (Admin Customizing)

* **PPT 템플릿 다중 지원**: `master/` 폴더에 여러 PPT 템플릿 파일을 넣어두면 Streamlit [고급 설정] 탭에서 원하는 템플릿을 선택하여 생성할 수 있습니다.
* **환경 설정 튜닝**: `.env` 파일을 통해 슬라이드 비율, 정렬 오차율, API 타임아웃, 하이퍼파라미터 등 코드를 수정하지 않고도 시스템 전반의 수치를 제어할 수 있습니다.
* **엔터프라이즈 로깅(Logging)**: 앱 실행 시 프로젝트 폴더에 `logs/system.log` 파일이 자동 생성되며, 사용자의 템플릿 선택, 소요 시간, 오류 상세 내역이 영구 기록되어 운영 및 장애 추적에 활용할 수 있습니다.

## 📚 Storybook 연동 및 활용 가이드 (Advanced)

사내 디자인 시스템(Storybook)과 연동하여 프론트엔드 코드 및 PPT 렌더링 스타일을 일원화하는 기능입니다.

### 1. CSS 연동 (`hds.css`)
사내 글로벌 CSS 파일을 `hds.css`에 덮어씌우면, AI가 1순위로 참조하여 표준 클래스 기반의 코드를 생성하고 미리보기 화면에 반영합니다.

### 2. 컴포넌트 통합 레지스트리 (`components_registry.json`)
자동 생성되는 이 파일에 사내 컴포넌트 사용법(`guide`)과 PPT 렌더링 스타일(`ppt_style`)을 정의하면, AI와 파이썬이 이를 참조해 렌더링합니다.

### 3. 역방향 스캐너 (디자인 토큰 자동 추출)
사내 템플릿 PPT에 도형을 그린 후, 도형 이름(또는 텍스트)을 `HdsButton`으로 설정합니다. 앱의 **[🪄 템플릿에서 디자인 토큰 스캔]** 버튼을 누르면 도형 스타일(색상, 테두리, 폰트 등)을 읽어 `components_registry.json`에 자동 등록합니다.