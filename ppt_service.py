import os
import datetime
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from schemas import ScreenAnalysisResult
from config import (
    MASTER_PPT_PATH, TARGET_LAYOUT_NAME, PPT_SLIDE_WIDTH, PPT_SLIDE_HEIGHT,
    PPT_UI_SCALE, PPT_ALIGN_THRESHOLD, PPT_CONTAINER_PADDING, HDS_PRIMARY_COLOR
)

def create_editable_ppt(analysis_result: ScreenAnalysisResult, output_file):
    """
    분석된 JSON 데이터를 바탕으로 수정 가능한 PPT 파일을 생성합니다.
    """
    # 사내 템플릿 로드 (파일이 존재하지 않으면 기본 빈 프레젠테이션 생성)
    template_path = MASTER_PPT_PATH
    if template_path and os.path.exists(template_path):
        prs = Presentation(template_path)
    else:
        prs = Presentation()
        # 16:9 와이드스크린 비율 설정
        prs.slide_width = Inches(PPT_SLIDE_WIDTH)
        prs.slide_height = Inches(PPT_SLIDE_HEIGHT)
    
    # --- [레이아웃 이름으로 템플릿 찾기] ---
    # 사용하는 템플릿의 슬라이드 마스터에 있는 실제 레이아웃 이름을 입력하세요.
    target_layout_name = TARGET_LAYOUT_NAME 
    slide_layout = None
    
    if target_layout_name:
        for layout in prs.slide_layouts:
            if layout.name == target_layout_name:
                slide_layout = layout
                break
            
    # 설정한 이름의 레이아웃을 찾지 못한 경우 (Fallback)
    if slide_layout is None:
        slide_layout = prs.slide_layouts[5] if len(prs.slide_layouts) > 5 else prs.slide_layouts[0]
    
    slide = prs.slides.add_slide(slide_layout)
    
    # 제목 설정
    if slide.shapes.title:
        slide.shapes.title.text = analysis_result.screen_name
    
    # 슬라이드 전체 너비/높이 (원본)
    actual_slide_width = prs.slide_width
    actual_slide_height = prs.slide_height
    
    # 우측에 설명 박스를 넣기 위해 UI 렌더링 영역을 65%로 축소
    ui_scale = PPT_UI_SCALE
    slide_width = actual_slide_width * ui_scale
    slide_height = actual_slide_height * ui_scale
    
    # UI 영역 위치 오프셋 (좌측 여백 5%, 세로 중앙 정렬)
    offset_left = int(actual_slide_width * 0.05)
    offset_top = int((actual_slide_height - slide_height) / 2)
    
    # --- [정렬 보정 알고리즘 추가 시작] ---
    # 설정된 오차 범위 이내인 요소들을 같은 그룹(행)으로 묶습니다.
    y_threshold = PPT_ALIGN_THRESHOLD 
    sorted_comps = sorted(analysis_result.components, key=lambda c: c.y_percent)
    
    if sorted_comps:
        groups, current_group = [], [sorted_comps[0]]
        for comp in sorted_comps[1:]:
            if abs(comp.y_percent - current_group[0].y_percent) <= y_threshold:
                current_group.append(comp)
            else:
                groups.append(current_group)
                current_group = [comp]
        groups.append(current_group)
        
        # 같은 행에 있는 요소들의 Y 좌표와 높이를 그룹의 평균값으로 통일하여 수평 정렬을 맞춥니다.
        for group in groups:
            avg_y = sum(c.y_percent for c in group) / len(group)
            avg_h = sum(c.height_percent for c in group) / len(group)
            for c in group:
                c.y_percent = avg_y
                c.height_percent = avg_h
    # --- [정렬 보정 알고리즘 추가 끝] ---
    
    # --- [수직 정렬(Column Alignment) 보정 알고리즘 추가 시작] ---
    # 설정된 오차 범위 이내인 요소들을 같은 그룹(열)으로 묶습니다.
    x_threshold = PPT_ALIGN_THRESHOLD 
    sorted_comps_x = sorted(analysis_result.components, key=lambda c: c.x_percent)
    
    if sorted_comps_x:
        groups_x, current_group_x = [], [sorted_comps_x[0]]
        for comp in sorted_comps_x[1:]:
            if abs(comp.x_percent - current_group_x[0].x_percent) <= x_threshold:
                current_group_x.append(comp)
            else:
                groups_x.append(current_group_x)
                current_group_x = [comp]
        groups_x.append(current_group_x)
        
        # 같은 열에 있는 요소들의 X 좌표를 그룹의 평균값으로 통일하여 왼쪽 맞춤을 합니다.
        for group in groups_x:
            avg_x = sum(c.x_percent for c in group) / len(group)
            for c in group:
                c.x_percent = avg_x
    # --- [수직 정렬(Column Alignment) 보정 알고리즘 추가 끝] ---

    # --- [시각적 컨테이너(배경 화면 박스) 추가 시작] ---
    if analysis_result.components:
        min_x = min(c.x_percent for c in analysis_result.components)
        min_y = min(c.y_percent for c in analysis_result.components)
        max_x = max(c.x_percent + c.width_percent for c in analysis_result.components)
        max_y = max(c.y_percent + c.height_percent for c in analysis_result.components)
        
        # 상하좌우 여백(Padding) 3% 추가
        pad = PPT_CONTAINER_PADDING
        bg_left = int(slide_width * max(0, min_x - pad)) + offset_left
        bg_top = int(slide_height * max(0, min_y - pad)) + offset_top
        bg_width = int(slide_width * min(1.0, (max_x - min_x + pad * 2)))
        bg_height = int(slide_height * min(1.0, (max_y - min_y + pad * 2)))
        
        # 둥근 사각형 배경 패널 그리기 (도형을 먼저 그리면 자동으로 맨 밑(Z-index 최하단)에 깔립니다)
        bg_shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, bg_left, bg_top, bg_width, bg_height)
        bg_shape.fill.solid()
        bg_shape.fill.fore_color.rgb = RGBColor(248, 249, 250) # 옅은 배경색 (Light Gray)
        bg_shape.line.color.rgb = RGBColor(220, 220, 220)      # 옅은 테두리선
    # --- [시각적 컨테이너(배경 화면 박스) 추가 끝] ---

    # --- [Z-Index 보정 알고리즘 추가] ---
    # 모달, 툴팁, 드롭다운 등 화면에 떠 있는(Floating) 요소들이 다른 도형에 가려지지 않도록 가장 마지막(최상단)에 그립니다.
    floating_types = {"Modal", "Tooltip", "Dropdown"}
    regular_comps = [c for c in analysis_result.components if c.component_type not in floating_types]
    floating_comps = [c for c in analysis_result.components if c.component_type in floating_types]
    
    # 반환된 컴포넌트들을 순회하며 그리기 (일반 도형 먼저 -> 플로팅 도형 나중에)
    for comp in regular_comps + floating_comps:
        # 비율(0.0~1.0)을 안전하게 클램핑(Clamping)하여 PPT 영역을 벗어나지 않도록 방어
        safe_x = max(0.0, min(1.0, comp.x_percent))
        safe_y = max(0.0, min(1.0, comp.y_percent))
        safe_w = max(0.0, min(1.0 - safe_x, comp.width_percent)) # 우측 화면 밖으로 나가는 것 방지
        safe_h = max(0.0, min(1.0 - safe_y, comp.height_percent)) # 하단 화면 밖으로 나가는 것 방지
        
        # PPT의 실제 길이(EMU 단위)로 변환 (오프셋 반영)
        left = int(slide_width * safe_x) + offset_left
        top = int(slide_height * safe_y) + offset_top
        width = int(slide_width * safe_w)
        height = int(slide_height * safe_h)
        
        # 최소 크기 지정 (오류값 보정)
        width = max(int(Inches(0.5)), width)
        height = max(int(Inches(0.3)), height)

        if comp.component_type == "PrimaryButton":
            # 둥근 모서리 사각형 (MSO_SHAPE.ROUNDED_RECTANGLE = 5)
            shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, top, width, height)
            shape.fill.solid()
            shape.fill.fore_color.rgb = RGBColor(*HDS_PRIMARY_COLOR) # 환경설정 메인 컬러 적용
            shape.line.color.rgb = RGBColor(*HDS_PRIMARY_COLOR)
            
            tf = shape.text_frame
            tf.text = comp.text if comp.text else "버튼"
            tf.paragraphs[0].alignment = PP_ALIGN.CENTER
            tf.paragraphs[0].font.color.rgb = RGBColor(255, 255, 255)
            tf.paragraphs[0].font.bold = True
            tf.paragraphs[0].font.size = Pt(14)
            
        elif comp.component_type == "Tooltip":
            # Ant Design 스타일의 Tooltip (어두운 배경의 말풍선 형태)
            shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, top, width, height)
            shape.fill.solid()
            shape.fill.fore_color.rgb = RGBColor(60, 60, 60) # 진한 회색/검정색 배경
            shape.line.color.rgb = RGBColor(60, 60, 60)
            
            tf = shape.text_frame
            tf.text = comp.text if comp.text else "도움말 툴팁"
            tf.word_wrap = True
            tf.paragraphs[0].alignment = PP_ALIGN.CENTER
            tf.paragraphs[0].font.color.rgb = RGBColor(255, 255, 255)
            tf.paragraphs[0].font.size = Pt(10)
            
        elif comp.component_type == "ProgressBar":
            # Ant Design 스타일의 Progress Bar (배경 트랙 + 메인 컬러 채움)
            bg_shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, top, width, height)
            bg_shape.fill.solid()
            bg_shape.fill.fore_color.rgb = RGBColor(240, 240, 240) # 옅은 배경 트랙
            bg_shape.line.color.rgb = RGBColor(230, 230, 230)
            
            # 시각적 기획을 위해 50% 정도 채워진 상태를 기본으로 덧그림
            fg_shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, top, int(width * 0.5), height)
            fg_shape.fill.solid()
            fg_shape.fill.fore_color.rgb = RGBColor(*HDS_PRIMARY_COLOR)
            fg_shape.line.color.rgb = RGBColor(*HDS_PRIMARY_COLOR)
            
        elif comp.component_type == "TextInput":
            # 일반 사각형 테두리 (MSO_SHAPE.RECTANGLE = 1)
            shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, left, top, width, height)
            shape.fill.solid()
            shape.fill.fore_color.rgb = RGBColor(255, 255, 255)
            shape.line.color.rgb = RGBColor(180, 180, 180) # 회색 테두리
            
            tf = shape.text_frame
            safe_text = comp.text if comp.text else ""
            tf.text = f" {safe_text}" # 좌측 여백을 위해 공백 추가
            tf.paragraphs[0].alignment = PP_ALIGN.LEFT
            tf.paragraphs[0].font.color.rgb = RGBColor(150, 150, 150)
            
        elif comp.component_type == "Dropdown":
            # Ant Design 스타일의 Select/Dropdown (우측에 ▼ 화살표 추가)
            shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, left, top, width, height)
            shape.fill.solid()
            shape.fill.fore_color.rgb = RGBColor(255, 255, 255)
            shape.line.color.rgb = RGBColor(200, 200, 200)
            
            tf = shape.text_frame
            safe_text = comp.text if comp.text else "선택"
            tf.text = f" {safe_text}   ▼"
            tf.paragraphs[0].alignment = PP_ALIGN.LEFT
            tf.paragraphs[0].font.color.rgb = RGBColor(80, 80, 80)
            tf.paragraphs[0].font.size = Pt(12)
            
        elif comp.component_type == "AgGrid":
            # AG Grid 스타일의 데이터 그리드
            # 3행 3열의 기본 표를 생성하여 AG Grid를 시각적으로 표현
            table_shape = slide.shapes.add_table(3, 3, left, top, width, height)
            table = table_shape.table
            
            # 헤더(첫 행) 및 데이터 행 스타일링
            for r_idx in range(3):
                for c_idx in range(3):
                    cell = table.cell(r_idx, c_idx)
                    if r_idx == 0:
                        cell.text = f"AG Col {c_idx + 1}"
                        cell.fill.solid()
                        cell.fill.fore_color.rgb = RGBColor(248, 248, 248) # AG Grid 기본 헤더 배경색
                        cell.text_frame.paragraphs[0].font.bold = True
                    else:
                        cell.text = comp.text if c_idx == 0 and r_idx == 1 else "Data"
                    
                    cell.text_frame.paragraphs[0].font.size = Pt(10)
                    cell.text_frame.paragraphs[0].font.color.rgb = RGBColor(80, 80, 80)
                    cell.vertical_anchor = MSO_ANCHOR.MIDDLE
                    
        elif comp.component_type == "AgGridToolbar":
            # AG Grid 상단 툴바 (우측 정렬된 액션 버튼이나 검색창 표현)
            txBox = slide.shapes.add_textbox(left, top, width, height)
            tf = txBox.text_frame
            # LLM이 추출한 텍스트가 있으면 넣고, 없으면 기본 툴바 텍스트를 넣습니다.
            tf.text = comp.text if comp.text else "🔍 검색   ⬇ 엑셀 다운로드"
            tf.paragraphs[0].alignment = PP_ALIGN.RIGHT
            tf.paragraphs[0].font.color.rgb = RGBColor(80, 80, 80)
            tf.paragraphs[0].font.size = Pt(11)
            tf.paragraphs[0].font.bold = True
            
        elif comp.component_type == "AgGridPagination":
            # AG Grid 하단 페이징 영역 (가운데 정렬된 페이지 번호)
            shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, left, top, width, height)
            shape.fill.solid()
            shape.fill.fore_color.rgb = RGBColor(255, 255, 255)
            shape.line.color.rgb = RGBColor(220, 220, 220)
            
            tf = shape.text_frame
            tf.text = "〈   1   2   3   4   5   〉"
            tf.paragraphs[0].alignment = PP_ALIGN.CENTER
            tf.paragraphs[0].font.color.rgb = RGBColor(100, 100, 100)
            tf.paragraphs[0].font.size = Pt(11)
            
        elif comp.component_type == "Checkbox":
            # Checkbox: 텍스트 박스를 그리고 좌측에 체크박스 특수문자(☑ 또는 ☐) 삽입
            txBox = slide.shapes.add_textbox(left, top, width, height)
            tf = txBox.text_frame
            # Ant Design의 체크 안 된 상태의 기본 박스 모양 표현
            tf.text = f"☐ {comp.text}" 
            tf.paragraphs[0].alignment = PP_ALIGN.LEFT
            tf.paragraphs[0].font.color.rgb = RGBColor(50, 50, 50)
            tf.paragraphs[0].font.size = Pt(12)
            
        elif comp.component_type == "ToggleSwitch":
            # Ant Design 스타일의 Toggle Switch (활성화 상태 표현)
            shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, top, width, height) # 둥근 사각형
            shape.fill.solid()
            shape.fill.fore_color.rgb = RGBColor(24, 144, 255) # Ant Design 기본 파란색 (활성화)
            shape.line.color.rgb = RGBColor(24, 144, 255)
            
            tf = shape.text_frame
            tf.text = " O" # 스위치 손잡이(노브)를 텍스트로 단순 표현
            tf.paragraphs[0].alignment = PP_ALIGN.RIGHT
            tf.paragraphs[0].font.color.rgb = RGBColor(255, 255, 255)
            
        elif comp.component_type == "RadioButton":
            # Ant Design 스타일의 Radio Button (동그란 라디오 버튼 + 텍스트)
            txBox = slide.shapes.add_textbox(left, top, width, height)
            tf = txBox.text_frame
            safe_text = comp.text if comp.text else ""
            tf.text = f"◉ {safe_text}" # 선택된 라디오 버튼 기호
            tf.paragraphs[0].alignment = PP_ALIGN.LEFT
            tf.paragraphs[0].font.color.rgb = RGBColor(50, 50, 50)
            tf.paragraphs[0].font.size = Pt(12)
            
        elif comp.component_type == "Modal":
            # Ant Design 스타일의 모달(Modal) 창 (팝업 컨테이너)
            shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, left, top, width, height)
            shape.fill.solid()
            shape.fill.fore_color.rgb = RGBColor(255, 255, 255)
            shape.line.color.rgb = RGBColor(120, 120, 120) # 팝업 느낌을 주기 위한 진한 테두리
            
            tf = shape.text_frame
            tf.text = f"  {comp.text}" if comp.text else "  모달 타이틀"
            tf.word_wrap = True
            tf.paragraphs[0].alignment = PP_ALIGN.LEFT
            tf.paragraphs[0].font.color.rgb = RGBColor(30, 30, 30)
            tf.paragraphs[0].font.bold = True
            tf.paragraphs[0].font.size = Pt(14)

        elif comp.component_type == "TextLabel":
            # 배경이 없는 투명한 텍스트 박스
            txBox = slide.shapes.add_textbox(left, top, width, height)
            tf = txBox.text_frame
            tf.text = comp.text if comp.text else "텍스트"
            tf.word_wrap = True
            tf.paragraphs[0].font.color.rgb = RGBColor(30, 30, 30)
            tf.paragraphs[0].font.size = Pt(14)
            
        elif comp.component_type == "ImagePlaceholder":
            # 대각선이 교차하는 이미지 자리표시자 스타일 (MSO_SHAPE.RECTANGLE = 1)
            shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, left, top, width, height)
            shape.fill.solid()
            shape.fill.fore_color.rgb = RGBColor(240, 240, 240)
            shape.line.color.rgb = RGBColor(200, 200, 200)
            
            tf = shape.text_frame
            tf.text = "[ 이미지 영역 ]"
            tf.paragraphs[0].alignment = PP_ALIGN.CENTER
            tf.paragraphs[0].font.color.rgb = RGBColor(150, 150, 150)

    # --- [우측 화면 설명(Description) 영역 추가 시작] ---
    desc_left = int(actual_slide_width * 0.72)
    desc_top = offset_top
    desc_width = int(actual_slide_width * 0.25)
    desc_height = slide_height
    
    desc_shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, desc_left, desc_top, desc_width, desc_height)
    desc_shape.fill.solid()
    desc_shape.fill.fore_color.rgb = RGBColor(250, 250, 250) # 옅은 배경색
    desc_shape.line.color.rgb = RGBColor(200, 200, 200)
    
    tf_desc = desc_shape.text_frame
    tf_desc.word_wrap = True
    
    p_title = tf_desc.paragraphs[0]
    p_title.text = "📌 화면 설명 및 정책"
    p_title.font.bold = True
    p_title.font.size = Pt(14)
    p_title.font.color.rgb = RGBColor(30, 30, 30)
    
    p_content = tf_desc.add_paragraph()
    p_content.text = f"\n{analysis_result.screen_description}\n\n[컴포넌트별 세부 기능]"
    p_content.font.size = Pt(12)
    p_content.font.color.rgb = RGBColor(80, 80, 80)
    
    for comp in analysis_result.components:
        if comp.event_description:
            p_event = tf_desc.add_paragraph()
            id_prefix = f"[{comp.component_id}] " if hasattr(comp, 'component_id') and comp.component_id else ""
            p_event.text = f"• {id_prefix}{comp.text or comp.component_type}: {comp.event_description}"
            p_event.font.size = Pt(11)
            p_event.font.color.rgb = RGBColor(100, 100, 100)
    # --- [우측 화면 설명(Description) 영역 추가 끝] ---
    
    # --- [하단 날짜 및 페이지 번호 자동 삽입 시작] ---
    current_date = datetime.datetime.now().strftime("%Y-%m-%d")
    slide_number = len(prs.slides) # 현재 생성된 슬라이드의 순번
    
    footer_top = actual_slide_height - Inches(0.4) # 슬라이드 맨 아래에서 약간 위쪽
    
    # 좌측 하단: 오늘 날짜
    date_box = slide.shapes.add_textbox(Inches(0.5), footer_top, Inches(2), Inches(0.3))
    tf_date = date_box.text_frame
    tf_date.text = current_date
    tf_date.paragraphs[0].font.size = Pt(10)
    tf_date.paragraphs[0].font.color.rgb = RGBColor(150, 150, 150)
    
    # 우측 하단: 페이지 번호
    page_box = slide.shapes.add_textbox(actual_slide_width - Inches(2.5), footer_top, Inches(2), Inches(0.3))
    tf_page = page_box.text_frame
    tf_page.text = f"- {slide_number} -"
    tf_page.paragraphs[0].alignment = PP_ALIGN.RIGHT
    tf_page.paragraphs[0].font.size = Pt(10)
    tf_page.paragraphs[0].font.color.rgb = RGBColor(150, 150, 150)
    # --- [하단 날짜 및 페이지 번호 자동 삽입 끝] ---

    # 지정된 경로에 파일 저장
    prs.save(output_file)