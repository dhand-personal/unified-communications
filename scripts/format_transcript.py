#!/usr/bin/env python3
"""
Format transcripts produced by gong_client.py fetch_transcripts.

Two modes:
  default — one readable .txt per call into --output-dir.
  --bulk  — output-dir + manifest.json + manifest.csv + transcripts/ subfolder.

Input JSON shape (from gong_client.py fetch_transcripts):
  {"transcripts": [
      {
        "call_id": "...",
        "title": "...",
        "started": "ISO",
        "duration_seconds": int,
        "url": "...",
        "parties": [{"name": "...", "email": "...", "affiliation": "..."}],
        "sentences": [{"start_ms": int, "speaker_name": "...", "speaker_email": "...",
                       "speaker_affiliation": "Internal|External", "text": "..."}],
        "customer_facing": bool
      }, ...
    ]
  }
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path


def _ms_to_time(ms: int | None) -> str:
    if ms is None:
        return ""
    s = int(ms) // 1000
    return f"{s // 60:02d}:{s % 60:02d}"


def _safe_title(title: str, max_len: int = 40) -> str:
    cleaned = re.sub(r"[^\w\-]", "_", title or "untitled").strip("_")
    return cleaned[:max_len] or "untitled"


def _format_single(call: dict) -> str:
    parties = call.get("parties") or []
    parties_block = "\n".join(
        f"  - {p.get('name', 'Unknown')}"
        + (f" <{p['email']}>" if p.get("email") else "")
        + (f" [{p['affiliation']}]" if p.get("affiliation") else "")
        for p in parties
    ) or "  (no party info)"

    started = call.get("started") or "unknown"
    dur_min = (call.get("duration_seconds") or 0) // 60
    header = (
        f"Call:     {call.get('title', 'Untitled')}\n"
        f"Date:     {started}\n"
        f"Duration: {dur_min} minutes\n"
        f"Gong:     {call.get('url', '')}\n"
        f"Audience: {'customer-facing' if call.get('customer_facing') else 'internal'}\n"
        f"Sentences: {len(call.get('sentences') or [])}\n\n"
        f"Parties:\n{parties_block}\n\n"
        + ("─" * 60) + "\n\n"
    )

    body_lines = []
    last_speaker = None
    for s in call.get("sentences") or []:
        spk_label = s.get("speaker_name") or "Unknown"
        if s.get("speaker_affiliation"):
            spk_label = f"{spk_label} [{s['speaker_affiliation']}]"
        ts = _ms_to_time(s.get("start_ms"))
        # Compact: blank line on speaker change
        if spk_label != last_speaker:
            body_lines.append("")
            last_speaker = spk_label
        body_lines.append(f"[{ts}] {spk_label}: {s.get('text', '')}")

    return header + "\n".join(body_lines).lstrip()


def _filename(call: dict) -> str:
    date = (call.get("started") or "0000-00-00")[:10]
    title = _safe_title(call.get("title", "untitled"))
    cid = call.get("call_id") or "noid"
    return f"{date}_{title}_{cid}.txt"


def write_single(transcripts: list[dict], output_dir: Path) -> list[Path]:
    """One .txt per call directly in output_dir."""
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for call in transcripts:
        path = output_dir / _filename(call)
        path.write_text(_format_single(call), encoding="utf-8")
        paths.append(path)
        sys.stderr.write(f"  wrote {path.name}\n")
    return paths


def write_bulk(transcripts: list[dict], output_dir: Path) -> dict:
    """output_dir/manifest.{json,csv} + output_dir/transcripts/<file>.txt"""
    tx_dir = output_dir / "transcripts"
    tx_dir.mkdir(parents=True, exist_ok=True)

    manifest_rows: list[dict] = []
    for call in transcripts:
        fname = _filename(call)
        path = tx_dir / fname
        path.write_text(_format_single(call), encoding="utf-8")
        manifest_rows.append({
            "call_id": call.get("call_id"),
            "title": call.get("title"),
            "date": (call.get("started") or "")[:10],
            "started": call.get("started"),
            "duration_min": (call.get("duration_seconds") or 0) // 60,
            "customer_facing": bool(call.get("customer_facing")),
            "participants": "; ".join(
                f"{(p or {}).get('name', 'Unknown')} <{(p or {}).get('email', '')}>"
                for p in call.get("parties") or []
            ),
            "gong_url": call.get("url"),
            "file": f"transcripts/{fname}",
        })

    (output_dir / "manifest.json").write_text(
        json.dumps({"transcripts": manifest_rows, "count": len(manifest_rows)},
                   indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    with (output_dir / "manifest.csv").open("w", newline="", encoding="utf-8") as f:
        fields = ["call_id", "title", "date", "started", "duration_min",
                  "customer_facing", "participants", "gong_url", "file"]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for row in manifest_rows:
            w.writerow(row)

    return {
        "output_dir": str(output_dir),
        "manifest_json": str(output_dir / "manifest.json"),
        "manifest_csv": str(output_dir / "manifest.csv"),
        "transcript_count": len(manifest_rows),
    }


def main() -> None:
    p = argparse.ArgumentParser(description="Format Gong transcripts to disk.")
    p.add_argument("--transcripts", required=True,
                   help="Path to JSON from gong_client.py fetch_transcripts.")
    p.add_argument("--output-dir", required=True,
                   help="Where to write transcript files.")
    p.add_argument("--bulk", action="store_true",
                   help="Bulk mode — produce manifest + transcripts/ subfolder.")
    args = p.parse_args()

    data = json.loads(Path(args.transcripts).read_text())
    transcripts = data.get("transcripts") if isinstance(data, dict) else data
    if not transcripts:
        sys.stderr.write("No transcripts to write.\n")
        sys.exit(1)

    out_dir = Path(args.output_dir).expanduser()
    if args.bulk:
        result = write_bulk(transcripts, out_dir)
        sys.stdout.write(json.dumps(result, indent=2) + "\n")
    else:
        paths = write_single(transcripts, out_dir)
        sys.stdout.write(json.dumps(
            {"output_dir": str(out_dir), "files": [str(p) for p in paths]},
            indent=2,
        ) + "\n")


if __name__ == "__main__":
    main()
