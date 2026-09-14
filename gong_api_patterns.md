# Gong + HubSpot API patterns

## Gong

**Base URL:** `https://api.gong.io` by default. Some tenants are region-pinned to a subdomain instead (e.g. `https://us-XXXXX.api.gong.io`) — the generic URL returns 403 from inside a region-pinned tenant, so if that happens, set `GONG_BASE_URL` to the tenant-specific region URL (ask your Gong admin for it).

**Auth:** HTTP Basic. `Authorization: Basic base64(GONG_ACCESS_KEY:GONG_SECRET)`.

### Key endpoints

`POST /v2/calls/extensive`
Lists or looks up calls. Filter by `fromDateTime`/`toDateTime`, `callIds`, or `primaryUserIds`. The `contentSelector.exposedFields` toggles what gets returned. For this skill we always want `parties: true` so we can build the speakerId→name map and apply the customer-facing filter.

Pagination is cursor-based: response carries `records.cursor`; pass it as `cursor` on the next request body. Page size defaults to 100. Stop when the response returns no cursor or no calls.

`POST /v2/calls/transcript`
Returns sentence-level transcripts for a list of call IDs. **Speakers come back as IDs only — no names.** You MUST also call `/v2/calls/extensive` for the same IDs (with parties) and merge. The skill's `gong_client.py fetch_transcripts` does this in one shot.

Batch limit: 20 IDs per request is safe. Larger batches sometimes timeout or partial-fail.

`GET /v2/users`
List Gong users. Used by owner mode to resolve a rep's name → primary user ID. Cursor-paginated like calls.

### Retries

429 / 502 / 503 / 504 → retry with linear backoff (2s, then 4s). Anything else → fail loud; almost always a credential or filter mistake worth surfacing.

## HubSpot

The HubSpot MCP exposes `search_crm_objects` and `get_crm_objects` directly to Claude — no custom Python needed. Three object types matter:

### `companies`

Account lookup. Prefer filtering by `domain` (e.g., `acme.com`, `northwind.co`) because free-text on `name` matches every record containing that fragment. Surface ambiguous results to the user (e.g., a parent company vs. its services subsidiary).

Key properties: `name`, `domain`, `website`, `hs_object_id`, `num_associated_contacts`, `num_associated_deals`, `hs_lastmodifieddate`.

### `deals`

Deal lookup or deal-scoped queries. Use `associatedWith: companies` to find deals on a company. Sort by `hs_lastmodifieddate` DESC to surface the live ones.

Key properties: `dealname`, `dealstage`, `pipeline`, `closedate`, `amount`, `deal_currency_code`, `hs_lastmodifieddate`. Note: HubSpot's `tool_guidance` requires `deal_currency_code` whenever `amount` is requested.

### `meetings` ← the important one

This is where Gong-synced calls land in HubSpot. NOT the `calls` object (which is nearly empty on this tenant). To find Gong calls for an account:

```
search_crm_objects:
  objectType: meetings
  filterGroups: [{
    filters: [
      {propertyName: hs_meeting_start_time, operator: GTE, value: <epoch_ms>},
      {propertyName: hs_meeting_start_time, operator: LTE, value: <epoch_ms>},
      {propertyName: hs_object_source_detail_1, operator: EQ, value: "Gong"},
      {propertyName: hs_meeting_outcome, operator: EQ, value: "COMPLETED"}
    ],
    associatedWith: [
      {objectType: companies, operator: EQUAL, objectIdValues: [<company_id>]}
    ]
  }]
  properties: [hs_meeting_title, hs_meeting_start_time, hs_meeting_end_time,
               hs_meeting_body, hs_meeting_outcome, hubspot_owner_id,
               hs_object_source_detail_1]
  sorts: [{propertyName: hs_meeting_start_time, direction: DESCENDING}]
```

Why each filter matters:
- `hs_object_source_detail_1 = "Gong"` — drops calendar invites and manually-logged meetings, keeps only Gong-synced records.
- `hs_meeting_outcome = "COMPLETED"` — drops cancellations and future occurrences of recurring meetings.
- Date upper bound — without it, future scheduled occurrences of recurring series flood the results.

**The Gong call ID is in `hs_meeting_body` as an HTML anchor:** `<a href="https://<tenant>.app.gong.io/call?id=NNN">`. Use the regex `gong\.io/call\?id=(\d+)`. The `extract_gong_ids.py` script does this.

Bonus: `hs_meeting_body` also contains Gong's AI-generated call brief (highlights, discussion points, next steps). Useful for summary-only mode without calling the Gong API at all.

## Date conversions

HubSpot's `hs_meeting_start_time` filters expect epoch milliseconds. Quick reference:
- `1776211200000` = 2026-04-15 00:00 UTC
- One day = 86400000 ms
- Compute N days back: `int(now.timestamp()*1000) - N*86400000`

Gong's `/v2/calls/extensive` takes ISO 8601: `2026-04-15T00:00:00Z`.

## Common failure modes

- **403 on api.gong.io** — the tenant is region-pinned; set `GONG_BASE_URL` to the tenant-specific region URL.
- **"Unknown" speakers** — only called `/v2/calls/transcript`, didn't merge parties from `/v2/calls/extensive`.
- **Zero meeting results** — queried `calls` object instead of `meetings`.
- **Hundreds of results for "Acme Corp calls last 30 days"** — missed the date upper bound, future recurring occurrences flooded in.
- **Wrong company match** — used name CONTAINS_TOKEN on a common word or fragment instead of filtering by domain.
