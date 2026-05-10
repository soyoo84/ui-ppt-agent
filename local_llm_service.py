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
    LLM_MAX_RETRIES, LLM_TIMEOUT_SECONDS, LLM_MAX_TOKENS, LLM_TEMPERATURE
)

logger = logging.getLogger(__name__)

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

    def _try_parse_json(self, j_str: str):
        """[토큰 잘림 방어 로직] 강제 닫기 시도용 JSON 파싱 헬퍼 함수"""
        try:
            return json.loads(j_str, strict=False)
        except json.JSONDecodeError:
            return None
            
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
                return response.choices[0].message.content or ""
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
        return ""

    def _extract_json_from_text(self, text: str) -> dict:
        """LLM이 반환한 텍스트에서 JSON 블록만 추출합니다. (오류 방지 최적화)"""
        # 명시적인 json 마크다운 블록을 먼저 찾습니다. (HTML 등 다른 코드 블록 오인식 방어)
        match = re.search(r'```json\s*(.*?)\s*```', text, re.DOTALL | re.IGNORECASE)
        if match:
            json_str = match.group(1)
        else:
            # 마크다운 블록이 아예 없고, 부가 설명이 섞여 있을 경우를 대비 (첫 '{' 부터 마지막 '}' 까지 추출)
            start_idx = text.find('{')
            end_idx = text.rfind('}')
            if start_idx != -1 and end_idx != -1 and start_idx < end_idx:
                # 끝에 불필요한 설명이 붙었을 수 있으므로 기본적으로 마지막 '}' 까지 자릅니다.
                json_str = text[start_idx:end_idx+1]
            elif start_idx != -1:
                # '}'가 아예 없거나 꼬인 경우 (토큰 잘림)
                json_str = text[start_idx:]
            else:
                json_str = text
            
        result = self._try_parse_json(json_str)
        if result is not None:
            return result
            
        # [2차 방어] 마크다운 안의 내용이 파싱 실패했을 경우, 텍스트 전체에서 중괄호({}) 범위를 다시 탐색
        if match:
            start_idx = text.find('{')
            end_idx = text.rfind('}')
            if start_idx != -1 and end_idx != -1 and start_idx < end_idx:
                json_str = text[start_idx:end_idx+1]
                result = self._try_parse_json(json_str)
                if result is not None:
                    return result
            elif start_idx != -1:
                json_str = text[start_idx:]

        # 파싱 실패 시 토큰 4400 제한에 의한 잘림(Truncation)으로 간주하고 자동 복구 시도
        logger.warning("JSON 파싱 에러 발생. 토큰 잘림으로 간주하고 자동 복구를 시도합니다.")
        
        if json_str.count('"') % 2 != 0:
            json_str += '"'
            
        for suffix in ["}", "]}", "}]}", '"}', '"]}', '"]}]}']:
            recovered_result = self._try_parse_json(json_str + suffix)
            if recovered_result is not None:
                logger.info(f"잘린 JSON 데이터를 성공적으로 복구했습니다. (추가된 접미사: {suffix})")
                return recovered_result
                
        raise ValueError("생성된 데이터가 LLM 토큰 제한(4400)에 의해 심하게 잘렸으며 복구에 실패했습니다. 더 작은 이미지를 사용해 보세요.\n" + json_str)

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
        css_content = ""
        if os.path.exists("hds.css"):
            try:
                with open("hds.css", "r", encoding="utf-8") as f:
                    raw_css = f.read()
                    if len(raw_css) > 2500:
                        # [토큰 다이어트] 파일이 너무 크면 내부 스타일 속성({ ... })은 버리고 클래스명만 추출
                        class_names = set(re.findall(r'\.([a-zA-Z0-9_-]+)', raw_css))
                        css_content = "/* CSS 용량 초과 방지: 사내 가이드 클래스명 목록만 요약 추출함 */\n" + ", ".join([f".{c}" for c in sorted(class_names)])
                        if len(css_content) > 1500:
                            css_content = css_content[:1500] + "..."
                    else:
                        css_content = raw_css
            except Exception as e:
                logger.warning(f"hds.css 읽기 실패: {e}")

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
        
        if previous_json and feedback:
            # [초고속 최적화] 피드백(채팅) 모드: Vision API 스킵 & Text API 단독 1-Pass
            # =================================================================
            logger.info("=== Speed Optimization: Feedback Fast-Track (Text API) ===")
            # 이미지가 빠져 입력 토큰이 2000~3000개 절약되므로, 4400 한계 걱정 없이 한 번에 JSON+코드를 생성합니다.
            fast_messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
            fast_output = self._call_api_with_retry(self.text_model, fast_messages, "Feedback Fast-Track")
            
            logger.info(f"Feedback Fast-Track 응답 길이: {len(fast_output)}자")
            parsed_dict = self._extract_json_from_text(fast_output)
            
            if "generated_html" in parsed_dict and isinstance(parsed_dict["generated_html"], str):
                # [최종 방어] Fast-Track에서도 대화형 텍스트 오염을 막기 위한 다중 필터링 적용
                cleaned_html = html.unescape(parsed_dict["generated_html"].strip())
                html_match = re.search(r'```(?:html|jsx|javascript|js)?\s*(.*?)\s*```', cleaned_html, re.DOTALL | re.IGNORECASE)
                if html_match:
                    cleaned_html = html_match.group(1)
                else:
                    cleaned_html = re.sub(r'^\s*```[a-zA-Z]*\n?', '', cleaned_html)
                    cleaned_html = re.sub(r'\n?```\s*$', '', cleaned_html)
                parsed_dict["generated_html"] = cleaned_html
        else:
            # =================================================================
            # 1. 고해상도 이미지 최적화 (최초 1차 생성 시에만 수행)
            # =================================================================
            img = Image.open(io.BytesIO(image_bytes))
            original_format = img.format if img.format else ("PNG" if image_bytes.startswith(b'\x89PNG') else "JPEG")
            img = ImageOps.exif_transpose(img)
            max_size = 1024 # 4400 토큰 한계 돌파를 위해 이미지 리사이징 기준을 1440에서 1024로 하향
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
            # [토큰 다이어트] Pass 1은 JSON 구조만 뽑으므로 출력 토큰을 800으로 제한하여 입력 공간 대폭 확보
            vision_output = self._call_api_with_retry(self.vision_model, vision_messages, "Pass 1", max_tokens_override=800)
            
            # JSON 추출 (복구 로직 포함)
            parsed_dict = self._extract_json_from_text(vision_output)
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
            
            text_output = self._call_api_with_retry(self.text_model, text_messages, "Pass 2")

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
                    fallback_json = self._extract_json_from_text(pass2_raw_html)
                    if "generated_html" in fallback_json:
                        pass2_raw_html = fallback_json["generated_html"]
                except Exception:
                    pass
            
            # [최종 방어] LLM이 쓸데없는 대화형 텍스트("여기 코드입니다~")를 코드 블록 위아래에 붙였을 경우 알맹이만 추출
            cleaned_html = html.unescape(pass2_raw_html.strip())
            html_match = re.search(r'```(?:html|jsx|javascript|js)?\s*(.*?)\s*```', cleaned_html, re.DOTALL | re.IGNORECASE)
            if html_match:
                cleaned_html = html_match.group(1)
            else:
                cleaned_html = re.sub(r'^\s*```[a-zA-Z]*\n?', '', cleaned_html)
                cleaned_html = re.sub(r'\n?```\s*$', '', cleaned_html)
            
            # [최종 방어 2] LLM이 Base 프롬프트의 압박을 이기지 못하고 리터럴 '\n' 문자를 출력했을 경우, 이를 실제 줄바꿈(엔터)으로 안전하게 변환
            cleaned_html = cleaned_html.replace('\\n', '\n')
            
            parsed_dict["generated_html"] = cleaned_html.strip()
            
        # 4. 최종 Pydantic 검증 (Fast-Track 및 2-Pass 공통)
        try:
            result = ScreenAnalysisResult(**parsed_dict)
            return result
        except ValidationError as e:
            logger.error(f"Pydantic Validation Error: {e}")
            raise ValueError(f"모델이 스키마에 맞지 않는 JSON을 생성했습니다. 상세 원인:\n{e}")