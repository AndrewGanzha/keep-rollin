from __future__ import annotations

import json
from pathlib import Path

from app.main import app

OUTPUT = Path(__file__).resolve().parents[2] / "contract" / "openapi.json"


def main() -> None:
    document = app.openapi()
    OUTPUT.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"wrote {OUTPUT.relative_to(OUTPUT.parents[1])}")


if __name__ == "__main__":
    main()
