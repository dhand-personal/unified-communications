# Source catalog

For each source: what it's for, the realistic way to connect to it, and — critically — whether the easy path gives you a full transcript or just a summary. Use this during the setup interview and whenever someone asks to add a connector.

**Default order: MCP first, API only if asked (or if the MCP structurally can't do it).** If an MCP connector for a source is already present and connected, use it — that's simpler and needs no separate credentials. Only reach for a direct API integration when there's no MCP for that source, the person specifically asks for API access, or (Gong being the one confirmed case of this below) the connected MCP is documented to never return what's actually needed, no matter which of its tools gets called. Some MCP servers bundle more than one tool (some full-content, some summary-only) — when that's the case, the note below says so, and the goal is to call the full-content tool when that's what's needed, not to treat "MCP" as automatically summary-only.

Only mark a source `"status": "live"` in the config if you've actually confirmed the access path works in this session: an MCP tool is present and connected, or a direct API integration has been set up and verified with a lightweight check call. For the API path, "set up" means the person configuring their own credentials as environment variables (or whatever mechanism that integration's setup calls for) on their own machine, following instructions you give them — never the person pasting a raw API key, secret, or token into the conversation for you to hold, type into a command, or write into a file on their behalf. Treat those exactly like a password: give steps, don't collect the value. Everything else stays `"planned"` until access is confirmed working this way, no matter how confident it seems.

## Email

**Gmail** — `access: "mcp"` when a Gmail MCP connector is present and connected in the session; that's the live path and it's usually already full message content, not a summary. If no connector is present, the fallback is `"planned"` with a note that it would need the person to connect a Gmail connector or provide API credentials.

**Microsoft 365 / Outlook** — `access: "api"` via Microsoft Graph, unless an O365/Outlook MCP connector is present, in which case treat it like Gmail. Without a connector, this needs an Azure app registration with mail read scope, which is a real setup lift — say so plainly rather than implying it's a quick add.

## Meetings and calls

**Gong** — now confirmed directly from Gong's own official MCP documentation, and it turns out the original caution about Gong was correct: **the Gong MCP server never returns raw transcripts, full stop, no matter which tool is called.** It exposes exactly three tools: `ask_account` (natural-language Q&A about one account), `ask_deal` (same, for one CRM deal), and `generate_brief` (a structured, multi-category summary — themes, stakeholders, risks, next steps — for an account, deal, or contact). Each analyzes calls and emails and returns a synthesized answer; each also has an `includeSources` parameter (default `false`) that, when true, returns *links* to the calls/emails used, not their content. Gong's own docs state it plainly: "Raw data such as call transcripts, message bodies, and activity lists is not returned." It's read-only, and private calls are excluded from everything.

This is the one real exception to "default to MCP" in this whole catalog: the Gong MCP doesn't just default to summaries, it is structurally incapable of returning a full transcript through any tool it offers. Because of that, Gong is the one source in this catalog where MCP-vs-API isn't a "default to MCP unless told otherwise" decision — **ask the person directly which they want**, since the two paths genuinely give different things:

- **MCP** — quick, no separate credentials, but every answer is Gong's AI synthesis (a brief, an account/deal Q&A answer, or a structured summary), never the actual words said on the call. Fine when the person wants "what happened" or "what's the state of this deal," not fine when they want to see or quote what was actually said.
- **Direct API** — the only way to get an actual verbatim transcript. Needs the person to get their own Gong API key and set it up (see below); more setup, but it's real call content, not a summary of one.

Ask something like: *"Gong's connector can only give you AI-generated summaries, never the actual transcript text — if you want real transcripts, that needs direct API access with its own setup instead. Which do you want: quick MCP-based Q&A, full transcripts via the API, or both?"* Then follow whichever path(s) they pick. Don't presume API just because it's "more thorough" — some people genuinely only want the summary path and shouldn't be walked through a credential setup they didn't ask for.

**If they choose MCP**: two independent setup choices apply. *Registration* is Automatic (marketplace/app-store connection, e.g. ChatGPT's or Copilot's directory, no admin-issued credentials) or Manual (a private integration — Gong issues a client ID/secret the admin installs in the connecting client; this is the path for "an enterprise Claude... console," since Claude isn't one of the preset marketplace connectors Gong lists — only Copilot and ChatGPT are). *Authorization context* is Personal access (each person's own Gong permissions) or Shared access (one org-wide token everyone sees the same data through). `access: "mcp"` once a connector is actually set up this way and connected.

**If they choose the API**: this skill ships everything needed to actually pull transcripts, not just a description of the endpoints — `scripts/gong_client.py` (list calls, search call content, fetch and merge transcripts, resolve a rep's user ID), `scripts/extract_gong_ids.py` (pull Gong call IDs out of HubSpot meeting records), and `scripts/format_transcript.py` (write pulled transcripts to readable files). `references/gong_api_patterns.md` has the underlying endpoint/auth/pagination details, `references/gong_modes.md` has the account/deal/bulk/owner/content-search routing logic for deciding *which* calls to pull based on how the person phrased the request, and `references/gong_content_search.md` has the content-search-mode internals. Read whichever of those the query actually needs — don't reread all three for every Gong query.

Getting the credential set up is the one part that needs care, because it's a real secret:
1. Tell them what to get: a Gong API key with `api:calls:read:basic`, `api:calls:read:extensive`, and `api:calls:read:transcript` scopes, from their Gong admin (Company Settings → API in Gong).
2. **Never ask them to paste the access key or secret into the chat, and never type a real secret value into a command yourself.** Give them the commands with a placeholder and have them fill in the real value themselves, in their own terminal — treat it exactly like a password.
3. Ask macOS/Linux or Windows and give the matching instructions:

   **macOS / Linux** — current session:
   ```bash
   export GONG_ACCESS_KEY="paste-your-access-key-here"
   export GONG_SECRET="paste-your-secret-here"
   ```
   Persistent: add those two lines to `~/.zshrc` (modern macOS) or `~/.bashrc`/`~/.bash_profile` (Linux/older macOS), then `source` it or open a new terminal.

   **Windows** — PowerShell, current session:
   ```powershell
   $env:GONG_ACCESS_KEY = "paste-your-access-key-here"
   $env:GONG_SECRET = "paste-your-secret-here"
   ```
   Persistent (that Windows user account):
   ```powershell
   setx GONG_ACCESS_KEY "paste-your-access-key-here"
   setx GONG_SECRET "paste-your-secret-here"
   ```
   `setx` only takes effect in *new* terminal windows — close and reopen before retrying. Same thing without the command line via Settings → System → About → Advanced system settings → Environment Variables.

4. Verify with `python3 scripts/gong_client.py ping` — returns `{"ok": true, ...}` or a clear error, never the credential value itself.
5. `GONG_BASE_URL` (only if their Gong tenant is region-pinned and calls 403 against the default) and `GONG_INTERNAL_DOMAINS` (comma-separated own-company domains, for the `--customer-facing` filter) aren't secrets — just tell them the values to set.

`access: "api"` once `ping` confirms it's actually working; `status: "planned"` with a note on which step is left until then.

**Zoom** — has an official MCP server, confirmed via Zoom's own developer docs and independent write-ups. Setup is an OAuth app registration in the Zoom App Marketplace (Client ID/Secret, defined OAuth scopes, the AI client's redirect URL registered back in Zoom). Once connected it exposes meeting summaries, full transcripts, recordings, notes and action items, plus Zoom Chat and calendar/scheduling — transcripts are a real, separate capability here, not summary-only. `access: "mcp"` once a connector is actually set up and connected; `status: "planned"` with a note on the OAuth app registration step until then.

**WebEx** — Cisco ships three separate official MCP servers: Meetings (8 tools), Messaging (24 tools), and Vidcast (video platform, 29 tools). For call/meeting history, the Meetings server is the relevant one: `webex-list-transcripts` returns full plain-text transcripts, while `webex-get-meeting-summary` returns only the AI-generated summary and action items — so within this one MCP server, which tool gets called still matters, same as the general note above. Auth is OAuth 2.0 Bearer tokens from `https://webexapis.com`, needing scopes including `meeting:transcripts_read` and `meeting:recordings_read` granted at setup. `access: "mcp"` once connected with the transcripts scope actually granted; otherwise `"planned"`.

**Otter.ai** — has an official MCP server (`https://mcp.otter.ai/mcp`) with three tools: get user info, search (overview-level results only), and fetch (full verbatim transcript). OAuth-based, and there's currently no public API key offered at all — which makes MCP not just the default here but the *only* realistic path in. `access: "mcp"` once connected through whichever client's own connector flow (Claude, ChatGPT web, Cursor, and Perplexity all have documented setups; Google Gemini isn't supported for this).

**Fathom** — confirmed directly from Claude's own connector directory listing: 7 tools are `find_person`, `get_identity`, `get_meeting_summary`, `get_meeting_transcript`, `list_meetings`, `list_teams`, and `search_meetings`. `get_meeting_transcript` is the one to use for full content; `get_meeting_summary` and `list_meetings`/`search_meetings` are summary/metadata-level. Sign-in is required (per-person OAuth, same as any Claude connector), and in a Team/Enterprise org an organization owner has to add it before individual members can connect — access is scoped to meetings the connected account recorded or had shared with it. Connector URL `https://api.fathom.ai/mcp`. `access: "mcp"` once actually connected in the session.

**Nooks** — confirmed via Nooks' own support article. The MCP connector exposes 37 tools total, covering sequencing/prospecting, CRM data, synced email activity, and — the relevant part here — calls and coaching. `getCallTranscript` returns the full transcript as speaker-labeled, timestamped turns, plus call metadata (rep, contact, duration, disposition). OAuth 2.0 with PKCE, set up through Claude's connector directory (org owner enables it, then each person connects and grants scopes). One real limitation worth flagging in results, not just in setup: transcript tools only cover calls made by reps who hold an **AI Coaching seat** — a call from a rep without that seat won't show up here regardless of who's asking, so "nothing found" doesn't necessarily mean the call didn't happen.

**Microsoft Teams (via Microsoft Graph)** — this is not the Teams "MCP server" Microsoft documents elsewhere (that one's an outbound bot framework — `notify`, `ask`, `request_approval` — with no read access to meetings or chat at all, worth ruling out explicitly since it's easy to grab the wrong doc). The actual path to Teams meeting transcripts is the Graph API: `GET /users/{id}/onlineMeetings/{meeting-id}/transcripts`, needing the `OnlineMeetingTranscript.Read.All` permission (delegated or application; application access additionally needs a tenant admin to set up an access policy). That call itself returns metadata only, including a `transcriptContentUrl` — a second call to that URL is what actually returns the transcript text, so plan for two calls, not one. This only works for non-expired meetings tied to a calendar event (not ad hoc meetings or live events), and a tenant admin can disable it entirely (shows up as a 403). `access: "api"` (the same Graph app registration as O365/OneNote can cover this too — no need for a separate one), `status: "planned"` until that registration and permission grant actually exist.

## Notes

**Evernote** — Evernote is building an official MCP server for Claude, confirmed from Evernote's own page on it, but as of this writing it's explicitly "currently in development" with sign-up via a waitlist — there's no live connector to actually set up yet, regardless of setup effort. Once it ships, it's described as read (search and retrieve real note content, not summaries) plus create (Claude can write summaries/drafts back into Evernote), with no ability to edit or delete existing notes. `status: "planned"` for a different reason than most other "planned" entries here: this isn't a credentials/OAuth gap, it's that the product itself hasn't launched. Worth checking back on rather than assuming it's still the old closed-API situation — that changed. Until then, the manual/paste path is the practical way to bring Evernote content in.

**OneNote** — confirmed via Microsoft's own guidance (a Microsoft moderator response on Microsoft Q&A): there is no official Microsoft-built OneNote MCP server, no announced roadmap or preview for one, and Microsoft's explicit recommendation is to use the Microsoft Graph OneNote REST API directly — `GET /me/onenote/{notebooks|sections|sectionGroups|pages}` (or `/users/{id}/onenote/...` for another user), with delegated-only auth (app-only access has been retired) and least-privilege scopes: `Notes.Read`, `Notes.Read.All`, `Notes.ReadWrite`, or `Notes.Create` depending on what's needed. Same Azure app registration as Microsoft 365/Teams above can cover this too. Community-built OneNote MCP servers do exist, but they're unofficial wrappers around this same Graph API, not a simpler path, and Microsoft's guidance treats them as custom integrations needing their own security review, not a supported shortcut. `access: "api"`, `status: "planned"` until that registration and scope grant exist.

## CRM

CRM tools are a different animal from the rest of this catalog: they're not just another place communication happens, they often *re-store* communication that already lives somewhere else (a synced email, a logged call). See "Watch for duplicates" below before treating a CRM as just one more source to add to the pile.

**Salesforce** — has official hosted MCP servers, confirmed via Salesforce's own developer docs. Auth is per-user OAuth, and Salesforce's standard security model (field-level security, object permissions, sharing rules) applies to every tool call — so a live connection can still come back empty on something the connected user doesn't have permission to see, which isn't the same as the data not existing. For read-only use, the **SObject Reads** server is the relevant one (there's also SObject All/Mutations/Deletes and some product-specific servers like Data 360, not needed here). Activities, Tasks, EmailMessage, and Event are all standard Salesforce objects, so querying across them for account/contact history should work through this server, but the exact tool name/shape wasn't confirmed from the overview page alone — check the SObject Reads server's own reference page before relying on a specific tool call. `access: "mcp"` once connected; `status: "planned"` with a note on which server (SObject Reads) to request until then.

**HubSpot** — has an official remote MCP server, well documented. OAuth 2.0 with PKCE (mandatory). Read access covers **Activities** (calls, emails, meetings, notes, tasks logged on a record) and **Conversations** (live chat, team email, WhatsApp, SMS, Facebook Messenger, and other channels connected to the conversations inbox) — this is broad enough to overlap with several other sources in this catalog, not just email. One real limitation to flag directly in results, not just at setup: if the account has **Sensitive Data protection** enabled, activity and conversation data are blocked from the MCP server entirely — an empty result under that setting means "blocked," not "nothing there." `access: "mcp"` once connected.

**Another CRM** — treat like any source not in the catalog (see "Adding a new source not listed here" below): ask what it is, check for an MCP connector or documented API, and note what's confirmed once it's actually been checked.

### Watch for duplicates

The reason CRM tools get their own warning: a call or email often lives natively in one place (Gmail, Gong, Zoom) *and* gets logged into the CRM as an activity, whether through an explicit sync (Einstein Activity Capture, a Gmail/Outlook integration, HubSpot's sales email tracking) or a person manually logging it. If both the native source and the CRM are live at the same time, the same event can surface twice.

During setup, when someone enables a CRM alongside sources it might sync with, ask directly: "does [Salesforce/HubSpot] automatically log your emails or calls — through something like Einstein Activity Capture, a Gmail/Outlook connection, or a dialer/call-logging integration? Which sources feed into it?" Record the answer against the CRM's config entry so later queries know which pairs of sources to check against each other, rather than trying to fuzzy-match every record against every other one.

When answering a query, for any two live sources flagged this way, check for likely duplicates before presenting results: same type (email/call/etc.), overlapping participants, and timestamps within a short window (about 15 minutes is reasonable). When two records clearly look like the same event, fold them into one and keep whichever has the richer `content_type` (full text over summary — a CRM-logged copy is often a synced-in summary of something that has the full version natively elsewhere). Say so plainly in the answer ("folded a duplicate of this call from Salesforce into the Gong version, which had the full transcript") rather than silently dropping one or silently presenting both as if they were separate events. When two records are similar but not clearly the same event, don't force the merge — show both and flag the possible overlap rather than guessing.

## Everything else

**Texts / SMS** — no general API path; this is a paste-in source in practice (export or copy the relevant exchange). `access: "manual"`, and it can be marked `"live"` immediately since it needs no setup.

**Pasted / copied text** — always available, always `"live"`, `access: "manual"`. This is the universal fallback for anything without a clean integration (texts, Evernote notes, a WebEx transcript someone downloaded, etc.). See `references/schema.md` for how to tag pasted content so it's usable in a query later, not just a wall of text in the transcript.

## Adding a new source not listed here

If someone asks about a tool that isn't in this catalog, don't refuse — apply the same questions used above: is there an MCP connector already connected? If not, does the tool have a documented API, and does it distinguish between a summary/highlights endpoint and a full-content endpoint? Note the answer in the config under `"notes"` so the next query (or the next person using this skill) doesn't have to re-derive it. This comes up more than the original ten might suggest — AI meeting recorders, dialers, and coaching platforms are a crowded, fast-changing category (Fathom and Nooks are two examples already added here, but there are plenty of others), so expect people to name tools that aren't listed above, and treat that as normal rather than an edge case.

Once someone has actually confirmed the details for a new source (what its API/MCP offers, whether it separates transcript from summary, what auth it needs), add a short entry to this file in the same style as the others above, so it becomes part of the catalog rather than a one-off note buried in someone's config.
