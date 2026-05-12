import json
import re
import base64
import time
import logging
import html
import io
import os
from PIL import Image, ImageOps
from pydantic import ValidationError
from schemas import ScreenAnalysisResult
from openai import Client, APITimeoutError, APIConnectionError, APIStatusError
from prompts import DEFAULT_PROMPT, USER_PROMPT_BASE, USER_PROMPT_REVISION, get_component_registry
from config import (
    HCP_API_KEY, HCP_VISION_MODEL, HCP_TEXT_MODEL,
    GEMINI_API_KEY, GEMINI_VISION_MODEL, GEMINI_TEXT_MODEL,
    LLM_MAX_RETRIES, LLM_TIMEOUT_SECONDS, LLM_MAX_TOKENS, LLM_TEMPERATURE
)

try:
    import google.generativeai as genai
except ImportError:
    genai = None

logger = logging.getLogger(__name__)

def try_parse_json(j_str: str):
    try:
        return json.loads(j_str, strict=False)
    except json.JSONDecodeError:
        return None

def extract_json_from_text(text: str) -> dict:
    match = re.search(r'```json\s*(.*?)\s*```', text, re.DOTALL | re.IGNORECASE)
    if match:
        json_str = match.group(1)
    else:
        start_idx = text.find('{')
        end_idx = text.rfind('}')
        if start_idx != -1 and end_idx != -1 and start_idx < end_idx:
            json_str = text[start_idx:end_idx+1]
        elif start_idx != -1:
            json_str = text[start_idx:]
        else:
            json_str = text
        
    result = try_parse_json(json_str)
    if result is not None:
        return result
        
    if match:
        start_idx = text.find('{')
        end_idx = text.rfind('}')
        if start_idx != -1 and end_idx != -1 and start_idx < end_idx:
            json_str = text[start_idx:end_idx+1]
            result = try_parse_json(json_str)
            if result is not None:
                return result
        elif start_idx != -1:
            json_str = text[start_idx:]
            
    logger.warning("JSON 파싱 에러 발생. 토큰 잘림으로 간주하고 자동 복구를 시도합니다.")
    if json_str.count('"') % 2 != 0: json_str += '"'
    for suffix in ["}", "]}", "}]}", '"}', '"]}', '"]}]}']:
        recovered_result = try_parse_json(json_str + suffix)
        if recovered_result is not None:
            return recovered_result
            
    raise ValueError("JSON 데이터 복구 실패\n" + json_str)

def clean_generated_html(raw_html: str) -> str:
    cleaned_html = html.unescape(raw_html.strip())
    html_match = re.search(r'```(?:html|jsx|javascript|js)?\s*(.*?)\s*```', cleaned_html, re.DOTALL | re.IGNORECASE)
    if html_match:
        cleaned_html = html_match.group(1)
    else:
        cleaned_html = re.sub(r'^\s*```[a-zA-Z]*\n?', '', cleaned_html)
        cleaned_html = re.sub(r'\n?```\s*$', '', cleaned_html)
    return cleaned_html.replace('\\n', '\n').strip()

def load_and_summarize_css(file_path="hds.css") -> str:
    css_content = ""
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                raw_css = f.read()
                if len(raw_css) > 5000:
                    class_names = set(re.findall(r'\.([a-zA-Z0-9_-]+)', raw_css))
                    
                    # [토큰 다이어트] 상태(State) 및 내부 래퍼(Wrapper/Inner) 등 불필요한 클래스명 필터링
                    ignore_words = ['hover', 'active', 'focus', 'disabled', 'inner', 'wrapper', 'hidden', 'show', 'enter', 'leave']
                    filtered_classes = [c for c in class_names if not any(w in c.lower() for w in ignore_words)]
                    
                    css_content = "/* CSS 핵심 클래스 요약 */\n" + ", ".join([f".{c}" for c in sorted(filtered_classes)])
                    
                    if len(css_content) > 4000:
                        css_content = css_content[:4000] + "..."
                else:
                    css_content = raw_css
        except Exception as e:
            logger.warning(f"hds.css 읽기 실패: {e}")
    return css_content

class HCPQwenService:
    def __init__(self, base_url: str):
        """
        SK하이닉스 내부망 HCP API 엔드포인트를 통해 Qwen 모델을 호출합니다.
        """
        self.base_url = base_url
        # 환경 변수는 config.py에서 중앙 관리
        self.client = Client(api_key=HCP_API_KEY, base_url=self.base_url)
        self.vision_model = HCP_VISION_MODEL
        self.text_model = HCP_TEXT_MODEL

    def _call_api_with_retry(self, model_name, messages, step_name, max_tokens_override=None):
        """OpenAI 호환 API 호출 (타임아웃 및 재시도 로직 공통화)"""
        max_retries = LLM_MAX_RETRIES
        timeout_seconds = LLM_TIMEOUT_SECONDS
        max_tokens = max_tokens_override if max_tokens_override else LLM_MAX_TOKENS
        temperature = LLM_TEMPERATURE
        
        for attempt in range(max_retries):
            try:
                response = self.client.chat.completions.create(
                    model=model_name,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    timeout=timeout_seconds
                )
                usage_dict = {}
                if hasattr(response, "usage") and response.usage:
                    usage_dict = {
                        "prompt_tokens": getattr(response.usage, "prompt_tokens", 0),
                        "completion_tokens": getattr(response.usage, "completion_tokens", 0),
                        "total_tokens": getattr(response.usage, "total_tokens", 0)
                    }
                return response.choices[0].message.content or "", usage_dict
            except APITimeoutError:
                if attempt == max_retries - 1:
                    raise ValueError(f"[{step_name}] LLM API 응답 시간이 초과되었습니다 ({timeout_seconds}초). 서버 상태가 혼잡할 수 있으니 잠시 후 다시 시도해 주세요.")
                logger.warning(f"[{step_name}] API 타임아웃 발생, 재시도 중... ({attempt + 1}/{max_retries})")
                time.sleep(2 ** attempt)
            except APIStatusError as e:
                if e.status_code == 400 and ("token" in str(e.message).lower() or "length" in str(e.message).lower() or "context" in str(e.message).lower()):
                    raise ValueError(f"[{step_name}] LLM의 최대 입력 토큰 제한(4400)을 초과했습니다. 화면이 너무 길거나 복잡합니다. 해상도를 줄이거나 일부 영역만 캡쳐해 주세요.")
                if e.status_code in [429, 500, 502, 503, 504]:
                    if attempt == max_retries - 1:
                        raise ValueError(f"[{step_name}] LLM API 서버 오류({e.status_code})가 지속되어 실패했습니다: {e.message}")
                    logger.warning(f"[{step_name}] API 상태 오류({e.status_code}) 발생, 재시도 중... ({attempt + 1}/{max_retries})")
                    time.sleep(2 ** attempt)
                else:
                    raise ValueError(f"[{step_name}] LLM API 요청 오류({e.status_code}): {e.message}")
            except APIConnectionError:
                if attempt == max_retries - 1:
                    raise ValueError(f"[{step_name}] LLM API 서버에 연결할 수 없습니다. 사내망 네트워크 상태를 확인해 주세요.")
                logger.warning(f"[{step_name}] API 연결 오류 발생, 재시도 중... ({attempt + 1}/{max_retries})")
                time.sleep(2 ** attempt)
        return "", {}

    def analyze_asis_image_local(
        self, image_bytes: bytes, 
        custom_system_prompt: str = None,
        previous_json: str = None,
        feedback: str = None
    ) -> ScreenAnalysisResult:
        """
        HCP API(Qwen 3.5)를 사용하여 이미지를 분석하고 컴포넌트를 추출합니다.
        """
        # [우선순위 역전] hds.css를 최우선 진실의 원천(Source of Truth)으로 LLM에게 제공
        css_content = load_and_summarize_css()

        system_prompt = custom_system_prompt.strip() if custom_system_prompt and custom_system_prompt.strip() else DEFAULT_PROMPT
        
        # [성능 최적화] 컴포넌트 레지스트리를 한 번만 로드하여 모든 로직에서 재사용
        registry = get_component_registry()
        
        user_prompt = USER_PROMPT_BASE
        if previous_json and feedback:
            user_prompt = USER_PROMPT_REVISION.format(previous_json=previous_json, feedback=feedback)
            
            # [초고속 최적화] 피드백(채팅) 모드에서도 동적 프롬프트 주입 적용
            try:
                prev_data = json.loads(previous_json)
                found_types = set([c.get("component_type", "") for c in prev_data.get("components", []) if isinstance(c, dict)])
                injected_guidelines = ""
                for comp_type in found_types:
                    if comp_type in registry and registry[comp_type].get("guide"):
                        injected_guidelines += f"- [{comp_type}]: {registry[comp_type]['guide']}\n"
                if injected_guidelines:
                    user_prompt += f"\n\n[🚨 사내 Storybook 컴포넌트 가이드 🚨]\n코드를 수정할 때 아래 명세를 반드시 엄수하세요:\n{injected_guidelines}"
            except Exception as e:
                logger.warning(f"피드백 모드 동적 주입 실패: {e}")
                
        # [우선순위 1순위] 최초 생성 및 피드백 모드 모두 CSS 컨텍스트를 제공해야 Vision API가 클래스명을 정확히 추출합니다.
        if css_content:
            user_prompt += f"\n\n[🚨 1순위: 사내 HDS CSS 스타일시트 🚨]\nHTML/JSX 코드 작성 및 컴포넌트 타입(component_type) 지정 시 아래 CSS에 정의된 클래스명(.ant-btn 등)을 최우선으로 매핑하여 화면을 구성하세요:\n```css\n{css_content}\n```"

        parsed_dict = {}
        total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        
        if previous_json and feedback:
            # [초고속 최적화] 피드백(채팅) 모드: Vision API 스킵 & Text API 단독 1-Pass
            # =================================================================
            logger.info("=== Speed Optimization: Feedback Fast-Track (Text API) ===")
            # 이미지가 빠져 입력 토큰이 2000~3000개 절약되므로, 4400 한계 걱정 없이 한 번에 JSON+코드를 생성합니다.
            fast_messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
            fast_output, u_fast = self._call_api_with_retry(self.text_model, fast_messages, "Feedback Fast-Track")
            total_usage["prompt_tokens"] += u_fast.get("prompt_tokens", 0)
            total_usage["completion_tokens"] += u_fast.get("completion_tokens", 0)
            total_usage["total_tokens"] += u_fast.get("total_tokens", 0)
            
            logger.info(f"Feedback Fast-Track 응답 길이: {len(fast_output)}자")
            parsed_dict = extract_json_from_text(fast_output)
            
            if "generated_html" in parsed_dict and isinstance(parsed_dict["generated_html"], str):
                parsed_dict["generated_html"] = clean_generated_html(parsed_dict["generated_html"])
        else:
            # =================================================================
            # 1. 고해상도 이미지 최적화 (최초 1차 생성 시에만 수행)
            # =================================================================
            img = Image.open(io.BytesIO(image_bytes))
            original_format = img.format if img.format else ("PNG" if image_bytes.startswith(b'\x89PNG') else "JPEG")
            img = ImageOps.exif_transpose(img)
            max_size = 1440 # 텍스트 및 소형 컴포넌트 누락 방지를 위해 해상도 상향
            if img.width > max_size or img.height > max_size:
                img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
                
            buffered = io.BytesIO()
            if original_format == "JPEG" and img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            img.save(buffered, format=original_format)
            processed_image_bytes = buffered.getvalue()
                
            # 2. 이미지를 Base64 인코딩
            mime_type = "image/png" if processed_image_bytes.startswith(b'\x89PNG') else "image/jpeg"
            base64_image = base64.b64encode(processed_image_bytes).decode('utf-8')

            # =================================================================
            # [Pass 1] Vision API: 이미지 분석 및 컴포넌트 좌표 추출 (코드 생성 제외)
            # =================================================================
            vision_system_prompt = system_prompt + "\n\n[🚨 2-Pass 아키텍처 1단계: 토큰 절약 지시사항]\n이번 단계에서는 'generated_html' 필드에 코드를 작성하지 말고, 반드시 빈 문자열(\"\")로 남겨두세요. 오직 화면 구조 분석과 'components' 배열 추출에만 모든 토큰과 역량을 집중하세요."
            
            vision_messages = [
                {"role": "system", "content": vision_system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_prompt},
                        {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{base64_image}"}}
                    ]
                }
            ]
            
            logger.info("=== 2-Pass Pipeline: [Pass 1] Vision API 시작 ===")
            # 컴포넌트 누락 방지를 위해 Pass 1의 출력 허용 토큰을 3000으로 넉넉하게 해제
            vision_output, u_vision = self._call_api_with_retry(self.vision_model, vision_messages, "Pass 1", max_tokens_override=3000)
            total_usage["prompt_tokens"] += u_vision.get("prompt_tokens", 0)
            total_usage["completion_tokens"] += u_vision.get("completion_tokens", 0)
            total_usage["total_tokens"] += u_vision.get("total_tokens", 0)
            
            # JSON 추출 (복구 로직 포함)
            parsed_dict = extract_json_from_text(vision_output)
            components_data = parsed_dict.get("components", [])
            
            # =================================================================
            # [Pass 2] Text API: 추출된 컴포넌트 데이터를 기반으로 코드 전문 생성
            # =================================================================
            logger.info("=== 2-Pass Pipeline: [Pass 2] Text API 시작 ===")
            
            # [2-Pass 최적화] 1단계에서 찾은 컴포넌트의 가이드만 동적으로 주입
            found_types = set([c.get("component_type", "") for c in components_data if isinstance(c, dict)])
            injected_guidelines = ""
            for comp_type in found_types:
                if comp_type in registry and registry[comp_type].get("guide"):
                    injected_guidelines += f"- [{comp_type}]: {registry[comp_type]['guide']}\n"
                    
            text_user_prompt = f"다음은 화면 이미지에서 추출된 UI 컴포넌트들의 JSON 데이터입니다:\n```json\n{json.dumps(components_data, ensure_ascii=False, indent=2)}\n```\n"
            if css_content:
                text_user_prompt += f"\n[🚨 1순위: 사내 HDS CSS 스타일시트 🚨]\nHTML/JSX 코드 작성 시 아래 CSS에 정의된 클래스명(.ant-btn 등)을 최우선으로 사용하여 화면을 구성하세요:\n```css\n{css_content}\n```\n"
            if injected_guidelines:
                text_user_prompt += f"\n[🚨 사내 Storybook 컴포넌트 가이드 🚨]\n위 JSON 데이터를 기반으로 코드를 작성하되, 아래의 명세를 반드시 엄수하세요:\n{injected_guidelines}\n"
            text_user_prompt += "\n위 데이터를 바탕으로, 원래의 시스템 프롬프트 지시사항에 맞추어 'generated_html'에 들어갈 코드를 작성하세요.\n다른 설명이나 마크다운 없이, 오직 HTML 또는 React(JSX) 코드 원본 자체만 텍스트로 반환하세요. (코드 블록 ```html 사용 무방)"
            
            # [2-Pass 최적화] 2단계에서는 시스템 프롬프트의 JSON 제약을 해제하여 충돌을 방지합니다.
            pass2_system_prompt = system_prompt + "\n\n[🚨 2-Pass 아키텍처 2단계: 응답 형식 변경]\n이전 지시사항의 'JSON 응답' 제약 및 '한 줄 작성(\\n)' 제약을 완전히 무시하세요. 이번 단계에서는 JSON 형식이 아닌, 들여쓰기와 줄바꿈(엔터)이 정상적으로 적용된 순수한 프론트엔드 코드(HTML/JSX) 원본 텍스트만을 출력해야 합니다."
            
            text_messages = [
                {"role": "system", "content": pass2_system_prompt},
                {"role": "user", "content": text_user_prompt}
            ]
            
            text_output, u_text = self._call_api_with_retry(self.text_model, text_messages, "Pass 2")
            total_usage["prompt_tokens"] += u_text.get("prompt_tokens", 0)
            total_usage["completion_tokens"] += u_text.get("completion_tokens", 0)
            total_usage["total_tokens"] += u_text.get("total_tokens", 0)

            # 3. 데이터 병합
            # --- [디버깅 로그: JSON 잘림 현상 확인용] ---
            token_limit_msg = LLM_MAX_TOKENS if LLM_MAX_TOKENS else "무제한 (AI 모델 물리적 최대치)"
            logger.info(f"설정된 최대 허용 토큰 수(Max Tokens): {token_limit_msg}")
            logger.info(f"Pass 1 (Vision) 응답 길이: {len(vision_output)}자")
            logger.info(f"Pass 2 (Text) 응답 길이: {len(text_output)}자")
            
            # Pass 2 응답이 프롬프트 지시를 무시하고 JSON 포맷으로 돌아왔을 경우를 대비한 방어 로직
            pass2_raw_html = text_output.strip()
            if "{" in pass2_raw_html and "generated_html" in pass2_raw_html:
                try:
                    fallback_json = extract_json_from_text(pass2_raw_html)
                    if "generated_html" in fallback_json:
                        pass2_raw_html = fallback_json["generated_html"]
                except Exception:
                    pass
            
            parsed_dict["generated_html"] = clean_generated_html(pass2_raw_html)
            
        parsed_dict["token_usage"] = total_usage
            
        # 4. 최종 Pydantic 검증 (Fast-Track 및 2-Pass 공통)
        try:
            result = ScreenAnalysisResult(**parsed_dict)
            return result
        except ValidationError as e:
            logger.error(f"Pydantic Validation Error: {e}")
            raise ValueError(f"모델이 스키마에 맞지 않는 JSON을 생성했습니다. 상세 원인:\n{e}")


class GeminiService:
    def __init__(self):
        """
        Google Gemini API 엔드포인트를 호출합니다.
        """
        if not genai:
            raise ImportError("google-generativeai 패키지가 설치되지 않았습니다. pip install google-generativeai 를 실행해주세요.")
        if not GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY가 설정되지 않았습니다.")
        
        genai.configure(api_key=GEMINI_API_KEY)
        self.vision_model = genai.GenerativeModel(GEMINI_VISION_MODEL)
        self.text_model = genai.GenerativeModel(GEMINI_TEXT_MODEL)

    def _call_api_with_retry(self, model, contents, step_name):
        max_retries = LLM_MAX_RETRIES
        
        for attempt in range(max_retries):
            try:
                response = model.generate_content(
                    contents,
                    generation_config=genai.types.GenerationConfig(
                        temperature=LLM_TEMPERATURE,
                    )
                )
                usage_dict = {}
                if hasattr(response, "usage_metadata") and response.usage_metadata:
                    usage_dict = {
                        "prompt_tokens": getattr(response.usage_metadata, "prompt_token_count", 0),
                        "completion_tokens": getattr(response.usage_metadata, "candidates_token_count", 0),
                        "total_tokens": getattr(response.usage_metadata, "total_token_count", 0)
                    }
                return response.text, usage_dict
            except Exception as e:
                if attempt == max_retries - 1:
                    raise ValueError(f"[{step_name}] Gemini API 요청 오류: {e}")
                logger.warning(f"[{step_name}] API 오류 발생, 재시도 중... ({attempt + 1}/{max_retries})")
                time.sleep(2 ** attempt)
        return "", {}

    def analyze_asis_image_local(
        self, image_bytes: bytes, 
        custom_system_prompt: str = None,
        previous_json: str = None,
        feedback: str = None
    ) -> ScreenAnalysisResult:
        
        css_content = load_and_summarize_css()

        system_prompt = custom_system_prompt.strip() if custom_system_prompt and custom_system_prompt.strip() else DEFAULT_PROMPT
        
        registry = get_component_registry()
        user_prompt = USER_PROMPT_BASE
        
        if previous_json and feedback:
            user_prompt = USER_PROMPT_REVISION.format(previous_json=previous_json, feedback=feedback)
            try:
                prev_data = json.loads(previous_json)
                found_types = set([c.get("component_type", "") for c in prev_data.get("components", []) if isinstance(c, dict)])
                injected_guidelines = ""
                for comp_type in found_types:
                    if comp_type in registry and registry[comp_type].get("guide"):
                        injected_guidelines += f"- [{comp_type}]: {registry[comp_type]['guide']}\n"
                if injected_guidelines:
                    user_prompt += f"\n\n[🚨 사내 Storybook 컴포넌트 가이드 🚨]\n코드를 수정할 때 아래 명세를 반드시 엄수하세요:\n{injected_guidelines}"
            except Exception as e:
                logger.warning(f"피드백 모드 동적 주입 실패: {e}")
                
        if css_content:
            user_prompt += f"\n\n[🚨 1순위: 사내 HDS CSS 스타일시트 🚨]\nHTML/JSX 코드 작성 및 컴포넌트 타입(component_type) 지정 시 아래 CSS에 정의된 클래스명(.ant-btn 등)을 최우선으로 매핑하여 화면을 구성하세요:\n```css\n{css_content}\n```"

        parsed_dict = {}
        total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        
        if previous_json and feedback:
            logger.info("=== Gemini Speed Optimization: Feedback Fast-Track ===")
            full_prompt = f"System:\n{system_prompt}\n\nUser:\n{user_prompt}"
            fast_output, u_fast = self._call_api_with_retry(self.text_model, [full_prompt], "Feedback Fast-Track")
            total_usage["prompt_tokens"] += u_fast.get("prompt_tokens", 0)
            total_usage["completion_tokens"] += u_fast.get("completion_tokens", 0)
            total_usage["total_tokens"] += u_fast.get("total_tokens", 0)
            
            logger.info(f"Feedback Fast-Track 응답 길이: {len(fast_output)}자")
            parsed_dict = extract_json_from_text(fast_output)
            
            if "generated_html" in parsed_dict and isinstance(parsed_dict["generated_html"], str):
                parsed_dict["generated_html"] = clean_generated_html(parsed_dict["generated_html"])
        else:
            img = Image.open(io.BytesIO(image_bytes))
            original_format = img.format if img.format else ("PNG" if image_bytes.startswith(b'\x89PNG') else "JPEG")
            img = ImageOps.exif_transpose(img)
            max_size = 1440
            if img.width > max_size or img.height > max_size:
                img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
                
            # Gemini는 PIL Image를 직접 지원하므로 그대로 사용할 수 있습니다.
            
            vision_system_prompt = system_prompt + "\n\n[🚨 2-Pass 아키텍처 1단계: 토큰 절약 지시사항]\n이번 단계에서는 'generated_html' 필드에 코드를 작성하지 말고, 반드시 빈 문자열(\"\")로 남겨두세요. 오직 화면 구조 분석과 'components' 배열 추출에만 모든 토큰과 역량을 집중하세요."
            
            logger.info("=== Gemini 2-Pass Pipeline: [Pass 1] Vision API 시작 ===")
            
            vision_contents = [f"System:\n{vision_system_prompt}\n\nUser:\n{user_prompt}", img]
            vision_output, u_vision = self._call_api_with_retry(self.vision_model, vision_contents, "Pass 1")
            total_usage["prompt_tokens"] += u_vision.get("prompt_tokens", 0)
            total_usage["completion_tokens"] += u_vision.get("completion_tokens", 0)
            total_usage["total_tokens"] += u_vision.get("total_tokens", 0)
            
            parsed_dict = extract_json_from_text(vision_output)
            components_data = parsed_dict.get("components", [])
            
            logger.info("=== Gemini 2-Pass Pipeline: [Pass 2] Text API 시작 ===")
            
            found_types = set([c.get("component_type", "") for c in components_data if isinstance(c, dict)])
            injected_guidelines = ""
            for comp_type in found_types:
                if comp_type in registry and registry[comp_type].get("guide"):
                    injected_guidelines += f"- [{comp_type}]: {registry[comp_type]['guide']}\n"
                    
            text_user_prompt = f"다음은 화면 이미지에서 추출된 UI 컴포넌트들의 JSON 데이터입니다:\n```json\n{json.dumps(components_data, ensure_ascii=False, indent=2)}\n```\n"
            if css_content:
                text_user_prompt += f"\n[🚨 1순위: 사내 HDS CSS 스타일시트 🚨]\nHTML/JSX 코드 작성 시 아래 CSS에 정의된 클래스명(.ant-btn 등)을 최우선으로 사용하여 화면을 구성하세요:\n```css\n{css_content}\n```\n"
            if injected_guidelines:
                text_user_prompt += f"\n[🚨 사내 Storybook 컴포넌트 가이드 🚨]\n위 JSON 데이터를 기반으로 코드를 작성하되, 아래의 명세를 반드시 엄수하세요:\n{injected_guidelines}\n"
            text_user_prompt += "\n위 데이터를 바탕으로, 원래의 시스템 프롬프트 지시사항에 맞추어 'generated_html'에 들어갈 코드를 작성하세요.\n다른 설명이나 마크다운 없이, 오직 HTML 또는 React(JSX) 코드 원본 자체만 텍스트로 반환하세요. (코드 블록 ```html 사용 무방)"
            
            pass2_system_prompt = system_prompt + "\n\n[🚨 2-Pass 아키텍처 2단계: 응답 형식 변경]\n이전 지시사항의 'JSON 응답' 제약 및 '한 줄 작성(\\n)' 제약을 완전히 무시하세요. 이번 단계에서는 JSON 형식이 아닌, 들여쓰기와 줄바꿈(엔터)이 정상적으로 적용된 순수한 프론트엔드 코드(HTML/JSX) 원본 텍스트만을 출력해야 합니다."
            
            text_contents = [f"System:\n{pass2_system_prompt}\n\nUser:\n{text_user_prompt}"]
            text_output, u_text = self._call_api_with_retry(self.text_model, text_contents, "Pass 2")
            total_usage["prompt_tokens"] += u_text.get("prompt_tokens", 0)
            total_usage["completion_tokens"] += u_text.get("completion_tokens", 0)
            total_usage["total_tokens"] += u_text.get("total_tokens", 0)

            logger.info(f"Pass 1 (Vision) 응답 길이: {len(vision_output)}자")
            logger.info(f"Pass 2 (Text) 응답 길이: {len(text_output)}자")
            
            pass2_raw_html = text_output.strip()
            if "{" in pass2_raw_html and "generated_html" in pass2_raw_html:
                try:
                    fallback_json = extract_json_from_text(pass2_raw_html)
                    if "generated_html" in fallback_json:
                        pass2_raw_html = fallback_json["generated_html"]
                except Exception:
                    pass
            
            parsed_dict["generated_html"] = clean_generated_html(pass2_raw_html)
            
        parsed_dict["token_usage"] = total_usage
            
        try:
            result = ScreenAnalysisResult(**parsed_dict)
            return result
        except ValidationError as e:
            logger.error(f"Pydantic Validation Error: {e}")
            raise ValueError(f"모델이 스키마에 맞지 않는 JSON을 생성했습니다. 상세 원인:\n{e}")