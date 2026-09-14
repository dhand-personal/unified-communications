# Unified Communication

A [Claude Skill](https://docs.claude.com) that consolidates a person's sales and business communications, email, call and meeting transcripts, CRM activity, and pasted notes, into one queryable history by account, person, or topic, instead of checking five tools separately.

Ask it things like:

- "What's the history on the Acme account?"
- "Has pricing come up with Jane Doe in the last quarter?"
- "Pull the discovery calls for the Northwind deal."

It pulls from whatever you actually have connected, Gmail, Gong, HubSpot, Salesforce, Zoom, OneNote, Nooks, or anything else you name, and is explicit about which sources it actually queried versus which ones aren't set up yet. It also hands the same history to other Claude Skills that need account or contact context, without you having to ask for it directly.

## Why this exists

Two rules drive everything else in this skill:

1. **Prefer full transcripts over summaries wherever the source allows it.** An AI-generated summary is someone else's compression of what was said, and it can miss the detail you actually need.
2. **Never claim a source is active when it isn't.** This skill is meant to be shared, and whoever runs it may have a completely different set of tools connected than you do. It only reports what's actually confirmed live in that session, not what's merely possible.

One connector, Gong, is a deliberate exception worth knowing up front: Gong's MCP connector can only return AI-generated summaries, never a raw transcript, no matter which of its tools you call. If you want the actual words said on a call, this skill can pull real transcripts through Gong's direct API instead, but that's a separate setup path with its own credentials. The skill asks which one you want rather than assuming.

## Setup

The first time you use it, the skill runs a short interview: it asks which tools you actually use for work communication, checks what's genuinely connected in your session, and records the result. Nothing more happens automatically after that; you can always say "add Zoom" or "what's connected right now" later without repeating the whole interview.

If you choose a source that needs its own API key (Gong's API path is the main example here), the skill walks you through setting the credential yourself as an environment variable on your own machine, for both Mac/Linux and Windows. It never asks you to paste a raw API key, secret, or token into the chat, and it never types one into a command on your behalf.

## What's inside

```
SKILL.md                              the skill's instructions
references/
  catalog.md                          every supported source: what it gives you, MCP vs API, setup notes
  schema.md                           the common record format every source's results get normalized into
  gong_modes.md                       Gong API mode routing (account/deal/bulk/owner/content-search)
  gong_api_patterns.md                Gong + HubSpot API endpoint, auth, and pagination details
  gong_content_search.md              Gong content-search mode internals
scripts/
  manage_config.py                    reads/writes the per-user connector config
  gong_client.py                      Gong API client (list calls, search content, fetch transcripts, resolve users)
  extract_gong_ids.py                 pulls Gong call IDs out of HubSpot meeting records
  format_transcript.py                writes fetched transcripts to readable files
```

## Known limitations, and where I'd appreciate feedback

I built and stress-tested this skill's logic through a wide range of simulated setups, mocking API responses and running the actual scripts against synthetic data to check the mode-routing, config, and error-handling logic. What I have **not** done yet is run it against my own live Salesforce, Zoom, OneNote, or Nooks connections, so I can't personally vouch for how it behaves against those real accounts.

Specific things worth testing if you try this against your own tools:

- Account and deal resolution when your CRM is Salesforce instead of HubSpot (the skill falls back to Gong's own account-domain filter, but I haven't confirmed this against a live Salesforce org).
- Gong's MCP tools (`ask_account`, `ask_deal`, `generate_brief`) against a real Gong MCP connection, since the behavior described in `catalog.md` comes from Gong's own published docs, not a live call I made myself.
- Any CRM auto-logging setup (Einstein Activity Capture, HubSpot's sales email tracking) where the same email or call might get counted twice.

If you run this against a live setup and something breaks or reads wrong, I'd genuinely appreciate an issue or a note, either works.

## License

MIT. See [LICENSE](LICENSE).
