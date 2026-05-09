import streamlit as st
from PIL import Image, ImageGrab
import io
import os
import re
import time
from prompts import PROMPT_TEMPLATES
from config import APP_TITLE, HCP_API_URL, HCP_TEXT_MODEL
from local_llm_service import HCPQwenService
from ppt_service import create_editable_ppt

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
st.markdown(f"AS-IS 화면 캡쳐본을 업로드하면, 내부망 HCP API({HCP_TEXT_MODEL})가 분석하여 **수정 가능한 PPT**로 자동 변환합니다.")

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
                        img = img.convert("RGB")
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
        st.image(image, caption=f"업로드된 AS-IS 화면 ({image_name})", use_container_width=True)
        
        with st.expander("⚙️ 고급 설정 (시스템 프롬프트 편집)"):
            st.markdown("LLM에 전달할 시스템 프롬프트를 선택하거나 직접 수정할 수 있습니다.")
            selected_template = st.selectbox("프롬프트 템플릿 선택", list(PROMPT_TEMPLATES.keys()))
            custom_prompt = st.text_area("시스템 프롬프트 내용", value=PROMPT_TEMPLATES[selected_template], height=400)

# 공통 PPT 생성 함수 (버튼 및 채팅창에서 호출)
def generate_and_render_ppt(img_bytes, prompt_text, prev_json, feedback_msg):
    with st.spinner(f"HCP API({HCP_TEXT_MODEL})를 통해 요청사항을 반영하여 PPT를 그리는 중입니다..."):
        try:
            llm_service = HCPQwenService(base_url=HCP_API_URL)
            analysis_result = llm_service.analyze_asis_image_local(
                img_bytes,
                custom_system_prompt=prompt_text,
                previous_json=prev_json,
                feedback=feedback_msg
            )
            
            ppt_stream = io.BytesIO()
            create_editable_ppt(analysis_result, ppt_stream)
            
            html_content = f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <title>{analysis_result.screen_name}</title>
    <link rel="stylesheet" href="./hds.css">
</head>
<body style="padding: 20px;">
    {analysis_result.generated_html}
</body>
</html>"""
            json_content = analysis_result.model_dump_json(indent=2)
            
            st.session_state["generated_data"] = {
                "ppt": ppt_stream.getvalue(),
                "html_str": html_content,
                "json_str": json_content
            }
            st.session_state["last_json"] = json_content
            st.success("🎉 성공적으로 생성되었습니다!")
        except Exception as e:
            st.error(f"처리 중 오류가 발생했습니다: {e}")

with col2:
    st.subheader("2. TO-BE PPT 결과 확인")
    if image_bytes is not None:
        # 최초 생성이 안 된 경우에만 큰 버튼 표시
        if not st.session_state.get("generated_data"):
            if st.button("🚀 PPT 생성 시작", use_container_width=True):
                st.session_state["generated_data"] = None
                generate_and_render_ppt(image_bytes, custom_prompt, None, None)
                
        # 결과 렌더링
        if st.session_state.get("generated_data"):
            data = st.session_state["generated_data"]
            try:
                css_content = ""
                if os.path.exists("hds.css"):
                    with open("hds.css", "r", encoding="utf-8") as f:
                        css_content = f.read()
                
                html_for_preview = re.sub(
                    r'<link\s+rel=["\']stylesheet["\']\s+href=["\']\./hds\.css["\']\s*/?>',
                    f"<style>\n{css_content}\n</style>",
                    data["html_str"],
                    flags=re.IGNORECASE
                )
                
                st.subheader("👀 HDS UI 화면 미리보기")
                st.components.v1.html(html_for_preview, height=450, scrolling=True)
                
                st.subheader("💻 생성된 HTML 코드")
                st.code(data["html_str"], language="html")
                
                st.subheader("📥 개별 파일 다운로드")
                col_dl1, col_dl2, col_dl3, col_dl4 = st.columns(4)
                
                col_dl1.download_button(label="📊 PPT 다운로드", data=data["ppt"], file_name=f"UI_정의서_{image_name}.pptx", mime="application/vnd.openxmlformats-officedocument.presentationml.presentation", use_container_width=True)
                col_dl2.download_button(label="🌐 HTML 다운로드", data=data["html_str"], file_name=f"index_{image_name}.html", mime="text/html", use_container_width=True)
                if css_content:
                    col_dl3.download_button(label="🎨 CSS 다운로드", data=css_content, file_name="hds.css", mime="text/css", use_container_width=True)
                col_dl4.download_button(label="📝 JSON 다운로드", data=data["json_str"], file_name=f"result_{image_name}.json", mime="application/json", use_container_width=True)
            except Exception as e:
                st.warning(f"결과 파일을 처리하는 중 오류가 발생했습니다: {e}")
    else:
        st.info("먼저 좌측에 이미지를 업로드해주세요.")

# 3. 하단 고정 채팅창 (피드백 반영용 Chat UI)
feedback = st.chat_input("🔄 PPT를 어떻게 그릴지 채팅으로 명령해 보세요! (예: 로그인 버튼을 파란색으로 변경해줘)")
if feedback:
    if image_bytes is None:
        st.error("앗! 먼저 좌측에 화면 이미지를 업로드(또는 Ctrl+V)해 주세요.")
    else:
        prompt_to_use = custom_prompt if 'custom_prompt' in locals() else PROMPT_TEMPLATES["기본 HDS 프롬프트 (HTML 기반)"]
        
        prev_json = st.session_state.get("last_json")
        if not prev_json:
            # 1차 생성 전에 처음부터 바로 채팅을 친 경우: 시스템 프롬프트에 요구사항 추가
            prompt_to_use += f"\n\n[특별 요청사항]\n{feedback}"
            generate_and_render_ppt(image_bytes, prompt_to_use, None, None)
        else:
            # 이미 1차 결과가 있는 경우: 피드백 루프로 반영
            generate_and_render_ppt(image_bytes, prompt_to_use, prev_json, feedback)
            
        st.rerun()