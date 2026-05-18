#!/usr/bin/env python3
"""
Update galenus_images.json with physical page counts derived from Zotero page ranges.

For each Kühn volume, collects every work's page range from the Zotero data,
finds the maximum edition page number across all works in that volume, then
writes count = max_edition_page + pdiff into galenus_images.json["kuhn"][vol].

count represents the total physical pages (1-indexed) in the Medica digitization
up to and including the last edition page. OSD sequence mode uses this to build
the full URL list; physical index i corresponds to URL with %% = zero-padded i.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ZOTERO_JSON = ROOT / "src/mera_galeni_folia/static/json/gv_zotero.json"
IMAGES_JSON = ROOT / "src/mera_galeni_folia/static/json/galenus_images.json"

KUHN_VERBATIM_COLLECTION_ID = "XWUKKHRC"


def parse_volumes(volume_str: str) -> list[str]:
    """Return individual volume identifiers from a string like '17b-18a' or '12-13'."""
    return re.findall(r"\d+[a-z]?", volume_str)


def parse_page_ranges(pages_str: str) -> list[str]:
    """Split a pages string into individual range tokens (space- or semicolon-separated)."""
    return re.split(r"[\s;]+", pages_str.strip())


def max_page(range_str: str) -> int:
    """Return the highest integer found in a range string like '1-173' or '173'."""
    nums = re.findall(r"\d+", range_str)
    return max(int(n) for n in nums) if nums else 0


def main() -> None:
    zotero_data = json.loads(ZOTERO_JSON.read_text(encoding="utf-8"))
    images_data = json.loads(IMAGES_JSON.read_text(encoding="utf-8"))

    kuhn_items = [
        item["data"]
        for item in zotero_data
        if KUHN_VERBATIM_COLLECTION_ID
        in (item.get("data", {}).get("collections") or [])
        and any(
            c.get("lastName") == "Kühn"
            for c in item.get("data", {}).get("creators", [])
        )
    ]

    # vol_id -> max edition page seen across all works
    vol_max: dict[str, int] = {}

    for item in kuhn_items:
        vol_str = item.get("volume") or ""
        pages_str = item.get("pages") or ""
        if not vol_str or not pages_str:
            continue

        volumes = parse_volumes(vol_str)
        ranges = parse_page_ranges(pages_str)

        if len(volumes) != len(ranges):
            print(
                f"Warning: volume/range count mismatch — "
                f"volume={vol_str!r} pages={pages_str!r}; skipping",
                file=sys.stderr,
            )
            continue

        for vol, rng in zip(volumes, ranges):
            p = max_page(rng)
            if p > vol_max.get(vol, 0):
                vol_max[vol] = p

    kuhn_config: dict = images_data.get("kuhn", {})
    updated = []
    missing = []

    for vol, config in kuhn_config.items():
        pdiff: int = config.get("pdiff", 0)
        if vol in vol_max:
            config["count"] = vol_max[vol] + pdiff
            updated.append(vol)
        else:
            missing.append(vol)

    IMAGES_JSON.write_text(
        json.dumps(images_data, indent=4, ensure_ascii=False), encoding="utf-8"
    )

    print("Updated galenus_images.json\n")
    print(f"{'Vol':<8} {'Max edition page':<20} {'pdiff':<8} {'count'}")
    print("-" * 48)
    for vol in sorted(kuhn_config.keys(), key=lambda v: (re.sub(r"[a-z]", "", v), v)):
        config = kuhn_config[vol]
        print(
            f"{vol:<8} {vol_max.get(vol, '—')!s:<20} "
            f"{config.get('pdiff', '—')!s:<8} {config.get('count', '—')}"
        )

    if missing:
        print(f"\nNo Zotero data found for volumes: {', '.join(missing)}", file=sys.stderr)


if __name__ == "__main__":
    main()
