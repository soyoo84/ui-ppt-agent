import streamlit as st
from PIL import Image, ImageGrab, ImageOps
import io
import os
import re
import time
import csv
import html
import logging
from prompts import PROMPT_TEMPLATES
from config import APP_TITLE, HCP_API_URL, HCP_TEXT_MODEL, MASTER_TEMPLATE_DIR, TARGET_LAYOUT_NAME
from local_llm_service import HCPQwenService
from ppt_service import create_editable_ppt, get_layout_names

# --- [엔터프라이즈 로깅 시스템 설정] ---
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("logs/system.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def load_css_content(file_path="hds.css"):
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    return ""

# 상태 관리 (State): 파일이 바뀌면 이전 JSON 초기화
if "last_file_id" not in st.session_state:
    st.session_state["last_file_id"] = ""
if "last_json" not in st.session_state:
    st.session_state["last_json"] = None
if "generated_data" not in st.session_state:
    st.session_state["generated_data"] = None
if "clipboard_image_bytes" not in st.session_state:
    st.session_state["clipboard_image_bytes"] = None
if "clipboard_file_id" not in st.session_state:
    st.session_state["clipboard_file_id"] = None

def on_file_upload():
    """파일 업로더에 새로운 파일이 올라오면 기존 클립보드 이미지를 무시하도록 초기화합니다."""
    st.session_state["clipboard_image_bytes"] = None
    st.session_state["clipboard_file_id"] = None

st.set_page_config(page_title=APP_TITLE, layout="wide")

st.title(f"🎨 {APP_TITLE}")
st.markdown(f"AS-IS 화면 캡쳐본을 업로드하면, 내부망 HCP API({HCP_TEXT_MODEL})가 분석하여 디자이너와 퍼블리셔를 위한 **수정 가능한 UI 정의서(PPT)**로 자동 변환합니다.")

# 화면을 좌우 반으로 나눔
col1, col2 = st.columns(2)

with col1:
    st.subheader("1. AS-IS 이미지 업로드 및 설정")
    st.info("💡 **꿀팁:** 파일 업로드 박스 안쪽을 한 번 클릭하신 후 **`Ctrl+V`**를 누르면 채팅창처럼 이미지가 즉시 붙여넣기 됩니다!")
    
    uploaded_file = st.file_uploader(
        "📁 파일 선택, 또는 박스 클릭 후 붙여넣기(Ctrl+V)", 
        type=["png", "jpg", "jpeg"],
        on_change=on_file_upload
    )
    
    if st.button("📋 클립보드에서 직접 가져오기", use_container_width=True):
        try:
            img = ImageGrab.grabclipboard()
            if img is not None:
                if isinstance(img, list) and len(img) > 0:
                    img = Image.open(img[0])
                
                if hasattr(img, 'save'):
                    if img.mode in ("RGBA", "P"):
                        # 투명 배경(PNG) 복사 시 배경이 검게 변하는 현상을 방지하기 위해 흰색 배경을 덧댐
                        rgba_img = img.convert("RGBA")
                        background = Image.new("RGB", rgba_img.size, (255, 255, 255))
                        background.paste(rgba_img, mask=rgba_img.getchannel('A'))
                        img = background
                    img_byte_arr = io.BytesIO()
                    img.save(img_byte_arr, format='PNG')
                    st.session_state["clipboard_image_bytes"] = img_byte_arr.getvalue()
                    st.session_state["clipboard_file_id"] = f"clipboard_{time.time()}"
                else:
                    st.warning("클립보드에 유효한 이미지가 없습니다. 화면을 캡쳐(복사)한 후 다시 시도해주세요.")
            else:
                st.warning("클립보드에 이미지가 없습니다. 화면을 캡쳐(복사)한 후 다시 시도해주세요.")
        except Exception as e:
            st.error(f"클립보드를 읽는 중 오류가 발생했습니다: {e}")

    # 활성화된 이미지 소스 결정
    image_bytes = None
    file_id = None
    image_name = ""
    selected_template_path = None
    selected_layout_name = None
    
    if st.session_state["clipboard_image_bytes"] is not None:
        image_bytes = st.session_state["clipboard_image_bytes"]
        file_id = st.session_state["clipboard_file_id"]
        image_name = "clipboard_image.png"
    elif uploaded_file is not None:
        image_bytes = uploaded_file.getvalue()
        file_id = uploaded_file.file_id
        image_name = uploaded_file.name

    if image_bytes is not None:
        # 새 이미지가 업로드/복사되면 이전 결과 초기화
        if file_id != st.session_state["last_file_id"]:
            st.session_state["last_json"] = None
            st.session_state["generated_data"] = None
            st.session_state["last_file_id"] = file_id
            
        # 업로드된 이미지 미리보기
        image = Image.open(io.BytesIO(image_bytes))
        # 스마트폰 캡쳐본의 회전 방향을 올바르게 보정하여 미리보기
        image = ImageOps.exif_transpose(image)
        st.image(image, caption=f"업로드된 AS-IS 화면 ({image_name})", use_container_width=True)
        
        with st.expander("⚙️ 고급 설정 (시스템 프롬프트 편집)"):
            st.markdown("LLM에 전달할 시스템 프롬프트를 선택하거나 직접 수정할 수 있습니다.")
            selected_template = st.selectbox("프롬프트 템플릿 선택", list(PROMPT_TEMPLATES.keys()))
            custom_prompt = st.text_area("시스템 프롬프트 내용", value=PROMPT_TEMPLATES[selected_template], height=400)

            st.markdown("---")
            st.markdown("### 🎨 PPT 템플릿 설정")
            template_files = []
            # 임시 파일(~$...) 제외하고 pptx 파일만 목록화
            if os.path.exists(MASTER_TEMPLATE_DIR):
                template_files = [f for f in os.listdir(MASTER_TEMPLATE_DIR) if f.endswith(".pptx") and not f.startswith("~")]
            
            if template_files:
                selected_ppt_name = st.selectbox("적용할 PPT 템플릿", template_files)
                selected_template_path = os.path.join(MASTER_TEMPLATE_DIR, selected_ppt_name)
                
                layout_names = get_layout_names(selected_template_path)
                if layout_names:
                    default_idx = 0
                    for i, name in enumerate(layout_names):
                        if TARGET_LAYOUT_NAME and TARGET_LAYOUT_NAME == name:
                            default_idx = i
                            break
                        elif not TARGET_LAYOUT_NAME and ("빈" in name or "blank" in name.lower()):
                            default_idx = i
                    selected_layout_name = st.selectbox("슬라이드 레이아웃 선택", layout_names, index=default_idx)
                else:
                    selected_layout_name = TARGET_LAYOUT_NAME
            else:
                st.info(f"'{MASTER_TEMPLATE_DIR}' 폴더에 PPT 템플릿이 없습니다. 기본 슬라이드로 생성됩니다.")
                
            st.markdown("---")
            with st.expander("🛠️ 관리자 도구 (디자인 토큰 자동 추출)"):
                st.markdown("현재 선택된 **PPT 템플릿**이나 **hds.css 파일**을 스캔하여 `components_registry.json`에 자동으로 등록합니다.")
                
                col_admin1, col_admin2 = st.columns(2)
                with col_admin1:
                    if st.button("🪄 PPT 템플릿 스캔", use_container_width=True):
                        if selected_template_path:
                            from ppt_service import sync_design_tokens_from_ppt
                            with st.spinner("PPT 파일을 스캔하여 속성을 추출하는 중..."):
                                count, msg = sync_design_tokens_from_ppt(selected_template_path)
                                if count > 0:
                                    st.success(f"🎉 성공! {count}개의 도형 스타일이 JSON에 저장되었습니다.")
                                else:
                                    st.warning(f"추출된 토큰이 없습니다. (사유: {msg})")
                        else:
                            st.error("먼저 PPT 템플릿을 선택해 주세요.")
                            
                with col_admin2:
                    if st.button("🎨 CSS 클래스 스캔", use_container_width=True):
                        from ppt_service import sync_design_tokens_from_css
                        with st.spinner("CSS 파일을 스캔하여 속성을 추출하는 중..."):
                            count, msg = sync_design_tokens_from_css("hds.css")
                            if count > 0:
                                st.success(f"🎉 성공! {count}개의 CSS 클래스가 JSON에 저장되었습니다.")
                            else:
                                st.warning(f"추출된 CSS 스타일이 없습니다. (사유: {msg})")

# 공통 PPT 생성 함수 (버튼 및 채팅창에서 호출)
def generate_and_render_ppt(img_bytes, prompt_text, prev_json, feedback_msg, template_path=None, layout_name=None) -> bool:
    spinner_msg = "피드백을 반영하여 PPT를 다시 그리는 중입니다..." if prev_json else f"HCP API({HCP_TEXT_MODEL})가 이미지를 분석하고 PPT를 그리는 중입니다..."
    with st.spinner(spinner_msg):
        start_time = time.time()
        logger.info(f"=== PPT 생성 요청 시작 (레이아웃: {layout_name}) ===")
        
        try:
            llm_service = HCPQwenService(base_url=HCP_API_URL)
            analysis_result = llm_service.analyze_asis_image_local(
                img_bytes,
                custom_system_prompt=prompt_text,
                previous_json=prev_json,
                feedback=feedback_msg
            )
            
            ppt_stream = io.BytesIO()
            create_editable_ppt(analysis_result, ppt_stream, template_path, layout_name)
            
            # HTML 삽입 시 <, > 등의 기호가 태그로 인식되어 화면이 깨지는 현상 방지
            safe_screen_desc = html.escape(analysis_result.screen_description)
            screen_desc_br = safe_screen_desc.replace('\n', '<br>')
            
            desc_html = f"<h3 style='margin-top:0;'>📌 UI 화면 설명 및 퍼블리싱 정책</h3>"
            desc_html += f"<p>{screen_desc_br}</p>"
            desc_html += "<h4>[컴포넌트별 세부 기능]</h4><ul style='padding-left:20px;'>"
            for comp in analysis_result.components:
                if comp.event_description:
                    safe_id = f"[{html.escape(comp.component_id)}] " if getattr(comp, 'component_id', None) else ""
                    safe_title = html.escape(comp.text or comp.component_type)
                    safe_event = html.escape(comp.event_description)
                    desc_html += f"<li style='margin-bottom:8px;'><b>{safe_id}{safe_title}</b>: {safe_event}</li>"
            desc_html += "</ul>"

            html_content = f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <title>{analysis_result.screen_name}</title>
    <!-- Ant Design 기본 스타일 CDN (미리보기 렌더링용) -->
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/antd/4.24.14/antd.min.css">
    <link rel="stylesheet" href="./hds.css">
    <style>
        body {{ background-color: #f0f2f5; padding: 20px; font-family: 'Malgun Gothic', 'Apple SD Gothic Neo', sans-serif; }}
        .preview-container {{ display: flex; gap: 20px; align-items: flex-start; }}
        .ui-area {{ flex: 7; background: #fff; padding: 20px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.05); min-height: 400px; overflow-x: auto; }}
        .desc-area {{ flex: 3; background: #fff; padding: 20px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.05); color: #333; }}
        .desc-area h3, .desc-area h4 {{ color: #1f1f1f; }}
        .desc-area p, .desc-area li {{ color: #555; font-size: 14px; line-height: 1.5; }}
    </style>
</head>
<body>
    <div class="preview-container">
        <div class="ui-area">
            {analysis_result.generated_html}
        </div>
        <div class="desc-area">
            {desc_html}
        </div>
    </div>
</body>
</html>"""
            json_content = analysis_result.model_dump_json(indent=2)
            
            st.session_state["generated_data"] = {
                "ppt": ppt_stream.getvalue(),
                "html_str": html_content,
                "raw_html": analysis_result.generated_html,
                "json_str": json_content,
                "components": analysis_result.components,
                "screen_name": analysis_result.screen_name,
                "is_react": "React" in prompt_text
            }
            st.session_state["last_json"] = json_content
            elapsed = round(time.time() - start_time, 1)
            logger.info(f"=== PPT 생성 성공 (소요시간: {elapsed}초) ===")
            st.toast("🎉 PPT 생성이 완료되었습니다!", icon="✅")
            return True
        except Exception as e:
            logger.error(f"PPT 생성 중 오류 발생: {e}", exc_info=True)
            st.error(f"처리 중 오류가 발생했습니다: {e}")
            return False

with col2:
    st.subheader("2. TO-BE UI 정의서 결과 확인")
    if image_bytes is not None:
        # 최초 생성이 안 된 경우에만 큰 버튼 표시
        if not st.session_state.get("generated_data"):
            if st.button("🚀 PPT 생성 시작", use_container_width=True):
                st.session_state["generated_data"] = None
                generate_and_render_ppt(image_bytes, custom_prompt, None, None, selected_template_path, selected_layout_name)
        else:
            # 이미 생성된 후, 좌측의 고급 설정(프롬프트, 템플릿)을 변경하고 다시 생성하고 싶을 때를 위한 버튼
            if st.button("🔄 새로운 설정으로 다시 생성", use_container_width=True):
                generate_and_render_ppt(image_bytes, custom_prompt, None, None, selected_template_path, selected_layout_name)
                
        # 결과 렌더링
        if st.session_state.get("generated_data"):
            data = st.session_state["generated_data"]
            try:
                css_content = load_css_content("hds.css")
                
                # [상태 동기화 방어] 생성 시점의 프롬프트 상태(is_react)를 기준으로 UI를 렌더링 (드롭다운 변경 시 UI 깨짐 방지)
                is_react_mode = data.get("is_react", "React" in custom_prompt)
                
                if is_react_mode:
                    html_for_preview = """<div style="display:flex; justify-content:center; align-items:center; height:400px; background:#f8f9fa; border-radius:8px; color:#555; text-align:center; font-family:sans-serif;">
                        <h3>⚛️ React(JSX) 코드는 브라우저에서 직접 렌더링할 수 없습니다.<br><br>상단의 <b>💻 React 코드</b> 탭과 다운로드 파일을 확인해 주세요.</h3>
                    </div>"""
                else:
                    html_for_preview = re.sub(
                        r'<link\s+rel=["\']stylesheet["\']\s+href=["\']\./hds\.css["\']\s*/?>',
                        lambda m: f"<style>\n{css_content}\n</style>",
                        data["html_str"],
                        flags=re.IGNORECASE
                    )
                
                code_title = "💻 React 코드" if is_react_mode else "💻 HTML 코드"
                code_lang = "jsx" if is_react_mode else "html"
                
                # CSS 존재 여부에 따라 탭을 동적으로 생성 (빈 탭 방지)
                tab_names = ["👀 화면 미리보기", code_title, "📝 JSON 데이터"]
                if css_content: tab_names.append("🎨 HDS CSS")
                tabs = st.tabs(tab_names)
                
                with tabs[0]:
                    st.components.v1.html(html_for_preview, height=450, scrolling=True)
                with tabs[1]:
                    st.code(data.get("raw_html", data["html_str"]), language=code_lang)
                with tabs[2]:
                    st.code(data["json_str"], language="json")
                if css_content:
                    with tabs[3]:
                        st.code(css_content, language="css")
                
                st.markdown("---")
                st.subheader("📥 개별 파일 다운로드")
                
                # [UX 최적화] AI가 지어준 화면 이름(screen_name)을 파일명으로 활용하여 직관성 향상
                safe_screen_name = re.sub(r'[\\/*?:"<>|]', "_", data.get("screen_name", "UI_Screen"))
                base_name = safe_screen_name.replace(" ", "_")
                
                # CSV 데이터 생성 (엑셀 호환을 위해 utf-8-sig 인코딩)
                csv_buffer = io.StringIO(newline='')
                csv_writer = csv.writer(csv_buffer)
                csv_writer.writerow(["ID", "타입", "텍스트", "이벤트/기능 설명", "X(%)", "Y(%)", "너비(%)", "높이(%)"])
                for c in data["components"]:
                    csv_writer.writerow([
                        c.component_id, c.component_type, c.text, c.event_description,
                        round(c.x_percent, 3), round(c.y_percent, 3), round(c.width_percent, 3), round(c.height_percent, 3)
                    ])
                csv_bytes = csv_buffer.getvalue().encode('utf-8-sig')

                # CSS 존재 여부에 따라 다운로드 버튼을 동적으로 꽉 차게 배치 (중간 빈 공백 제거)
                dl_buttons = [
                    ("📊 PPT 다운로드", data["ppt"], f"UI_정의서_{base_name}.pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation")
                ]
                if is_react_mode:
                    dl_buttons.append(("⚛️ React(JSX) 다운로드", data.get("raw_html", ""), f"{base_name}.jsx", "text/plain"))
                else:
                    dl_buttons.append(("🌐 HTML 다운로드", data["html_str"], f"index_{base_name}.html", "text/html"))
                if css_content:
                    dl_buttons.append(("🎨 CSS 다운로드", css_content, "hds.css", "text/css"))
                dl_buttons.extend([
                    ("📝 JSON 다운로드", data["json_str"], f"result_{base_name}.json", "application/json"),
                    ("📈 CSV 다운로드", csv_bytes, f"components_{base_name}.csv", "text/csv")
                ])
                
                cols = st.columns(len(dl_buttons))
                for col, (lbl, bdata, fname, mime) in zip(cols, dl_buttons):
                    col.download_button(label=lbl, data=bdata, file_name=fname, mime=mime, use_container_width=True)
            except Exception as e:
                st.warning(f"결과 파일을 처리하는 중 오류가 발생했습니다: {e}")
    else:
        st.info("먼저 좌측에 이미지를 업로드해주세요.")

# 3. 사이드바 채팅창 (피드백 반영용 Chat UI)
with st.sidebar:
    st.header("💬 AI 피드백 채팅")
    st.info("결과물에 수정이 필요하신가요?\n아래 채팅창에 원하는 변경사항을 입력하시면 즉시 반영됩니다.")
    feedback = st.chat_input("예: 로그인 버튼을 파란색으로 변경해줘")

if feedback:
    if image_bytes is None:
        st.error("앗! 먼저 좌측에 화면 이미지를 업로드(또는 Ctrl+V)해 주세요.")
    else:
        prompt_to_use = custom_prompt if 'custom_prompt' in locals() else PROMPT_TEMPLATES["기본 HDS 프롬프트 (HTML 기반)"]
        
        prev_json = st.session_state.get("last_json")
        if not prev_json:
            # 1차 생성 전에 처음부터 바로 채팅을 친 경우: 시스템 프롬프트에 요구사항 추가
            prompt_to_use += f"\n\n[특별 요청사항]\n{feedback}"
            success = generate_and_render_ppt(image_bytes, prompt_to_use, None, None, selected_template_path, selected_layout_name)
        else:
            # 이미 1차 결과가 있는 경우: 피드백 루프로 반영
            success = generate_and_render_ppt(image_bytes, prompt_to_use, prev_json, feedback, selected_template_path, selected_layout_name)
            
        if success:
            st.rerun()