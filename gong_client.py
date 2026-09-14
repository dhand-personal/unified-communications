#!/usr/bin/env python3
"""
Gong API client for the unified-communication skill's Gong integration.

Requires a Gong API key with the appropriate read scopes (see below). This
script does not ship with any credentials embedded — whoever runs it must
supply their own via environment variables.

Subcommands:
  list_calls         List calls in a date window. Optional customer-facing filter,
                     min-duration filter, owner filter. Returns JSON with parties.
  search_content     Find calls where a phrase appears in Gong's AI summaries
                     (brief, key points, outline, highlights, trackers, topics).
                     Add --deep-search to also grep transcripts.
  fetch_transcripts  Fetch transcripts for a list of call IDs. Two-call pattern:
                     /v2/calls/extensive (for parties) + /v2/calls/transcript
                     (for sentences). Output merges speaker names onto sentences.
  find_user          Resolve a Gong user name → primary user ID for owner mode.
  ping               Health check — confirm credentials work.

Required setup — environment variables:
  GONG_ACCESS_KEY       Required. From your Gong admin (Company Settings ->
                         API in Gong), an API key with at least
                         api:calls:read:basic, api:calls:read:extensive, and
                         api:calls:read:transcript scopes.
  GONG_SECRET           Required. The secret paired with that access key.
  GONG_BASE_URL         Optional. Some Gong tenants are pinned to a specific
                         region subdomain (e.g. https://us-XXXXX.api.gong.io)
                         rather than the generic https://api.gong.io. Ask
                         your Gong admin if calls fail with a 403 against the
                         default below.
  GONG_INTERNAL_DOMAINS Optional. Comma-separated list of your own company's
                         email domains (e.g. "yourcompany.com,yourteam.io"),
                         used to tell internal parties from customer-facing
                         ones for the --customer-facing filter. If unset,
                         every party is treated as external (see
                         `_is_external` below) rather than guessing at a
                         domain list that doesn't belong to whoever is
                         running this.

The script exits with an error rather than running if GONG_ACCESS_KEY or
GONG_SECRET is missing — there is no built-in fallback credential.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

try:
    import requests
except ImportError:
    print("Installing 'requests'...", file=sys.stderr)
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install",
                           "requests", "--break-system-packages", "-q"])
    import requests

# Company-internal email domains, used only to tell internal parties from
# customer-facing ones for the --customer-facing filter. Not hardcoded — set
# via the GONG_INTERNAL_DOMAINS env var (comma-separated), e.g.:
#   export GONG_INTERNAL_DOMAINS="yourcompany.com,yourteam.io"
_internal_domains_raw = os.environ.get("GONG_INTERNAL_DOMAINS", "")
INTERNAL_DOMAINS = {d.strip().lower() for d in _internal_domains_raw.split(",") if d.strip()}

DEFAULT_BASE_URL = "https://api.gong.io"


# ─── auth ─────────────────────────────────────────────────────────────────────

def _credentials() -> tuple[str, str, str]:
    # No embedded fallback on purpose — whoever runs this must supply their
    # own Gong API credentials.
    access = os.environ.get("GONG_ACCESS_KEY")
    secret = os.environ.get("GONG_SECRET")
    base = os.environ.get("GONG_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    if not access or not secret:
        sys.stderr.write(
            "ERROR: No Gong credentials found. Set the GONG_ACCESS_KEY and "
            "GONG_SECRET environment variables before running this script.\n"
            "Get an API key with call-read scopes from your Gong admin "
            "(Company Settings -> API in Gong).\n"
        )
        sys.exit(2)
    return access, secret, base


def _auth_headers() -> dict[str, str]:
    access, secret, _ = _credentials()
    token = base64.b64encode(f"{access}:{secret}".encode()).decode()
    return {"Authorization": f"Basic {token}", "Content-Type": "application/json"}


def _base() -> str:
    return _credentials()[2]


# ─── helpers ──────────────────────────────────────────────────────────────────

def _eprint(msg: str) -> None:
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()


def _parse_date(s: str) -> str:
    """Accept YYYY-MM-DD or full ISO. Return ISO Zulu string."""
    if "T" in s:
        return s
    return f"{s}T00:00:00Z"


def _date_window(from_date: str, to_date: str | None) -> tuple[str, str]:
    from_iso = _parse_date(from_date)
    to_iso = _parse_date(to_date) if to_date else datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    return from_iso, to_iso


def _is_external(email: str | None) -> bool:
    if not email:
        return False
    if not INTERNAL_DOMAINS:
        # No internal domain list configured — there's no safe default to
        # guess here, so every party with an email is treated as external.
        return True
    email = email.lower()
    return not any(email.endswith("@" + d) or email.endswith("." + d) for d in INTERNAL_DOMAINS)


def _request(method: str, path: str, **kwargs) -> dict[str, Any]:
    url = f"{_base()}{path}"
    for attempt in range(3):
        try:
            r = requests.request(method, url, headers=_auth_headers(), timeout=60, **kwargs)
        except requests.exceptions.RequestException as e:
            # Connection-level failure (DNS, proxy/firewall block, timeout,
            # TLS error, etc.) -- not an HTTP status code, so it never hits
            # the retry-on-status-code logic below. Report it cleanly
            # instead of letting the exception surface as a raw traceback.
            sys.stderr.write(
                f"ERROR: could not reach Gong ({method} {path}): {e}\n"
                "Check network/proxy access to the Gong API host and that "
                "GONG_BASE_URL (if set) is correct.\n"
            )
            sys.exit(1)
        if r.status_code == 200:
            return r.json()
        if r.status_code in (429, 502, 503, 504) and attempt < 2:
            wait = (attempt + 1) * 2
            _eprint(f"  [{r.status_code}] retrying in {wait}s...")
            time.sleep(wait)
            continue
        sys.stderr.write(f"ERROR {r.status_code} on {method} {path}\n{r.text[:500]}\n")
        sys.exit(1)
    return {}  # unreachable


# ─── core ─────────────────────────────────────────────────────────────────────

def list_calls(from_date: str,
               to_date: str | None,
               customer_facing: bool,
               min_duration_minutes: int,
               primary_user_ids: list[str] | None,
               title_match: str | None = None,
               party_domain: str | None = None) -> list[dict[str, Any]]:
    """Page through /v2/calls/extensive, attach parties, apply filters.

    Filters (all optional, AND'd together):
      customer_facing       - keep calls with ≥1 external (non-internal) party
      min_duration_minutes  - drop short calls
      primary_user_ids      - server-side filter to a rep
      title_match           - case-insensitive regex over call title
                              ("discovery|demo|poc|pov|renewal|kickoff", etc.)
      party_domain          - keep calls where ≥1 party email contains this
                              substring (e.g., "acme.com", "northwind.co")
    """
    from_iso, to_iso = _date_window(from_date, to_date)
    _eprint(f"Listing calls {from_iso[:10]} → {to_iso[:10]}...")

    body: dict[str, Any] = {
        "filter": {"fromDateTime": from_iso, "toDateTime": to_iso},
        "contentSelector": {"exposedFields": {"parties": True}},
    }
    if primary_user_ids:
        body["filter"]["primaryUserIds"] = primary_user_ids

    all_calls: list[dict[str, Any]] = []
    cursor = None
    page = 0
    while True:
        page += 1
        if cursor:
            body["cursor"] = cursor
        data = _request("POST", "/v2/calls/extensive", json=body)
        calls = data.get("calls") or []
        all_calls.extend(calls)
        records = data.get("records") or {}
        cursor = records.get("cursor")
        _eprint(f"  page {page}: +{len(calls)} (running total {len(all_calls)})")
        if not cursor or not calls:
            break

    _eprint(f"Fetched {len(all_calls)} calls.")

    # compile title regex once
    title_re = re.compile(title_match, re.IGNORECASE) if title_match else None
    domain_needle = party_domain.lower() if party_domain else None

    # filter
    keep = []
    min_sec = int(min_duration_minutes) * 60
    filtered_counts = {"duration": 0, "customer_facing": 0, "title": 0, "domain": 0}
    for c in all_calls:
        meta = c.get("metaData") or {}
        title = meta.get("title") or ""
        dur = meta.get("duration") or 0
        parties = c.get("parties") or []

        if dur < min_sec:
            filtered_counts["duration"] += 1
            continue
        if customer_facing and not any(_is_external(p.get("emailAddress")) for p in parties):
            filtered_counts["customer_facing"] += 1
            continue
        if title_re and not title_re.search(title):
            filtered_counts["title"] += 1
            continue
        if domain_needle and not any(
            domain_needle in (p.get("emailAddress") or "").lower() for p in parties
        ):
            filtered_counts["domain"] += 1
            continue

        keep.append({
            "id": meta.get("id"),
            "title": title or "Untitled",
            "started": meta.get("started"),
            "duration_seconds": dur,
            "duration_minutes": dur // 60,
            "url": meta.get("url"),
            "primary_user_id": meta.get("primaryUserId"),
            "parties": [
                {
                    "name": p.get("name"),
                    "email": p.get("emailAddress"),
                    "affiliation": p.get("affiliation"),
                    "speaker_id": p.get("speakerId"),
                } for p in parties
            ],
            "customer_facing": any(_is_external(p.get("emailAddress")) for p in parties),
        })
    drops = ", ".join(f"{k}={v}" for k, v in filtered_counts.items() if v)
    _eprint(f"After filters: {len(keep)} calls ({drops or 'no drops'}).")
    return keep


def search_content(from_date: str,
                   to_date: str | None,
                   query: str,
                   customer_facing: bool = False,
                   min_duration_minutes: int = 0,
                   primary_user_ids: list[str] | None = None,
                   deep_search: bool = False,
                   party_domain: str | None = None) -> list[dict[str, Any]]:
    """Find calls where the query phrase appears in Gong's content metadata.

    By default searches Gong's pre-computed content (AI brief, key points,
    outline, highlights, trackers, topics). This is fast — everything comes
    back in one /v2/calls/extensive call, no transcript fetching.

    With deep_search=True, also pulls every transcript in the window and
    greps sentence text. Slower but catches phrases the AI brief missed.

    party_domain      - keep calls where ≥1 party email contains this
                        substring (e.g., "acme.com"). Same account-scoping
                        role as list_calls' --party-domain, for when there's
                        no HubSpot to resolve an account name to a domain.

    Returns matched calls with a `match_reasons` field listing where in the
    content the phrase was found (e.g., "keyPoint", "brief", "tracker:Pricing").
    """
    from_iso, to_iso = _date_window(from_date, to_date)
    _eprint(f"Searching content {from_iso[:10]} → {to_iso[:10]} for: {query!r}")

    body: dict[str, Any] = {
        "filter": {"fromDateTime": from_iso, "toDateTime": to_iso},
        "contentSelector": {
            "exposedFields": {
                "parties": True,
                "content": {
                    "brief": True,
                    "keyPoints": True,
                    "outline": True,
                    "highlights": True,
                    "trackers": True,
                    "topics": True,
                },
            },
        },
    }
    if primary_user_ids:
        body["filter"]["primaryUserIds"] = primary_user_ids

    # Compile case-insensitive query. Caller can pass a regex if they want.
    try:
        pat = re.compile(query, re.IGNORECASE)
    except re.error:
        pat = re.compile(re.escape(query), re.IGNORECASE)

    all_calls: list[dict[str, Any]] = []
    cursor = None
    page = 0
    while True:
        page += 1
        if cursor:
            body["cursor"] = cursor
        data = _request("POST", "/v2/calls/extensive", json=body)
        calls = data.get("calls") or []
        all_calls.extend(calls)
        records = data.get("records") or {}
        cursor = records.get("cursor")
        _eprint(f"  page {page}: +{len(calls)} (running total {len(all_calls)})")
        if not cursor or not calls:
            break

    _eprint(f"Fetched {len(all_calls)} calls. Scanning content...")

    min_sec = int(min_duration_minutes) * 60
    domain_needle = party_domain.lower() if party_domain else None
    matched: list[dict[str, Any]] = []

    for c in all_calls:
        meta = c.get("metaData") or {}
        dur = meta.get("duration") or 0
        if dur < min_sec:
            continue
        parties = c.get("parties") or []
        if customer_facing and not any(_is_external(p.get("emailAddress")) for p in parties):
            continue
        if domain_needle and not any(
            domain_needle in (p.get("emailAddress") or "").lower() for p in parties
        ):
            continue

        content = c.get("content") or {}
        reasons: list[dict[str, str]] = []

        # 1) AI brief — free text summary
        brief = content.get("brief") or ""
        if brief and pat.search(brief):
            m = pat.search(brief)
            snippet = brief[max(0, m.start()-60):m.end()+60].strip()
            reasons.append({"source": "brief", "snippet": snippet})

        # 2) keyPoints — bullet-form summaries
        for kp in content.get("keyPoints") or []:
            text = (kp or {}).get("text") or ""
            if text and pat.search(text):
                reasons.append({"source": "keyPoint", "snippet": text})

        # 3) outline — section narrative
        for section in content.get("outline") or []:
            sec_name = (section or {}).get("section") or ""
            for item in (section or {}).get("items") or []:
                text = (item or {}).get("text") or ""
                if text and pat.search(text):
                    reasons.append({
                        "source": f"outline:{sec_name}",
                        "snippet": text[:280],
                        "start_seconds": item.get("startTime"),
                    })

        # 4) highlights — next steps / decisions
        for hl in content.get("highlights") or []:
            hl_title = (hl or {}).get("title") or ""
            for item in (hl or {}).get("items") or []:
                text = (item or {}).get("text") or ""
                if text and pat.search(text):
                    reasons.append({
                        "source": f"highlight:{hl_title}",
                        "snippet": text,
                    })

        # 5) trackers — configured keyword trackers with hit counts
        for t in content.get("trackers") or []:
            t_name = (t or {}).get("name") or ""
            t_count = (t or {}).get("count") or 0
            if t_count > 0 and pat.search(t_name):
                reasons.append({
                    "source": f"tracker:{t_name}",
                    "snippet": f"{t_count} hit(s) on tracker '{t_name}'",
                    "hit_count": t_count,
                })

        # 6) topics — auto-detected discussion topics
        for tp in content.get("topics") or []:
            tp_name = (tp or {}).get("name") or ""
            tp_dur = (tp or {}).get("duration") or 0
            if tp_dur > 0 and pat.search(tp_name):
                reasons.append({
                    "source": f"topic:{tp_name}",
                    "snippet": f"{tp_dur}s spent on topic '{tp_name}'",
                    "duration_seconds": tp_dur,
                })

        if reasons:
            matched.append({
                "id": meta.get("id"),
                "title": meta.get("title") or "Untitled",
                "started": meta.get("started"),
                "duration_seconds": dur,
                "duration_minutes": dur // 60,
                "url": meta.get("url"),
                "primary_user_id": meta.get("primaryUserId"),
                "parties": [
                    {"name": p.get("name"), "email": p.get("emailAddress"),
                     "affiliation": p.get("affiliation")} for p in parties
                ],
                "customer_facing": any(_is_external(p.get("emailAddress")) for p in parties),
                "match_reasons": reasons,
                "match_count": len(reasons),
            })

    _eprint(f"Content match: {len(matched)} call(s).")

    # Deep search: pull every transcript and grep sentences for calls NOT
    # already matched (and add hits there). For efficiency we limit deep
    # search to the candidate set if the user already has a content match,
    # so they don't pay the transcript cost for nothing.
    if deep_search:
        already = {m["id"] for m in matched}
        candidates = [c for c in all_calls
                      if (c.get("metaData") or {}).get("id") not in already]
        # apply the same audience/duration prefilters
        candidate_ids = []
        for c in candidates:
            meta = c.get("metaData") or {}
            if (meta.get("duration") or 0) < min_sec:
                continue
            parties = c.get("parties") or []
            if customer_facing and not any(_is_external(p.get("emailAddress")) for p in parties):
                continue
            if domain_needle and not any(
                domain_needle in (p.get("emailAddress") or "").lower() for p in parties
            ):
                continue
            candidate_ids.append(meta.get("id"))
        if candidate_ids:
            _eprint(f"Deep search: scanning {len(candidate_ids)} additional transcript(s)...")
            transcripts = fetch_transcripts(candidate_ids)
            for t in transcripts:
                hits = []
                for s in t.get("sentences") or []:
                    text = s.get("text") or ""
                    if pat.search(text):
                        hits.append({
                            "source": "transcript",
                            "snippet": text,
                            "start_ms": s.get("start_ms"),
                            "speaker": s.get("speaker_name"),
                        })
                if hits:
                    matched.append({
                        "id": t["call_id"],
                        "title": t.get("title", "Untitled"),
                        "started": t.get("started"),
                        "duration_seconds": t.get("duration_seconds", 0),
                        "duration_minutes": (t.get("duration_seconds", 0)) // 60,
                        "url": t.get("url"),
                        "primary_user_id": None,
                        "parties": t.get("parties", []),
                        "customer_facing": t.get("customer_facing", False),
                        "match_reasons": hits[:20],  # cap at 20 to keep payload sane
                        "match_count": len(hits),
                        "match_source": "transcript_only",
                    })
            _eprint(f"Total after deep search: {len(matched)} call(s).")

    # sort newest first
    matched.sort(key=lambda m: m.get("started") or "", reverse=True)
    return matched


def _speaker_map(call_ids: list[str]) -> dict[str, dict[str, dict[str, str]]]:
    """Pull parties for the given call IDs; return {call_id: {speaker_id: party_info}}."""
    out: dict[str, dict[str, dict[str, str]]] = {}
    # Gong allows up to ~100 IDs per extensive call; batch to be safe.
    batch = 50
    for i in range(0, len(call_ids), batch):
        chunk = call_ids[i:i+batch]
        data = _request("POST", "/v2/calls/extensive", json={
            "filter": {"callIds": chunk},
            "contentSelector": {"exposedFields": {"parties": True}},
        })
        for c in data.get("calls") or []:
            cid = (c.get("metaData") or {}).get("id")
            if not cid:
                continue
            spk = {}
            for p in c.get("parties") or []:
                sid = p.get("speakerId")
                if sid:
                    spk[sid] = {
                        "name": p.get("name") or p.get("emailAddress") or "Unknown",
                        "email": p.get("emailAddress") or "",
                        "affiliation": p.get("affiliation") or "",
                    }
            out[cid] = spk
    return out


def _meta_map(call_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Pull lightweight call metadata for the given IDs."""
    out: dict[str, dict[str, Any]] = {}
    batch = 50
    for i in range(0, len(call_ids), batch):
        chunk = call_ids[i:i+batch]
        data = _request("POST", "/v2/calls/extensive", json={
            "filter": {"callIds": chunk},
            "contentSelector": {"exposedFields": {"parties": True}},
        })
        for c in data.get("calls") or []:
            meta = c.get("metaData") or {}
            cid = meta.get("id")
            if not cid:
                continue
            parties = c.get("parties") or []
            out[cid] = {
                "id": cid,
                "title": meta.get("title") or "Untitled",
                "started": meta.get("started"),
                "duration_seconds": meta.get("duration") or 0,
                "url": meta.get("url"),
                "parties": [
                    {
                        "name": p.get("name"),
                        "email": p.get("emailAddress"),
                        "affiliation": p.get("affiliation"),
                    } for p in parties
                ],
            }
    return out


def fetch_transcripts(call_ids: list[str]) -> list[dict[str, Any]]:
    """Fetch transcripts and merge speaker names. Returns a list of call records."""
    if not call_ids:
        return []

    _eprint(f"Fetching speaker maps for {len(call_ids)} call(s)...")
    spk = _speaker_map(call_ids)
    meta = _meta_map(call_ids)

    # /v2/calls/transcript accepts batches; doc suggests up to ~20-50.
    out: list[dict[str, Any]] = []
    batch = 20
    for i in range(0, len(call_ids), batch):
        chunk = call_ids[i:i+batch]
        _eprint(f"  transcripts batch {i//batch + 1}: {len(chunk)} call(s)")
        data = _request("POST", "/v2/calls/transcript",
                        json={"filter": {"callIds": chunk}})
        for ct in data.get("callTranscripts") or []:
            cid = ct.get("callId")
            if not cid:
                continue
            this_spk = spk.get(cid, {})
            sentences: list[dict[str, Any]] = []
            for track in ct.get("transcript") or []:
                sid = track.get("speakerId")
                info = this_spk.get(sid, {})
                name = info.get("name") or track.get("speakerName") or "Unknown"
                email = info.get("email") or ""
                affil = info.get("affiliation") or ""
                for s in track.get("sentences") or []:
                    sentences.append({
                        "start_ms": s.get("start"),
                        "end_ms": s.get("end"),
                        "speaker_id": sid,
                        "speaker_name": name,
                        "speaker_email": email,
                        "speaker_affiliation": affil,
                        "text": (s.get("text") or "").strip(),
                    })
            sentences.sort(key=lambda x: x.get("start_ms") or 0)
            m = meta.get(cid, {})
            out.append({
                "call_id": cid,
                "title": m.get("title", "Untitled"),
                "started": m.get("started"),
                "duration_seconds": m.get("duration_seconds", 0),
                "url": m.get("url"),
                "parties": m.get("parties", []),
                "sentences": sentences,
                "customer_facing": any(_is_external((p or {}).get("email")) for p in m.get("parties", [])),
            })
    _eprint(f"Done. {len(out)} transcript(s) fetched.")
    return out


def find_user(name: str) -> list[dict[str, Any]]:
    """List Gong users matching the given name (case-insensitive substring)."""
    _eprint(f"Searching Gong users for '{name}'...")
    cursor = None
    matches: list[dict[str, Any]] = []
    needle = name.lower()
    while True:
        params = {"limit": 100}
        if cursor:
            params["cursor"] = cursor
        try:
            r = requests.get(f"{_base()}/v2/users", headers=_auth_headers(),
                             params=params, timeout=30)
            r.raise_for_status()
        except requests.exceptions.RequestException as e:
            sys.stderr.write(f"ERROR: find_user request failed: {e}\n")
            sys.exit(1)
        data = r.json()
        for u in data.get("users") or []:
            fn = (u.get("firstName") or "").lower()
            ln = (u.get("lastName") or "").lower()
            em = (u.get("emailAddress") or "").lower()
            full = f"{fn} {ln}".strip()
            if needle in fn or needle in ln or needle in em or needle in full:
                matches.append({
                    "id": u.get("id"),
                    "name": full.title(),
                    "email": u.get("emailAddress"),
                    "title": u.get("title"),
                    "active": u.get("active"),
                })
        records = data.get("records") or {}
        cursor = records.get("cursor")
        if not cursor:
            break
    _eprint(f"Found {len(matches)} match(es).")
    return matches


def ping() -> dict[str, Any]:
    """Health check — pull 1 user record to confirm credentials."""
    try:
        r = requests.get(f"{_base()}/v2/users", headers=_auth_headers(),
                         params={"limit": 1}, timeout=15)
    except requests.exceptions.RequestException as e:
        return {"ok": False, "error": f"could not reach Gong: {e}", "base_url": _base()}
    if r.status_code == 200:
        data = r.json()
        return {"ok": True, "totalRecords": (data.get("records") or {}).get("totalRecords"),
                "base_url": _base()}
    return {"ok": False, "status": r.status_code, "body": r.text[:300]}


# ─── CLI ──────────────────────────────────────────────────────────────────────

def _write_out(data: Any, out_path: str | None) -> None:
    text = json.dumps(data, indent=2, ensure_ascii=False)
    if out_path and out_path != "-":
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text(text, encoding="utf-8")
        _eprint(f"Wrote {out_path}")
    else:
        sys.stdout.write(text + "\n")


def main() -> None:
    p = argparse.ArgumentParser(description="Gong API client for the unified-communication skill.")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("ping", help="Confirm credentials work.")

    s = sub.add_parser("list_calls", help="List calls in a date window with parties.")
    s.add_argument("--from-date", required=True, help="ISO date or YYYY-MM-DD.")
    s.add_argument("--to-date", help="ISO date or YYYY-MM-DD. Defaults to now.")
    s.add_argument("--customer-facing", action="store_true",
                   help="Keep only calls with >=1 external party (outside GONG_INTERNAL_DOMAINS).")
    s.add_argument("--min-duration", type=int, default=0, help="Minutes (default 0).")
    s.add_argument("--primary-user-id", action="append",
                   help="Filter to calls owned by this Gong user ID. Repeatable.")
    s.add_argument("--title-match",
                   help='Case-insensitive regex on call title. Examples: '
                        '"discovery|demo", "poc|pov", "renewal|renew", '
                        '"kickoff|onboarding".')
    s.add_argument("--party-domain",
                   help='Substring to match against party email domains '
                        '(e.g., "acme.com", "northwind.co"). Useful for account scoping '
                        'when HubSpot isn\'t available.')
    s.add_argument("--out", help="Write JSON here. Default stdout.")

    s = sub.add_parser("search_content",
                       help="Find calls where a phrase appears in Gong's AI summaries "
                            "(brief, key points, outline, highlights, trackers, topics). "
                            "Add --deep-search to also grep transcripts.")
    s.add_argument("--from-date", required=True, help="ISO date or YYYY-MM-DD.")
    s.add_argument("--to-date", help="ISO date or YYYY-MM-DD. Defaults to now.")
    s.add_argument("--query", required=True,
                   help='Phrase or regex to find. Case-insensitive. Examples: '
                        '"virtual usb", "in-app purchase", "gridrunner|cloudtestly", '
                        '"pricing pushback".')
    s.add_argument("--customer-facing", action="store_true")
    s.add_argument("--min-duration", type=int, default=0)
    s.add_argument("--primary-user-id", action="append")
    s.add_argument("--deep-search", action="store_true",
                   help="Also fetch transcripts and grep sentence text for the query. "
                        "Catches phrases that Gong's AI summaries missed. Slower.")
    s.add_argument("--party-domain",
                   help='Substring to match against party email domains '
                        '(e.g., "acme.com"). Useful for account scoping '
                        'when HubSpot isn\'t available.')
    s.add_argument("--out", help="Write JSON here. Default stdout.")

    s = sub.add_parser("fetch_transcripts", help="Fetch transcripts for call IDs.")
    s.add_argument("--call-ids", required=True,
                   help="Comma-separated call IDs, OR @file.json containing a list.")
    s.add_argument("--out", help="Write merged transcripts JSON here. Default stdout.")

    s = sub.add_parser("find_user", help="Resolve a Gong user name → ID.")
    s.add_argument("--name", required=True)
    s.add_argument("--out", help="Write JSON here. Default stdout.")

    args = p.parse_args()

    if args.cmd == "ping":
        _write_out(ping(), None)
        return

    if args.cmd == "list_calls":
        result = list_calls(
            from_date=args.from_date,
            to_date=args.to_date,
            customer_facing=args.customer_facing,
            min_duration_minutes=args.min_duration,
            primary_user_ids=args.primary_user_id,
            title_match=args.title_match,
            party_domain=args.party_domain,
        )
        _write_out({"calls": result, "count": len(result)}, args.out)
        return

    if args.cmd == "search_content":
        result = search_content(
            from_date=args.from_date,
            to_date=args.to_date,
            query=args.query,
            customer_facing=args.customer_facing,
            min_duration_minutes=args.min_duration,
            primary_user_ids=args.primary_user_id,
            deep_search=args.deep_search,
            party_domain=args.party_domain,
        )
        _write_out({"calls": result, "count": len(result), "query": args.query}, args.out)
        return

    if args.cmd == "fetch_transcripts":
        raw = args.call_ids
        if raw.startswith("@"):
            data = json.loads(Path(raw[1:]).read_text())
            ids = data if isinstance(data, list) else data.get("call_ids") or data.get("ids") or []
        else:
            ids = [x.strip() for x in raw.split(",") if x.strip()]
        result = fetch_transcripts(ids)
        _write_out({"transcripts": result, "count": len(result)}, args.out)
        return

    if args.cmd == "find_user":
        result = find_user(args.name)
        _write_out({"users": result, "count": len(result)}, args.out)
        return


if __name__ == "__main__":
    main()
