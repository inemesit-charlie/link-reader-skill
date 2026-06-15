# link-reader

A Claude skill that automatically fetches and reads any URL shared in conversation — including JavaScript-rendered pages (React, Next.js, Lovable, Vercel apps) that standard web fetch tools cannot read.

## What it does

- Auto-fetches any URL the moment it appears in conversation, no prompting needed
- Uses a two-layer fetch strategy: static HTML fetch first, headless Chromium browser (Playwright) as fallback for SPAs and client-side rendered pages
- Reads the full visible page content the way a real browser user would
- Returns a structured summary by default, or targets a specific section on request
- Has special handling for portfolio and case study pages

## How it works

**Layer 1 — Static fetch:** Fast, works for server-rendered pages (Behance, articles, docs, blogs).

**Layer 2 — Headless browser:** Launches a Chromium instance via Playwright, waits for JavaScript to execute and the page to fully render, then extracts all visible text. Used automatically when Layer 1 returns incomplete content or the URL is a known SPA domain (`.lovable.app`, `.vercel.app`, `.netlify.app`, `.webflow.io`, etc.).

## Installation

1. Download `link-reader-v2.skill`
2. Go to Claude.ai → Settings → Skills
3. Upload the `.skill` file
4. The skill is active immediately in all new conversations

## Dependencies

The headless browser layer requires Playwright and Chromium. These are installed automatically when the skill runs in a Claude environment with bash access:

```bash
pip install playwright --break-system-packages -q
python -m playwright install chromium
```

## Trigger phrases

The skill activates automatically when any URL appears in the conversation. No explicit command needed. You can also say:
- "Open this link and tell me what you see"
- "Look at this page and give me feedback"
- "Check this section on [URL]"

## Output format

**Default (no specific instruction):**
- What it is (one sentence)
- Key content (3–5 bullets)
- Notable details relevant to your work context

**Targeted lookup:**
Re-fetches the page and isolates only the section or element you asked about.

## Built by

The Inch Branding & Design Services  
Built as part of a personal AI workflow system for brand and research work.
