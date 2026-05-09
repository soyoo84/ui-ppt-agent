import streamlit as st
from PIL import Image
import io
import os
import re
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

st.set_page_config(page_title=APP_TITLE, layout="wide")

st.title(f"🎨 {APP_TITLE}")
st.markdown(f"AS-IS 화면 캡쳐본을 업로드하면, 내부망 HCP API({HCP_TEXT_MODEL})가 분석하여 **수정 가능한 PPT**로 자동 변환합니다.")

# 화면을 좌우 반으로 나눔
col1, col2 = st.columns(2)

with col1:
    st.subheader("1. AS-IS 이미지 업로드 및 설정")
    uploaded_file = st.file_uploader("📁 이미지 파일을 선택하거나, 화면 캡쳐 후 여기를 클릭하고 붙여넣기(Ctrl+V) 하세요.", type=["png", "jpg", "jpeg"])
    
    if uploaded_file is not None:
        # 새 이미지가 업로드되면 이전 결과 초기화 (이름이 같아도 파일 내용이 다르면 초기화됨)
        if uploaded_file.file_id != st.session_state["last_file_id"]:
            st.session_state["last_json"] = None
            st.session_state["generated_data"] = None
            st.session_state["last_file_id"] = uploaded_file.file_id
            
        # 업로드된 이미지 미리보기
        image = Image.open(uploaded_file)
        st.image(image, caption="업로드된 AS-IS 화면", use_container_width=True)
        
        with st.expander("⚙️ 고급 설정 (시스템 프롬프트 편집)"):
            st.markdown("LLM에 전달할 시스템 프롬프트를 선택하거나 직접 수정할 수 있습니다.")
            selected_template = st.selectbox("프롬프트 템플릿 선택", list(PROMPT_TEMPLATES.keys()))
            custom_prompt = st.text_area("시스템 프롬프트 내용", value=PROMPT_TEMPLATES[selected_template], height=400)

with col2:
    st.subheader("2. TO-BE PPT 생성 및 다운로드")
    if uploaded_file is not None:
        feedback = ""
        if st.session_state["last_json"]:
            st.info("💡 이전 생성 결과를 수정하려면 아래에 피드백을 입력하고 다시 생성하세요.")
            feedback = st.text_area("🔄 수정 요청사항 (피드백)", placeholder="예: '우측 상단에 닫기(X) 모달 버튼을 추가해줘', '로그인 버튼을 파란색으로 변경해줘'")
            
        button_label = "✨ 피드백 반영하여 다시 생성" if st.session_state["last_json"] else "🚀 PPT 생성 시작"
        
        if st.button(button_label, use_container_width=True):
            st.session_state["generated_data"] = None # 즉시 초기화
            with st.spinner(f"HCP API({HCP_TEXT_MODEL})를 통해 요청사항을 반영하여 PPT를 그리는 중입니다..."):
                try:
                    # 1. 로컬에서 직접 LLM 호출 (네트워크 통신 불필요)
                    llm_service = HCPQwenService(base_url=HCP_API_URL)
                    analysis_result = llm_service.analyze_asis_image_local(
                        uploaded_file.getvalue(),
                        custom_system_prompt=custom_prompt,
                        previous_json=st.session_state["last_json"],
                        feedback=feedback
                    )
                    
                    # 2. PPT 메모리 버퍼에 렌더링
                    ppt_stream = io.BytesIO()
                    create_editable_ppt(analysis_result, ppt_stream)
                    
                    # 3. HTML / JSON 문자열 생성
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
                    
                    # 4. 결과 상태 저장 (디스크 쓰기 없음)
                    st.session_state["generated_data"] = {
                        "ppt": ppt_stream.getvalue(),
                        "html_str": html_content,
                        "json_str": json_content
                    }
                    st.session_state["last_json"] = json_content
                    st.success("🎉 성공적으로 PPT가 생성되었습니다!")
                except Exception as e:
                    st.error(f"처리 중 오류가 발생했습니다: {e}")
                    
        # 생성 버튼의 실행 흐름과 무관하게, 세션에 데이터가 있으면 항상 미리보기 및 다운로드 버튼 렌더링
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
                
                col_dl1.download_button(label="📊 PPT 다운로드", data=data["ppt"], file_name=f"UI_정의서_{uploaded_file.name}.pptx", mime="application/vnd.openxmlformats-officedocument.presentationml.presentation", use_container_width=True)
                col_dl2.download_button(label="🌐 HTML 다운로드", data=data["html_str"], file_name=f"index_{uploaded_file.name}.html", mime="text/html", use_container_width=True)
                if css_content:
                    col_dl3.download_button(label="🎨 CSS 다운로드", data=css_content, file_name="hds.css", mime="text/css", use_container_width=True)
                col_dl4.download_button(label="📝 JSON 다운로드", data=data["json_str"], file_name=f"result_{uploaded_file.name}.json", mime="application/json", use_container_width=True)
            except Exception as e:
                st.warning(f"결과 파일을 처리하는 중 오류가 발생했습니다: {e}")
    else:
        st.info("먼저 좌측에 이미지를 업로드해주세요.")