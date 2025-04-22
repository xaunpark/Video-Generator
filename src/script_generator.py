# src/script_generator.py
import os
import sys
import time
import json
import requests
import datetime
from dotenv import load_dotenv

from src.logger_config import setup_logger
logger = setup_logger(__name__)

from src.video_styles.base_style import BaseVideoStyle

from src.utils import detect_language, safe_truncate, generate_project_id

from config.credentials import OPENAI_API_KEY, DEEPSEEK_API_KEY
from config.settings import TEMP_DIR, VIDEO_SETTINGS, LLM_PROVIDERS, DEFAULT_LLM_PROVIDER

class ScriptGenerator:
    def __init__(self, selected_provider=None): # Add selected_provider argument
        self.temp_dir = TEMP_DIR

        self.selected_provider_name = selected_provider or DEFAULT_LLM_PROVIDER
        if self.selected_provider_name not in LLM_PROVIDERS:
            logger.warning(f"Selected provider '{self.selected_provider_name}' not found in settings. Falling back to default '{DEFAULT_LLM_PROVIDER}'.")
            self.selected_provider_name = DEFAULT_LLM_PROVIDER
        logger.info(f"Using LLM Provider: {self.selected_provider_name}")

        # Store configurations for the selected provider
        self.provider_config = LLM_PROVIDERS[self.selected_provider_name]

        # Load the correct API key
        self.api_key = None
        api_key_name = self.provider_config.get("api_key_name")
        if api_key_name == "OPENAI_API_KEY":
            self.api_key = OPENAI_API_KEY
        elif api_key_name == "DEEPSEEK_API_KEY":
            self.api_key = DEEPSEEK_API_KEY
        # Add elif for future providers

        if not self.api_key:
            logger.error(f"API key ('{api_key_name}') for selected provider '{self.selected_provider_name}' is missing or empty.")
            raise ValueError(f"API key for {self.selected_provider_name} not found.")

        # Common headers structure (adjust in specific methods if needed)
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        self.base_url = self.provider_config.get("base_url") # Base URL for the selected provider
        self.chat_model = self.provider_config.get("chat_model") # Chat model for the selected provider
        self.supports_json_mode = self.provider_config.get("supports_json_mode", False) # Get JSON support flag

        os.makedirs(self.temp_dir, exist_ok=True)

    # --- HÀM GỌI API ---
    def _call_openai_api_internal(self, system_prompt, user_prompt, model_name, base_url, headers, supports_json, force_json_output, max_retries=3, request_timeout=90):
        """
        Internal method to call OpenAI compatible API.

        Args:
            system_prompt (str): The system message.
            user_prompt (str): The user's prompt.
            model_name (str): The specific model to use (e.g., "gpt-4o").
            base_url (str): The base URL for the API endpoint.
            headers (dict): The request headers (including Authorization).
            supports_json (bool): Whether the selected model/endpoint supports native JSON mode.
            force_json_output (bool): Whether the caller requires JSON output (even if via prompt).
            max_retries (int): Maximum number of retries.
            request_timeout (int): Request timeout in seconds.

        Returns:
            str or None: The content string from the API response, or None on failure.
        """
        payload = {
            "model": model_name, # Dùng tham số
            "messages": [
                {"role": "system", "content": ""}, # Sẽ đặt lại bên dưới
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.7, # Có thể điều chỉnh hoặc đưa ra settings
            # "max_tokens": 4096, # Cân nhắc thêm giới hạn token nếu cần
        }

        system_prompt_to_use = system_prompt # Bắt đầu với prompt gốc

        # Add JSON mode if supported and requested by the caller
        if force_json_output and supports_json:
            payload["response_format"] = {"type": "json_object"}
            # Adjust system prompt specifically for JSON mode for better compliance
            system_prompt_to_use = "You are a helpful assistant designed to output JSON. Respond ONLY with the valid JSON object requested, without any introductory text, explanations, or markdown formatting."
            logger.debug(f"OpenAI/Compatible API ({model_name}): Using native JSON mode.")
        elif force_json_output and not supports_json:
             # Nếu cần JSON nhưng model không hỗ trợ native JSON mode (trường hợp ít gặp với OpenAI, nhưng có thể cho các API tương thích khác)
             # --> Yêu cầu JSON qua prompt.
             logger.warning(f"OpenAI/Compatible API ({model_name}): Native JSON mode not supported or requested off. Modifying user prompt to request JSON within markers.")
             json_request_instruction = (
                 "\n\n"
                 "CRITICAL REQUIREMENT: Your *entire response* MUST be ONLY the valid JSON object requested in the prompt above. "
                 "Enclose this JSON object within triple backticks followed by 'json' like this:\n"
                 "```json\n"
                 "{\n"
                 '  "key": "value",\n'
                 '  ...\n'
                 "}\n"
                 "```\n"
                 "DO NOT include ANY introduction, explanation, concluding remarks, or any other text outside the ```json ... ``` markers."
             )
             payload["messages"][1]["content"] = user_prompt + json_request_instruction # Cập nhật user prompt
             # system_prompt_to_use giữ nguyên là system_prompt gốc

        # Set the final system prompt in the payload
        payload["messages"][0]["content"] = system_prompt_to_use.strip()

        # Xác định URL endpoint hoàn chỉnh
        url = f"{base_url}/chat/completions" # Dùng tham số base_url

        # --- Retry Loop ---
        attempt = 0
        while attempt < max_retries:
            attempt += 1
            try:
                # Log chi tiết hơn về request
                logger.debug(f"Calling OpenAI/Compatible API (Attempt {attempt}/{max_retries}, Model: {model_name}, URL: {url}, Timeout: {request_timeout}s)...")
                # Log payload nếu cần debug (cẩn thận với dữ liệu nhạy cảm)
                # logger.debug(f"Request Payload (Attempt {attempt}): {json.dumps(payload, indent=2)}")

                response = requests.post(url, headers=headers, json=payload, timeout=request_timeout) # Dùng tham số headers

                logger.debug(f"API Response Status Code: {response.status_code}") # Log status code

                response.raise_for_status() # Kiểm tra lỗi HTTP (4xx, 5xx)

                data = response.json()
                # Log raw response nếu cần debug
                # logger.debug(f"Raw JSON Response (Attempt {attempt}): {data}")

                if 'choices' in data and data['choices']:
                    message_content = data['choices'][0].get('message', {}).get('content')
                    # Kiểm tra None hoặc chuỗi rỗng
                    if message_content is not None and message_content.strip() != "":
                        content = message_content.strip()
                        logger.debug(f"OpenAI/Compatible API call successful (Attempt {attempt}). Content length: {len(content)}")
                        return content # Trả về chuỗi nội dung thô
                    elif message_content is None:
                         logger.warning(f"API response has 'content: null' (Attempt {attempt}/{max_retries}).")
                         # Có thể thử lại hoặc thất bại ngay
                    else: # Chuỗi rỗng ''
                         logger.warning(f"API response has empty string content '' (Attempt {attempt}/{max_retries}).")
                else:
                    logger.warning(f"Invalid API response structure - 'choices' missing or empty (Attempt {attempt}/{max_retries}): {data}")

            except requests.exceptions.Timeout:
                logger.warning(f"OpenAI/Compatible API call timed out after {request_timeout}s (Attempt {attempt}/{max_retries}). Retrying...")
            except requests.exceptions.RequestException as e:
                 # Log lỗi request chi tiết hơn
                 err_msg = f"OpenAI/Compatible API request error (Attempt {attempt}/{max_retries}, Model: {model_name}): {type(e).__name__} - {e}"
                 status_code = -1
                 resp_text = "N/A"
                 if hasattr(e, 'response') and e.response is not None:
                     status_code = e.response.status_code
                     try: resp_text = e.response.text[:500] # Giới hạn độ dài log
                     except Exception: resp_text = "[Could not decode response text]"
                     err_msg += f" | Status: {status_code}, Response: {resp_text}"
                 logger.error(err_msg)

                 # Dừng retry nếu lỗi client (trừ rate limit, auth, ...)
                 if 400 <= status_code < 500 and status_code not in [401, 403, 429]:
                      logger.error("Client error detected, stopping retries.")
                      break
            except json.JSONDecodeError as json_err:
                 # Lỗi khi response không phải JSON hợp lệ (vd: trang lỗi HTML)
                 logger.error(f"Failed to decode JSON response from API (Attempt {attempt}/{max_retries}): {json_err}")
                 logger.debug(f"Raw Response Text (First 500 chars): {response.text[:500] if response else 'No Response Object'}")
                 break # Thường không retry lỗi decode JSON
            except Exception as e:
                # Bắt các lỗi không mong muốn khác
                logger.error(f"Unexpected error type {type(e).__name__} calling API (Attempt {attempt}/{max_retries}): {e}", exc_info=True)
                break # Có thể dừng retry với lỗi không rõ

            # Logic chờ trước khi retry
            if attempt < max_retries:
                wait_time = 2 ** attempt
                logger.info(f"Waiting {wait_time}s before retrying API call...")
                time.sleep(wait_time)

        # Nếu vòng lặp kết thúc mà không thành công
        logger.error(f"Failed to get valid response from OpenAI/Compatible API (Model: {model_name}) after {max_retries} attempts.")
        return None
    
    def _call_deepseek_api_internal(self, system_prompt, user_prompt, model_name, base_url, headers, supports_json, force_json_output, max_retries=3, request_timeout=90):
        """
        Internal method to call DeepSeek API.

        Args:
            system_prompt (str): The system message.
            user_prompt (str): The user's prompt.
            model_name (str): The specific model to use (e.g., "deepseek-chat", "deepseek-reasoner").
            base_url (str): The base URL for the API endpoint.
            headers (dict): The request headers (including Authorization).
            supports_json (bool): Whether the selected model/endpoint supports native JSON mode.
            force_json_output (bool): Whether the caller requires JSON output (even if via prompt).
            max_retries (int): Maximum number of retries.
            request_timeout (int): Request timeout in seconds.

        Returns:
            str or None: The content string from the API response, or None on failure.
        """
        # Xác định URL endpoint hoàn chỉnh
        url = f"{base_url}/chat/completions" # Dùng tham số base_url

        # Khởi tạo payload cơ bản
        payload = {
            "model": model_name, # Dùng tham số model_name
            "messages": [
                {"role": "system", "content": ""}, # Sẽ đặt lại bên dưới
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.7, # Có thể điều chỉnh hoặc đưa ra settings
            # "max_tokens": 4096, # Cân nhắc giới hạn nếu cần
        }

        system_prompt_to_use = system_prompt # Bắt đầu với prompt gốc

        # --- JSON Mode Handling specific to DeepSeek ---
        if force_json_output: # Kiểm tra xem có yêu cầu JSON không
            if supports_json: # Kiểm tra xem model có hỗ trợ JSON mode gốc không
                # --- Trường hợp: Có yêu cầu JSON VÀ model hỗ trợ (deepseek-chat) ---
                payload["response_format"] = {'type': 'json_object'}
                # Sử dụng system prompt đặc biệt cho JSON mode gốc của DeepSeek
                system_prompt_to_use = f"""
                You are an assistant that outputs ONLY valid JSON objects. Ensure your entire response is a single JSON object matching the structure requested or exemplified in the user prompt. Include the word "json" in your thinking process if needed, but the final output must be ONLY the JSON itself.
                Original system instruction (if any): {system_prompt}
                """
                logger.debug(f"DeepSeek API ({model_name}): Using native JSON mode.")
            else:
                # --- Trường hợp: Có yêu cầu JSON NHƯNG model KHÔNG hỗ trợ (deepseek-reasoner) ---
                # --> Phải yêu cầu JSON thông qua prompt engineering.
                logger.warning(f"DeepSeek API ({model_name}): Native JSON mode not supported. Modifying user prompt to request JSON within markers.")
                # Instruction yêu cầu JSON trong dấu ```json``` (đã tăng cường ở bước trước)
                json_request_instruction = (
                    "\n\n"
                    "CRITICAL REQUIREMENT: Your *entire response* MUST be ONLY the valid JSON object requested in the prompt above. "
                    "Enclose this JSON object within triple backticks followed by 'json' like this:\n"
                    "```json\n"
                    "{\n"
                    '  "key": "value",\n'
                    '  ...\n'
                    "}\n"
                    "```\n"
                    "DO NOT include ANY introduction, explanation, concluding remarks, or any other text outside the ```json ... ``` markers."
                )
                payload["messages"][1]["content"] = user_prompt + json_request_instruction # Cập nhật user prompt
                # system_prompt_to_use giữ nguyên là system_prompt gốc vì hướng dẫn chính nằm ở user_prompt
        # else: (force_json_output is False)
             # Không yêu cầu JSON, sử dụng system_prompt gốc
             # logger.debug(f"DeepSeek API ({model_name}): Not requesting JSON output.")
             # system_prompt_to_use giữ nguyên

        # Set the final system prompt in the payload
        payload["messages"][0]["content"] = system_prompt_to_use.strip()

        # --- Retry Loop (Improved Logging) ---
        attempt = 0
        while attempt < max_retries:
            attempt += 1
            try:
                # Log request details (cẩn thận với dữ liệu nhạy cảm)
                # logger.debug(f"DeepSeek Request Payload (Attempt {attempt}): {json.dumps(payload, indent=2)}")
                logger.debug(f"Calling DeepSeek API (Attempt {attempt}/{max_retries}, Model: {model_name}, URL: {url}, Timeout: {request_timeout}s)...") # Dùng model_name

                response = requests.post(url, headers=headers, json=payload, timeout=request_timeout) # Dùng tham số headers

                logger.debug(f"DeepSeek Response Status Code: {response.status_code}") # Log status code

                response.raise_for_status() # Check for HTTP errors (4xx, 5xx)

                data = response.json()
                # Log raw response nếu cần debug
                # logger.debug(f"DeepSeek Raw JSON Response (Attempt {attempt}): {data}")

                if 'choices' in data and data['choices']:
                    message_content = data['choices'][0].get('message', {}).get('content')
                    # Check specifically for None or empty string
                    if message_content is not None and message_content.strip() != "":
                        content = message_content.strip()
                        logger.debug(f"DeepSeek API call successful (Attempt {attempt}). Content length: {len(content)}")
                        return content # Return the raw content string
                    elif message_content is None:
                         logger.warning(f"API response has 'content: null' (Attempt {attempt}/{max_retries}). DeepSeek might return this with JSON mode sometimes.")
                         # Có thể thử lại hoặc thất bại ngay
                    else: # Empty string ''
                         logger.warning(f"API response has empty string content '' (Attempt {attempt}/{max_retries}).")
                else:
                    logger.warning(f"Invalid API response structure - 'choices' missing or empty (Attempt {attempt}/{max_retries}): {data}")

            except requests.exceptions.Timeout:
                logger.warning(f"DeepSeek API call timed out after {request_timeout}s (Attempt {attempt}/{max_retries}). Retrying...")
            except requests.exceptions.RequestException as e:
                # Log lỗi request chi tiết hơn
                err_msg = f"DeepSeek API request error (Attempt {attempt}/{max_retries}, Model: {model_name}): {type(e).__name__} - {e}" # Thêm model_name vào log lỗi
                status_code = -1
                resp_text = "N/A"
                if hasattr(e, 'response') and e.response is not None:
                    status_code = e.response.status_code
                    try: resp_text = e.response.text[:500] # Giới hạn độ dài log
                    except Exception: resp_text = "[Could not decode response text]"
                    err_msg += f" | Status: {status_code}, Response: {resp_text}"
                logger.error(err_msg)

                # Dừng retry nếu lỗi client (trừ rate limit, auth, ...)
                if 400 <= status_code < 500 and status_code not in [401, 403, 429]:
                    logger.error("Client error detected, stopping retries.")
                    break
            except json.JSONDecodeError as json_err:
                 # Lỗi khi response không phải JSON hợp lệ (vd: trang lỗi HTML)
                 logger.error(f"Failed to decode JSON response from DeepSeek API (Attempt {attempt}/{max_retries}): {json_err}")
                 logger.debug(f"Raw Response Text (First 500 chars): {response.text[:500] if response else 'No Response Object'}")
                 break # Thường không retry lỗi decode JSON
            except Exception as e:
                # Bắt các lỗi không mong muốn khác
                logger.error(f"Unexpected error type {type(e).__name__} calling DeepSeek API (Attempt {attempt}/{max_retries}): {e}", exc_info=True)
                break # Có thể dừng retry với lỗi không rõ

            # Logic chờ trước khi retry
            if attempt < max_retries:
                wait_time = 2 ** attempt
                logger.info(f"Waiting {wait_time}s before retrying DeepSeek API call...")
                time.sleep(wait_time)

        # Nếu vòng lặp kết thúc mà không thành công
        logger.error(f"Failed to get valid response from DeepSeek API (Model: {model_name}) after {max_retries} attempts.") # Thêm model_name vào log lỗi
        return None

    def _call_llm_api(self, user_prompt, system_prompt="You are a helpful assistant.", max_retries=3, request_timeout=90, require_json=True, is_core_content_task=True):
        """
        Calls the selected LLM provider's API, potentially overriding for non-core tasks.

        Args:
            user_prompt (str): The user's prompt.
            system_prompt (str): The system message/instruction.
            max_retries (int): Number of retries on failure.
            request_timeout (int): Timeout in seconds for the request.
            require_json (bool): If True, expects a JSON string response. If provider
                                 doesn't support native JSON mode, prompt is modified
                                 and output needs parsing.
            is_core_content_task (bool): If False, and Reasoner was selected, use default provider.

        Returns:
            str or None: The content string from the LLM response, or None on failure.
                         If require_json is True and native JSON mode isn't supported,
                         this might return a string containing JSON within markdown markers.
        """
        # --- XÁC ĐỊNH PROVIDER VÀ CẤU HÌNH SẼ DÙNG ---
        provider_key_to_use = self.selected_provider_name
        provider_config_to_use = self.provider_config
        supports_json_mode_to_use = self.supports_json_mode
        api_key_to_use = self.api_key # Lấy API key tương ứng với provider đã chọn ban đầu

        # Logic override nếu người dùng chọn Reasoner nhưng task không phải core
        if self.selected_provider_name == "deepseek_reasoner" and not is_core_content_task:
            default_provider_key = DEFAULT_LLM_PROVIDER # Lấy default từ settings
            if default_provider_key != "deepseek_reasoner": # Chỉ override nếu default khác Reasoner
                logger.info(f"Non-core task: User selected Reasoner, overriding to default provider '{default_provider_key}'.")
                provider_key_to_use = default_provider_key
                if provider_key_to_use in LLM_PROVIDERS:
                    provider_config_to_use = LLM_PROVIDERS[provider_key_to_use]
                    supports_json_mode_to_use = provider_config_to_use.get("supports_json_mode", False)
                    # LẤY ĐÚNG API KEY CHO PROVIDER MẶC ĐỊNH
                    default_api_key_name = provider_config_to_use.get("api_key_name")
                    if default_api_key_name == "OPENAI_API_KEY":
                        api_key_to_use = OPENAI_API_KEY
                    elif default_api_key_name == "DEEPSEEK_API_KEY":
                        api_key_to_use = DEEPSEEK_API_KEY
                    # Add elif for future default providers if needed
                    if not api_key_to_use:
                        logger.error(f"API Key for default provider '{default_provider_key}' is missing! Reverting to Reasoner for this call.")
                        # Hoặc raise lỗi ở đây nếu muốn chặt chẽ hơn
                        provider_key_to_use = self.selected_provider_name # Revert về Reasoner nếu key default thiếu
                        provider_config_to_use = self.provider_config
                        supports_json_mode_to_use = self.supports_json_mode
                        api_key_to_use = self.api_key # Revert key
                else:
                    logger.error(f"Default provider '{default_provider_key}' not found in LLM_PROVIDERS config! Reverting to Reasoner for this call.")
                    provider_key_to_use = self.selected_provider_name # Revert về Reasoner nếu default config lỗi
                    provider_config_to_use = self.provider_config
                    supports_json_mode_to_use = self.supports_json_mode
                    # api_key_to_use giữ nguyên của Reasoner
            else:
                 # Default provider LÀ Reasoner hoặc người dùng chọn Reasoner và task LÀ core
                 logger.debug(f"Task type core={is_core_content_task}. Using initially selected provider (DeepSeek Reasoner).")
                 # Không cần làm gì thêm, các biến đã đúng
        else:
             # Trường hợp người dùng không chọn Reasoner ban đầu
             logger.debug(f"Task type core={is_core_content_task}. Using initially selected provider: {provider_key_to_use}")
             # Không cần làm gì thêm, các biến đã đúng

        # Lấy thông tin cụ thể từ cấu hình đã chọn (config và key đã được xác định ở trên)
        model_to_use = provider_config_to_use.get("chat_model")
        base_url_to_use = provider_config_to_use.get("base_url")
        headers_to_use = {
            "Authorization": f"Bearer {api_key_to_use}",
            "Content-Type": "application/json"
        }
        # --- KẾT THÚC XÁC ĐỊNH PROVIDER ---

        logger.info(f"Executing LLM call with: Provider='{provider_key_to_use}', Model='{model_to_use}', SupportsJSON={supports_json_mode_to_use}, RequireJSON={require_json}")

        content = None
        # --- SỬ DỤNG provider_key_to_use để quyết định gọi hàm nào ---
        # --- VÀ TRUYỀN CÁC THAM SỐ CẤU HÌNH VÀO HÀM NỘI BỘ ---
        if provider_key_to_use == "openai":
            content = self._call_openai_api_internal(
                system_prompt=system_prompt, user_prompt=user_prompt,
                model_name=model_to_use, base_url=base_url_to_use, headers=headers_to_use,
                supports_json=supports_json_mode_to_use, # Đã đổi tên tham số
                force_json_output=require_json, # Đã đổi tên tham số
                max_retries=max_retries, request_timeout=request_timeout
            )
        elif provider_key_to_use in ["deepseek", "deepseek_reasoner"]: # Gộp cả hai deepseek
            content = self._call_deepseek_api_internal(
                system_prompt=system_prompt, user_prompt=user_prompt,
                model_name=model_to_use, base_url=base_url_to_use, headers=headers_to_use,
                supports_json=supports_json_mode_to_use, # Đã đổi tên tham số
                force_json_output=require_json, # Đã đổi tên tham số
                max_retries=max_retries, request_timeout=request_timeout
            )
        # Add elif for future providers
        else:
            logger.error(f"LLM provider '{provider_key_to_use}' is not implemented.")
            return None

        # --- Post-processing for JSON if native mode wasn't supported ---
        # SỬ DỤNG supports_json_mode_to_use đã xác định ở trên
        if content and require_json and not supports_json_mode_to_use:
            logger.debug(f"Attempting to extract JSON from response (Provider: {provider_key_to_use}, Native JSON support: {supports_json_mode_to_use})...")
            import re
            # Try to find JSON within ```json ... ``` markers
            match = re.search(r"```json\s*(\{.*?\})\s*```", content, re.DOTALL | re.IGNORECASE) # Thêm IGNORECASE
            if match:
                json_string = match.group(1).strip() # Lấy group 1 và strip()
                # Basic validation: Bắt đầu bằng { và kết thúc bằng }
                if json_string.startswith('{') and json_string.endswith('}'):
                    logger.debug("Successfully extracted JSON from markdown markers.")
                    # Thử parse để đảm bảo nó là JSON hợp lệ trước khi trả về
                    try:
                        json.loads(json_string)
                        return json_string # Trả về string JSON đã trích xuất
                    except json.JSONDecodeError as parse_err:
                         logger.warning(f"Found markers, but content inside failed JSON parsing: {parse_err}")
                         logger.debug(f"Extracted invalid JSON string: {json_string[:200]}...")
                         return None # Coi như thất bại nếu không parse được
                else:
                    logger.warning("Found markers, but content inside doesn't look like a JSON object (doesn't start/end with {}).")
                    logger.debug(f"Content inside markers: {json_string[:200]}...")
                    return None # Failed to extract valid JSON object
            else:
                 # Nếu không có markers, thử kiểm tra xem toàn bộ content có phải JSON không
                 # Loại bỏ khoảng trắng đầu/cuối trước khi kiểm tra
                 trimmed_content = content.strip()
                 if trimmed_content.startswith('{') and trimmed_content.endswith('}'):
                     logger.debug("Response seems to be JSON directly (no markers found).")
                     # Thử parse để đảm bảo hợp lệ
                     try:
                         json.loads(trimmed_content)
                         return trimmed_content # Trả về toàn bộ nội dung nếu parse thành công
                     except json.JSONDecodeError as parse_err:
                          logger.warning(f"Content looks like JSON but failed parsing: {parse_err}")
                          logger.debug(f"Direct content received: {trimmed_content[:200]}...")
                          return None # Coi như thất bại
                 else:
                     logger.warning("Could not extract JSON from response (no markers and not direct JSON object).")
                     logger.debug(f"Raw content received: {content[:200]}...")
                     return None # Failed to extract JSON

        # If JSON wasn't required, or if native JSON mode was used and successful,
        # or if extraction failed but require_json was False, return content directly.
        return content

    # --- Chia Câu thành Shots ---
    def _breakdown_sentence_into_shots(self, sentence_text, target_style_tone):
        """Yêu cầu OpenAI chia một câu/đoạn văn thành các shots ngắn."""
        logger.debug(f"Step 2: Breaking down sentence: '{sentence_text[:100]}...'")
        
        # --- Xây dựng Prompt cho Bước 2 ---
        prompt_step2 = f"""
        Your task is to break down the provided narrative sentence into shorter visual "shots" for a video script, BUT **only when truly necessary** for visual clarity or pacing. Your default preference should be to **KEEP the sentence as ONE single shot**.

        **Guiding Principles (Apply Strictly):**

        1.  **Prioritize No Splitting:** Keep the entire sentence as a single shot unless there is a compelling reason to split based on the criteria below.
        2.  **Split Reason 1: Distinct Visual Concepts:** ONLY split the sentence if it clearly contains **multiple, distinct visual actions, subjects, or concepts** that would benefit significantly from separate visual representations (different images/video clips). Ask yourself: "Does this sentence describe things that look visually different and should appear sequentially?"
        3.  **Split Reason 2: Pacing & Emphasis (Use Sparingly):** Occasionally, splitting a slightly longer sentence *at a natural pause* (like a comma or conjunction) can improve pacing or emphasize a key phrase. However, this should be secondary to visual distinctness.
        4.  **Word Count as a *Guideline Only*:**
            *   Sentences under ~12-15 words: **Almost NEVER split.**
            *   Sentences ~15-25 words: **Strongly prefer keeping as ONE shot.** Only split if there are very clearly distinct visual elements AND a natural grammatical break point.
            *   Sentences over ~25-30 words: **Consider splitting more seriously**, BUT STILL prioritize splitting based on distinct visual concepts first. If the long sentence describes one continuous action or idea, keeping it as one shot might still be best.
        5.  **Context Matters (Previous Sentence):** If the *previous* sentence/speech unit was already split into multiple shots, be **EXTREMELY reluctant** to split the current sentence. Avoid sequences of many short shots unless the style is intentionally very fast-paced and choppy ({target_style_tone}).
        6.  **Maintain Cohesion:** Do NOT split in a way that breaks a single, cohesive thought, a proper name, or a tightly linked phrase (e.g., don't split "New York City" or "state-of-the-art technology").
        7.  **Shot Length Goal (If Splitting):** If you *do* split, aim for resultant shots between ~7 and 18 words. Avoid creating extremely short shots (< 5 words) unless absolutely necessary for dramatic effect.

        **OUTPUT FORMAT (JSON ONLY):**
        Return ONLY a valid JSON object containing a list of the resulting shot texts.
        {{
        "shots": ["Shot 1 text", "Shot 2 text", ...] // This list might contain only one element if no split was needed.
        }}

        **EXAMPLES (Illustrating the Philosophy):**

        *Input:* "The vibrant coral reef teemed with colorful fish and intricate sea anemones."
        *Analysis:* Describes one overall scene, even with multiple elements. No strong need to split visually.
        *Output:* `{{"shots": ["The vibrant coral reef teemed with colorful fish and intricate sea anemones."]}}`

        *Input:* "Researchers announced the discovery, then immediately began analyzing the samples in the lab."
        *Analysis:* Two distinct actions/locations (announcement, analysis in lab). Splitting is justified for visual clarity.
        *Output:* `{{"shots": ["Researchers announced the discovery,", "then immediately began analyzing the samples in the lab."]}}`

        *Input:* "Economic indicators showed slow growth in the first quarter, raising concerns among investors about future market stability and potential downturns."
        *Analysis:* Long sentence (>30 words). Concepts: "slow growth", "investor concerns", "market stability", "potential downturns". Could potentially be 3 shots based on visual concepts.
        *Output:* `{{"shots": ["Economic indicators showed slow growth in the first quarter,", "raising concerns among investors about future market stability", "and potential downturns."]}}` (Or potentially just 2 shots if "stability" and "downturns" are visually similar).

        *Input:* "The newly elected president promised sweeping reforms across multiple sectors."
        *Analysis:* Around 10 words. Clearly one concept. No split needed.
        *Output:* `{{"shots": ["The newly elected president promised sweeping reforms across multiple sectors."]}}`

        **TEXT TO BREAK DOWN (Apply Principles Above):**
        "{sentence_text}"
        """

        # --- Gọi API cho Bước 2 ---
        response_json_str = self._call_llm_api(
            user_prompt=prompt_step2,
            request_timeout=45,
            require_json=True,
            is_core_content_task=False, # Không phải core task, dùng LLM mặc định ngay cả khi DeepSeek Reasoner được chọn
        )
        if not response_json_str:
            logger.warning(f"Step 2 Failed: No response from API for breaking down sentence.")
            return None # Trả về None nếu không breakdown được

        # --- Parse và Validate kết quả Bước 2 ---
        try:
            data_step2 = json.loads(response_json_str)
            if not isinstance(data_step2, dict) or \
               "shots" not in data_step2 or not isinstance(data_step2["shots"], list) or \
               not data_step2["shots"]: # Phải có ít nhất 1 shot
                logger.warning(f"Step 2 Failed: Invalid JSON structure or empty shots list received: {data_step2}")
                return None
            # Kiểm tra xem các phần tử có phải string không
            if not all(isinstance(s, str) for s in data_step2["shots"]):
                 logger.warning(f"Step 2 Failed: Not all items in 'shots' are strings: {data_step2['shots']}")
                 return None

            logger.debug(f"Step 2 Success: Broke sentence into {len(data_step2['shots'])} shots.")
            return data_step2["shots"] # Chỉ trả về list các strings
        except json.JSONDecodeError as e:
            logger.warning(f"Step 2 Failed: Could not decode JSON response: {e}")
            logger.debug(f"Received content: {response_json_str}")
            return None
        except Exception as e:
            logger.warning(f"Step 2 Failed: Unexpected error parsing result: {e}", exc_info=True)
            return None

    # --- Gộp logic xử lý Basic/Advanced vào một hàm nội bộ duy nhất ---
    def _generate_script_internal(self, source_data: dict, style_strategy: BaseVideoStyle, language: str, video_mode: str, project_id: str) -> dict | None:
        """
        Hàm nội bộ xử lý logic tạo script chính, phân nhánh Basic/Advanced.
        """
        style_config = style_strategy.get_style_config()
        style_tone = style_config.get('tone', 'Unknown')
        input_type = source_data.get('type', 'unknown') # Lấy type từ source_data

        logger.info(f"Internal generation for project '{project_id}' (Input: {input_type}, Style: {style_tone}, Mode: {video_mode})")

        # --- Xác định chế độ thực thi ---
        use_advanced_layout = style_strategy.should_override_layout() or video_mode == "advanced"
        # ... (log và xử lý conflict mode như trước) ...
        if use_advanced_layout and video_mode == "basic" and style_strategy.should_override_layout(): logger.info(...)
        elif not use_advanced_layout and video_mode == "advanced" and not style_strategy.should_override_layout(): logger.warning(...); video_mode = "basic" # Sửa lại video_mode

        script_result = None

        # --- Luồng Advanced ---
        if use_advanced_layout:
            logger.info("Processing in Advanced (Chapters) mode...")
            # === STAGE 1: LAYOUT ===
            layout_data = self._generate_video_layout(source_data, style_strategy, language)
            if not layout_data: return None

            # === STAGE 2: CONTENT ===
            all_chapters_sentences = {}
            for chapter_outline in layout_data.get('layout', []):
                chapter_num = chapter_outline.get('chapter_number')
                if chapter_num is None: continue
                chapter_sentences = self._generate_chapter_content(source_data, layout_data, chapter_outline, style_strategy, language)
                if chapter_sentences is None: return None
                all_chapters_sentences[chapter_num] = chapter_sentences
            if not all_chapters_sentences: return None

            # === STAGE 3: ASSEMBLE ===
            # Chuẩn bị source_info dựa trên input_type
            source_info_for_assembly = {
                'source': f"AI Gen ({input_type})", # Tên nguồn chung hơn
                'url': f"{input_type}://{project_id}",
                'image_url': None,
                'keyword': None
            }
            if input_type == 'article':
                article_data = source_data.get('data', {})
                source_info_for_assembly['source'] = article_data.get('source', 'Unknown Article')
                source_info_for_assembly['url'] = article_data.get('url', '')
                source_info_for_assembly['image_url'] = article_data.get('image_url')
            elif input_type == 'keyword':
                source_info_for_assembly['keyword'] = source_data.get('data')
                source_info_for_assembly['url'] = f"keyword_chapters://{source_data.get('data')}"
            elif input_type == 'text':
                 context_hint = source_data.get('context', 'Input Text')
                 source_info_for_assembly['source'] = f"AI Gen from Text (Chapters - {context_hint})"
                 source_info_for_assembly['url'] = f"text_chapters://{project_id}"


            script_result = self._assemble_final_script(
                project_id, layout_data, all_chapters_sentences,
                style_strategy, language, input_type, source_info_for_assembly
            )
            if script_result: logger.info("Advanced script assembly successful.")

        # --- Luồng Basic ---
        else: # if not use_advanced_layout
            logger.info("Processing in Basic mode...")
            # === STEP 1: GET INITIAL SENTENCES ===
            prompt_step1 = style_strategy.generate_script_prompt(source_data, language, 'basic')
            if "Error:" in prompt_step1: return None
            response_json_str = self._call_llm_api(user_prompt=prompt_step1, require_json=True, request_timeout=180)
            initial_script_data = None
            if response_json_str:
                 try: initial_script_data = json.loads(response_json_str); #... validate ...
                 except: initial_script_data = None
            if not initial_script_data: return None

            final_title = initial_script_data.get("title", "Untitled")
            initial_sentences = initial_script_data.get("initial_scenes", [])

            # === STEP 2: BREAKDOWN SENTENCES (LLM CALLS) ===
            final_scenes = []
            final_speech_units = []
            global_shot_number = 1
            speech_unit_number = 1
            for sentence in initial_sentences:
                 original_sentence = sentence.strip()
                 if not original_sentence: continue
                 shots_for_sentence = self._breakdown_sentence_into_shots(original_sentence, style_tone)
                 if not shots_for_sentence: shots_for_sentence = [original_sentence]
                 # ... (logic tạo final_scenes, final_speech_units như cũ) ...
                 shot_numbers_for_this_unit = []; valid_shots_found = False
                 if shots_for_sentence:
                     for shot_content in shots_for_sentence:
                          shot_content_stripped = shot_content.strip()
                          if not shot_content_stripped: continue
                          final_scenes.append({"number": global_shot_number, "content": shot_content_stripped})
                          shot_numbers_for_this_unit.append(global_shot_number)
                          global_shot_number += 1; valid_shots_found = True
                 if valid_shots_found:
                     final_speech_units.append({"unit_number": speech_unit_number,"text": original_sentence,"scene_numbers": shot_numbers_for_this_unit})
                     speech_unit_number += 1

            if not final_scenes or not final_speech_units: return None

            # === STEP 3: ANALYZE SHOTS ===
            logger.info("Analyzing scenes for video clip suitability...")
            # Gọi hàm phân tích cho danh sách scenes cuối cùng
            analysis_results = self._analyze_shots_for_video_batch(final_scenes)

            if analysis_results:
                logger.info(f"Updating {len(final_scenes)} scenes with video preference analysis results...")
                updated_scene_count = 0
                for scene in final_scenes:
                    scene_num = scene.get('number')
                    if scene_num is not None:
                        # Lấy kết quả phân tích (True/False) cho scene này, mặc định là False nếu không tìm thấy
                        prefer_video_flag = analysis_results.get(scene_num, False)
                        # Thêm hoặc cập nhật key 'prefer_video' vào dictionary của scene
                        scene['prefer_video'] = prefer_video_flag
                        if prefer_video_flag:
                            updated_scene_count += 1
                    else:
                        # Xử lý trường hợp scene không có 'number' (dù không nên xảy ra)
                        scene['prefer_video'] = False
                logger.info(f"Marked {updated_scene_count} scenes as preferring video.")
            else:
                # Log nếu phân tích bị tắt, lỗi hoặc không trả về kết quả hợp lệ
                logger.warning("Video analysis skipped or failed. Proceeding without 'prefer_video' flags in scenes.")
                # Đảm bảo key 'prefer_video' tồn tại và là False nếu không có phân tích
                for scene in final_scenes:
                    scene['prefer_video'] = False
            # === KẾT THÚC BƯỚC PHÂN TÍCH VIDEO PREFERENCE ===

            # === STEP 4: CREATE FINAL SCRIPT OBJECT ===
            is_ai_gen = input_type in ['keyword', 'text']
            # Tạo source_info tương tự như advanced nhưng cho basic
            final_source = f"AI Gen ({input_type})"
            final_url = f"{input_type}://{project_id}"
            final_image_url = None
            final_keyword = None
            if input_type == 'article':
                 article_data = source_data.get('data', {})
                 final_source = article_data.get('source', 'Unknown Article')
                 final_url = article_data.get('url', '')
                 final_image_url = article_data.get('image_url')
            elif input_type == 'keyword':
                 final_keyword = source_data.get('data')
                 final_url = f"keyword://{final_keyword}"
            elif input_type == 'text':
                  context_hint = source_data.get('context', 'Input Text')
                  final_source = f"AI Gen from Text ({context_hint})"
                  final_url = f"text://{project_id}"

            script_result = {
                "project_id": project_id,
                "title": final_title,
                "scenes": final_scenes,
                "speech_units": final_speech_units,
                "source": final_source,
                "url": final_url,
                "image_url": final_image_url,
                "style": style_tone,
                "language": language,
                "script_mode": "basic",
                "is_ai_generated": is_ai_gen,
                "creation_timestamp": datetime.datetime.now().isoformat()
            }
            if final_keyword: script_result['keyword'] = final_keyword
            logger.info("Basic script generation successful.")

        # --- RETURN CHO CẢ HAI LUỒNG ---
        return script_result # Trả về dict script hoặc None nếu lỗi

    # --- Tạo Script với INPUT là ARTICLE (RSS, ARTICLE URL) ---
    def generate_script_from_article(self, article, style_strategy: BaseVideoStyle, language=None, video_mode="basic"):
        """
        Tạo kịch bản cho article bằng cách gọi hàm xử lý nội bộ.
        """
        project_id = generate_project_id(article.get('title', ''))
        source_data = {'type': 'article', 'data': article}

        return self._generate_script_internal(source_data, style_strategy, language, video_mode, project_id)

    # --- Tạo Script với INPUT là KEYWORD ---
    def generate_script_from_keyword(self, keyword, style_strategy: BaseVideoStyle, language=None, video_mode="basic"):
        """
        Tạo kịch bản từ từ khóa bằng cách gọi hàm xử lý nội bộ.
        """
        project_id = generate_project_id(keyword)
        source_data = {'type': 'keyword', 'data': keyword}

        return self._generate_script_internal(source_data, style_strategy, language, video_mode, project_id)
        
    # --- Tạo Script với INPUT là TEXT/TRANSCRIPT ---
    def generate_script_from_text(self, input_text, style_strategy: BaseVideoStyle, language="en", context_hint=None, video_mode="basic"):
        """
        Tạo kịch bản từ text bằng cách gọi hàm xử lý nội bộ.
        """
        project_id_hint = context_hint if context_hint else input_text[:50]
        project_id = generate_project_id(project_id_hint)
        source_data = {'type': 'text', 'data': input_text, 'context': context_hint}

        return self._generate_script_internal(source_data, style_strategy, language, video_mode, project_id)
    
    def _generate_video_layout(self, source_data, style_strategy: BaseVideoStyle, language):
        """
        Giai đoạn 1 (Advanced Mode): Tạo layout/outline cho video.
        Sử dụng cấu hình layout_override linh hoạt để xử lý các style đặc biệt
        mà không ảnh hưởng đến các style thông thường.

        Args:
            source_data (dict): Chứa {'type': 'article'/'keyword'/'text', 'data': ..., 'context': ...}.
            style_config (dict): Cấu hình style hiện tại (bao gồm cả layout_override nếu có).
            language (str): Ngôn ngữ ('en', 'vi').

        Returns:
            dict: Dictionary chứa layout {'title': ..., 'layout': [...]} hoặc None nếu lỗi.
        """
        logger.info("Stage 1 (Advanced): Generating video layout/outline...")

        # --- 1. Kiểm tra và Lấy Cấu hình Layout Override ---
        style_config_data = style_strategy.get_style_config() # Lấy config chung
        use_override_layout = style_strategy.should_override_layout()
        layout_params = style_strategy.get_layout_generation_params() if use_override_layout else {}
        target_audience = style_config_data.get("target_audience") # Lấy target audience từ config

        # --- 2. Xác định Tham số Layout Động ---
        if use_override_layout:
            logger.info(f"Using specific layout override instructions for style '{style_config_data.get('tone', 'N/A')}'.")
            ch_min, ch_max = layout_params.get("chapter_count_range", (3, 5))
            wt_min, wt_max = layout_params.get("chapter_word_target_range", (400, 700))
            ttw_min, ttw_max = layout_params.get("target_total_word_range", (1500, 3000))
            raw_structure_instruction = layout_params.get("structure_prompt", "")
            structure_instruction = raw_structure_instruction.format(chapter_count_min=ch_min, chapter_count_max=ch_max) if raw_structure_instruction else ""
        else:
            ch_min, ch_max = (3, 7)
            wt_min, wt_max = (150, 300)
            ttw_min, ttw_max = (0, 0)
            structure_instruction = ""

        # --- 3. Xây dựng Prompt ---
        prompt_step1_layout = f"""
        You are an expert video script outliner and story structure planner.
        Your task is to analyze the provided source material and propose a compelling video structure (layout).
        Focus ONLY on the high-level structure: a main title and a list of logical chapters with titles and brief summaries.
        Do NOT write the detailed script content yet.

        Video Style Context:
        - Tone: {style_config_data['tone']}
        - Goal: {style_config_data.get('goal', 'To inform and engage')}
        """
        if target_audience: # Thêm target audience nếu có
            prompt_step1_layout += f"- Target Audience: {target_audience}\n"

        prompt_step1_layout += f"""

        Source Material:
        """
        # --- 3a. Thêm Source Material (Không đổi so với trước) ---
        input_type = source_data.get('type', 'unknown')
        content_data = source_data.get('data', '')
        context_hint = source_data.get('context', None)
        lang_instruction = "in English" if language == "en" else "bằng tiếng Việt"

        if input_type == 'article':
            prompt_step1_layout += f"- Type: News Article\n"
            prompt_step1_layout += f"- Title: {content_data.get('title', '')}\n"
            prompt_step1_layout += f"- Content to Analyze:\n{safe_truncate(content_data.get('content', ''), 8000)}\n"
            prompt_step1_layout += "\nTask: Based on the article, define a main video title and logical chapters."
        elif input_type == 'keyword':
            prompt_step1_layout += f"- Topic: \"{content_data}\"\n"
            prompt_step1_layout += f"\nTask: Develop a video outline {lang_instruction} about '{content_data}'. Define a main title and logical chapters."
        elif input_type == 'text':
            prompt_step1_layout += f"- Type: Input Text {f'({context_hint})' if context_hint else ''}\n"
            prompt_step1_layout += f"- Text Content to Structure:\n{safe_truncate(content_data, 10000)}\n"
            prompt_step1_layout += f"\nTask: Structure the provided text {lang_instruction} into a video outline. Define a main title and logical chapters."
        else:
            logger.error("Invalid source data type for layout generation.")
            return None
        # --- Kết thúc phần Source Material ---

        # --- 3b. Thêm Chapter Requirements động ---
        prompt_step1_layout += "\n\n**Chapter Requirements:**\n"

        if use_override_layout:
            # Sử dụng các tham số từ layout_override config
            if target_audience:
                prompt_step1_layout += f"- **Target Audience:** Ensure chapter titles and summaries are appropriate for **{target_audience}**.\n"
            if structure_instruction:
                prompt_step1_layout += f"- **Structure Guidance:** {structure_instruction}\n" # Hướng dẫn cấu trúc từ config
            prompt_step1_layout += f"- **Chapter Count:** Create between **{ch_min} and {ch_max}** distinct chapters that fulfill the requested structure.\n"
            prompt_step1_layout += "- **Chapter Titles:** Create concise, engaging, and appropriate `chapter_title` (max 5-7 words) for each chapter.\n"
            prompt_step1_layout += "- **Chapter Summaries:** For each chapter, write a brief `summary` (1-2 sentences) outlining its key content or purpose.\n"
            prompt_step1_layout += f"- **Word Count & Detail Level:** The goal is a substantial total script length (target: {ttw_min}-{ttw_max} words approx). Set an appropriate `word_count_target` (integer) for **each chapter** (typically between **{wt_min} and {wt_max} words per chapter**, adjust based on the chapter's role and the total count). This target indicates the **required depth and detail** for the next writing stage. Ensure the sum aligns reasonably with the total target range.\n"
        else:
            # Yêu cầu mặc định cho các style thông thường
            prompt_step1_layout += f"- Identify **{ch_min} to {ch_max}** distinct, logical sections or themes.\n"
            prompt_step1_layout += f"- For each section, create a concise and engaging `chapter_title` (max 5-7 words).\n"
            prompt_step1_layout += f"- For each section, write a brief `summary` (1-2 sentences) outlining the key points.\n"
            prompt_step1_layout += f"- For each section, estimate an appropriate `word_count_target` (integer, typically between {wt_min}-{wt_max} words, adjust for intro/conclusion). Ensure the value is an integer.\n"

        # --- 3c. Phần Output Format (Không đổi về cấu trúc, nhưng ví dụ word count động) ---
        prompt_step1_layout += f"""

        Output Format:
        Return ONLY a valid JSON object following this exact structure, without explanations or markdown formatting:
        {{
        "title": "Engaging Main Video Title based on Source and Style",
        "layout": [
            {{
            "chapter_number": 1,
            "chapter_title": "Concise Title for Chapter 1",
            "summary": "Brief summary of what Chapter 1 will cover.",
            "word_count_target": {wt_min} // Example: Adjust based on actual chapter role and instructions!
            }},
            {{
            "chapter_number": 2,
            "chapter_title": "Engaging Title for Chapter 2",
            "summary": "Brief summary focusing on Chapter 2's content.",
            "word_count_target": {int((wt_min + wt_max) / 2)} // Example: Adjust based on actual chapter role and instructions!
            }}
            // ... continue for all {ch_min} to {ch_max} chapters
        ]
        }}

        **REMEMBER:** JSON ONLY. No extra text. Ensure `word_count_target` is an integer reflecting the required detail level (higher for styles with layout override).
        """
        # --- Kết thúc xây dựng Prompt ---

        # --- 4. Gọi API (Không đổi) ---
        response_json_str = self._call_llm_api(
            user_prompt=prompt_step1_layout,
            request_timeout=120, # Giữ timeout đủ dài
            require_json=True
        )
        if not response_json_str:
            logger.error("Stage 1 (Advanced) Failed: No response from API for layout generation.")
            return None

        # --- 5. Parse và Validate Kết quả (Cập nhật default word count) ---
        try:
            layout_data = json.loads(response_json_str)

            # Validate cấu trúc cơ bản (không đổi)
            if not isinstance(layout_data, dict) or "title" not in layout_data or not isinstance(layout_data["title"], str) or not layout_data["title"]:
                 logger.error("Stage 1 Failed: Missing or invalid 'title' in layout response.")
                 return None
            if "layout" not in layout_data or not isinstance(layout_data["layout"], list) or not layout_data["layout"]:
                 logger.error("Stage 1 Failed: Missing or invalid 'layout' list in response.")
                 return None

            # Validate từng chapter
            expected_chapter_num = 1
            total_target_words = 0
            num_chapters_generated = len(layout_data["layout"])

            # Cảnh báo nếu số chapter nằm ngoài khoảng mong đợi (lấy từ config hoặc default)
            if not (ch_min <= num_chapters_generated <= ch_max):
                logger.warning(f"Stage 1 Warning: Generated {num_chapters_generated} chapters, outside the expected range of {ch_min}-{ch_max} for this style.")

            for i, chapter in enumerate(layout_data["layout"]):
                if not isinstance(chapter, dict):
                    logger.error(f"Stage 1 Failed: Item at index {i} in 'layout' is not a dictionary.")
                    return None
                # Validate chapter number sequence
                if not chapter.get("chapter_number") == expected_chapter_num:
                    logger.error(f"Stage 1 Failed: Chapter number mismatch. Expected {expected_chapter_num}, got {chapter.get('chapter_number')}.")
                    return None
                # Validate chapter title
                if not isinstance(chapter.get("chapter_title"), str) or not chapter.get("chapter_title"):
                    logger.error(f"Stage 1 Failed: Missing or invalid 'chapter_title' for chapter {expected_chapter_num}.")
                    return None
                # Validate summary (optional string)
                if not isinstance(chapter.get("summary"), str):
                    logger.warning(f"Stage 1 Note: Missing or non-string 'summary' for chapter {expected_chapter_num}. Setting to empty string.")
                    chapter["summary"] = chapter.get("summary", "")
                # Validate word_count_target (positive integer)
                word_target = chapter.get("word_count_target")
                if not isinstance(word_target, int) or word_target <= 0:
                     # Gán default word count dựa trên việc có dùng override hay không
                     default_target = int((wt_min + wt_max) / 2) if use_override_layout else 150 # Default trung bình cho override, 150 cho normal
                     logger.warning(f"Stage 1 Warning: Missing or invalid 'word_count_target' for chapter {expected_chapter_num}. Assigning default {default_target}.")
                     chapter["word_count_target"] = default_target
                     word_target = default_target

                total_target_words += word_target
                expected_chapter_num += 1

            logger.info(f"Stage 1 (Advanced) Success: Generated layout with title '{layout_data['title']}' and {num_chapters_generated} chapters.")
            logger.info(f"  Total Target Word Count across chapters: {total_target_words}")

            # Cảnh báo nếu tổng word count nằm ngoài khoảng mong đợi (chỉ khi dùng override)
            if use_override_layout and not (ttw_min <= total_target_words <= ttw_max):
                logger.warning(f"  Note: Total target word count ({total_target_words}) is outside the configured range ({ttw_min}-{ttw_max}) for this style.")

            return layout_data # Trả về layout đã validate

        except json.JSONDecodeError as e:
            logger.error(f"Stage 1 (Advanced) Failed: Could not decode JSON response for layout: {e}")
            logger.debug(f"Received content: {response_json_str}")
            return None
        except Exception as e:
            logger.error(f"Stage 1 (Advanced) Failed: Unexpected error parsing layout result: {e}", exc_info=True)
            return None
    # --- Kết thúc hàm _generate_video_layout ---

    def _generate_chapter_content(self, original_source_data, full_layout_data, current_chapter_outline, style_strategy: BaseVideoStyle, language):
        """
        Giai đoạn 2 (Advanced Mode): Tạo nội dung tường thuật chi tiết cho một chapter cụ thể.
        Sử dụng style_config để điều chỉnh prompt về tone, audience, detail level, và transitions.

        Args:
            original_source_data (dict): Dữ liệu gốc ban đầu {'type': ..., 'data': ...}.
            full_layout_data (dict): Toàn bộ layout từ Stage 1 {'title': ..., 'layout': [...]}.
            current_chapter_outline (dict): Outline của chapter hiện tại {'chapter_number': ..., 'chapter_title': ..., 'summary': ..., 'word_count_target': ...}.
            style_config (dict): Cấu hình style hiện tại.
            language (str): Ngôn ngữ.

        Returns:
            list: Danh sách các câu tường thuật (strings) cho chapter này, hoặc None nếu lỗi.
        """
        # --- 1. Trích xuất thông tin cần thiết ---
        chapter_num = current_chapter_outline['chapter_number']
        chapter_title = current_chapter_outline['chapter_title']
        chapter_summary = current_chapter_outline.get('summary', '')
        word_count_target = current_chapter_outline.get('word_count_target', 150)

        # --- Lấy thông tin từ strategy ---
        style_config_data = style_strategy.get_style_config() # Lấy config từ strategy
        style_tone = style_config_data.get('tone', 'Unknown')
        style_instructions = style_config_data.get('instructions', [])
        target_audience = style_config_data.get("target_audience")     

        logger.info(f"  Stage 2: Generating content for Chapter {chapter_num}: '{chapter_title}' (Target: ~{word_count_target} words)...")
        if target_audience: logger.info(f"    Target Audience: {target_audience}")

        # --- 2. Xác định thông tin Chapter tiếp theo (để gợi ý chuyển tiếp) ---
        next_chapter_title = None
        layout_list = full_layout_data.get('layout', [])
        if chapter_num < len(layout_list):
            next_chapter_outline = layout_list[chapter_num] # Index là chapter_num vì list 0-based, chapter_num 1-based
            next_chapter_title = next_chapter_outline.get('chapter_title')

        # --- 3. Xây dựng Prompt ---
        prompt_stage2_chapter = f"""
        You are a detailed and engaging scriptwriter specializing in the style: '{style_tone}'.
        Your task is to write the narrative script content *ONLY* for a specific chapter of a video, based on the provided context and overall structure.
        """
        # --- 3a. Thêm thông tin Target Audience (nếu có) ---
        if target_audience:
            prompt_stage2_chapter += f"\n**IMPORTANT: Tailor your language, examples, and explanations specifically for the target audience: {target_audience}.**\n"

        prompt_stage2_chapter += f"""

        **Overall Video Context:**
        - Main Video Title: "{full_layout_data['title']}"
        - Full Video Layout (Outline):
        ```json
        {json.dumps(full_layout_data['layout'], indent=2, ensure_ascii=False)}
        ```
        - Target Style/Tone: {style_tone}

        **Current Chapter Focus:**
        - You are writing ONLY for: **Chapter {chapter_num}: "{chapter_title}"**
        - Chapter Summary/Goal: "{chapter_summary}"
        - **Target Word Count Guideline for this Chapter: Approximately {word_count_target} words.** This target dictates the necessary **depth and detail**.

        **Source Material (Use this for information):**
        """
        # --- 3b. Thêm Source Material (Không đổi) ---
        input_type = original_source_data.get('type', 'unknown')
        content_data = original_source_data.get('data', '')
        context_hint = original_source_data.get('context', None)
        lang_instruction = "in English" if language == "en" else "bằng tiếng Việt"

        if input_type == 'article':
            prompt_stage2_chapter += f"- Source Article Title: {content_data.get('title', '')}\n"
            prompt_stage2_chapter += f"- Source Article Content:\n{safe_truncate(content_data.get('content', ''), 12000)}\n" # Giữ nguyên limit này
        elif input_type == 'keyword':
            prompt_stage2_chapter += f"- Main Topic: \"{content_data}\"\n"
        elif input_type == 'text':
            prompt_stage2_chapter += f"- Type: Input Text {f'({context_hint})' if context_hint else ''}\n"
            prompt_stage2_chapter += f"- Source Text Content:\n{safe_truncate(content_data, 15000)}\n" # Giữ nguyên limit này
        # --- Kết thúc Source Material ---

        # --- LẤY VÀ THÊM HƯỚNG DẪN VIẾT TỪNG CHAPTER TỪ STRATEGY ---
        try:
            logger.info(">>> Đang thực thi: get_chapter_content_instructions")
            total_chapters_in_layout = len(full_layout_data.get('layout', []))
            chapter_content_instructions = style_strategy.get_chapter_content_instructions(
                chapter_num=chapter_num,
                total_chapters=total_chapters_in_layout,
                chapter_summary=current_chapter_outline.get('summary', ''),
                word_count_target=current_chapter_outline.get('word_count_target', 150),
                next_chapter_title=next_chapter_title
            )
            if chapter_content_instructions:
                prompt_stage2_chapter += f"\n{chapter_content_instructions}\n" # Thêm hướng dẫn lấy từ strategy
        except Exception as content_instr_err:
             logger.error(f"Error getting chapter content instructions from strategy: {content_instr_err}")
        # --- KẾT THÚC LẤY VÀ THÊM HƯỚNG DẪN CONTENT ---

        prompt_stage2_chapter += f"""

        **Your Task & Instructions:**
        """
        # --- 3c. Thêm hướng dẫn Hook cho Chapter 1 ---
        if chapter_num == 1:
            try:
                hook_instructions = style_strategy.hook_instructions()
                if hook_instructions:
                    prompt_stage2_chapter += f"\n{hook_instructions}\n" # Thêm trực tiếp
                else:
                    logger.warning("Strategy returned empty hook instructions for Chapter 1.")
            except AttributeError:
                logger.error("Strategy object is missing the hook_instructions method.")
            except Exception as hook_err:
                logger.error(f"Error getting hook instructions: {hook_err}")

        # --- 3d. Hướng dẫn Chung ---
        prompt_stage2_chapter += f"""
        **General Instructions (Apply to all sentences written for Chapter {chapter_num}):**
        1.  Write detailed, engaging narrative sentences {lang_instruction} that thoroughly explore the key points outlined in the Chapter Summary/Goal. Aim to reach the **Target Word Count Guideline (~{word_count_target} words)** by providing **sufficient depth, detail, examples, and explanation**.
        2.  Expand significantly on the summary using information *strictly* from the provided Source Material. Do NOT invent facts.
        3.  Consistently maintain the specified video style ({style_tone}) and follow the general style instructions: {'; '.join(style_instructions)}
        4.  Ensure sentences flow logically within the chapter.
        5.  **Smooth Transitions:**
            - If this is Chapter > 1, ensure the *first sentence* provides a natural, conversational continuation from the previous chapter's topic (implied from the layout summary). Avoid abrupt starts.
            - If this is **NOT** the final chapter"""
        if next_chapter_title:
             prompt_stage2_chapter += f" (the next chapter is about '{next_chapter_title}')"
        prompt_stage2_chapter += f""", ensure the **final sentence(s)** naturally and subtly lead into the topic of the next chapter. **DO NOT explicitly state "Next, we'll talk about..."**. Instead, end with a thought or statement that logically bridges to the next subject."""
        prompt_stage2_chapter += f"""
        6.  Write ONLY natural-sounding sentences suitable for professional voice-over. **CRITICAL: ABSOLUTELY NO visual descriptions (e.g., "As you can see...", "This image shows..."), camera directions, scene markers (like #SCENE#), bullet points, or mentioning the chapter title itself within the narrative.** Write as one continuous conversational flow.
        7.  Focus on delivering value and insight according to the target word count. Avoid filler content.
        """
        # --- Kết thúc Instructions ---

        # --- 3e. Output Format (Không đổi) ---
        prompt_stage2_chapter += f"""
        **Output Format:**
        Return ONLY a valid JSON object containing a list of the generated narrative sentences for this chapter.
        {{
        "chapter_content": [
            "First sentence for Chapter {chapter_num} (Hook if Chapter 1, otherwise smooth transition).",
            "Second detailed sentence...",
            "...",
            "Final sentence for Chapter {chapter_num} (potentially bridging to next chapter)."
        ]
        }}

        **REMEMBER:** JSON ONLY. Focus *solely* on writing the content for Chapter {chapter_num}. Adhere strictly to the target word count guideline ({word_count_target} words) to achieve the required level of detail and depth. Ensure transitions are natural and conversational.
        """
        # --- Kết thúc Output Format ---

        # --- 4. Gọi API (Không đổi) ---
        timeout = 150 + int(word_count_target / 1.5) # Timeout động, tăng nhẹ
        response_json_str = self._call_llm_api(
            user_prompt=prompt_stage2_chapter,
            request_timeout=timeout,
            require_json=True
        )
        if not response_json_str:
            logger.error(f"  Stage 2 Failed: No response from API for Chapter {chapter_num} content.")
            return None

        # --- 5. Parse và Validate Kết quả (Không đổi) ---
        try:
            chapter_content_data = json.loads(response_json_str)
            if not isinstance(chapter_content_data, dict) or \
            "chapter_content" not in chapter_content_data or \
            not isinstance(chapter_content_data["chapter_content"], list):
                logger.error(f"  Stage 2 Failed: Invalid JSON structure for Chapter {chapter_num}. Response: {chapter_content_data}")
                return None

            generated_sentences = [s.strip() for s in chapter_content_data["chapter_content"] if isinstance(s, str) and s.strip()]

            if not generated_sentences:
                logger.warning(f"  Stage 2 Warning: No valid sentences generated for Chapter {chapter_num}.")
                return [] # Trả về list rỗng

            # Log thêm word count thực tế (ước lượng)
            actual_words = sum(len(s.split()) for s in generated_sentences)
            logger.info(f"  Stage 2 Success: Generated {len(generated_sentences)} sentences (~{actual_words} words) for Chapter {chapter_num} (Target: ~{word_count_target}).")
            # Cảnh báo nếu quá chênh lệch
            if word_count_target > 0 and abs(actual_words - word_count_target) / word_count_target > 0.4: # Chênh lệch > 40%
                 logger.warning(f"    Word count deviation significant (Actual: {actual_words}, Target: {word_count_target}). May impact pacing.")

            return generated_sentences # Trả về danh sách câu

        except json.JSONDecodeError as e:
            logger.error(f"  Stage 2 Failed: Could not decode JSON for Chapter {chapter_num}: {e}")
            logger.debug(f"Received content: {response_json_str}")
            return None
        except Exception as e:
            logger.error(f"  Stage 2 Failed: Unexpected error parsing content for Chapter {chapter_num}: {e}", exc_info=True)
            return None
    # --- Kết thúc hàm _generate_chapter_content ---

    def _assemble_final_script(self, project_id, layout_data, all_chapters_sentences, style_strategy: BaseVideoStyle, language, input_type, source_info):
        """
        Giai đoạn 3 (Advanced Mode): Gộp nội dung chapter, breakdown thành shots, và tạo script cuối cùng.

        Args:
            project_id (str): ID của project.
            layout_data (dict): Layout từ Stage 1 {'title': ..., 'layout': [...]}.
            all_chapters_sentences (dict): Content từ Stage 2 {chapter_num: [sentences]}.
            style_config (dict): Cấu hình style.
            language (str): Ngôn ngữ.
            input_type (str): Loại input gốc ('article', 'keyword', 'text').
            source_info (dict): Thông tin nguồn gốc để điền vào script cuối
                                (ví dụ: {'source': 'Reuters', 'url': 'http://...', 'keyword': None} hoặc
                                {'source': 'AI Gen', 'url': 'keyword://...', 'keyword': 'topic'})

        Returns:
            dict: Script cuối cùng hoàn chỉnh hoặc None nếu lỗi.
        """
        logger.info("Starting Stage 3: Assembling final script...")

        # --- Lấy thông tin từ strategy ---
        style_config_data = style_strategy.get_style_config()
        style_tone = style_config_data.get('tone', 'Unknown')

        final_title = layout_data.get("title", "Untitled Video")
        final_scenes = []
        final_speech_units = []
        global_shot_number = 1
        speech_unit_number = 1

        # Lặp qua layout để đảm bảo thứ tự chapter
        for chapter_outline in layout_data.get('layout', []):
            chapter_num = chapter_outline.get('chapter_number')
            chapter_title = chapter_outline.get('chapter_title', f"Chapter {chapter_num}")

            # Lấy danh sách câu của chapter này từ kết quả Stage 2
            chapter_sentences = all_chapters_sentences.get(chapter_num, [])

            if not chapter_sentences:
                logger.warning(f"Stage 3: No sentences found for Chapter {chapter_num} in Stage 2 results. Skipping chapter content.")
                continue # Bỏ qua nếu không có câu nào cho chapter này

            logger.debug(f"  Stage 3: Processing {len(chapter_sentences)} sentences for Chapter {chapter_num}...")

            # Lặp qua từng câu gốc của chapter
            for original_sentence in chapter_sentences:
                original_sentence = original_sentence.strip()
                if not original_sentence: continue

                # --- Breakdown câu thành shots ---
                enable_breakdown = VIDEO_SETTINGS.get("enable_sentence_to_shot_breakdown", True)
                shots_content_list = []

                if enable_breakdown:
                    # logger.debug(f"    Breaking down: '{original_sentence[:50]}...'")
                    shots_content_list = self._breakdown_sentence_into_shots(original_sentence, style_tone)
                    if not shots_content_list:
                        logger.warning(f"    Breakdown failed for sentence in Ch {chapter_num}, using full sentence.")
                        shots_content_list = [original_sentence]
                else:
                    # logger.debug(f"    Using full sentence as single shot.")
                    shots_content_list = [original_sentence]
                # --- Kết thúc breakdown ---

                # --- Xử lý các shots ---
                shot_numbers_for_this_unit = []
                valid_shots_found = False

                if shots_content_list:
                    for shot_content in shots_content_list:
                        shot_content_stripped = shot_content.strip()
                        if not shot_content_stripped: continue

                        # Tạo scene object VỚI thông tin chapter
                        scene = {
                            "number": global_shot_number,
                            "content": shot_content_stripped,
                            "chapter_number": chapter_num, # Thêm chapter info
                            "chapter_title": chapter_title  # Thêm chapter info
                        }
                        final_scenes.append(scene)
                        shot_numbers_for_this_unit.append(global_shot_number)
                        global_shot_number += 1
                        valid_shots_found = True
                # --- Kết thúc xử lý shots ---

                # --- Tạo speech unit ---
                if valid_shots_found:
                    speech_unit = {
                        "unit_number": speech_unit_number,
                        "text": original_sentence, # Câu gốc cho TTS
                        "scene_numbers": shot_numbers_for_this_unit,
                        "chapter_number": chapter_num, # Thêm chapter info
                        "chapter_title": chapter_title  # Thêm chapter info
                    }
                    final_speech_units.append(speech_unit)
                    speech_unit_number += 1
                elif original_sentence:
                    logger.warning(f"Stage 3: No valid shots generated for non-empty sentence in Chapter {chapter_num}: '{original_sentence[:50]}...'. Skipping speech unit.")
                # --- Kết thúc tạo speech unit ---
            # --- Kết thúc lặp qua câu trong chapter ---
        # --- Kết thúc lặp qua các chapter ---

        # --- Kiểm tra và Tạo Script Cuối Cùng ---
        if not final_scenes or not final_speech_units:
            logger.error("Stage 3 Failed: No valid scenes or speech units were created after assembly.")
            return None

        logger.info(f"Stage 3 Success: Assembled script with {len(final_scenes)} shots and {len(final_speech_units)} speech units.")

        # Xác định is_ai_generated dựa trên input_type
        is_ai_generated = (input_type == 'keyword' or input_type == 'text')

        # *** Lấy image_url từ source_info nếu là article ***
        article_image_url = None
        if input_type == 'article':
            # source_info['data'] chính là article dictionary trong trường hợp này
            article_data = source_info.get('data', {})
            article_image_url = article_data.get('image_url')
        # *** Kết thúc lấy image_url ***

        # === BƯỚC PHÂN TÍCH VIDEO PREFERENCE (THÊM VÀO) ===
        logger.info("Analyzing scenes for video clip suitability...")
        # Gọi hàm phân tích cho danh sách scenes cuối cùng
        analysis_results = self._analyze_shots_for_video_batch(final_scenes)

        if analysis_results:
            logger.info(f"Updating {len(final_scenes)} scenes with video preference analysis results...")
            updated_scene_count = 0
            for scene in final_scenes:
                scene_num = scene.get('number')
                if scene_num is not None:
                    # Lấy kết quả phân tích (True/False) cho scene này, mặc định là False nếu không tìm thấy
                    prefer_video_flag = analysis_results.get(scene_num, False)
                    # Thêm hoặc cập nhật key 'prefer_video' vào dictionary của scene
                    scene['prefer_video'] = prefer_video_flag
                    if prefer_video_flag:
                        updated_scene_count += 1
                else:
                    # Xử lý trường hợp scene không có 'number' (dù không nên xảy ra)
                    scene['prefer_video'] = False
            logger.info(f"Marked {updated_scene_count} scenes as preferring video.")
        else:
            # Log nếu phân tích bị tắt, lỗi hoặc không trả về kết quả hợp lệ
            logger.warning("Video analysis skipped or failed. Proceeding without 'prefer_video' flags in scenes.")
            # Đảm bảo key 'prefer_video' tồn tại và là False nếu không có phân tích
            for scene in final_scenes:
                scene['prefer_video'] = False
        # === KẾT THÚC BƯỚC PHÂN TÍCH VIDEO PREFERENCE ===

        script_result = {
            "project_id": project_id,
            "title": final_title,
            "scenes": final_scenes,
            "speech_units": final_speech_units,
            "source": source_info.get('source', 'Unknown'),
            "url": source_info.get('url', ''),
            "image_url": article_image_url,
            "style": style_tone,
            "language": language,
            "script_mode": "advanced",
            "is_chapter_based": True,
            "is_ai_generated": is_ai_generated,
            "creation_timestamp": datetime.datetime.now().isoformat()
        }
        # Thêm keyword nếu có
        if source_info.get('keyword'):
            script_result["keyword"] = source_info.get('keyword')

        # Có thể thêm lại 'layout' vào đây nếu muốn giữ trong script cuối cùng để tham khảo
        # script_result["layout"] = layout_data.get('layout', [])

        # --- THÊM KHỐI DEBUG LOG ---
        logger.debug("---------------------------------------------")
        logger.debug(f"Preparing to return from _assemble_final_script (Advanced)...")
        # (Copy khối debug log giống như trong generate_script_from_keyword)
        if isinstance(script_result, dict):
             logger.debug(f"Returning type: dict")
             logger.debug(f"Script Keys: {list(script_result.keys())}")
             logger.debug(f"Scene count: {len(script_result.get('scenes', []))}")
             logger.debug(f"Speech unit count: {len(script_result.get('speech_units', []))}")
        elif script_result is None:
            logger.debug("Returning type: None")
        else:
             logger.debug(f"Returning UNEXPECTED type: {type(script_result)}")
             logger.debug(f"Value being returned: {script_result}")
        logger.debug("---------------------------------------------")
        # --- KẾT THÚC DEBUG LOG ---

        return script_result
    # --- Kết thúc hàm _assemble_final_script ---

    def _generate_advanced_script(self, source_data, style_config, language, style, project_id):
        """Generates a chapter-based script using OpenAI."""
        logger.info("Step 1 (Advanced): Generating chapter structure...")

        # --- Bước 1: Tạo Prompt cho Chapters ---

        prompt_step1_advanced = f"""
        You are an expert video scriptwriter and storyteller known for creating highly engaging, insightful, emotionally resonant, and comprehensive video scripts.

        Your goal is to produce the highest quality, deeply thoughtful, and truly comprehensive video script possible, carefully avoiding superficial summaries or brief overviews.

        Video Style Requirements:
        - Tone: {style_config['tone']}
        - Instructions: {'; '.join(style_config['instructions'])}

        Input Content Details:
        """
        input_type = source_data.get('type', 'unknown')
        content_data = source_data.get('data', '')
        context_hint = source_data.get('context', None)

        if input_type == 'article':
            prompt_step1_advanced += f"- Type: News Article\n"
            prompt_step1_advanced += f"- Title: {content_data.get('title', '')}\n"
            prompt_step1_advanced += f"- Content to Analyze & Structure:\n{safe_truncate(content_data.get('content', ''))}\n"
            prompt_step1_advanced += "\nTask: Thoroughly analyze the article. Provide a deep, comprehensive, detailed narrative across clearly defined chapters. Include substantial background context, critical insights, emotional depth, illustrative examples, multiple perspectives, and implications to deliver a fully-rounded narrative."
        elif input_type == 'keyword':
            lang_instruction = "in English" if language == "en" else "bằng tiếng Việt"
            prompt_step1_advanced += f"- Type: Keyword/Topic\n"
            prompt_step1_advanced += f"- Topic: \"{content_data}\"\n"
            prompt_step1_advanced += f"""
        Task: Extensively research and develop a truly comprehensive, detailed, and highly informative script {lang_instruction} about '{content_data}'.

        Explicitly adhere to these guidelines:
        - Aim for depth, providing extensive analysis, detailed explanations, historical context, practical examples, critical viewpoints, emotional resonance, and storytelling techniques to significantly enhance viewer engagement.
        - Avoid superficial or overly brief chapters; each chapter must comprehensively explore its respective facet of the topic.
        - Provide rich context and clear narrative progression from foundational concepts to advanced insights, ensuring clarity and complete understanding for the audience.
        - Clearly define your intended audience and tailor language, tone, and examples accordingly to maximize viewer resonance and impact.
        - Conclude each chapter with thoughtful reflections, actionable insights, or intriguing points that encourage further thinking or action by the viewers.
        """
        elif input_type == 'text':
            lang_instruction = "in English" if language == "en" else "bằng tiếng Việt"
            prompt_step1_advanced += f"- Type: Input Text {f'({context_hint})' if context_hint else ''}\n"
            prompt_step1_advanced += f"- Text Content to Structure:\n{safe_truncate(content_data, 12000)}\n"
            prompt_step1_advanced += f"\nTask: Provide a deeply analytical, well-organized, and genuinely comprehensive narrative based on the text {lang_instruction}. Structure into detailed chapters, fully exploring each aspect with emotional depth, compelling storytelling, and rich explanations, avoiding superficial summaries at all costs."
        else:
            logger.error("Invalid source data type for advanced script generation.")
            return None

        prompt_step1_advanced += f"""

        Chapter Requirements:
        - Create between 3 and 7 chapters, focusing exclusively on achieving comprehensive depth and clarity. Never sacrifice content quality or detail for brevity.
        - Clearly identify the emotional goals (e.g., curiosity, empathy, inspiration, excitement, nostalgia) and deliberately structure the narrative to consistently achieve these emotional impacts throughout.
        - Each chapter must explore its topic comprehensively, providing rich context, detailed examples, extensive explanations, critical analysis, emotional resonance, and engaging storytelling.
        - Chapters must logically build upon each other, presenting information clearly, progressively, and cohesively from foundational to advanced levels.
        - Actively employ storytelling techniques—including anecdotes, metaphors, rhetorical questions, suspenseful narratives, historical examples—to enhance emotional and intellectual engagement.
        - Explicitly tailor your narrative style (language complexity, tone, and choice of examples) to your defined target audience, ensuring maximum resonance and viewer satisfaction.
        - Include actionable insights or reflective conclusions at the end of each chapter, enabling viewers to derive personal or practical value from the video.
        - Begin Chapter 1 with an intriguing opening that strongly captures viewer attention and clearly communicates the importance of the topic.
        - End the final chapter with a memorable and thoughtful conclusion, reinforcing key ideas and inspiring viewer reflection or further exploration.
        - Generate insightful, concise, and engaging `chapter_title` for each chapter (max 5-7 words).
        - For each chapter, provide extensive narrative content as a list of natural-sounding, detailed sentences (`chapter_content`) designed specifically for professional-quality voice-over narration.
        - Absolutely DO NOT include visual directions, editing instructions, or formatting cues.

        Output Format:
        Return ONLY a valid JSON object following this exact structure, without explanations or markdown formatting:
        {{
        "title": "Highly Engaging and Insightful Video Title About the Topic",
        "chapters": [
            {{
            "chapter_number": 1,
            "chapter_title": "Concise Chapter 1 Title",
            "chapter_content": [
                "Detailed opening sentence(s), strongly engaging viewers with context and emotional resonance.",
                "Further extensive and insightful sentences, continuing with comprehensive explanations and vivid storytelling."
            ]
            }},
            {{
            "chapter_number": 2,
            "chapter_title": "Insightful Chapter 2 Title",
            "chapter_content": [
                "Comprehensive and detailed exploration of chapter 2's main points, enriched by critical perspectives and compelling storytelling.",
                "Additional sentences providing thorough analysis, context-rich examples, emotional resonance, and actionable takeaways."
            ]
            }}
            // ... additional detailed and comprehensive chapters
        ]
        }}
        """

        # Call OpenAI API (potentially longer timeout needed)
        response_json_str = self._call_llm_api(
            user_prompt=prompt_step1_advanced,
            request_timeout=45,
            require_json=True # Need JSON { "shots": [...] }
        )        
        if not response_json_str:
            logger.error("Step 1 (Advanced) Failed: No response from API for chapter structure.")
            return None

        # --- Bước 2: Parse và Flatten ---
        try:
            chapter_data = json.loads(response_json_str)

            # Validate structure
            if not isinstance(chapter_data, dict) or \
            "title" not in chapter_data or not isinstance(chapter_data["title"], str) or \
            "chapters" not in chapter_data or not isinstance(chapter_data["chapters"], list) or \
            not chapter_data["chapters"]:
                logger.error(f"Step 1 (Advanced) Failed: Invalid JSON structure received: {chapter_data}")
                return None

            final_title = chapter_data["title"]
            final_scenes = []
            final_speech_units = []
            global_shot_number = 1
            speech_unit_number = 1

            logger.info("Step 2 (Advanced): Flattening chapters and breaking sentences into shots...")

            for chapter in chapter_data["chapters"]:
                # Validate chapter structure
                if not isinstance(chapter, dict) or \
                "chapter_number" not in chapter or not isinstance(chapter["chapter_number"], int) or \
                "chapter_title" not in chapter or not isinstance(chapter["chapter_title"], str) or \
                "chapter_content" not in chapter or not isinstance(chapter["chapter_content"], list):
                    logger.warning(f"Skipping invalid chapter structure: {chapter}")
                    continue

                chapter_num = chapter["chapter_number"]
                chapter_title = chapter["chapter_title"].strip()
                chapter_content_sentences = chapter["chapter_content"]

                logger.info(f"  Processing Chapter {chapter_num}: '{chapter_title}' ({len(chapter_content_sentences)} sentences)")

                if not chapter_content_sentences:
                    logger.warning(f"Chapter {chapter_num} has empty content. Skipping.")
                    continue

                for sentence in chapter_content_sentences:
                    original_sentence = sentence.strip() # Lưu câu gốc
                    if not original_sentence: continue # Bỏ qua câu rỗng

                    # --- THÊM LOGIC KIỂM TRA SETTING (TƯƠNG TỰ BASIC) ---
                    enable_breakdown = VIDEO_SETTINGS.get("enable_sentence_to_shot_breakdown", True)
                    shots_for_sentence_content = [] # List chứa nội dung text của shots

                    if enable_breakdown:
                        logger.debug(f"(Adv/Breakdown) Ch-{chapter_num} Processing sentence '{original_sentence[:50]}...'")
                        shots_for_sentence_content = self._breakdown_sentence_into_shots(original_sentence, style_config['tone'])
                        if not shots_for_sentence_content:
                            logger.warning(f"(Adv/Breakdown) Breakdown failed in Ch-{chapter_num}, using full sentence.")
                            shots_for_sentence_content = [original_sentence]
                    else:
                        logger.debug(f"(Adv/No Breakdown) Ch-{chapter_num} Using full sentence as single shot.")
                        shots_for_sentence_content = [original_sentence]
                    # --- KẾT THÚC LOGIC TẠO SHOTS CONTENT ---


                    # --- Xử lý danh sách shots đã tạo ---
                    shot_numbers_for_this_unit = []
                    valid_shots_found = False

                    if shots_for_sentence_content:
                        for shot_content in shots_for_sentence_content:
                            shot_content_stripped = shot_content.strip()
                            if not shot_content_stripped: continue

                            # Tạo scene VỚI chapter info
                            scene = {
                                "number": global_shot_number,
                                "content": shot_content_stripped,
                                "chapter_number": chapter_num, # Thêm chapter info
                                "chapter_title": chapter_title # Thêm chapter info
                            }
                            final_scenes.append(scene)
                            shot_numbers_for_this_unit.append(global_shot_number)
                            global_shot_number += 1
                            valid_shots_found = True

                    # Tạo speech unit nếu có scene hợp lệ
                    if valid_shots_found:
                        speech_unit = {
                            "unit_number": speech_unit_number,
                            "text": original_sentence, # Câu gốc cho TTS
                            "scene_numbers": shot_numbers_for_this_unit,
                            "chapter_number": chapter_num, # Thêm chapter info
                            "chapter_title": chapter_title # Thêm chapter info
                        }
                        final_speech_units.append(speech_unit)
                        speech_unit_number += 1
                    elif original_sentence:
                         logger.warning(f"No valid shots generated for non-empty sentence in Chapter {chapter_num}: '{original_sentence[:50]}...'. Skipping speech unit.")
                # --- Kết thúc vòng lặp sentences trong chapter ---
            # --- Kết thúc vòng lặp chapters ---

            logger.info(f"Script generation complete (Advanced): {len(final_scenes)} shots, {len(final_speech_units)} speech units across {len(chapter_data['chapters'])} chapters.")

            # --- Bước 3: Return final script object ---
            # Basic metadata - specific source/url will be added in the calling function
            advanced_script_result = {
                "project_id": project_id,
                "title": final_title,
                "scenes": final_scenes,
                "speech_units": final_speech_units,
                "source": "AI Generated (Chapters)", # Placeholder, specific source added later
                "url": "",                          # Placeholder, specific URL added later
                "style": style,
                "language": language,
                "script_mode": "advanced", # Indicate mode
                "is_chapter_based": True, # Explicit flag
                "is_ai_generated": True, # Always true for advanced mode currently
                "creation_timestamp": datetime.datetime.now().isoformat()
            }
            return advanced_script_result

        except json.JSONDecodeError as e:
            logger.error(f"Step 1 (Advanced) Failed: Could not decode JSON response for chapters: {e}")
            logger.debug(f"Received content: {response_json_str}")
            return None
        except Exception as e:
            logger.error(f"Step 2 (Advanced) Failed: Unexpected error parsing or flattening chapters: {e}", exc_info=True)
            return None
    # --- End of _generate_advanced_script ---

    def _analyze_shots_for_video_batch(self, scenes):
        """
        Analyzes a list of scene contents in batch to determine video suitability using a single API call.

        Args:
            scenes (list): A list of scene dictionaries, each containing at least 'number' and 'content'.

        Returns:
            dict: A dictionary mapping scene number to a boolean (True if video is preferred, False otherwise).
                Returns an empty dictionary if analysis fails or is disabled.
        """
        if not scenes:
            logger.warning("No scenes provided for batch video analysis.")
            return {}

        if not VIDEO_SETTINGS.get("enable_video_clips", False) or not self.api_key:
            logger.info("Video clip analysis is disabled or OpenAI API key is missing. Skipping batch analysis.")
            # Return a dict with all False if disabled, so the structure exists but doesn't prefer video
            return {scene['number']: False for scene in scenes}

        logger.info(f"Starting batch video suitability analysis for {len(scenes)} shots...")

        # 1. Prepare data for the prompt
        # Create a simplified list of scenes just for the prompt
        scenes_for_prompt = [{"number": s['number'], "content": s['content']} for s in scenes]
        # Convert the list to a JSON string to include in the prompt
        try:
            scenes_json_string = json.dumps(scenes_for_prompt, ensure_ascii=False, indent=2)
        except Exception as json_err:
            logger.error(f"Error converting scenes to JSON for prompt: {json_err}")
            return {scene['number']: False for scene in scenes} # Fallback: assume no video

        # 2. Build the Prompt
        analysis_prompt = f"""
        You are an expert video editor assistant. Your task is to analyze a list of short video script shots (scenes) provided below in JSON format.
        For EACH shot in the list, decide whether its content is BEST represented by a VIDEO clip or a STATIC IMAGE.

        Consider these factors for each shot:
        - **Action/Movement:** Prefer VIDEO for shots describing actions, movements, processes, changes, demonstrations (e.g., "running", "building", "exploding", "presenting", "market fluctuating").
        - **Static/Abstract:** Prefer IMAGE for shots describing states, static locations, abstract concepts, quotes, data, inner thoughts (e.g., "the building stands tall", "statistics show", "he thought about...", "according to experts", "a graph illustrating").
        - **Overall Pacing:** Look at the sequence. Avoid recommending video clips for too many consecutive shots (e.g., try not to have more than 2-3 'true' values in a row). Aim for roughly {int(VIDEO_SETTINGS.get('video_clip_frequency', 0.4)*100)}% video usage if the content allows, but prioritize appropriate representation.

        Input JSON (list of shots):
        ```json
        {scenes_json_string}
        ```

        Output Requirements:
        - Respond ONLY with a valid JSON object. Do not include any introduction, explanation, or markdown formatting.
        - The JSON object must contain a single key "analysis_results".
        - The value of "analysis_results" must be a LIST of objects.
        - Each object in the list must correspond to a shot from the input list and contain:
            - "number": The original number of the shot (integer).
            - "prefer_video": A boolean value (true if video is preferred, false if image is preferred).

        Example Output Format:
        {{
        "analysis_results": [
            {{ "number": 1, "prefer_video": false }},
            {{ "number": 2, "prefer_video": true }},
            {{ "number": 3, "prefer_video": true }},
            {{ "number": 4, "prefer_video": false }}
            // ... continue for all shots in the input list
        ]
        }}
        """

        # 3. Call OpenAI API
        # Use a potentially longer timeout as the request/response might be larger
        response_json_str = self._call_llm_api(
            user_prompt=analysis_prompt,
            request_timeout=45,
            require_json=True,
            is_core_content_task=False, # Không phải core task, dùng LLM mặc định ngay cả khi DeepSeek Reasoner được chọn
        )        
        if not response_json_str:
            logger.error("Batch video analysis failed: No response from API.")
            return {scene['number']: False for scene in scenes} # Fallback

        # 4. Process Results
        try:
            analysis_data = json.loads(response_json_str)

            # Validate the response structure
            if not isinstance(analysis_data, dict) or "analysis_results" not in analysis_data:
                logger.error(f"Batch video analysis failed: Invalid JSON structure in response. Got: {analysis_data}")
                return {scene['number']: False for scene in scenes}

            results_list = analysis_data["analysis_results"]
            if not isinstance(results_list, list):
                logger.error(f"Batch video analysis failed: 'analysis_results' is not a list. Got: {type(results_list)}")
                return {scene['number']: False for scene in scenes}


            # Create the result map {scene_number: prefer_video}
            analysis_map = {}
            processed_numbers = set()
            for result_item in results_list:
                if isinstance(result_item, dict) and \
                "number" in result_item and isinstance(result_item["number"], int) and \
                "prefer_video" in result_item and isinstance(result_item["prefer_video"], bool):
                    scene_num = result_item["number"]
                    analysis_map[scene_num] = result_item["prefer_video"]
                    processed_numbers.add(scene_num)
                else:
                    logger.warning(f"Skipping invalid item in analysis results: {result_item}")

            # Check if all original scene numbers were processed
            original_numbers = {s['number'] for s in scenes}
            missing_numbers = original_numbers - processed_numbers
            if missing_numbers:
                logger.warning(f"Batch video analysis results missing for scene numbers: {sorted(list(missing_numbers))}. Defaulting them to 'prefer_video: false'.")
                for num in missing_numbers:
                    analysis_map[num] = False # Default missing ones to False

            logger.info(f"Batch video analysis complete. Results obtained for {len(analysis_map)} scenes.")
            return analysis_map

        except json.JSONDecodeError as e:
            logger.error(f"Batch video analysis failed: Could not decode JSON response: {e}")
            logger.debug(f"Received content: {response_json_str}")
            return {scene['number']: False for scene in scenes} # Fallback
        except Exception as e:
            logger.error(f"Batch video analysis failed: Unexpected error processing results: {e}", exc_info=True)
            return {scene['number']: False for scene in scenes} # Fallback

# --- Phần Test Cuối File (Cập nhật để kiểm tra quy trình 2 bước) ---
if __name__ == "__main__":
    print("--- Testing ScriptGenerator (2-Step Process: Sentences -> Shots) ---")
    # --- Cấu hình Logger (Tùy chọn) ---
    # import logging
    # import sys
    # ... (giữ nguyên cấu hình logger nếu cần) ...

    # --- TẠM THỜI TẮT PHÂN TÍCH VIDEO CHO TEST ---
    # Import settings ở đây để có thể sửa đổi tạm thời
    from config.settings import VIDEO_SETTINGS
    original_enable_video_clips = VIDEO_SETTINGS.get("enable_video_clips", False)
    VIDEO_SETTINGS["enable_video_clips"] = False
    logger.info("--- Video analysis explicitly disabled for this test run ---")
    # ----------------------------------------------

    # --- Dữ liệu Test ---
    test_article_vi = {
        'title': 'Nông nghiệp Ai Cập Cổ đại',
        'content': 'Họ chủ yếu trồng các loại cây như là đại mạch, tiểu mạch, chà là, sen hay là táo. Đồng thời đồng bằng sông Nile cũng là nơi sinh sống của những sinh vật đa dạng và quan trọng đến tín ngưỡng Ai Cập như là chim ưng, trâu bò, cá sấu, hổ báo và nhiều loại động vật khác.',
        'source': 'Wikipedia (vi)',
        'language': 'vi'
    }
    test_article_en = {
        'title': 'Electric Vehicle Market Growth',
        'content': 'The global electric vehicle market continues to experience rapid growth, driven by government incentives, improving battery technology, and increasing consumer awareness about environmental issues. Major automakers are heavily investing in new EV models to compete.',
        'source': 'Reuters',
        'language': 'en'
    }
    test_keyword_vi = "lợi ích của việc đọc sách"
    test_keyword_en = "impact of social media on teenagers"
    test_transcript = """
    Hello everyone, and welcome back to the channel. Today, we're diving deep into the world of sustainable gardening.
    First, let's talk about composting. It's a fantastic way to reduce waste and enrich your soil naturally.
    You can compost kitchen scraps like vegetable peelings and coffee grounds. Avoid meat and dairy products.
    Another key aspect is water conservation. Using rain barrels and drip irrigation systems can save a lot of water compared to traditional sprinklers.
    Choosing native plants is also crucial. They are adapted to the local climate and require less maintenance. That's all for today! Happy gardening!
    """
    # --- Khởi tạo Generator và Thực hiện Test ---
    generator = None # Khởi tạo là None để đảm bảo nó nằm trong scope của finally
    try:
        # Đảm bảo API key đã được load
        if not OPENAI_API_KEY:
             raise ValueError("OPENAI_API_KEY is not set. Please check config/credentials.py or your .env file.")

        generator = ScriptGenerator()

        # --- Test 1: Tạo script từ Bài báo Tiếng Việt ---
        print("\n" + "="*10 + " Test 1: Article (Vietnamese) - Informative " + "="*10)
        # Giờ đây khi gọi generate_script, bước phân tích video sẽ bị bỏ qua do cài đặt đã tắt
        script_vi = generator.generate_script(test_article_vi, "informative")

        if script_vi:
            print(f"\nSUCCESS: Generated script for '{script_vi.get('title')}'")
            # Output sẽ không còn các log "Analyzing..." nữa
            print(f"Total Shots (items in 'scenes' list): {len(script_vi.get('scenes', []))}")
            print(f"Total Speech Units (original sentences): {len(script_vi.get('speech_units', []))}")

            print("\n--- Example Shots (First 5): ---")
            for i, scene in enumerate(script_vi.get('scenes', [])[:5]):
                print(f"  Shot {scene.get('number')}: '{scene.get('content')}'")
            if len(script_vi.get('scenes', [])) > 5: print("  ...")

            print("\n--- Speech Units (First 2): ---")
            for i, unit in enumerate(script_vi.get('speech_units', [])[:2]):
                print(f"  Unit {unit.get('unit_number')}:")
                print(f"    Original Text: '{unit.get('text')}'")
                print(f"    Covers Shot Numbers: {unit.get('scene_numbers')}")
            if len(script_vi.get('speech_units', [])) > 2: print("  ...")
            print("-" * 30)
        else:
            print("\nFAILED to generate script from Vietnamese article.")
            print("-" * 30)

        # --- Test 2: Tạo script từ Từ khóa Tiếng Anh ---
        print("\n" + "="*10 + " Test 2: Keyword (English) - Conversational " + "="*10)
        script_en_kw = generator.generate_script_from_keyword(test_keyword_en, "conversational", "en")

        if script_en_kw:
            print(f"\nSUCCESS: Generated script for keyword '{test_keyword_en}'")
            print(f"Title: {script_en_kw.get('title')}")
            print(f"Total Shots (items in 'scenes' list): {len(script_en_kw.get('scenes', []))}")
            print(f"Total Speech Units (original sentences): {len(script_en_kw.get('speech_units', []))}")

            print("\n--- Example Shots (First 5): ---")
            for i, scene in enumerate(script_en_kw.get('scenes', [])[:5]):
                print(f"  Shot {scene.get('number')}: '{scene.get('content')}'")
            if len(script_en_kw.get('scenes', [])) > 5: print("  ...")

            print("\n--- Speech Units (First 2): ---")
            for i, unit in enumerate(script_en_kw.get('speech_units', [])[:2]):
                print(f"  Unit {unit.get('unit_number')}:")
                print(f"    Original Text: '{unit.get('text')}'")
                print(f"    Covers Shot Numbers: {unit.get('scene_numbers')}")
            if len(script_en_kw.get('speech_units', [])) > 2: print("  ...")
            print("-" * 30)
        else:
            print("\nFAILED to generate script from English keyword.")
            print("-" * 30)

        # --- NEW Test 3: Transcript (En) ---
        print("\n" + "="*10 + " Test 3: Transcript (English) - Informative " + "="*10)
        script_transcript = generator.generate_script_from_text(test_transcript, "informative", "en", context_hint="Sustainable Gardening Tips")

        if script_transcript:
            print(f"\nSUCCESS: Generated script from transcript")
            print(f"Title: {script_transcript.get('title')}")
            print(f"Total Shots: {len(script_transcript.get('scenes', []))}")
            print(f"Total Speech Units: {len(script_transcript.get('speech_units', []))}")
            # ... (print more details as needed) ...
            print("-" * 30)
        else:
            print("\nFAILED to generate script from transcript.")
            print("-" * 30)

    except ValueError as ve:
         print(f"\nERROR: Configuration Error: {ve}")
    except Exception as e:
        print(f"\n--- An unexpected error occurred during testing ---")
        import traceback
        print(traceback.format_exc())
    finally:
        VIDEO_SETTINGS["enable_video_clips"] = original_enable_video_clips
        logger.info(f"--- Video analysis setting restored to: {original_enable_video_clips} ---")

    print("\n--- Testing Finished ---")