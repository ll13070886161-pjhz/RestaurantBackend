import base64
import io
import json
import time
from typing import Any, Dict

import requests
from PIL import Image, UnidentifiedImageError


class OtherProviderClient:
    """
    HTTP client for vision providers using OpenAI-compatible API.
    Defaults are set for Volcengine Ark endpoints.
    """

    def __init__(self, base_url: str, api_key: str, model_name: str, timeout: int = 45) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model_name = model_name
        self.timeout = timeout

    def _build_headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _prepare_image_data_url(self, image_bytes: bytes) -> str:
        """
        Normalize uploaded image before sending to model:
        - convert to RGB jpeg
        - cap max edge to reduce payload size
        """
        try:
            image = Image.open(io.BytesIO(image_bytes))
            image = image.convert("RGB")
            max_edge = 2048
            if max(image.size) > max_edge:
                image.thumbnail((max_edge, max_edge))
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=85, optimize=True)
            normalized_bytes = output.getvalue()
        except (UnidentifiedImageError, OSError):
            # Keep original bytes for unknown formats.
            normalized_bytes = image_bytes
        image_b64 = base64.b64encode(normalized_bytes).decode("utf-8")
        return f"data:image/jpeg;base64,{image_b64}"

    def parse_image(self, image_bytes: bytes, prompt: str) -> Dict[str, Any]:
        """
        Payload follows OpenAI-compatible chat/completions style.
        Works for Doubao vision models on Volcengine Ark.
        """
        if not self.base_url:
            raise ValueError("LLM_BASE_URL is required for provider 'other'.")

        image_data_url = self._prepare_image_data_url(image_bytes)
        payload = {
            "model": self.model_name,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": image_data_url}},
                    ],
                }
            ],
            "temperature": 0.1,
        }
        response = None
        timeout_err = None
        for attempt in range(3):
            try:
                response = requests.post(
                    self.base_url,
                    headers=self._build_headers(),
                    data=json.dumps(payload),
                    timeout=(10, self.timeout),
                )
                timeout_err = None
                break
            except requests.Timeout as exc:
                timeout_err = exc
                if attempt < 2:
                    time.sleep(1.5 * (attempt + 1))
        if response is None and timeout_err is not None:
            raise RuntimeError(
                f"Provider timeout after 3 attempts: url={self.base_url}, "
                f"model={self.model_name}, read_timeout={self.timeout}s"
            ) from timeout_err
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            # Keep upstream body for faster config troubleshooting.
            body = response.text[:1200]
            raise RuntimeError(
                f"Provider request failed: status={response.status_code}, "
                f"url={self.base_url}, model={self.model_name}, body={body}"
            ) from exc
        return response.json()

    def chat_text(self, *, system_prompt: str, user_prompt: str) -> Dict[str, Any]:
        if not self.base_url:
            raise ValueError("LLM_BASE_URL is required for provider 'other'.")
        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.1,
        }
        response = requests.post(
            self.base_url,
            headers=self._build_headers(),
            data=json.dumps(payload),
            timeout=(10, self.timeout),
        )
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            body = response.text[:1200]
            raise RuntimeError(
                f"Provider request failed: status={response.status_code}, "
                f"url={self.base_url}, model={self.model_name}, body={body}"
            ) from exc
        return response.json()
