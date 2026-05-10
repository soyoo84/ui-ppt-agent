import re
from pydantic import BaseModel, Field, model_validator
from typing import List, Optional, Any

NUMBER_PATTERN = re.compile(r'-?\d+(\.\d+)?')

class UIComponent(BaseModel):
    component_id: Optional[str] = Field(default="", description="컴포넌트의 고유 ID (예: btn-login-01, input-email-01)")
    component_type: Optional[str] = Field(default="Box", description="TO-BE 컴포넌트 타입 (AI가 화면에 맞게 ant-btn-primary, ag-header 등 CSS 클래스 네이밍 규칙에 따라 명명)")
    text: Optional[str] = Field(default="", description="컴포넌트 내부에 들어갈 텍스트 (예: '로그인', '아이디를 입력하세요')")
    event_description: Optional[str] = Field(default="", description="컴포넌트 클릭 등 이벤트 발생 시 동작할 세부 기능 설명")
    x_percent: Optional[float] = Field(default=0.0, description="화면 좌측 상단 기준 X 좌표 비율 (0.0 ~ 1.0)")
    y_percent: Optional[float] = Field(default=0.0, description="화면 좌측 상단 기준 Y 좌표 비율 (0.0 ~ 1.0)")
    width_percent: Optional[float] = Field(default=0.1, description="요소의 너비 비율 (0.0 ~ 1.0)")
    height_percent: Optional[float] = Field(default=0.1, description="요소의 높이 비율 (0.0 ~ 1.0)")

    @model_validator(mode='before')
    @classmethod
    def preprocess_percentages(cls, data: Any):
        if isinstance(data, dict):
            # LLM이 실수 대신 "50%", "0.5px" 같은 문자열 단위를 붙여 반환했을 때 숫자만 추출 (ValidationError 사전 차단)
            for key in ['x_percent', 'y_percent', 'width_percent', 'height_percent']:
                val = data.get(key)
                if isinstance(val, str):
                    match = NUMBER_PATTERN.search(val)
                    if match:
                        data[key] = float(match.group())
                    else:
                        data[key] = None # 변환 실패 시 None으로 넘겨서 after 로직의 기본값이 적용되도록 함
        return data

    @model_validator(mode='after')
    def normalize_percentages(self):
        # LLM이 null을 반환할 경우 안전하게 빈 문자열로 치환
        if self.text is None: self.text = ""
        if self.event_description is None: self.event_description = ""
        if self.component_id is None: self.component_id = ""
        if self.component_type is None: self.component_type = "Box"
        
        # 숫자 필드 null 환각 방어
        if self.x_percent is None: self.x_percent = 0.0
        if self.y_percent is None: self.y_percent = 0.0
        if self.width_percent is None: self.width_percent = 0.1
        if self.height_percent is None: self.height_percent = 0.1
        
        # LLM이 0.15 대신 15처럼 1.0을 초과하는 백분율 정수로 응답할 경우 자동 보정 (환각 방어)
        if self.x_percent > 1.0: self.x_percent /= 100.0
        if self.y_percent > 1.0: self.y_percent /= 100.0
        if self.width_percent > 1.0: self.width_percent /= 100.0
        if self.height_percent > 1.0: self.height_percent /= 100.0
        
        # 좌표가 화면(0.0~1.0)을 완전히 벗어나는 극단적인 환각(음수 등) 방어 (Clamping)
        self.x_percent = max(0.0, min(1.0, self.x_percent))
        self.y_percent = max(0.0, min(1.0, self.y_percent))
        self.width_percent = max(0.0, min(1.0, self.width_percent))
        self.height_percent = max(0.0, min(1.0, self.height_percent))
        return self

class ScreenAnalysisResult(BaseModel):
    screen_name: Optional[str] = Field(default="UI 화면", description="분석된 화면의 이름 (예: 로그인 화면)")
    screen_description: Optional[str] = Field(default="", description="해당 화면의 주요 기능, 목적, 정책 등에 대한 상세 설명")
    generated_html: Optional[str] = Field(default="", description="Ant Design 클래스명을 사용한 HTML DOM 구조 코드")
    components: Optional[List[UIComponent]] = Field(default_factory=list, description="화면에서 추출된 TO-BE UI 컴포넌트 목록")

    @model_validator(mode='before')
    @classmethod
    def preprocess_screen_data(cls, data: Any):
        if isinstance(data, dict):
            comps = data.get('components')
            # LLM이 배열([])이 아닌 단일 객체({})로 컴포넌트를 1개만 반환했을 경우 강제로 배열로 감싸줌
            if isinstance(comps, dict):
                data['components'] = [comps]
        return data

    @model_validator(mode='after')
    def normalize_screen_data(self):
        # 루트 데이터 null 환각 방어
        if self.screen_name is None: self.screen_name = "UI 화면"
        if self.screen_description is None: self.screen_description = ""
        if self.generated_html is None: self.generated_html = ""
        if self.components is None: self.components = []
        return self