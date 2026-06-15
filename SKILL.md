---
name: link-reader
description: Auto-fetch and read any URL shared in the conversation. Trigger this skill immediately and automatically whenever the user shares any link or URL — including portfolio links, Behance pages, websites, articles, docs, product pages, landing pages, or any other web address. Do not wait for the user to ask you to read it. Fetch it, read it fully, and provide a brief summary. If the user asks about a specific section or element on the page, fetch the link again and locate that section independently. Always use this skill when a URL appears in the user's message.
---

# Link Reader Skill

## Trigger Condition
Any URL or link appearing in the user's message — auto-fetch immediately without being asked.

---

## Fetch Strategy: Two-Layer Approach

Always attempt both methods. Never stop at one.

### Layer 1: Static Fetch (web_fetch)
- Use `web_fetch` with `html_extraction_method: "markdown"` first
- This works for server-rendered pages (Behance, articles, docs, most blogs)
- If full content is returned, proceed directly to output

### Layer 2: Headless Browser (Playwright)
Trigger this when:
- `web_fetch` returns a blank shell, navigation only, or login wall
- The URL is a known SPA/React/Vue/Next.js app (e.g. `.lovable.app`, `vercel.app`, or any app with client-side routing)
- The page content is clearly incomplete or missing the main body

**How to run the headless browser:**

```bash
pip install playwright --break-system-packages -q
python -m playwright install chromium --quiet
python3 /home/claude/link-reader-v2/scripts/fetch_page.py "<URL>"
```

Or inline:

```python
from playwright.sync_api import sync_playwright

def fetch_rendered(url):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page.goto(url, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(2000)
        content = page.inner_text("body")
        browser.close()
        return content

print(fetch_rendered("<URL>"))
```

Run this via `bash_tool`. Extract the stdout as the page content.

---

## Behavior Rules

### 1. Auto-Fetch on Link Detection
- As soon as a URL appears in the conversation, fetch it immediately
- Do not ask the user what they want first
- If multiple links are shared, fetch all of them
- Always try Layer 1 first, fall back to Layer 2 if content is incomplete

### 2. Full Page Read
- Read the entire page content
- If content is very long, prioritize main body over nav/footer boilerplate
- If truncated, note it and offer to dig deeper

### 3. Default Output (no specific instruction given)
Return a brief summary structured as:
- **What it is** (one sentence)
- **Key content** (3-5 bullet points of what's on the page)
- **Notable details** (anything relevant to Inemesit's work context — brand, design, clients, tech stack, etc.)

### 4. Targeted Lookup (user asks about a specific section)
- Re-fetch the link independently using the appropriate layer
- Locate the specific section, element, or detail referenced
- Report only what's relevant — no need to re-summarize the whole page

### 5. Portfolio / Case Study Pages
When the link is a portfolio, Behance, or case study page:
- Extract: project name, client, brief, problem, research, strategy, design decisions, outcome
- Flag what's strong and what's weak for MDes applications or client pitches
- Note anything relevant to The Inch positioning

### 6. If Both Layers Fail
- Report clearly what was and was not accessible
- Never guess or hallucinate page content
- Ask the user to confirm the page is publicly accessible

---

## SPA Detection Signals
Treat a URL as likely needing Layer 2 (headless browser) if:
- Domain includes: `.lovable.app`, `.vercel.app`, `.netlify.app`, `.webflow.io`
- URL has client-side routes like `/work/`, `/project/`, `/case-study/`
- Layer 1 returns only nav links and no body content
- Page title loads but body is empty

---

## Tone of Output
Match Inemesit's preferred style: direct, no fluff, no filler. Lead with the most useful finding.
