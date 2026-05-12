import json
import os
import logging

logger = logging.getLogger(__name__)

DEFAULT_PROMPT = """당신은 수석 UI/UX 디자이너입니다. 사용자가 제공한 UI 화면을 분석하여 TO-BE 컴포넌트로 분해하세요.
이 시스템(HDS)은 Ant Design 컴포넌트(Button, Input, Select, Modal, Switch, Radio, Tooltip, Progress 등)와 AG Grid(데이터 그리드)를 기반으로 커스텀 UI가 적용되어 있습니다. 화면의 요소들을 해당 패턴에 맞게 식별하세요. AG Grid의 상단 툴바(검색, 엑셀 다운로드 등)와 하단 페이징 영역도 분리해서 인식하세요. 팝업 창이 있다면 'Modal' 컴포넌트로, 도움말 말풍선은 'Tooltip', 진행 상태 바는 'ProgressBar'로 인식하세요.
날짜 선택기는 'DatePicker'로 인식하세요. 또한 각 컴포넌트별로 고유한 'component_id'(예: btn-login-01, input-id-01)를 부여하고, 클릭이나 입력 시 작동해야 하는 세부 기능(Event)을 'event_description'에 구체적으로 작성하세요.
추가로, 식별된 컴포넌트들을 바탕으로 Ant Design의 기본 클래스명(예: ant-btn)과 방금 부여한 'component_id'를 id 속성으로 사용한 HTML DOM 구조를 'generated_html'에 작성하세요. (CSS는 외부 파일인 hds.css를 연결할 것이므로 인라인 스타일은 최소화하세요.)

[🚨 JSON 작성 시 엄격한 주의사항 🚨]
1. HTML 태그(<, >)를 '&lt;' 나 '&gt;' 로 절대 이스케이프(Escape)하지 말고 실제 꺾쇠 괄호 형태 그대로 작성하세요.
2. HTML 요소의 속성값(class, id 등)을 작성할 때는 반드시 홑따옴표(')만 사용하세요. (예: <div class='ant-btn'>) 쌍따옴표를 사용하면 JSON 파싱 에러가 발생합니다.
3. 'generated_html' 문자열 내부에서 실제 엔터키(줄바꿈)를 치지 말고, 반드시 `\\n` 문자를 사용하여 한 줄로 작성하세요.
4. [매우 중요] 'generated_html' 코드가 너무 길어지면 시스템 오류(잘림 현상)가 발생합니다. 반복되는 리스트, 표(Table)의 행/열, 긴 텍스트 등은 모두 생략하고 핵심 뼈대만 남기세요. 전체 HTML 코드가 1,500자를 넘지 않도록 극도로 요약해야 합니다.

반드시 아래의 JSON 형식에 맞추어 답변해야 하며, 다른 텍스트는 출력하지 마세요.
컴포넌트 타입('component_type')은 사내 HDS CSS에 정의된 클래스명(예: ant-btn-primary, ant-input 등)을 우선 적용하고, 매칭되는 것이 없다면 CSS 네이밍 규칙(kebab-case)에 따라 자유롭게 지어주세요.
위치(x_percent, y_percent)와 크기(width_percent, height_percent)는 0.0 에서 1.0 사이의 실수로 표현하세요.

[출력 JSON 예시]
{
  "screen_name": "로그인 화면",
  "screen_description": "사용자 인증을 위한 로그인 화면입니다. ID/PW 입력 및 소셜 로그인 기능을 제공합니다.",
  "generated_html": "<div class='login-container'>\\n  <input id='input-id-01' class='ant-input' placeholder='ID' />\\n  <button id='btn-login-01' class='ant-btn ant-btn-primary'>로그인</button>\\n</div>",
  "components": [
    {
      "component_id": "btn-login-01",
      "component_type": "ant-btn-primary",
      "text": "로그인",
      "event_description": "클릭 시 입력된 ID/PW로 로그인 API를 호출하고 성공 시 메인 화면으로 이동",
      "x_percent": 0.15,
      "y_percent": 0.80,
      "width_percent": 0.70,
      "height_percent": 0.08
    }
  ]
}"""

REACT_PROMPT = """당신은 수석 프론트엔드 개발자이자 UI/UX 디자이너입니다. 사용자가 제공한 UI 화면을 분석하여 TO-BE 컴포넌트로 분해하세요.
이 시스템(HDS)은 Ant Design 컴포넌트(Button, Input, Select, Modal, Switch, Radio, Tooltip, Progress 등)와 AG Grid를 기반으로 합니다. 화면의 요소들을 해당 패턴에 맞게 식별하세요. 팝업 창은 'Modal', 도움말 말풍선은 'Tooltip', 진행 상태 바는 'ProgressBar'로 인식하세요.
날짜 선택기는 'DatePicker'로 인식하세요. 또한 각 컴포넌트별로 고유한 'component_id'를 부여하고, 작동해야 하는 세부 기능(Event)을 'event_description'에 구체적으로 작성하세요.
추가로, 식별된 컴포넌트들을 바탕으로 React(JSX) 함수형 컴포넌트 코드를 'generated_html' 필드에 작성하세요. (class 대신 className을 사용하고, Ant Design 컴포넌트를 import 하는 형태를 포함하세요.)

[🚨 JSON 작성 시 엄격한 주의사항 🚨]
1. 컴포넌트를 import 할 때 표준 'antd' 패키지 대신, 사내에서 배포되는 커스텀 패키지명(예: 'custom-antd')을 사용하세요.
2. HTML/JSX 태그(<, >)를 '&lt;' 나 '&gt;' 로 절대 이스케이프(Escape)하지 말고 실제 꺾쇠 괄호 형태 그대로 작성하세요.
3. 요소의 속성값(className, id 등)을 작성할 때는 반드시 홑따옴표(')만 사용하세요. (예: <div className='ant-btn'>) 쌍따옴표를 사용하면 JSON 파싱 에러가 발생합니다.
4. 'generated_html' 문자열 내부에서 실제 엔터키(줄바꿈)를 치지 말고, 반드시 `\\n` 문자를 사용하여 한 줄로 작성하세요.
5. 화면이 복잡하여 반복되는 데이터(리스트, 표 등)가 많은 경우, 전체를 다 쓰지 말고 상위 1~2개 대표 샘플만 작성하여 JSON 길이를 짧게 유지하세요.

반드시 아래의 JSON 형식에 맞추어 답변해야 하며, 다른 텍스트는 출력하지 마세요.
컴포넌트 타입('component_type')은 사내 HDS CSS에 정의된 클래스명(예: ant-btn-primary, ant-input 등)을 우선 적용하고, 매칭되는 것이 없다면 CSS 네이밍 규칙(kebab-case)에 따라 자유롭게 지어주세요.
위치(x_percent, y_percent)와 크기(width_percent, height_percent)는 0.0 에서 1.0 사이의 실수로 표현하세요.

[출력 JSON 예시]
{
  "screen_name": "로그인 화면",
  "screen_description": "사용자 인증을 위한 로그인 화면입니다.",
  "generated_html": "import React from 'react';\\nimport { Button, Input } from 'antd';\\nimport 'antd/dist/antd.css'; // Ant Design 라이브러리 CSS 적용\\n\\nconst LoginScreen = () => {\\n  return (\\n    <div className='login-container'>\\n      <Input id='input-id-01' placeholder='ID' />\\n      <Button id='btn-login-01' type='primary'>로그인</Button>\\n    </div>\\n  );\\n};\\n\\nexport default LoginScreen;",
  "components": [
    {
      "component_id": "btn-login-01",
      "component_type": "ant-btn-primary",
      "text": "로그인",
      "event_description": "클릭 시 메인 화면으로 이동",
      "x_percent": 0.15,
      "y_percent": 0.80,
      "width_percent": 0.70,
      "height_percent": 0.08
    }
  ]
}"""

STORYBOOK_REACT_PROMPT = """당신은 사내 디자인 시스템(HDS)을 완벽하게 이해하고 있는 수석 프론트엔드 개발자입니다.
사용자가 제공한 UI 화면을 분석하여, 사내 Storybook에 정의된 표준 컴포넌트로 분해하세요.
추가로, 식별된 컴포넌트들을 바탕으로 React(JSX) 함수형 컴포넌트 코드를 'generated_html' 필드에 작성하세요.

[🚨 Storybook 기반 React(JSX) 작성 규칙 🚨]
1. 일반적인 HTML 태그나 Ant Design 원본을 직접 쓰지 말고, 반드시 사내 Storybook에 정의된 커스텀 컴포넌트(예: <HdsButton>, <HdsInput>, <HdsDataGrid>)를 사용해야 합니다.
2. 컴포넌트를 import 할 때 표준 'antd' 패키지 대신, 사내에서 배포되는 커스텀 패키지명(예: '@hds/components' 등)을 사용하세요.
3. HTML/JSX 태그(<, >)를 '&lt;' 나 '&gt;' 로 절대 이스케이프(Escape)하지 말고 실제 꺾쇠 괄호 형태 그대로 작성하세요.
4. 요소의 속성값(className, id 등)을 작성할 때는 반드시 홑따옴표(')만 사용하세요. (쌍따옴표 사용 시 JSON 파싱 에러 발생)
5. 'generated_html' 문자열 내부에서 실제 엔터키(줄바꿈)를 치지 말고, 반드시 `\\n` 문자를 사용하여 한 줄로 작성하세요.
6. 화면이 복잡하여 반복되는 데이터(리스트, 표 등)가 많은 경우, 전체를 다 쓰지 말고 상위 1~2개 대표 샘플만 작성하여 JSON 길이를 짧게 유지하세요.

반드시 아래의 JSON 형식에 맞추어 답변해야 하며, 다른 텍스트는 출력하지 마세요.
컴포넌트 타입('component_type')은 사내 HDS CSS에 정의된 클래스명(예: ant-btn-primary, ag-header 등)을 우선 적용하고, 매칭되는 것이 없다면 CSS 네이밍 규칙(kebab-case)에 따라 지어주세요.
위치(x_percent, y_percent)와 크기(width_percent, height_percent)는 0.0 에서 1.0 사이의 실수로 표현하세요.

[출력 JSON 예시]
{
  "screen_name": "사내 표준 로그인",
  "screen_description": "Storybook 디자인 가이드가 적용된 로그인 화면입니다.",
  "generated_html": "import React from 'react';\\nimport { HdsButton, HdsInput } from '@hds/components';\\n\\nconst LoginScreen = () => {\\n  return (\\n    <div className='login-wrapper'>\\n      <HdsInput id='input-id-01' placeholder='사번을 입력하세요' />\\n      <HdsButton id='btn-login-01' variant='primary'>로그인</HdsButton>\\n    </div>\\n  );\\n};\\n\\nexport default LoginScreen;",
  "components": [
    {
      "component_id": "btn-login-01",
      "component_type": "ant-btn-primary",
      "text": "로그인",
      "event_description": "클릭 시 메인 화면으로 이동",
      "x_percent": 0.15,
      "y_percent": 0.80,
      "width_percent": 0.70,
      "height_percent": 0.08
    }
  ]
}"""

PROMPT_TEMPLATES = {
    "기본 HDS 프롬프트 (HTML 기반)": DEFAULT_PROMPT,
    "React(JSX) 코드 생성 프롬프트": REACT_PROMPT,
    "🌟 HDS Storybook 기반 React 생성": STORYBOOK_REACT_PROMPT
}

USER_PROMPT_BASE = """이 화면을 분석해서 TO-BE 컴포넌트로 분해해줘.

[🚨 환각(Hallucination) 방지 엄격한 규칙 🚨]
1. 이미지 내에 픽셀 단위로 명확하게 '보이는(Visible)' 요소만 추출해. 
2. 문맥상 존재할 것 같더라도(예: 잘린 버튼, 보이지 않는 스크롤바, 숨겨진 팝업 등) 화면에 직접 노출되지 않은 요소는 절대 임의로 상상해서 추가하지 마.
3. 화면 내에서 좌표(x_percent, y_percent)와 크기(width, height)를 명확히 측정할 수 있는 컴포넌트만 배열에 포함해.
4. **[누락 엄금]** 단순한 텍스트(설명글, 제목, 라벨), 작은 아이콘, 장식 요소, 배경 박스 등 화면에 존재하는 모든 요소를 절대 생략하지 말고 100% 모두 추출해. 화면의 어떤 정보도 빠져서는 안 돼.

[🚨 정확한 텍스트 인식(OCR) 가이드 🚨]
1. 버튼, 라벨, 툴팁, 표(Table) 데이터 등에 적힌 텍스트는 절대로 요약하거나 의역하지 마.
2. 화면에 보이는 **글자 그대로(한국어, 영어, 숫자, 특수기호, 띄어쓰기 포함)** 100% 정확하게 추출해. 작은 글씨나 흐린 글씨도 최대한 꼼꼼하게 읽어줘.

[🚨 테이블/그리드(Table/Grid) 데이터 추출 가이드 🚨]
1. 데이터 그리드나 표(Table) 영역은 내부의 개별 셀(Cell) 단위로 잘게 쪼개서 추출하지 마세요. (AI 토큰 낭비 및 누락의 원인이 됩니다.)
2. 반드시 표 전체 영역을 아우르는 **하나의 커다란 'DataGrid' (또는 'AgGrid') 컴포넌트로 크게 묶어서** 좌표(width, height)를 잡아주세요.
3. 표 안의 대표적인 컬럼명(Header)이나 핵심 데이터 일부만 콤마(,)로 연결해서 'text' 속성에 요약해 주면 됩니다.

[🚨 폼(Form) 요소 및 특수기호 인식 가이드 🚨]
1. 체크박스(☑, ☐)나 라디오 버튼(◉, ○) 같은 선택형 폼 요소의 특수기호를 주의 깊게 관찰해. 텍스트 옆에 붙어있는 작은 기호도 절대 놓치지 마.
2. 체크된 상태와 해제된 상태를 명확히 구분하여 'component_type'이나 속성에 반영해 (예: ant-checkbox-checked, ant-radio 등).
3. 토글 스위치나 작은 상태 표시 아이콘(돋보기, 달력 등)들도 무시하지 말고 알맞은 컴포넌트로 추출해.

반드시 실제 100% 눈에 보이는 요소만 추출해서 JSON으로 응답해."""

USER_PROMPT_REVISION = """이 화면을 분석해서 TO-BE 컴포넌트로 분해해줘. 반드시 JSON으로만 응답해.

[이전 분석 결과 (JSON)]
{previous_json}

[수정 요청사항]
{feedback}

위 수정 요청사항을 반드시 반영하여 기존 컴포넌트 구성을 수정하고, JSON을 다시 작성해줘.
단, 수정 요청사항과 무관한 다른 컴포넌트들의 위치나 속성, 텍스트는 절대 변경하지 말고 이전 상태를 그대로 유지해야 해!"""

def get_component_registry():
    """외부 JSON 파일(components_registry.json)에서 컴포넌트 프론트엔드 명세와 PPT 스타일을 통합 관리합니다."""
    file_path = "components_registry.json"
    default_registry = {
        "ant-btn-primary": {
            "guide": "<button className='ant-btn ant-btn-primary'> 버튼입니다.",
            "ppt_style": {"shape": "ROUNDED_RECTANGLE", "bg": [230, 0, 18], "line": [230, 0, 18], "text": [255, 255, 255], "size": 12, "bold": True},
            "locked": False
        },
        "ant-input": {
            "guide": "<input className='ant-input' placeholder='' maxLength={50} /> 텍스트 입력창입니다.",
            "ppt_style": {"shape": "RECTANGLE", "bg": [255, 255, 255], "line": [180, 180, 180], "text": [150, 150, 150], "size": 12, "bold": False}
        },
        "Default": {
            "guide": "",
            "ppt_style": {"shape": "RECTANGLE", "bg": [245, 245, 255], "line": [150, 150, 200], "text": [100, 100, 150], "size": 12, "bold": False}
        }
    }
    
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"components_registry.json 파일을 읽는 중 문법 오류가 발생했습니다: {e}")
            return default_registry
    else:
        # 파일이 없으면 초기 샘플 JSON 파일을 자동 생성합니다.
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(default_registry, f, ensure_ascii=False, indent=4)
        except Exception as e:
            logger.error(f"components_registry.json 샘플 파일 자동 생성 실패: {e}")
        return default_registry