"""Quick manual check: hits Marketaux directly and prints normalized
results, so you can confirm MARKETAUX_API_TOKEN works and see what a real
article + its tagged symbols look like before running the full app.

Usage:
    python scripts/test_news_api.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, news_client  # noqa: E402


def main() -> None:
    if not config.MARKETAUX_API_TOKEN:
        print("MARKETAUX_API_TOKEN is empty -- fill in .env first.")
        return

    print(f"Base URL: {config.MARKETAUX_BASE_URL}")
    try:
        items = news_client.get_news(limit=5)
        print(f"\n{len(items)} normalized item(s) with at least one tagged symbol:")
        print(json.dumps(items, indent=2))
        if not items:
            print("(Got a response but no items had entities -- try again later, news volume varies.)")
    except Exception as exc:
        print(f"Call FAILED: {exc}")


if __name__ == "__main__":
    main()
