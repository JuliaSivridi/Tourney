import json
from pathlib import Path

_LOCALES_DIR = Path(__file__).parent
_SUPPORTED = {"en", "de", "fr", "pt-br", "uk", "ru"}
_DEFAULT = "en"
_FLAGS = {"en": "🇬🇧", "de": "🇩🇪", "fr": "🇫🇷", "pt-br": "🇧🇷", "uk": "🇺🇦", "ru": "🇷🇺"}

_cache: dict[str, dict] = {}


def _load(lang: str) -> dict:
    if lang not in _cache:
        path = _LOCALES_DIR / f"{lang}.json"
        with path.open(encoding="utf-8") as f:
            _cache[lang] = json.load(f)
    return _cache[lang]


def t(lang: str, key: str, **kwargs) -> str:
    l = lang if lang in _SUPPORTED else _DEFAULT
    text = _load(l).get(key) or _load(_DEFAULT).get(key, key)
    return text.format(**kwargs) if kwargs else text


def normalize_lang(lang: str) -> str:
    if lang in _SUPPORTED:
        return lang
    # e.g. "pt" -> "pt-br", "uk" stays "uk"
    for supported in _SUPPORTED:
        if supported.startswith(lang):
            return supported
    return _DEFAULT


def flags_keyboard() -> list[str]:
    return [f"{flag} {code}" for code, flag in _FLAGS.items()]


def lang_from_flag_btn(text: str) -> str | None:
    parts = text.split(" ", 1)
    if len(parts) == 2 and parts[1] in _SUPPORTED:
        return parts[1]
    return None
