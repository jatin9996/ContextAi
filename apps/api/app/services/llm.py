import logging
from collections.abc import Awaitable, Callable

from app.core.config import settings
from app.core.errors import AppError

logger = logging.getLogger(__name__)


def categorize_model_error(exc: Exception) -> str:
    text = f"{type(exc).__name__} {exc}".lower()
    if "timeout" in text or "timed out" in text:
        return "model_timeout"
    if "429" in text or "resource_exhausted" in text or "rate limit" in text:
        return "rate_limited"
    return "model_failed"


def public_model_message(category: str) -> str:
    if category == "model_timeout":
        return "The model took too long to respond."
    if category == "rate_limited":
        return "The model provider is rate limiting requests. Try again shortly."
    return "The model request failed."


async def generate_text(
    prompt: str,
    on_token: Callable[[str], Awaitable[None]] | None = None,
) -> tuple[str, dict]:
    if not settings.llm_configured:
        raise AppError("llm_unconfigured", "No generative model is configured.", 503)
    try:
        from google import genai
        from google.genai import types
    except Exception as exc:
        raise AppError("llm_unconfigured", "The model client is not available.", 503) from exc

    client = genai.Client(api_key=settings.google_api_key)
    pieces: list[str] = []
    usage: dict = {}
    try:
        stream = await client.aio.models.generate_content_stream(
            model=settings.gemini_model,
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.2),
        )
        async for chunk in stream:
            text = getattr(chunk, "text", None) or ""
            if text:
                pieces.append(text)
                if on_token is not None:
                    await on_token(text)
            metadata = getattr(chunk, "usage_metadata", None)
            if metadata is not None:
                usage = {
                    "prompt_tokens": getattr(metadata, "prompt_token_count", None),
                    "completion_tokens": getattr(metadata, "candidates_token_count", None),
                    "provider": "gemini",
                    "model": settings.gemini_model,
                }
    except AppError:
        raise
    except Exception as exc:
        category = categorize_model_error(exc)
        logger.warning(
            "model request failed",
            extra={"component": "llm", "error_category": category},
        )
        raise AppError(category, public_model_message(category), 502) from exc
    text = "".join(pieces).strip()
    if not text:
        raise AppError("empty_response", "The model returned an empty response.", 502)
    if "prompt_tokens" in usage:
        prompt_tokens = usage.get("prompt_tokens") or 0
        completion_tokens = usage.get("completion_tokens") or 0
        usage["estimated_cost_usd"] = round(
            (prompt_tokens / 1_000_000) * settings.gemini_input_cost_per_million
            + (completion_tokens / 1_000_000) * settings.gemini_output_cost_per_million,
            6,
        )
        usage["cost_is_estimate"] = True
    return text, usage
