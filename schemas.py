from pydantic import BaseModel, Field
from typing import List

class UIComponent(BaseModel):
    component_id: str = Field(default="", description="컴포넌트의 고유 ID (예: btn-login-01, input-email-01)")
    component_type: str = Field(description="TO-BE 컴포넌트 타입 (예: PrimaryButton, TextInput, TextLabel, ImagePlaceholder, Dropdown, Checkbox, AgGrid, AgGridToolbar, AgGridPagination, Modal, ToggleSwitch, RadioButton, Tooltip, ProgressBar)")
    text: str = Field(description="컴포넌트 내부에 들어갈 텍스트 (예: '로그인', '아이디를 입력하세요')")
    event_description: str = Field(default="", description="컴포넌트 클릭 등 이벤트 발생 시 동작할 세부 기능 설명")
    x_percent: float = Field(description="화면 좌측 상단 기준 X 좌표 비율 (0.0 ~ 1.0)")
    y_percent: float = Field(description="화면 좌측 상단 기준 Y 좌표 비율 (0.0 ~ 1.0)")
    width_percent: float = Field(description="요소의 너비 비율 (0.0 ~ 1.0)")
    height_percent: float = Field(description="요소의 높이 비율 (0.0 ~ 1.0)")

class ScreenAnalysisResult(BaseModel):
    screen_name: str = Field(description="분석된 화면의 이름 (예: 로그인 화면)")
    screen_description: str = Field(description="해당 화면의 주요 기능, 목적, 정책 등에 대한 상세 설명")
    generated_html: str = Field(default="", description="Ant Design 클래스명을 사용한 HTML DOM 구조 코드")
    components: List[UIComponent] = Field(description="화면에서 추출된 TO-BE UI 컴포넌트 목록")