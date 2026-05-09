import json
import re
import base64
import time
import logging
from pydantic import ValidationError
from schemas import ScreenAnalysisResult
from openai import Client, APITimeoutError, APIConnectionError
from prompts import DEFAULT_PROMPT, USER_PROMPT_BASE, USER_PROMPT_REVISION
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

    def _extract_json_from_text(self, text: str) -> dict:
        """LLM이 반환한 텍스트에서 JSON 블록만 추출합니다. (오류 방지 최적화)"""
        # 마크다운에 'json' 태그가 누락되거나 대소문자가 달라도 처리할 수 있도록 정규식 개선
        match = re.search(r'```(?:json)?\s*(.*?)\s*```', text, re.DOTALL | re.IGNORECASE)
        if match:
            json_str = match.group(1)
        else:
            # 마크다운 블록이 아예 없고, 부가 설명이 섞여 있을 경우를 대비 (첫 '{' 부터 마지막 '}' 까지 추출)
            start_idx = text.find('{')
            end_idx = text.rfind('}')
            if start_idx != -1 and end_idx != -1 and start_idx < end_idx:
                json_str = text[start_idx:end_idx+1]
            else:
                json_str = text
            
        try:
            # strict=False: LLM이 생성한 텍스트에 포함될 수 있는 제어 문자(Control Char) 예외 허용
            return json.loads(json_str, strict=False)
        except json.JSONDecodeError:
            raise ValueError("생성된 텍스트에서 유효한 JSON을 파싱할 수 없습니다:\n" + text)

    def analyze_asis_image_local(
        self, image_bytes: bytes, 
        custom_system_prompt: str = None,
        previous_json: str = None,
        feedback: str = None
    ) -> ScreenAnalysisResult:
        """
        HCP API(Qwen 3.5)를 사용하여 이미지를 분석하고 컴포넌트를 추출합니다.
        """
        # 1. 이미지를 Base64 인코딩
        base64_image = base64.b64encode(image_bytes).decode('utf-8')
        
        system_prompt = custom_system_prompt.strip() if custom_system_prompt and custom_system_prompt.strip() else DEFAULT_PROMPT
        
        user_prompt = USER_PROMPT_BASE
        if previous_json and feedback:
            user_prompt = USER_PROMPT_REVISION.format(previous_json=previous_json, feedback=feedback)

        # 2. OpenAI 호환 API 호출 (타임아웃 및 재시도 로직 추가)
        # --- [LLM 하이퍼파라미터 설정] ---
        # 최대 재시도 횟수: 일시적인 네트워크 장애나 서버 과부하 시 다시 요청할 횟수
        max_retries = LLM_MAX_RETRIES
        
        # 타임아웃(초): API 응답을 기다리는 최대 시간 (복잡한 이미지 분석을 고려하여 여유 있게 설정)
        timeout_seconds = LLM_TIMEOUT_SECONDS
        
        # 최대 토큰 수(Max Tokens): LLM이 생성할 수 있는 최대 텍스트 길이 (JSON 데이터 잘림 방지를 위해 2048 기본값 적용)
        max_tokens = LLM_MAX_TOKENS
        
        # 온도(Temperature): 0.0 ~ 1.0 사이의 값. 정형화된 JSON 포맷을 일관되게 추출하기 위해 0.1(낮은 창의성)로 설정
        temperature = LLM_TEMPERATURE
        
        for attempt in range(max_retries):
            try:
                response = self.client.chat.completions.create(
                    model=self.text_model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": user_prompt},
                                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                            ]
                        }
                    ],
                    max_tokens=max_tokens,
                    temperature=temperature,
                    timeout=timeout_seconds
                )
                output_text = response.choices[0].message.content
                break  # 성공 시 루프 탈출
            except APITimeoutError:
                if attempt == max_retries - 1:
                    raise ValueError(f"LLM API 응답 시간이 초과되었습니다 ({timeout_seconds}초). 서버 상태가 혼잡할 수 있으니 잠시 후 다시 시도해 주세요.")
                logger.warning(f"API 타임아웃 발생, 재시도 중... ({attempt + 1}/{max_retries})")
                # 지수 백오프(Exponential Backoff) 적용: 1초, 2초, 4초 대기
                time.sleep(2 ** attempt)
            except APIConnectionError:
                if attempt == max_retries - 1:
                    raise ValueError("LLM API 서버에 연결할 수 없습니다. 사내망 네트워크 상태를 확인해 주세요.")
                logger.warning(f"API 연결 오류 발생, 재시도 중... ({attempt + 1}/{max_retries})")
                time.sleep(2 ** attempt)

        # 3. JSON 추출 및 Pydantic 검증
        try:
            parsed_dict = self._extract_json_from_text(output_text)
            result = ScreenAnalysisResult(**parsed_dict)
            return result
        except ValidationError as e:
            logger.error(f"Pydantic Validation Error: {e}")
            raise ValueError("모델이 스키마에 맞지 않는 JSON을 생성했습니다.")