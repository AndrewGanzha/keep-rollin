from __future__ import annotations

import secrets

RECOVERY_CODE_COUNT = 10


def generate_recovery_codes() -> list[str]:
    codes: list[str] = []
    for _ in range(RECOVERY_CODE_COUNT):
        raw = secrets.token_hex(10).upper()
        codes.append("-".join(raw[index : index + 4] for index in range(0, 20, 4)))
    return codes


def normalize_recovery_code(code: str) -> str:
    normalized = "".join(character for character in code.upper() if character.isalnum())
    if len(normalized) != 20:
        raise ValueError("invalid recovery code")
    return normalized
