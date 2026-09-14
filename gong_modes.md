# Mode-by-mode notes and edge cases

## Account mode

**When:** user names a company ("Acme Corp", "Northwind", "Globex").

**Resolution priority:**
1. If a domain is mentioned ("northwind.co"), filter `companies` by `domain` EQ. Highest precision.
2. Otherwise filter `name` CONTAINS_TOKEN — but be ready for false positives. A search for "Acme" can turn up an unrelated "Acme Systems" and separate "Acme Corp Parent" vs "Acme Corp Services, Inc." records (related but distinct).
3. When more than one plausible match returns, **ask the user** which one. Don't pick by recency alone — the parent record may have more contacts but the subsidiary may be the active deal owner.

**No HubSpot?** This resolution path — and `scripts/extract_gong_ids.py`, which it depends on — is HubSpot-specific: it queries HubSpot's `companies` object and parses the Gong link out of HubSpot's `hs_meeting_body` field. If the person's CRM isn't HubSpot (Salesforce, something else, or no CRM at all), skip this resolution path entirely and use Bulk mode's `--party-domain` filter instead (see Bulk mode below) — it hits Gong directly with the account's email domain, no CRM involved, and gets the same account-scoped result without needing HubSpot to exist.

`--party-domain` needs an actual domain, and without HubSpot there's no CRM company record to pull one from — so get it in this order rather than guessing: (1) the person already said it ("northwind.co"); (2) it's visible in a live source already queried this turn — a contact's email address from Gmail, Salesforce, or pasted text that matches the account name; (3) if neither, ask the person for the company's email domain before running the pull. Don't substitute the company name for the domain (`--party-domain "Northwind"` won't match anything real).

**Default window:** 90 days, same as the rest of this skill (see `SKILL.md`'s "Answering a query" step 1) — don't apply a different default here just because this is the Gong-specific mode. If Gong's window and another source's window in the same synthesis don't match, the receipts will look inconsistent with no explanation why. Users routinely extend or narrow the window ("past 30 days", "this year"); accept any natural phrasing and normalize, and say what window was actually used either way.

**Edge cases:**
- Company has multiple legal entities in HubSpot (e.g., a parent + a services subsidiary). Offer to query both and dedupe.
- Account just created; no Gong meetings yet (will return zero). Tell the user explicitly — don't leave them wondering.
- Meeting series with recurring instances. The bidirectional Google Calendar sync sometimes creates a calendar-sourced duplicate of the Gong-sourced meeting at the same start time. The `hs_object_source_detail_1 = "Gong"` filter handles this.

## Deal mode

**When:** user names a deal or refers to one ("the POC", "the renewal", "Northwind's discovery deal").

Same flow as account mode but step-1 association is `deals` instead of `companies`. Helpful when an account has multiple parallel opportunities and the user only wants one.

If you can't disambiguate the deal from the user's phrasing, list the account's open deals (sorted by last modified) and ask which.

**No HubSpot?** A "deal" is a HubSpot object, so without HubSpot there's no formal deal record to resolve against — the same fallback as Account mode applies, but it can only approximate the deal, not isolate it precisely. Use Bulk mode's `--party-domain` filter for the account (get the domain the same way as Account mode's no-HubSpot note above — stated, already visible in a live source, or ask), combined with `--title-match` on how the person described the deal (e.g. `"renewal"`, `"poc|proof of concept"` — see Bulk mode's filter combos below). Tell the person plainly that this is an approximation based on call titles, not an exact deal match, since there's no CRM deal record backing it up.

## Bulk mode

**When:** the user wants volume — "all customer-facing calls last quarter", "every demo this month", "pull everything Eng can sift through."

HubSpot is not in the loop. Hit Gong directly:

```bash
python3 scripts/gong_client.py list_calls \
  --from-date YYYY-MM-DD \
  --customer-facing \
  --min-duration 5 \
  --out /tmp/bulk_calls.json
```

**Volume sanity check:** before fetching transcripts, look at the count. A 90-day customer-facing pull can easily run into the hundreds of calls depending on team size. Always confirm with the user before fetching that many transcripts.

**Output:** always bulk (folder + manifest + per-call .txt). Picker doesn't scale here.

**Useful filter combos (using --title-match, a first-class flag):**

- All discovery calls past quarter → `--title-match "discovery|disco"`
- All demos → `--title-match "demo|product demonstration"`
- All POVs/POCs → `--title-match "pov|poc|proof of (concept|value)"`
- Customer-facing renewals → `--title-match "renewal|renew" --customer-facing`
- All onboarding/kickoff calls (Support's go-to) → `--title-match "kickoff|onboarding|first session"`
- All QBRs → `--title-match "qbr|business review|monthly business"`

Combine with `--party-domain` for account-scoped queries without HubSpot:

```bash
# All Acme Corp discovery + POV calls past quarter, no HubSpot needed
python3 scripts/gong_client.py list_calls \
  --from-date 2026-02-15 \
  --party-domain "acme.com" \
  --title-match "discovery|pov|poc"
```

## Owner mode

**When:** user names a rep without an account — "Jordan's calls", "Sam's pipeline calls", "all of Taylor's discovery calls past quarter".

1. Resolve the rep:
   ```bash
   python3 scripts/gong_client.py find_user --name "Jordan Rivera"
   ```
   Returns a list of matches (a large Gong org can have hundreds of users, so name collisions are possible). Confirm with the user if multiple.

2. Run `list_calls --primary-user-id <id>` with the time window.

3. Picker if small, bulk if large.

**Caveats:**
- "Primary user" in Gong is the host. A rep who attended but didn't host won't be caught. If the user wants "every call Jordan was on" (vs. "every call Jordan hosted"), do bulk mode and post-filter on parties instead.
- Inactive Gong users still exist in `/v2/users` — note `active=false` in the resolved record.

## Content-search mode

Fully implemented — see `references/gong_content_search.md` for the design and implementation details, and `SKILL.md`'s "Answering a query" section (the Gong-via-`api` bullet) for how this fits into the overall query flow. The subcommand is `gong_client.py search_content`.

Account-scoped content search (e.g., "did pricing come up on Acme's calls") works the same with or without HubSpot: `search_content` takes the same `--party-domain` flag as `list_calls`, so the same no-HubSpot fallback and domain-resolution order described under Account mode above applies here too — see `references/gong_content_search.md`'s "No HubSpot?" note for the specifics.

## Ambiguity — when to ask

Always ask if you can't tell which mode the user means:

- "Pull Gong calls" with no qualifier → which account or what window?
- Single name mentioned that could be a company OR a rep ("Jordan") → which Jordan, or did you mean Jordan Rivera the rep?
- "Customer calls" without time → which window?

Never silently default to a broad bulk pull. Defaults are okay for time windows and audience filters; never for scope.
