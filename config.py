import os
from dotenv import load_dotenv

# .env 파일 로드 (수정 시 기존 메모리 환경변수를 강제로 덮어쓰기)
load_dotenv(override=True)

# --- [안전한 환경변수 파싱 헬퍼 함수] ---
def _get_env_int(key: str, default: int) -> int:
    val = os.getenv(key)
    if not val: return default
    try: return int(val)
    except ValueError: return default

def _get_env_float(key: str, default: float) -> float:
    val = os.getenv(key)
    if not val: return default
    try: return float(val)
    except ValueError: return default

# [API Settings]
HCP_API_URL = os.getenv("HCP_API_URL") or "https://hcp.skhynix.com/llm/v1"
HCP_API_KEY = os.getenv("HCP_API_KEY") or "EMPTY"
HCP_VISION_MODEL = os.getenv("HCP_VISION_MODEL") or "qwen-2.5-vl"
HCP_TEXT_MODEL = os.getenv("HCP_TEXT_MODEL") or "qwen-3.5"

# [LLM Settings]
LLM_MAX_RETRIES = _get_env_int("LLM_MAX_RETRIES", 3)
LLM_TIMEOUT_SECONDS = _get_env_float("LLM_TIMEOUT_SECONDS", 120.0)
LLM_MAX_TOKENS = _get_env_int("LLM_MAX_TOKENS", 1500)
LLM_TEMPERATURE = _get_env_float("LLM_TEMPERATURE", 0.1)

# [Frontend Settings]
APP_TITLE = os.getenv("APP_TITLE") or "UI-PPT 자동 생성기"

# [PPT Settings]
MASTER_PPT_PATH = os.getenv("MASTER_PPT_PATH")
MASTER_TEMPLATE_DIR = os.getenv("MASTER_TEMPLATE_DIR") or "master"
TARGET_LAYOUT_NAME = os.getenv("TARGET_LAYOUT_NAME")
PPT_SLIDE_WIDTH = _get_env_float("PPT_SLIDE_WIDTH", 13.333)
PPT_SLIDE_HEIGHT = _get_env_float("PPT_SLIDE_HEIGHT", 7.5)
PPT_UI_SCALE = _get_env_float("PPT_UI_SCALE", 0.65)
PPT_TOP_OFFSET_RATIO = _get_env_float("PPT_TOP_OFFSET_RATIO", 0.25)
PPT_ALIGN_THRESHOLD = _get_env_float("PPT_ALIGN_THRESHOLD", 0.03)
PPT_CONTAINER_PADDING = _get_env_float("PPT_CONTAINER_PADDING", 0.03)

# [Design Settings]
_primary_color_str = os.getenv("HDS_PRIMARY_COLOR_RGB") or "230,0,18"

try:
    # 사용자가 .env에 띄어쓰기를 포함해 입력하더라도 안전하게 처리되도록 공백 제거 후 파싱
    parsed_color = tuple(map(int, _primary_color_str.replace(" ", "").split(",")))
    if len(parsed_color) != 3:
        raise ValueError("RGB 값은 반드시 3개의 숫자여야 합니다.")
        if any(c < 0 or c > 255 for c in parsed_color):
            raise ValueError("RGB 값은 0~255 사이여야 합니다.")
    HDS_PRIMARY_COLOR = parsed_color
except Exception as e:
    print(f"⚠️ [Warning] HDS_PRIMARY_COLOR_RGB 설정 오류 ({e}) - 기본값(230,0,18)으로 롤백됩니다.")
    HDS_PRIMARY_COLOR = (230, 0, 18) # 파싱 실패 시 기본 컬러(Red)로 안전하게 롤백