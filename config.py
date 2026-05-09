import os
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()

# [API Settings]
HCP_API_URL = os.getenv("HCP_API_URL") or "https://hcp.skhynix.com/llm/v1"
HCP_API_KEY = os.getenv("HCP_API_KEY") or "EMPTY"
HCP_VISION_MODEL = os.getenv("HCP_VISION_MODEL") or "qwen-2.5-vl"
HCP_TEXT_MODEL = os.getenv("HCP_TEXT_MODEL") or "qwen-3.5"

# [LLM Settings]
LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES") or 3)
LLM_TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS") or 120.0)
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS") or 2048)
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE") or 0.1)

# [Frontend Settings]
APP_TITLE = os.getenv("APP_TITLE") or "UI-PPT 자동 생성기"

# [PPT Settings]
MASTER_PPT_PATH = os.getenv("MASTER_PPT_PATH")
TARGET_LAYOUT_NAME = os.getenv("TARGET_LAYOUT_NAME")
PPT_SLIDE_WIDTH = float(os.getenv("PPT_SLIDE_WIDTH") or 13.333)
PPT_SLIDE_HEIGHT = float(os.getenv("PPT_SLIDE_HEIGHT") or 7.5)
PPT_UI_SCALE = float(os.getenv("PPT_UI_SCALE") or 0.65)
PPT_ALIGN_THRESHOLD = float(os.getenv("PPT_ALIGN_THRESHOLD") or 0.03)
PPT_CONTAINER_PADDING = float(os.getenv("PPT_CONTAINER_PADDING") or 0.03)

# [Design Settings]
_primary_color_str = os.getenv("HDS_PRIMARY_COLOR_RGB") or "230,0,18"

try:
    # 사용자가 .env에 띄어쓰기를 포함해 입력하더라도 안전하게 처리되도록 공백 제거 후 파싱
    HDS_PRIMARY_COLOR = tuple(map(int, _primary_color_str.replace(" ", "").split(",")))
except ValueError:
    HDS_PRIMARY_COLOR = (230, 0, 18) # 파싱 실패 시 기본 컬러(Red)로 안전하게 롤백