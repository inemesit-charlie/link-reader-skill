"""
YouTube Transcriber MCP Server — The Inch
Hybrid architecture: OpenAI Whisper (primary) + AssemblyAI (fallback)
Deployed on Railway. Keys stored as environment variables — never exposed.
"""

import os
import re
import json
import time
import tempfile
import subprocess
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional
from contextlib import asynccontextmanager

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field, ConfigDict

# ─────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────

OPENAI_KEY     = os.environ.get("OPENAI_API_KEY", "")
ASSEMBLYAI_KEY = os.environ.get("ASSEMBLYAI_API_KEY", "")
WHISPER_MODEL  = "whisper-1"
MAX_MB         = 24
CHUNK_SECS     = 1200  # 20 min chunks for large files

QUOTA_ERRORS   = ["insufficient_quota", "rate_limit_exceeded",
                  "billing_hard_limit", "exceeded your current quota"]

# ─────────────────────────────────────────────
# MCP SERVER
# ─────────────────────────────────────────────

mcp = FastMCP("yt_transcriber_mcp")

# ─────────────────────────────────────────────
# INPUT MODELS
# ─────────────────────────────────────────────

class TranscribeInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    url: str = Field(..., description="YouTube or other video URL to transcribe", min_length=10)

class MetadataInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    url: str = Field(..., description="YouTube video URL", min_length=10)

# ─────────────────────────────────────────────
# UTILITIES
# ─────────────────────────────────────────────

def extract_video_id(url: str) -> Optional[str]:
    patterns = [
        r'youtu\.be/([^?&\s]+)',
        r'youtube\.com/watch\?v=([^&\s]+)',
        r'youtube\.com/shorts/([^?&\s]+)',
        r'youtube\.com/embed/([^?&\s]+)',
    ]
    for p in patterns:
        m = re.search(p, url)
        if m:
            return m.group(1)
    return None

def format_ts(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"

def file_mb(path: str) -> float:
    return os.path.getsize(path) / (1024 * 1024)

def is_quota_error(error_body: str, status_code: int) -> bool:
    body_lower = error_body.lower()
    return (status_code in [402, 429] or
            any(e in body_lower for e in QUOTA_ERRORS))

# ─────────────────────────────────────────────
# AUDIO DOWNLOAD
# ─────────────────────────────────────────────

def download_audio(url: str, output_path: str) -> None:
    cmd = [
        "yt-dlp",
        "--extract-audio",
        "--audio-format", "mp3",
        "--audio-quality", "5",
        "--no-playlist",
        "--no-check-certificate",
        "-o", output_path,
        url
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp failed: {result.stderr[:400]}")

# ─────────────────────────────────────────────
# OPENAI WHISPER
# ─────────────────────────────────────────────

def whisper_single(audio_path: str) -> dict:
    if not OPENAI_KEY:
        raise ValueError("OPENAI_API_KEY not set")

    boundary = "----WhisperMCPBoundary"
    with open(audio_path, 'rb') as f:
        audio_data = f.read()

    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"model\"\r\n\r\n{WHISPER_MODEL}\r\n"
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"response_format\"\r\n\r\nverbose_json\r\n"
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"timestamp_granularities[]\"\r\n\r\nsegment\r\n"
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"audio.mp3\"\r\nContent-Type: audio/mpeg\r\n\r\n"
    ).encode() + audio_data + f"\r\n--{boundary}--\r\n".encode()

    req = urllib.request.Request(
        "https://api.openai.com/v1/audio/transcriptions",
        data=body,
        headers={
            "Authorization": f"Bearer {OPENAI_KEY}",
            "Content-Type": f"multipart/form-data; boundary={boundary}"
        }
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read())

def whisper_chunked(audio_path: str) -> dict:
    chunk_dir = Path(audio_path).parent / "chunks"
    chunk_dir.mkdir(exist_ok=True)

    result = subprocess.run([
        "ffprobe", "-v", "quiet", "-show_entries", "format=duration",
        "-of", "csv=p=0", audio_path
    ], capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError("ffprobe unavailable — cannot chunk large file")

    duration = float(result.stdout.strip())
    chunks = []
    start = 0
    i = 0

    while start < duration:
        chunk_path = str(chunk_dir / f"chunk_{i:03d}.mp3")
        subprocess.run([
            "ffmpeg", "-y", "-ss", str(start), "-t", str(CHUNK_SECS),
            "-i", audio_path, chunk_path
        ], capture_output=True)
        chunks.append((chunk_path, start))
        start += CHUNK_SECS
        i += 1

    all_segments = []
    for chunk_path, offset in chunks:
        res = whisper_single(chunk_path)
        for seg in res.get("segments", []):
            seg["start"] += offset
            seg["end"] += offset
            all_segments.append(seg)

    return {
        "segments": all_segments,
        "text": " ".join(s["text"].strip() for s in all_segments)
    }

def whisper_transcribe(audio_path: str) -> dict:
    size = file_mb(audio_path)
    if size > MAX_MB:
        return whisper_chunked(audio_path)
    return whisper_single(audio_path)

# ─────────────────────────────────────────────
# ASSEMBLYAI FALLBACK
# ─────────────────────────────────────────────

def assemblyai_transcribe(audio_path: str) -> dict:
    if not ASSEMBLYAI_KEY:
        raise ValueError("ASSEMBLYAI_API_KEY not set")

    # Upload
    with open(audio_path, 'rb') as f:
        audio_data = f.read()

    upload_req = urllib.request.Request(
        "https://api.assemblyai.com/v2/upload",
        data=audio_data,
        headers={
            "authorization": ASSEMBLYAI_KEY,
            "content-type": "application/octet-stream"
        }
    )
    with urllib.request.urlopen(upload_req, timeout=300) as resp:
        audio_url = json.loads(resp.read())["upload_url"]

    # Request transcription
    tr_req = urllib.request.Request(
        "https://api.assemblyai.com/v2/transcript",
        data=json.dumps({
            "audio_url": audio_url,
            "language_detection": True,
            "punctuate": True,
            "format_text": True
        }).encode(),
        headers={
            "authorization": ASSEMBLYAI_KEY,
            "content-type": "application/json"
        }
    )
    with urllib.request.urlopen(tr_req, timeout=30) as resp:
        job_id = json.loads(resp.read())["id"]

    # Poll
    while True:
        poll = urllib.request.Request(
            f"https://api.assemblyai.com/v2/transcript/{job_id}",
            headers={"authorization": ASSEMBLYAI_KEY}
        )
        with urllib.request.urlopen(poll, timeout=30) as resp:
            data = json.loads(resp.read())

        if data["status"] == "completed":
            words = data.get("words", [])
            segs = []
            if words:
                cur = {"start": words[0]["start"] / 1000, "words": []}
                for w in words:
                    ws = w["start"] / 1000
                    if ws - cur["start"] > 10 and cur["words"]:
                        segs.append({
                            "start": cur["start"],
                            "end": cur["words"][-1]["end"] / 1000,
                            "text": " ".join(x["text"] for x in cur["words"])
                        })
                        cur = {"start": ws, "words": []}
                    cur["words"].append(w)
                if cur["words"]:
                    segs.append({
                        "start": cur["start"],
                        "end": cur["words"][-1]["end"] / 1000,
                        "text": " ".join(x["text"] for x in cur["words"])
                    })
            return {"segments": segs, "text": data.get("text", "")}

        elif data["status"] == "error":
            raise RuntimeError(f"AssemblyAI error: {data.get('error')}")

        time.sleep(5)

# ─────────────────────────────────────────────
# HYBRID ENGINE
# ─────────────────────────────────────────────

def transcribe_hybrid(audio_path: str) -> tuple[dict, str]:
    if OPENAI_KEY:
        try:
            result = whisper_transcribe(audio_path)
            return result, "OpenAI Whisper"
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            if is_quota_error(body, e.code):
                # Silent fallback
                return assemblyai_transcribe(audio_path), "AssemblyAI (Whisper quota exhausted)"
            return assemblyai_transcribe(audio_path), f"AssemblyAI (Whisper HTTP {e.code})"
        except Exception:
            return assemblyai_transcribe(audio_path), "AssemblyAI (Whisper fallback)"
    else:
        return assemblyai_transcribe(audio_path), "AssemblyAI"

# ─────────────────────────────────────────────
# FORMAT OUTPUT
# ─────────────────────────────────────────────

def format_transcript(result: dict, url: str, engine: str, title: str = "") -> str:
    segments = result.get("segments", [])
    lines = [
        "=" * 70,
        "VERBATIM TRANSCRIPT",
        f"Source : {url}",
        f"Title  : {title}" if title else "",
        f"Engine : {engine}",
        f"Segs   : {len(segments)}",
        "=" * 70,
        ""
    ]
    lines = [l for l in lines if l != ""]

    if segments:
        for seg in segments:
            ts = format_ts(seg.get("start", 0))
            text = seg.get("text", "").strip()
            if text:
                lines.append(f"[{ts}]  {text}")
    else:
        lines.append(result.get("text", ""))

    lines += ["", "=" * 70, "END OF TRANSCRIPT", "=" * 70]
    return "\n".join(lines)

def get_video_metadata(url: str) -> dict:
    api_url = f"https://www.youtube.com/oembed?url={url}&format=json"
    req = urllib.request.Request(api_url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception:
        return {}

# ─────────────────────────────────────────────
# MCP TOOLS
# ─────────────────────────────────────────────

@mcp.tool(
    name="transcribe_video",
    annotations={
        "title": "Transcribe YouTube Video",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True
    }
)
async def transcribe_video(params: TranscribeInput) -> str:
    """
    Download audio from a YouTube (or other) video URL, transcribe it using
    OpenAI Whisper with automatic fallback to AssemblyAI if Whisper quota
    is exhausted or any error occurs. Returns full verbatim timestamped transcript.

    Args:
        params (TranscribeInput): Input containing:
            - url (str): YouTube or other video URL

    Returns:
        str: Full verbatim transcript with timestamps and engine metadata
    """
    metadata = get_video_metadata(params.url)
    title = metadata.get("title", "")
    channel = metadata.get("author_name", "")

    with tempfile.TemporaryDirectory() as tmpdir:
        audio_path = str(Path(tmpdir) / "audio.mp3")

        try:
            download_audio(params.url, audio_path)
        except RuntimeError as e:
            return f"Error downloading audio: {e}\n\nTry updating yt-dlp on the server."

        try:
            result, engine = transcribe_hybrid(audio_path)
        except Exception as e:
            return f"Transcription failed on all engines: {e}"

        transcript = format_transcript(result, params.url, engine, title)

        header = ""
        if title:
            header = f"Video: {title}\nChannel: {channel}\n\n"

        return header + transcript


@mcp.tool(
    name="get_video_info",
    annotations={
        "title": "Get YouTube Video Metadata",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True
    }
)
async def get_video_info(params: MetadataInput) -> str:
    """
    Fetch metadata for a YouTube video including title, channel name,
    and thumbnail URL using the YouTube oEmbed API.

    Args:
        params (MetadataInput): Input containing:
            - url (str): YouTube video URL

    Returns:
        str: JSON string with title, author_name, thumbnail_url
    """
    metadata = get_video_metadata(params.url)
    if not metadata:
        return json.dumps({"error": "Could not fetch metadata. Check URL."})
    return json.dumps({
        "title": metadata.get("title", ""),
        "channel": metadata.get("author_name", ""),
        "thumbnail": metadata.get("thumbnail_url", ""),
        "video_url": params.url
    }, indent=2)


@mcp.tool(
    name="health_check",
    annotations={
        "title": "Health Check",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False
    }
)
async def health_check() -> str:
    """
    Check server health and which transcription engines are configured.

    Returns:
        str: JSON with engine availability status
    """
    return json.dumps({
        "status": "ok",
        "openai_whisper": bool(OPENAI_KEY),
        "assemblyai": bool(ASSEMBLYAI_KEY),
        "yt_dlp": subprocess.run(["yt-dlp", "--version"],
                                  capture_output=True).returncode == 0
    }, indent=2)


if __name__ == "__main__":
    mcp.run(transport="streamable-http", port=int(os.environ.get("PORT", 8000)))
