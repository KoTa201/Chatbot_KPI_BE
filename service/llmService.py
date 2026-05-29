"""Service untuk komunikasi ke LLM (NL-to-SQL dan analisis hasil)."""

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, cast, NoReturn
import httpx
from fastapi import HTTPException, status
from openai import AsyncOpenAI, APIConnectionError, APITimeoutError, APIStatusError
from openai.types.chat import ChatCompletion
from configCredidential import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


@dataclass
class VisualizationDecision:
    is_visualize: bool
    chart_type: str | None = None


class LLMService:
    """Wrapper LLM API dengan alur request yang eksplisit."""

    def __init__(self, timeout_seconds: float = 20.0, max_retries: int = 3):
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.retry_delay_seconds = 1
        self.api_key = (settings.LLM_API_KEY or "").strip()
        self.base_url = (
            settings.LLM_BASE_URL or "").strip().rstrip("/")
        # Inisialisasi client OpenAI (LLM kompatibel)
        self.client = AsyncOpenAI(
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
        """
        Generic method untuk memanggil LLM dengan prompt dan parameter custom.
        Digunakan oleh services lain seperti ClarificationQuestionGeneratorService.

        Args:
            prompt: Pertanyaan/prompt untuk LLM
            temperature: Tingkat kreativitas (0.0-1.0)
            max_tokens: Maksimal token output
            model: Model yang digunakan (default: LLM_MODEL_ANALYSIS)

        Returns:
            Respons text dari LLM
        """
        if model is None:
            model = settings.LLM_MODEL_ANALYSIS

        return await self._call_llm(
            model=model,
            prompt=prompt,
            temperature=temperature,
            max_output_tokens=max_tokens,
        )

    async def generate_sql(self, prompt: str) -> str:
        """
        Stage 1: Konversi prompt NL-to-SQL.
        Temperature rendah (0.1) untuk konsistensi output SQL.
        """
        raw = await self._call_llm(
            model=settings.LLM_MODEL_NL_TO_SQL,
            prompt=prompt,
            temperature=0.1,
            max_output_tokens=1024,
            stop_sequences=["```"],
        )

        logger.debug("Raw SQL output from LLM: %s", raw)
        return self._clean_sql_output(raw)

    async def analyze_result(self, prompt: str) -> str:
        """
        Stage 4: Analisis hasil query menjadi narasi Bahasa Indonesia.
        Temperature lebih tinggi (0.4) untuk narasi yang natural.
        """
        return await self._call_llm(
            model=settings.LLM_MODEL_ANALYSIS,
            prompt=prompt,
            temperature=0.4,
            max_output_tokens=3000,
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
            return self._parse_visualization_decision(raw)
        except HTTPException:
            return VisualizationDecision(is_visualize=False, chart_type=None)

    @staticmethod
    def _build_payload(
            model: str,
        prompt: str,
        temperature: float,
        max_output_tokens: int,
        stop_sequences: list[str] | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_output_tokens,
        }
        if stop_sequences:
            payload["stop"] = stop_sequences
        return payload

    async def _post_chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = await self.client.chat.completions.create(**payload)
        response = cast(ChatCompletion, response)
        return response.model_dump()  # pydantic v2; atau .dict() jika v1

    async def _request_with_retry(
        self,
        payload: dict[str, Any],
        has_next_model: bool,
    ) -> str:
        for attempt in range(self.max_retries + 1):
            try:
                data = await self._post_chat_completion(payload)
                return self._extract_text(data)

            except APITimeoutError as error:
                is_last_attempt = attempt >= self.max_retries
                if is_last_attempt:
                    logger.error(
                        "LLM request timed out after %.1f seconds: %s",
                        self.timeout_seconds,
                        error,
                    )
                    self._raise_model_not_available()
                await asyncio.sleep(self.retry_delay_seconds)

            except APIConnectionError as error:
                is_last_attempt = attempt >= self.max_retries
                if is_last_attempt:
                    logger.error("LLM connection failed: %s", error)
                    self._raise_model_not_available()
                await asyncio.sleep(self.retry_delay_seconds)

            except APIStatusError as error:
                status_code = error.status_code
                if status_code == 404 and has_next_model:
                    raise _UseNextModelCandidate() from error
                if status_code == 429:
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail="Terlalu banyak permintaan. Silakan coba lagi nanti.",
                    ) from error
                if status_code >= 500:
                    is_last_attempt = attempt >= self.max_retries
                    if is_last_attempt:
                        logger.error("LLM API server error %d: %s", status_code, error)
                        self._raise_model_not_available()
                    wait = self.retry_delay_seconds * (2 ** attempt)
                    logger.warning("LLM API server error %d, retrying in %.1fs (attempt %d/%d)",
                                   status_code, wait, attempt + 1, self.max_retries + 1)
                    await asyncio.sleep(wait)
                    continue
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Layanan AI sementara tidak tersedia. Silakan coba lagi.",
                ) from error

            except httpx.TimeoutException as error:
                is_last_attempt = attempt >= self.max_retries
                if is_last_attempt:
                    logger.error(
                        "LLM HTTP timeout after %.1f seconds: %s",
                        self.timeout_seconds,
                        error,
                    )
                    self._raise_model_not_available()
                await asyncio.sleep(self.retry_delay_seconds)

            except httpx.HTTPError as error:
                is_last_attempt = attempt >= self.max_retries
                if is_last_attempt:
                    logger.error("LLM HTTP request failed: %s", error)
                    self._raise_model_not_available()
                await asyncio.sleep(self.retry_delay_seconds)
        self._raise_model_not_available()

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
            payload = self._build_payload(
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

    @staticmethod
    def _raise_model_not_available() -> NoReturn:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Layanan AI sementara tidak tersedia. Silakan coba lagi.",
        )

    def _extract_text(self, response_data: dict[str, Any]) -> str:
        try:
            self._raise_if_error_payload(response_data)
            message_content = self._extract_message_content(response_data)
            text = self._normalize_content_to_text(message_content)
            if not text:
                raise ValueError("Response LLM kosong.")
            return text
        except (KeyError, IndexError) as error:
            raise ValueError(
                f"Format response AI tidak sesuai: {str(error)}") from error

    @staticmethod
    def _raise_if_error_payload(response_data: dict[str, Any]) -> None:
        if "error" not in response_data:
            return
        error_payload = response_data.get("error") or {}
        error_message = error_payload.get("message") or "Unknown LLM error"
        raise ValueError(f"LLM error payload: {error_message}")

    @staticmethod
    def _extract_message_content(response_data: dict[str, Any]) -> Any:
        choices = response_data.get("choices", [])
        if not choices:
            raise ValueError("Tidak ada choices pada response LLM.")
        message = choices[0].get("message") or {}
        return message.get("content")

    @staticmethod
    def _normalize_content_to_text(content: Any) -> str:
        if isinstance(content, str):
            return content.strip()

        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str) and item.strip():
                    parts.append(item.strip())
                    continue
                if isinstance(item, dict):
                    text_part = item.get("text")
                    if isinstance(text_part, str) and text_part.strip():
                        parts.append(text_part.strip())
            return "\n".join(parts)

        return ""

    @staticmethod
    def _parse_visualization_decision(raw: str) -> VisualizationDecision:
        cleaned = (raw or "").strip()
        if cleaned.startswith("```"):
            lines = [line for line in cleaned.splitlines()
                     if not line.strip().startswith("```")]
            cleaned = "\n".join(lines).strip()

        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError:
            return VisualizationDecision(is_visualize=False, chart_type=None)

        is_visualize = bool(payload.get("is_visualize", False))
        chart_type = payload.get("chart_type")
        if chart_type not in {"bar", "pie", "donut"}:
            chart_type = "bar" if is_visualize else None

        return VisualizationDecision(
            is_visualize=is_visualize,
            chart_type=chart_type,
        )

    @staticmethod
    def _clean_sql_output(raw: str) -> str:
        """
        Bersihkan output LLM dari artefak markdown atau karakter tak diinginkan.
        """
        # Hapus backtick markdown jika ada
        sql = raw.strip()
        if sql.startswith("```"):
            lines = sql.split("\n")
            # Hapus baris pertama (```sql atau ```) dan terakhir (```)
            lines = [l for l in lines if not l.strip().startswith("```")]
            sql = "\n".join(lines).strip()
        return sql


class _UseNextModelCandidate(Exception):
    """Signal internal agar service mencoba kandidat model berikutnya."""
