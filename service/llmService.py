"""Service untuk komunikasi ke LLM (NL-to-SQL dan analisis hasil)."""

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any, cast, NoReturn
import httpx
from fastapi import HTTPException, status
from openai import AsyncOpenAI, APIConnectionError, APITimeoutError, APIStatusError
from openai.types.chat import ChatCompletion
from configCredidential import get_settings
from utils.helper.llmPayloadHelpers import (
    VisualizationDecision,
    build_payload,
    clean_sql_output,
    extract_text,
    parse_visualization_decision,
)

settings = get_settings()
logger = logging.getLogger(__name__)

__all__ = ["LLMService", "VisualizationDecision"]


class LLMService:
    """Wrapper LLM API dengan alur request yang eksplisit."""

    def __init__(self, timeout_seconds: float = 20.0, max_retries: int = 3):
        self.timeout_seconds: float = timeout_seconds
        self.max_retries: int = max_retries
        self.retry_delay_seconds: int = 1
        self.api_key: str = (settings.LLM_API_KEY or "").strip()
        self.base_url: str = (
            settings.LLM_BASE_URL or "").strip().rstrip("/")
        self.client: AsyncOpenAI = AsyncOpenAI(
            base_url=self.base_url if self.base_url else None,
            api_key=self.api_key,
            timeout=self.timeout_seconds,
            max_retries=0,
        )

    async def call_model(
        self,
        prompt: str,
        temperature: float = 0.3,
        max_tokens: int = 500,
        model: str | None = None,
    ) -> str:
        if model is None:
            model = settings.LLM_MODEL_ANALYSIS

        return await self._call_llm(
            model=model,
            prompt=prompt,
            temperature=temperature,
            max_output_tokens=max_tokens,
        )

    async def generate_sql(self, prompt: str) -> str:
        raw = await self._call_llm(
            model=settings.LLM_MODEL_NL_TO_SQL,
            prompt=prompt,
            temperature=0.1,
            max_output_tokens=1024,
            stop_sequences=None,
        )

        logger.debug("Raw SQL output from LLM: %s", raw)
        return clean_sql_output(raw)

    async def analyze_result_stream(self, prompt: str) -> AsyncIterator[str]:
        model = settings.LLM_MODEL_ANALYSIS
        self._ensure_runtime_config(model)
        payload = build_payload(
            model=model,
            prompt=prompt,
            temperature=0.4,
            max_output_tokens=3000,
            stop_sequences=None,
        )
        payload["stream"] = True
        try:
            stream = await self.client.chat.completions.create(**payload)
            async for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta and delta.content:
                    yield delta.content
        except (APITimeoutError, APIConnectionError, httpx.TimeoutException, httpx.HTTPError):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Layanan AI sementara tidak tersedia. Silakan coba lagi.",
            )
        except APIStatusError as error:
            if error.status_code == 429:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Terlalu banyak permintaan. Silakan coba lagi nanti.",
                )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Layanan AI sementara tidak tersedia. Silakan coba lagi.",
            )

    async def decide_visualization_request(self, prompt: str) -> VisualizationDecision:
        """
        Fungsi classifier khusus untuk memutuskan apakah user meminta visualisasi.
        Chart yang didukung hanya: bar, pie, donut.
        """

        try:
            raw = await self._call_llm(
                model=settings.LLM_MODEL_GRAPHIC_CLASSIFIER,
                prompt=prompt,
                temperature=0.0,
                max_output_tokens=100,
            )
            return parse_visualization_decision(raw)
        except HTTPException:
            return VisualizationDecision(is_visualize=False, chart_type=None)


    async def _call_llm(
        self,
        model: str,
        prompt: str,
        temperature: float,
        max_output_tokens: int,
        stop_sequences: list[str] | None = None,
    ) -> str:
        try:
            self._ensure_runtime_config(model)
            payload = build_payload(
                model=model,
                prompt=prompt,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                stop_sequences=stop_sequences,
            )
            return await self._request_with_retry(
                payload=payload,
                has_next_model=False,
            )
        except (KeyError, ValueError) as error:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Respons AI tidak sesuai format yang diharapkan: {str(error)}",
            ) from error

    def _ensure_runtime_config(self, model: str) -> None:
        if self.api_key and self.base_url and model:
            return
        logger.error(
            "LLM config incomplete (base_url_set=%s, api_key_set=%s, model_set=%s)",
            bool(self.base_url),
            bool(self.api_key),
            bool(model),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Konfigurasi layanan AI belum lengkap. Hubungi admin.",
        )

    def _is_last_attempt(self, attempt: int) -> bool:
        return attempt >= self.max_retries

    @staticmethod
    def _raise_model_not_available() -> NoReturn:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Layanan AI sementara tidak tersedia. Silakan coba lagi.",
        )

    async def _request_with_retry(
            self,
            payload: dict[str, Any],
            has_next_model: bool,
    ) -> str:
        for attempt in range(self.max_retries + 1):
            try:
                data = await self._post_chat_completion(payload)
                return extract_text(data)

            except (APITimeoutError, httpx.TimeoutException) as error:
                await self._retry_or_raise(
                    attempt,
                    error,
                    "LLM request timed out after %.1f seconds: %s",
                    self.timeout_seconds,
                )

            except APIConnectionError as error:
                await self._retry_or_raise(
                    attempt, error, "LLM connection failed: %s",
                )

            except httpx.HTTPError as error:
                await self._retry_or_raise(
                    attempt, error, "LLM HTTP request failed: %s",
                )

            except APIStatusError as error:
                await self._handle_status_error(error, attempt, has_next_model)

        self._raise_model_not_available()

    async def _retry_or_raise(
            self,
            attempt: int,
            error: Exception,
            log_message: str,
            *log_args: Any,
    ) -> None:
        """Sleep and continue if attempts remain, otherwise log and raise."""
        if self._is_last_attempt(attempt):
            logger.error(log_message, *log_args, error)
            self._raise_model_not_available()
        await asyncio.sleep(self.retry_delay_seconds)

    async def _handle_status_error(
            self,
            error: APIStatusError,
            attempt: int,
            has_next_model: bool,
    ) -> None:
        status_code = error.status_code

        if status_code == 429:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Terlalu banyak permintaan. Silakan coba lagi nanti.",
            ) from error

        if status_code >= 500:
            if self._is_last_attempt(attempt):
                logger.error("LLM API server error %d: %s", status_code, error)
                self._raise_model_not_available()
            wait = self.retry_delay_seconds * (2 ** attempt)
            logger.warning(
                "LLM API server error %d, retrying in %.1fs (attempt %d/%d)",
                status_code, wait, attempt + 1, self.max_retries + 1,
            )
            await asyncio.sleep(wait)
            return

        if 400 <= status_code < 500:
            logger.error("LLM API request error %d: %s", status_code, error)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Permintaan ke layanan AI ditolak ({status_code}).",
            ) from error

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Layanan AI sementara tidak tersedia. Silakan coba lagi.",
        ) from error

    async def _post_chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = await self.client.chat.completions.create(**payload)
        response = cast(ChatCompletion, response)
        return response.model_dump()  # pydantic v2; atau .dict() jika v1