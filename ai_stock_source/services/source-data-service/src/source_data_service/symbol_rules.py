from __future__ import annotations

from typing import Any


def normalize_symbol(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if not text:
        return None
    lowered = text.lower()
    if lowered.startswith(("sz", "sh", "bj")) and len(lowered) == 8:
        return f"{lowered[2:8]}.{lowered[:2].upper()}"
    if "." in text:
        market, code = text.split(".", 1)
        if market in {"0", "1"} and len(code) >= 6:
            return f"{code[:6]}.{'SH' if market == '1' else 'SZ'}"
        if market.lower() in {"sz", "sh", "bj"} and len(code) >= 6:
            return f"{code[:6]}.{market.upper()}"
        if code.upper() in {"SZ", "SH", "BJ"} and len(market) >= 6:
            return f"{market[:6]}.{code.upper()}"
    if len(text) == 9 and text[-3:].upper() in {".SZ", ".SH", ".BJ"}:
        return f"{text[:6]}.{text[-2:].upper()}"
    if len(text) == 6 and text.isdigit():
        if text.startswith(("60", "68", "5", "9")):
            return f"{text}.SH"
        if text.startswith(("00", "30", "1", "2", "3")):
            return f"{text}.SZ"
        if text.startswith(("4", "8", "92")):
            return f"{text}.BJ"
    return text


def is_a_share_symbol(value: Any) -> bool:
    symbol = normalize_symbol(value)
    if not symbol or len(symbol) != 9 or symbol[6] != ".":
        return False
    code, exchange = symbol.split(".", 1)
    if len(code) != 6 or not code.isdigit():
        return False
    if exchange == "SH":
        return code.startswith(("60", "68"))
    if exchange == "SZ":
        return code.startswith(("00", "30"))
    if exchange == "BJ":
        return code.startswith(("4", "8", "92"))
    return False
