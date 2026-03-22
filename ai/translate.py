"""Translate bot content to a user's preferred language using Claude."""

import hashlib
import logging
from typing import Optional

import anthropic

from config import ANTHROPIC_API_KEY, CLAUDE_MODEL

logger = logging.getLogger(__name__)

_client: Optional[anthropic.AsyncAnthropic] = None

LANGUAGE_NAMES = {
    "en": "English",
    "es": "Spanish",
    "de": "German",
    "ru": "Russian",
    "uz": "Uzbek",
    "uk": "Ukrainian",
    "fr": "French",
    "zh": "Chinese (Simplified)",
}


def _get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
    return _client


async def translate_text(text: str, target_lang: str) -> str:
    """Translate HTML-formatted text to target_lang. Returns original on error or if lang=en.

    Results are cached in Supabase for 3 hours to avoid duplicate Claude API calls.
    """
    if target_lang == "en" or not target_lang:
        return text

    from db import supabase as db

    cache_key = hashlib.md5(f"{target_lang}:{text}".encode()).hexdigest()

    cached = db.get_cached_translation(cache_key)
    if cached:
        logger.debug("Translation cache hit for lang=%s key=%s", target_lang, cache_key[:8])
        return cached

    lang_name = LANGUAGE_NAMES.get(target_lang, target_lang)

    try:
        async with _get_client().messages.stream(
            model=CLAUDE_MODEL,
            max_tokens=4096,
            messages=[{
                "role": "user",
                "content": (
                    f"Translate the following financial market analysis text to {lang_name}. "
                    "Preserve all HTML tags (<b>, <i>, <code>, <u>), emoji, numbers, and symbols exactly as they are. "
                    "Only output the translated text — nothing else.\n\n"
                    f"{text}"
                ),
            }],
        ) as stream:
            response = await stream.get_final_message()

        translated = response.content[0].text.strip()
        db.save_cached_translation(cache_key, translated)
        return translated

    except Exception as exc:
        logger.error("Translation to %s failed: %s", target_lang, exc)
        return text  # Fall back to English on any error
