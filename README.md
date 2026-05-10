# 🎨 UI-PPT 자동 생성 에이전트 (HDS 기반)

AS-IS 화면 캡쳐본을 분석하여 실무에서 즉시 활용 가능한 **사내 표준 UI 정의서(PPT)**와 **프론트엔드 코드(HTML/React)**로 자동 변환하는 AI 에이전트입니다.

---

## 🌟 주요 기능

1. 📸 **Vision AI 기반 UI 자동 분석 및 PPT 렌더링**
   * 캡처본을 붙여넣기(Ctrl+V)하면, 버튼, 표, 모달 등을 파워포인트 네이티브 도형으로 자동 변환 및 정렬해 줍니다.
2. 💻 **사내 표준 프론트엔드 코드 자동 생성**
   * HDS(Ant Design) 및 Storybook 가이드라인이 적용된 React(JSX)/HTML 코드를 즉시 제공합니다.
3. 💬 **실시간 채팅(Chat UI) 피드백**
   * "버튼을 파란색으로 변경해" 등 채팅을 통해 초고속으로 화면을 수정하고 갱신할 수 있습니다.
4. 📑 **다양한 포맷 및 명세서 추출**
   * PPT, HTML/JSX, CSS, JSON 데이터 및 컴포넌트 명세서(CSV) 다운로드를 지원합니다.
5. 🪄 **디자인 토큰 양방향 스캐너**
   * 사내 PPT 템플릿과 CSS 파일을 스캔하여 컴포넌트 속성(색상, 폰트 등)을 시스템에 자동 동기화합니다.

---

## 🛠 기술 스택

* **Frontend:** Streamlit (`app.py`)
* **AI / LLM:** SK하이닉스 내부망 HCP API (Qwen-3.5 / Qwen-2.5-VL), OpenAI Python SDK
* **PPT Generation:** `python-pptx`
* **Data Validation:** Pydantic

---

## 🏗️ 시스템 아키텍처 및 동작 로직

이 시스템은 LLM의 토큰 한계를 극복하고 디자인 환각(Hallucination)을 차단하기 위해 철저한 **역할 분담(하이브리드 파이프라인)**으로 동작합니다.

1. **[Pass 1] 뼈대 추출 (LLM의 눈 👀)**
   * Vision LLM이 캡처 화면을 보고 **"어떤 컴포넌트가 어느 좌표(X, Y)에 있는지"** 구조만 파악하여 `JSON`으로 추출합니다.
2. **[Pass 2] 코드 생성 (LLM의 뇌 🧠)**
   * Text LLM이 `hds.css`와 `components_registry.json`의 가이드를 읽고, 추출된 뼈대를 바탕으로 완벽한 **HTML/React 코드**를 작성합니다. *(※ LLM은 PPT를 직접 그리지 않습니다.)*
3. **PPT 렌더링 (파이썬의 손 ✍️)**
   * 파이썬 백엔드(`ppt_service.py`)가 LLM이 넘겨준 좌표를 읽고, `components_registry.json`에 정의된 디자인 토큰(색상, 폰트 등)을 참고하여 **파워포인트 네이티브 도형을 오차 없이 직접 그려냅니다.**

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
## 📖 사용 가이드

1. **이미지 업로드:** 화면에 캡처본 붙여넣기(Ctrl+V).
2. **설정:** 프롬프트 및 PPT 템플릿 선택 후 `🚀 PPT 생성 시작` 클릭.
3. **결과 확인:** 미리보기 탭에서 결과 및 코드 확인 후 원클릭 복사 또는 파일 다운로드.
4. **피드백:** 좌측 사이드바 채팅창에 수정 요청사항 입력 시 초고속 반영.

---

## ⚙️ 관리자 및 고급 설정 (Admin & Advanced)

* **PPT 템플릿 다중 지원**: `master/` 폴더에 여러 `.pptx` 파일을 넣으면 UI에서 선택하여 생성할 수 있습니다.
* **환경 설정 튜닝**: `.env` 파일을 통해 슬라이드 비율, 정렬 오차율, API 타임아웃 등을 제어할 수 있습니다.
* **엔터프라이즈 로깅**: `logs/system.log`에 앱 사용 이력 및 오류가 자동 기록됩니다.
* **CSS 연동**: `hds.css` 파일에 사내 글로벌 CSS를 덮어씌우면 AI가 이를 최우선 참조하여 코드를 생성합니다.
* **컴포넌트 통합 레지스트리 (`components_registry.json`)**: 
  * 컴포넌트별 프론트엔드 사용법(`guide`)과 PPT 렌더링 스타일(`ppt_style`)을 단일 파일로 동기화 및 관리합니다.
  * 특정 컴포넌트에 `"locked": true`를 부여하면 스캐너 실행 시 값이 덮어씌워지지 않고 안전하게 보존됩니다.
* **디자인 토큰 자동 추출 (양방향 스캐너)**: 
  * 앱 하단의 **[🛠️ 관리자 도구]**를 통해 사내 템플릿 PPT 도형 또는 `hds.css`의 색상 속성을 스캔하여 레지스트리에 자동 등록합니다.