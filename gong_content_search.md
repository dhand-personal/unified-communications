# Content-search mode — implementation notes

Finds calls where a phrase appears in Gong's content metadata or, optionally,
in raw transcript sentences. Implemented as `gong_client.py search_content`.

## Two search layers

**Default — content metadata search (fast):**

For every call in the date window, Gong's `/v2/calls/extensive` endpoint
returns:

- `brief` — Gong's AI-generated 2-3 sentence call summary
- `keyPoints` — bullet-form summary of the 8-10 most important moments
- `outline` — section-by-section narrative with per-section text and timestamps
- `highlights` — categorized highlights (e.g., "Next steps") with text + timestamps
- `trackers` — pre-configured Gong keyword trackers, with hit counts (KEYWORD type)
- `topics` — auto-detected discussion topics with durations

The script regex-matches the user's query against each of these and returns
matched calls with a `match_reasons` array indicating where the hit came from.
Everything comes back in one API call (with pagination); no transcript fetching.

**Optional — deep search (slower, exhaustive):**

When `--deep-search` is set, the script also pulls transcripts for every
call in the window that DIDN'T match on metadata, and greps the sentence text
for the query. Catches phrases that didn't make it into the AI summary.

Reasonable mental model: metadata search catches what Gong noticed; deep
search catches what Gong missed.

## What goes into `match_reasons`

Each matched call returns an array of reasons. Each entry has:

- `source` — one of `brief`, `keyPoint`, `outline:<section>`, `highlight:<title>`,
  `tracker:<name>`, `topic:<name>`, or `transcript` (deep search only)
- `snippet` — the matched text or context summary
- Additional fields per source type:
  - `outline:*` adds `start_seconds` so you can deep-link to the moment
  - `highlight:*` carries the same text but tagged with the highlight category
  - `tracker:*` adds `hit_count` (how many times Gong's tracker fired)
  - `topic:*` adds `duration_seconds` (how long the conversation stayed on topic)
  - `transcript` adds `start_ms` and `speaker`

The `match_count` field on each call rolls up the total reason count. Calls
with many matches are likely more on-topic than calls with one fleeting mention.

## How tracker matching works

Gong trackers are configured per Gong instance — every org sets up its own (sales-methodology trackers like MEDDPICC stages, sentiment trackers, per-competitor trackers, integration mentions, whatever that org cares about). This skill doesn't ship a tracker list because there isn't a universal one to ship; find out what's actually configured by running a broad `search_content` query first, or by asking the user, rather than assuming any specific tracker exists.

Tracker names get matched the same way as any other field. To make that concrete with made-up examples: if an org had trackers named `Competitor: Acme Rival` and `Competitor: Other Rival`, searching "competitor" would match both tracker names generically, while searching "acme rival" would match only the specific one. Tracker matches require `count > 0` on the call so we don't return every call just because the tracker is defined but never actually fired.

## Cost considerations

| Mode | Calls per request | Transcript fetches |
|------|-------------------|---------------------|
| Default content search | All in window (cursor-paginated, ~100 per page) | 0 |
| `--deep-search` | All in window, plus 1 transcript per non-matching candidate | Up to ~200 for a 90-day customer-facing window |

Always confirm with the user before running deep search on a wide window. The
diagnostic line at the end of the run shows the count of additional transcripts
pulled.

## When the metadata-search misses things

Cases worth knowing about:

- **Acronyms and product-internal jargon** that don't appear in Gong's AI
  brief because the AI doesn't recognize them as important. (E.g., "UDID",
  "MFA", "HAR file".)
- **Phrases spoken once briefly** that don't make it into key points.
- **Technical specifications** like version numbers or model names.

For all of these, deep search is the right tool. It's slower but exhaustive.

## Composing with other filters

`search_content` accepts the same `--customer-facing`, `--min-duration`,
`--primary-user-id`, and `--party-domain` flags as `list_calls`. You can stack:

```bash
# Customer-facing calls > 10min where someone mentioned pricing pushback
# in the past quarter, on Jordan's deals
python3 scripts/gong_client.py search_content \
  --from-date 2026-02-15 \
  --query "pricing.*(too high|concern|expensive|push.?back|budget)" \
  --customer-facing \
  --min-duration 10 \
  --primary-user-id 5265254121265435286
```

```bash
# Same kind of search, but scoped to one account instead of one rep —
# useful when there's no HubSpot to resolve "Acme Corp" to a company record
python3 scripts/gong_client.py search_content \
  --from-date 2026-02-15 \
  --query "pricing.*(too high|concern|expensive|push.?back|budget)" \
  --party-domain "acme.com" \
  --customer-facing
```

The query is a full regex (escape literal punctuation with `\`), so you can
build precise multi-phrase expressions.

**No HubSpot?** Same situation as Account/Deal mode (see `gong_modes.md`): `--party-domain`
needs an actual domain, and without HubSpot there's no CRM record to pull one from. Get it in
the same order — stated by the person, already visible in a live source queried this turn, or
ask — rather than guessing or substituting the company name for a domain.

## Worked example

Searching for "virtual usb" over the past 30 days returned 13 hits across
multiple deals — Northwind discovery, Globex touch point, Initech MBR
(asking for the Virtual USB 2.0 ETA), Fabrikam discovery, Contoso
performance testing. Each came back with at least one snippet from
`keyPoint` or `outline:<section>` showing the surrounding context. Total
runtime: under 10 seconds, no transcripts fetched.
