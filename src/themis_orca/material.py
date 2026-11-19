"""Translate Orca's material field using Themis's filament-tuple suffix contract.

Keep aligned with app.services.filament_tuple.split_type; integration tests compare
the two without making the Orca wheel depend on the backend. Never parse preset names.
"""
import re


_ALIASES = {"+": "plus", "plus": "plus", "silk": "silk", "cf": "cf", "gf": "gf", "hf": "hf",
            "carbon fiber": "cf", "carbon": "cf", "glass fiber": "gf", "glass": "gf",
            "high flow": "hf", "basic": "standard", "standard": "standard"}
_BASE_TYPES = frozenset({"pla", "petg", "pet", "abs", "asa", "pc", "pa", "tpu", "hips", "pp", "pva", "pps", "pei", "pctg"})


def split_material(raw):
    text = str(raw).strip() if raw is not None else ""
    if not text:
        return None, None
    if text.endswith("+"):
        base, suffix = text[:-1].strip(), "+"
    else:
        parts = re.split(r"[\s_/-]+", text, maxsplit=1)
        base, suffix = parts[0], parts[1].strip() if len(parts) > 1 else ""
    if not base:
        return text, "standard"
    if not suffix:
        return base, "standard"
    if base.casefold() in _BASE_TYPES and suffix.casefold() in _BASE_TYPES:
        return text, "standard"
    return base, _ALIASES.get(suffix.casefold(), suffix.casefold())
