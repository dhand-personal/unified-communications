#!/usr/bin/env python3
"""
Extract Gong call IDs from HubSpot meeting records.

Gong syncs calls into HubSpot as 'meetings'. The Gong call ID is embedded as
an HTML <a href="..."> link inside `hs_meeting_body`. This script reads a JSON
list of HubSpot meeting records and returns the extracted call IDs plus a
manifest joining HubSpot meeting metadata to the Gong call ID.

Input shapes accepted:
  - {"results": [<meeting>, ...]} (HubSpot search_crm_objects response)
  - [<meeting>, ...] (already a list)
Each <meeting> must include at minimum {id, properties:{hs_meeting_body, ...}}.

Output: JSON list of
  {
    "hubspot_meeting_id": str,
    "gong_call_id": str,
    "title": str,
    "start_time": ISO str,
    "end_time": ISO str,
    "outcome": str,
    "source_detail": str,
    "owner_id": str
  }

Meetings without a Gong link are dropped (with a stderr note).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

GONG_ID_RE = re.compile(r"gong\.io/call\?id=(\d+)")


def extract(meetings: list[dict]) -> list[dict]:
    out: list[dict] = []
    skipped = 0
    for m in meetings:
        props = m.get("properties") or {}
        body = props.get("hs_meeting_body") or ""
        match = GONG_ID_RE.search(body)
        if not match:
            skipped += 1
            continue
        out.append({
            "hubspot_meeting_id": str(m.get("id") or props.get("hs_object_id") or ""),
            "gong_call_id": match.group(1),
            "title": props.get("hs_meeting_title"),
            "start_time": props.get("hs_meeting_start_time"),
            "end_time": props.get("hs_meeting_end_time"),
            "outcome": props.get("hs_meeting_outcome"),
            "source_detail": props.get("hs_object_source_detail_1"),
            "owner_id": props.get("hubspot_owner_id"),
        })
    if skipped:
        sys.stderr.write(f"Note: skipped {skipped} meeting(s) with no Gong link.\n")
    return out


def main() -> None:
    p = argparse.ArgumentParser(description="Extract Gong call IDs from HubSpot meetings.")
    p.add_argument("--input", required=True,
                   help="Path to JSON file with HubSpot meetings (search response or list).")
    p.add_argument("--out", help="Write extracted manifest here. Default stdout.")
    args = p.parse_args()

    data = json.loads(Path(args.input).read_text())
    if isinstance(data, dict):
        meetings = data.get("results") or data.get("meetings") or []
    else:
        meetings = data

    result = extract(meetings)
    text = json.dumps({"meetings": result, "count": len(result)}, indent=2, ensure_ascii=False)
    if args.out and args.out != "-":
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
        sys.stderr.write(f"Wrote {args.out}\n")
    else:
        sys.stdout.write(text + "\n")


if __name__ == "__main__":
    main()
