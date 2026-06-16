# YouTube Transcriber MCP — The Inch

A fully automated YouTube transcription MCP server. Drop any YouTube link in Claude and get a full verbatim transcript + section-by-section summary with zero manual steps.

## Architecture

```
Claude Chat → MCP Tool Call → Railway Server → yt-dlp download → Whisper/AssemblyAI → Transcript → Claude Summary
```

Hybrid engine: OpenAI Whisper (primary) auto-switches to AssemblyAI on quota exhaustion.

## Deploy to Railway (5 minutes)

### Step 1 — Push to GitHub
```bash
git init
git add .
git commit -m "yt-transcriber-mcp init"
gh repo create yt-transcriber-mcp --private --push --source=.
```

### Step 2 — Deploy on Railway
1. Go to railway.app → New Project → Deploy from GitHub
2. Select your `yt-transcriber-mcp` repo
3. Railway auto-detects and deploys

### Step 3 — Add Environment Variables
In Railway dashboard → your service → Variables, add:
```
OPENAI_API_KEY     = sk-your-key
ASSEMBLYAI_API_KEY = your-key
```

### Step 4 — Get Your MCP URL
Railway gives you a public URL like:
`https://yt-transcriber-mcp-production.up.railway.app`

Your MCP endpoint is:
`https://yt-transcriber-mcp-production.up.railway.app/mcp`

### Step 5 — Connect to Claude
In claude.ai → Settings → Integrations → Add MCP Server
Paste your Railway MCP URL.

Done. Every YouTube link you drop in Claude is now handled automatically.

## MCP Tools

| Tool | Description |
|------|-------------|
| `transcribe_video` | Download + transcribe any video URL |
| `get_video_info` | Fetch title, channel, thumbnail |
| `health_check` | Check engine availability |

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | One of these two | Whisper API key |
| `ASSEMBLYAI_API_KEY` | One of these two | AssemblyAI key |
| `PORT` | No (Railway sets it) | Server port |

## Supported Platforms
yt-dlp supports 1000+ sites. Works for YouTube, Vimeo, Loom, Twitter/X, and more.
