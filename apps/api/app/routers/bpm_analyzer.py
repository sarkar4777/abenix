"""BPM Analyzer — multimodal chat for BPMN / flowchart artefacts."""
from __future__ import annotations

import base64
import io
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.responses import error, success

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))
from models.agent import Agent  # type: ignore
from models.conversation import Conversation, Message  # type: ignore
from models.user import User  # type: ignore

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/bpm-analyzer", tags=["bpm-analyzer"])

APP_SLUG = "bpm-analyzer"
AGENT_SLUG = "bpm-process-analyst"
MAX_PAGES = 20            # cap so a 200-page PDF doesn't blow the context window
RENDER_DPI = 144          # diagram detail vs payload size sweet spot


def _render_pdf_pages(pdf_bytes: bytes, max_pages: int = MAX_PAGES) -> list[dict[str, str]]:
    """Render up to `max_pages` of a PDF to (base64 PNG + text).

    Returns: [{"page": 1, "image_b64": "...", "text": "...", "width":, "height":}]
    """
    try:
        import fitz  # PyMuPDF
    except ImportError as e:
        raise RuntimeError(f"PyMuPDF not installed in this image: {e}") from e

    out: list[dict[str, str]] = []
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        n = min(doc.page_count, max_pages)
        zoom = RENDER_DPI / 72.0
        mat = fitz.Matrix(zoom, zoom)
        for i in range(n):
            page = doc.load_page(i)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            png_bytes = pix.tobytes("png")
            out.append({
                "page": i + 1,
                "image_b64": base64.b64encode(png_bytes).decode("ascii"),
                "text": (page.get_text("text") or "").strip()[:4000],
                "width": pix.width,
                "height": pix.height,
            })
    finally:
        doc.close()
    return out


def _extract_docx_text(file_bytes: bytes) -> str:
    """Pull plain text from a .docx without depending on python-docx."""
    import zipfile
    import xml.etree.ElementTree as ET

    with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
        with z.open("word/document.xml") as f:
            tree = ET.parse(f)
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    paragraphs: list[str] = []
    for p in tree.iter(f"{{{ns}}}p"):
        text = "".join((t.text or "") for t in p.iter(f"{{{ns}}}t"))
        if text:
            paragraphs.append(text)
    return "\n\n".join(paragraphs)


def _process_upload(
    file_bytes: bytes, content_type: str, filename: str,
) -> tuple[list[dict[str, Any]], str]:
    """Detect modality of the upload and return persistence-ready attachments."""
    ct = (content_type or "").lower()
    name = filename or "upload"
    fn = name.lower()

    # PDFs — keep the page-rasterization path so diagrams stay legible.
    if ct in ("application/pdf", "application/x-pdf") or fn.endswith(".pdf"):
        pages = _render_pdf_pages(file_bytes)
        if not pages:
            raise RuntimeError("PDF has no readable pages")
        return ([
            {
                "type": "pdf_page",
                "page": p["page"],
                "image_b64": p["image_b64"],
                "text": p["text"],
                "width": p["width"],
                "height": p["height"],
                "filename": name,
            } for p in pages
        ], "")

    # Images — pass straight through as base64 to all three providers.
    if ct.startswith("image/") or fn.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")):
        if not ct.startswith("image/"):
            ext = fn.rsplit(".", 1)[-1] if "." in fn else "png"
            ct = f"image/{'jpeg' if ext == 'jpg' else ext}"
        return ([
            {
                "type": "image",
                "image_b64": base64.b64encode(file_bytes).decode("ascii"),
                "media_type": ct,
                "filename": name,
            }
        ], "")

    # Audio — Gemini-only.
    if ct.startswith("audio/") or fn.endswith((".mp3", ".wav", ".ogg", ".m4a", ".flac", ".aac")):
        if not ct.startswith("audio/"):
            ext = fn.rsplit(".", 1)[-1] if "." in fn else "mpeg"
            ext_map = {"mp3": "mpeg", "m4a": "mp4", "ogg": "ogg", "wav": "wav", "flac": "flac", "aac": "aac"}
            ct = f"audio/{ext_map.get(ext, ext)}"
        return ([
            {
                "type": "audio",
                "audio_b64": base64.b64encode(file_bytes).decode("ascii"),
                "media_type": ct,
                "filename": name,
            }
        ], "google")

    # Video — Gemini-only.
    if ct.startswith("video/") or fn.endswith((".mp4", ".webm", ".mov", ".avi", ".mkv")):
        if not ct.startswith("video/"):
            ext = fn.rsplit(".", 1)[-1] if "." in fn else "mp4"
            ext_map = {"mov": "quicktime", "mp4": "mp4", "webm": "webm", "avi": "x-msvideo", "mkv": "x-matroska"}
            ct = f"video/{ext_map.get(ext, ext)}"
        return ([
            {
                "type": "video",
                "video_b64": base64.b64encode(file_bytes).decode("ascii"),
                "media_type": ct,
                "filename": name,
            }
        ], "google")

    # DOCX — extract paragraphs into a single text doc.
    if fn.endswith(".docx") or ct == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        try:
            text = _extract_docx_text(file_bytes)
        except Exception as e:
            raise RuntimeError(f"Could not parse DOCX: {e}") from e
        if not text.strip():
            raise RuntimeError("DOCX appears to be empty")
        return ([
            {
                "type": "text_doc",
                "text": text[:200000],
                "filename": name,
                "doc_kind": "docx",
            }
        ], "")

    # Plain text / markdown / csv.
    if ct.startswith("text/") or fn.endswith((".txt", ".md", ".csv")):
        text = file_bytes.decode("utf-8", errors="replace")
        if not text.strip():
            raise RuntimeError("Text file is empty")
        return ([
            {
                "type": "text_doc",
                "text": text[:200000],
                "filename": name,
                "doc_kind": (fn.rsplit(".", 1)[-1] if "." in fn else "txt"),
            }
        ], "")

    raise RuntimeError(f"Unsupported file type: {ct or fn}")


def _parse_agent_specs(raw: str) -> dict[str, Any] | None:
    """Parse the BPM analyst's agent-spec reply out of an LLM response."""
    import json
    import re

    if not raw:
        return None
    s = raw.strip().lstrip("﻿")

    # Strip a fenced block (```json ... ``` or just ``` ... ```)
    fence = re.search(r"```(?:json|JSON)?\s*\n?([\s\S]*?)```", s)
    if fence:
        s = fence.group(1).strip()

    # Normalize smart quotes + non-breaking spaces
    s = (s.replace("“", '"').replace("”", '"')
           .replace("‘", "'").replace("’", "'")
           .replace(" ", " "))

    # Walk the string and collect every balanced top-level {...} block,
    # respecting string literals and escapes.
    candidates: list[str] = []
    depth = 0
    start = -1
    in_str = False
    esc = False
    for i, ch in enumerate(s):
        if esc:
            esc = False
            continue
        if ch == "\\":
            esc = True
            continue
        if ch == '"' and not (depth == 0 and not in_str and start == -1):
            in_str = not in_str
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start != -1:
                    candidates.append(s[start:i + 1])
                    start = -1

    # Prefer the longest candidate that mentions "agents"
    candidates.sort(key=lambda c: (0 if '"agents"' in c else 1, -len(c)))

    def _clean(blk: str) -> str:
        # Block comments
        blk = re.sub(r"/\*[\s\S]*?\*/", "", blk)
        # Line comments — only outside of double-quoted strings.
        out_lines: list[str] = []
        for line in blk.splitlines():
            in_q = False
            esc_q = False
            cut: int | None = None
            for j, c in enumerate(line):
                if esc_q:
                    esc_q = False
                    continue
                if c == "\\":
                    esc_q = True
                    continue
                if c == '"':
                    in_q = not in_q
                    continue
                if not in_q and c == "/" and j + 1 < len(line) and line[j + 1] == "/":
                    cut = j
                    break
            out_lines.append(line[:cut] if cut is not None else line)
        blk = "\n".join(out_lines)
        # Trailing commas before } or ]
        blk = re.sub(r",(\s*[}\]])", r"\1", blk)
        return blk

    for c in candidates:
        for variant in (c, _clean(c)):
            try:
                obj = json.loads(variant)
            except Exception:
                continue
            if isinstance(obj, dict) and isinstance(obj.get("agents"), list):
                return obj

    # Last-resort: clean the whole string
    try:
        obj = json.loads(_clean(s))
        if isinstance(obj, dict) and isinstance(obj.get("agents"), list):
            return obj
    except Exception:
        pass
    return None


def _opening_for(primary_type: str) -> str:
    """Pick a context-appropriate opening prompt based on what was uploaded."""
    if primary_type == "pdf_page":
        return ("Analyze this BPM diagram in detail. Produce the full Detailed "
                "Agentification Report per your system prompt.")
    if primary_type == "image":
        return ("Analyze this process artifact image (diagram, screenshot, or "
                "whiteboard photo). Produce the full Detailed Agentification "
                "Report per your system prompt.")
    if primary_type == "audio":
        return ("Listen to this recorded process walkthrough. Transcribe the "
                "steps the speaker describes, then produce the full Detailed "
                "Agentification Report per your system prompt.")
    if primary_type == "video":
        return ("Watch this recorded process walkthrough — both the visuals "
                "and any spoken audio describe the workflow. Then produce the "
                "full Detailed Agentification Report per your system prompt.")
    if primary_type == "text_doc":
        return ("Analyze this process document (SOP / runbook / specification). "
                "Identify the workflow it describes, then produce the full "
                "Detailed Agentification Report per your system prompt.")
    return ("Analyze the attached process artifact. Produce the full Detailed "
            "Agentification Report per your system prompt.")


def _serialize_thread(c: Conversation) -> dict[str, Any]:
    return {
        "id": str(c.id),
        "title": c.title,
        "agent_slug": c.agent_slug,
        "app_slug": c.app_slug,
        "message_count": c.message_count,
        "last_message_preview": c.last_message_preview,
        "total_cost": float(c.total_cost or 0.0),
        "total_tokens": c.total_tokens,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }


def _serialize_message(m: Message, *, include_attachments: bool = False) -> dict[str, Any]:
    out = {
        "id": str(m.id),
        "role": m.role,
        "content": m.content,
        "model_used": m.model_used,
        "input_tokens": m.input_tokens,
        "output_tokens": m.output_tokens,
        "cost": float(m.cost or 0.0),
        "duration_ms": m.duration_ms,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }
    if include_attachments:
        out["attachments"] = m.attachments
    return out


async def _get_agent(db: AsyncSession) -> Agent | None:
    row = await db.execute(select(Agent).where(Agent.slug == AGENT_SLUG))
    return row.scalar_one_or_none()


def _attachments_to_blocks(attachments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Translate persisted attachments into provider-agnostic content blocks."""
    blocks: list[dict[str, Any]] = []
    for a in attachments or []:
        atype = a.get("type")
        if atype == "pdf_page":
            blocks.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": a.get("image_b64", ""),
                },
            })
            if a.get("text"):
                blocks.append({
                    "type": "text",
                    "text": f"=== PAGE {a.get('page')} EXTRACTED TEXT ===\n{a['text']}",
                })
        elif atype == "image":
            blocks.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": a.get("media_type", "image/png"),
                    "data": a.get("image_b64", ""),
                },
            })
            if a.get("filename"):
                blocks.append({"type": "text", "text": f"=== IMAGE: {a['filename']} ==="})
        elif atype == "audio":
            blocks.append({
                "type": "audio",
                "source": {
                    "type": "base64",
                    "media_type": a.get("media_type", "audio/mpeg"),
                    "data": a.get("audio_b64", ""),
                },
            })
            blocks.append({
                "type": "text",
                "text": (f"=== AUDIO: {a.get('filename') or 'recording'} === "
                         "Listen to the recording, transcribe the process the "
                         "speaker describes, then proceed with your normal analysis."),
            })
        elif atype == "video":
            blocks.append({
                "type": "video",
                "source": {
                    "type": "base64",
                    "media_type": a.get("media_type", "video/mp4"),
                    "data": a.get("video_b64", ""),
                },
            })
            blocks.append({
                "type": "text",
                "text": (f"=== VIDEO: {a.get('filename') or 'recording'} === "
                         "Watch carefully — both the visuals and any spoken "
                         "audio describe the process. Then proceed with your "
                         "normal analysis."),
            })
        elif atype == "text_doc":
            kind = a.get("doc_kind", "txt")
            blocks.append({
                "type": "text",
                "text": (f"=== DOCUMENT: {a.get('filename') or 'attachment'} "
                         f"({kind}) ===\n{a.get('text', '')}"),
            })
    return blocks


def _build_anthropic_messages(
    attachments: list[dict[str, Any]],
    history_turns: list[Message],
    new_user_question: str,
) -> list[dict[str, Any]]:
    """Build the provider-agnostic messages[] array for the BPM analyst."""
    msgs: list[dict[str, Any]] = []
    first_content: list[dict[str, Any]] = _attachments_to_blocks(attachments)

    user_turns = [m for m in history_turns if m.role == "user"]
    if user_turns:
        first_content.append({"type": "text", "text": user_turns[0].content})
        msgs.append({"role": "user", "content": first_content})
        in_first = True
        for m in history_turns:
            if in_first and m.role == "user":
                in_first = False
                continue
            msgs.append({
                "role": m.role,
                "content": m.content if m.role == "user" else (m.content or ""),
            })
        msgs.append({"role": "user", "content": new_user_question})
    else:
        first_content.append({"type": "text", "text": new_user_question})
        msgs.append({"role": "user", "content": first_content})
    return msgs


DEFAULT_VISION_MODELS = [
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "claude-sonnet-4-5-20250929",
    "claude-haiku-4-5-20251001",
    "gpt-4o",
    "gpt-4o-mini",
]

# Approximate per-1M-token pricing (USD). Used for cost attribution.
MODEL_PRICING = {
    "gemini-2.5-pro":              {"in": 1.25, "out": 10.0},
    "gemini-2.5-flash":            {"in": 0.075, "out": 0.30},
    "claude-sonnet-4-5-20250929":  {"in": 3.0, "out": 15.0},
    "claude-haiku-4-5-20251001":   {"in": 1.0, "out": 5.0},
    "gpt-4o":                      {"in": 2.5, "out": 10.0},
    "gpt-4o-mini":                 {"in": 0.15, "out": 0.60},
}


def _provider_for(model: str) -> str:
    m = (model or "").lower()
    if m.startswith("gemini"): return "google"
    if m.startswith("claude"): return "anthropic"
    if m.startswith("gpt-") or m.startswith("openai/"): return "openai"
    raise RuntimeError(f"Unsupported model for vision dispatch: {model}")


def _cost_for(model: str, in_tok: int, out_tok: int) -> float:
    p = MODEL_PRICING.get(model, {"in": 0.0, "out": 0.0})
    return round((in_tok / 1_000_000) * p["in"] + (out_tok / 1_000_000) * p["out"], 6)


async def _run_anthropic(
    *, system_prompt: str, messages: list[dict[str, Any]], model: str,
    force_json: bool = False,
) -> tuple[str, dict[str, Any]]:
    """Call Anthropic Messages API."""
    import anthropic
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not configured on this pod")
    safe: list[dict[str, Any]] = []
    for m in messages:
        c = m.get("content")
        if isinstance(c, list):
            c = [b for b in c if b.get("type") in ("text", "image")]
        safe.append({"role": m["role"], "content": c})
    if force_json:
        safe.append({"role": "assistant", "content": "{"})
    started = datetime.now(timezone.utc)
    client = anthropic.AsyncAnthropic(api_key=api_key)
    resp = await client.messages.create(
        model=model,
        max_tokens=8000,
        system=system_prompt,
        messages=safe,
    )
    elapsed_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
    text_parts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
    text = "\n".join(text_parts)
    if force_json and not text.lstrip().startswith("{"):
        text = "{" + text
    in_tok = resp.usage.input_tokens or 0
    out_tok = resp.usage.output_tokens or 0
    return text, {
        "model": resp.model,
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "cost": _cost_for(model, in_tok, out_tok),
        "duration_ms": elapsed_ms,
    }


async def _run_gemini(
    *, system_prompt: str, messages: list[dict[str, Any]], model: str,
    force_json: bool = False,
) -> tuple[str, dict[str, Any]]:
    """Call Google Gemini Generative AI with multimodal content."""
    import google.generativeai as genai
    api_key = (os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY (or GEMINI_API_KEY) not configured on this pod")
    genai.configure(api_key=api_key)

    contents: list[dict[str, Any]] = []
    for m in messages:
        # Gemini uses "model" for assistant turns
        role = "model" if m["role"] == "assistant" else "user"
        parts: list[dict[str, Any]] = []
        c = m["content"]
        if isinstance(c, str):
            parts.append({"text": c})
        elif isinstance(c, list):
            for block in c:
                btype = block.get("type")
                if btype == "text":
                    parts.append({"text": block.get("text", "")})
                elif btype in ("image", "audio", "video"):
                    src = block.get("source", {})
                    if src.get("type") == "base64":
                        parts.append({
                            "inline_data": {
                                "mime_type": src.get("media_type", "application/octet-stream"),
                                "data": src.get("data", ""),
                            }
                        })
        contents.append({"role": role, "parts": parts})

    started = datetime.now(timezone.utc)
    gen_cfg: dict[str, Any] = {"temperature": 0.15, "max_output_tokens": 8000}
    if force_json:
        gen_cfg["response_mime_type"] = "application/json"
    model_obj = genai.GenerativeModel(
        model,
        system_instruction=system_prompt,
        generation_config=gen_cfg,
    )
    # The library's async path is generate_content_async
    resp = await model_obj.generate_content_async(contents)
    elapsed_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)

    text = ""
    try:
        text = resp.text or ""
    except Exception:
        # Fall back to walking candidates if .text raised (e.g. blocked content)
        for cand in getattr(resp, "candidates", []) or []:
            for p in getattr(getattr(cand, "content", None), "parts", []) or []:
                t = getattr(p, "text", None)
                if t: text += t

    usage = getattr(resp, "usage_metadata", None)
    in_tok = int(getattr(usage, "prompt_token_count", 0) or 0) if usage else 0
    out_tok = int(getattr(usage, "candidates_token_count", 0) or 0) if usage else 0
    return text, {
        "model": model,
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "cost": _cost_for(model, in_tok, out_tok),
        "duration_ms": elapsed_ms,
    }


async def _run_openai(
    *, system_prompt: str, messages: list[dict[str, Any]], model: str,
    force_json: bool = False,
) -> tuple[str, dict[str, Any]]:
    """Call OpenAI Chat Completions with multimodal content (GPT-4o etc)."""
    import openai
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not configured on this pod")
    client = openai.AsyncOpenAI(api_key=api_key)

    oa_messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    for m in messages:
        c = m["content"]
        if isinstance(c, str):
            oa_messages.append({"role": m["role"], "content": c})
            continue
        parts: list[dict[str, Any]] = []
        for block in c:
            btype = block.get("type")
            if btype == "text":
                parts.append({"type": "text", "text": block.get("text", "")})
            elif btype == "image":
                src = block.get("source", {})
                if src.get("type") == "base64":
                    parts.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{src.get('media_type','image/png')};base64,{src.get('data','')}",
                        },
                    })
        oa_messages.append({"role": m["role"], "content": parts})

    started = datetime.now(timezone.utc)
    create_kwargs: dict[str, Any] = {
        "model": model,
        "messages": oa_messages,
        "max_tokens": 8000,
        "temperature": 0.15,
    }
    if force_json:
        create_kwargs["response_format"] = {"type": "json_object"}
    resp = await client.chat.completions.create(**create_kwargs)
    elapsed_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
    text = (resp.choices[0].message.content or "") if resp.choices else ""
    in_tok = resp.usage.prompt_tokens if resp.usage else 0
    out_tok = resp.usage.completion_tokens if resp.usage else 0
    return text, {
        "model": resp.model,
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "cost": _cost_for(model, in_tok, out_tok),
        "duration_ms": elapsed_ms,
    }


async def _run_vision_model(
    *, system_prompt: str, messages: list[dict[str, Any]], model: str,
    force_json: bool = False,
) -> tuple[str, dict[str, Any]]:
    """Provider-route based on model name. `force_json` activates each"""
    provider = _provider_for(model)
    if provider == "anthropic":
        return await _run_anthropic(system_prompt=system_prompt, messages=messages, model=model, force_json=force_json)
    if provider == "google":
        return await _run_gemini(system_prompt=system_prompt, messages=messages, model=model, force_json=force_json)
    if provider == "openai":
        return await _run_openai(system_prompt=system_prompt, messages=messages, model=model, force_json=force_json)
    raise RuntimeError(f"No dispatch path for provider {provider}")


@router.get("/models")
async def list_vision_models(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Vision-capable models for the BPM Analyzer's model picker."""
    from app.routers.admin_settings import AVAILABLE_MODELS
    vision_models = [m for m in AVAILABLE_MODELS if "vision" in (m.get("capabilities") or [])]
    agent = await _get_agent(db)
    default = (agent.model_config_ if agent else {}).get("model") or "gemini-2.5-pro"
    return success({
        "models": vision_models,    # rich objects: {id, label, provider, family, capabilities}
        "default": default,
    })


@router.post("/upload")
async def upload_pdf(
    request: Request,
    file: UploadFile = File(...),
    title: str = Form(""),
    model: str = Form(""),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Upload a process artifact and kick off the multimodal analysis."""
    raw = await file.read()
    if not raw:
        return error("Empty file", 400)
    if len(raw) > 50 * 1024 * 1024:
        return error("Upload exceeds 50 MB limit", 413)

    try:
        attachments, required_provider = _process_upload(
            raw, file.content_type or "", file.filename or "",
        )
    except Exception as e:
        logger.exception("BPM upload processing failed")
        return error(f"Could not process upload: {e}", 415)
    if not attachments:
        return error("Upload produced no attachments", 422)

    agent = await _get_agent(db)
    if not agent:
        return error(f"Agent {AGENT_SLUG} not seeded — run alembic + seed_agents", 503)

    fname = (file.filename or "BPM Artifact").rsplit(".", 1)[0]
    thread_title = (title or fname).strip()[:255] or "BPM Analysis"

    # Pick a model. Audio/video force a Google model since the others
    # don't accept those modalities at the API level.
    chosen_model = (model or "").strip() or (agent.model_config_ or {}).get("model") or "gemini-2.5-pro"
    if required_provider and _provider_for(chosen_model) != required_provider:
        chosen_model = "gemini-2.5-pro"

    conv = Conversation(
        id=uuid.uuid4(),
        tenant_id=user.tenant_id,
        user_id=user.id,
        agent_id=agent.id,
        agent_slug=agent.slug,
        app_slug=APP_SLUG,
        subject_type=getattr(getattr(request.state, "acting_subject", None), "subject_type", None) or "user",
        subject_id=getattr(getattr(request.state, "acting_subject", None), "subject_id", None) or str(user.id),
        title=thread_title,
        model_used=chosen_model,
    )
    db.add(conv)
    await db.flush()

    primary_type = attachments[0].get("type") if attachments else "pdf_page"
    opening = _opening_for(primary_type)

    user_msg = Message(
        id=uuid.uuid4(),
        conversation_id=conv.id,
        role="user",
        content=opening,
        attachments=attachments,
    )
    db.add(user_msg)
    conv.message_count = 1
    conv.last_message_preview = opening
    await db.commit()
    await db.refresh(conv)

    try:
        anthro_msgs = _build_anthropic_messages(attachments, history_turns=[user_msg], new_user_question="")
        if anthro_msgs and isinstance(anthro_msgs[-1].get("content"), str) and not anthro_msgs[-1]["content"]:
            anthro_msgs = anthro_msgs[:-1]
        text, meta = await _run_vision_model(
            system_prompt=agent.system_prompt or "",
            messages=anthro_msgs,
            model=chosen_model,
        )
    except Exception as e:
        logger.exception("BPM analyzer initial call failed")
        await db.execute(
            select(Conversation).where(Conversation.id == conv.id)  # ensure attached
        )
        err_msg = Message(
            id=uuid.uuid4(),
            conversation_id=conv.id,
            role="assistant",
            content=f"[error] {e}",
        )
        db.add(err_msg)
        conv.message_count += 1
        conv.last_message_preview = "[error]"
        await db.commit()
        return error(f"Analysis failed: {e}", 502)

    asst = Message(
        id=uuid.uuid4(),
        conversation_id=conv.id,
        role="assistant",
        content=text,
        model_used=meta["model"],
        input_tokens=meta["input_tokens"],
        output_tokens=meta["output_tokens"],
        cost=meta["cost"],
        duration_ms=meta["duration_ms"],
    )
    db.add(asst)
    conv.message_count = 2
    conv.last_message_preview = text[:200]
    conv.total_tokens = (conv.total_tokens or 0) + meta["input_tokens"] + meta["output_tokens"]
    conv.total_cost = float(conv.total_cost or 0.0) + meta["cost"]
    conv.model_used = meta["model"]
    conv.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(conv)
    await db.refresh(asst)

    return success({
        "thread": _serialize_thread(conv),
        "user_message": _serialize_message(user_msg),
        "assistant_message": _serialize_message(asst),
        "attachments_count": len(attachments),
        "primary_type": primary_type,
    })


@router.post("/chat/{thread_id}/turn")
async def chat_turn(
    thread_id: str,
    body: dict,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Append a follow-up question on an existing BPM analysis thread."""
    try:
        conv_uuid = uuid.UUID(thread_id)
    except ValueError:
        return error("Invalid thread id", 400)
    conv = (await db.execute(select(Conversation).where(Conversation.id == conv_uuid))).scalar_one_or_none()
    if not conv:
        return error("Thread not found", 404)
    if conv.tenant_id != user.tenant_id:
        return error("Forbidden", 403)

    content = (body.get("content") or "").strip()
    if not content:
        return error("content is required", 400)

    agent = await _get_agent(db)
    if not agent:
        return error(f"Agent {AGENT_SLUG} not seeded", 503)

    history = (await db.execute(
        select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at)
    )).scalars().all()
    # Pull the multimodal attachments off the first user turn (PDF
    # pages, images, audio/video, or extracted text — any modality the
    # upload route accepts).
    attachments: list[dict[str, Any]] = []
    for m in history:
        if m.role == "user" and m.attachments:
            attachments = [a for a in m.attachments if isinstance(a, dict)]
            break
    if not attachments:
        return error("No source artifact found on this thread — re-upload the file", 400)

    user_msg = Message(
        id=uuid.uuid4(),
        conversation_id=conv.id,
        role="user",
        content=content,
    )
    db.add(user_msg)
    conv.message_count = (conv.message_count or 0) + 1
    conv.last_message_preview = content[:200]
    conv.updated_at = datetime.now(timezone.utc)
    await db.commit()

    history2 = (await db.execute(
        select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at)
    )).scalars().all()

    try:
        anthro_msgs = _build_anthropic_messages(attachments, history_turns=history2[:-1], new_user_question=content)
        # Use the model the thread was opened with; fall back to the agent default
        chosen_model = conv.model_used or (agent.model_config_ or {}).get("model") or "gemini-2.5-pro"
        text, meta = await _run_vision_model(
            system_prompt=agent.system_prompt or "",
            messages=anthro_msgs,
            model=chosen_model,
        )
    except Exception as e:
        logger.exception("BPM analyzer turn failed")
        err = Message(
            id=uuid.uuid4(),
            conversation_id=conv.id,
            role="assistant",
            content=f"[error] {e}",
        )
        db.add(err)
        conv.message_count += 1
        conv.last_message_preview = "[error]"
        await db.commit()
        return error(f"Turn failed: {e}", 502)

    asst = Message(
        id=uuid.uuid4(),
        conversation_id=conv.id,
        role="assistant",
        content=text,
        model_used=meta["model"],
        input_tokens=meta["input_tokens"],
        output_tokens=meta["output_tokens"],
        cost=meta["cost"],
        duration_ms=meta["duration_ms"],
    )
    db.add(asst)
    conv.message_count += 1
    conv.last_message_preview = text[:200]
    conv.total_tokens = (conv.total_tokens or 0) + meta["input_tokens"] + meta["output_tokens"]
    conv.total_cost = float(conv.total_cost or 0.0) + meta["cost"]
    conv.model_used = meta["model"]
    conv.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(asst)
    await db.refresh(conv)

    return success({
        "thread": _serialize_thread(conv),
        "user_message": _serialize_message(user_msg),
        "assistant_message": _serialize_message(asst),
    })


@router.get("/threads")
async def list_threads(
    request: Request,
    limit: int = 50,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    q = (
        select(Conversation)
        .where(Conversation.tenant_id == user.tenant_id)
        .where(Conversation.app_slug == APP_SLUG)
        .order_by(desc(Conversation.updated_at))
        .limit(min(max(limit, 1), 100))
    )
    rows = (await db.execute(q)).scalars().all()
    return success({"threads": [_serialize_thread(c) for c in rows]})


@router.get("/threads/{thread_id}")
async def get_thread(
    thread_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    try:
        cid = uuid.UUID(thread_id)
    except ValueError:
        return error("Invalid thread id", 400)
    conv = (await db.execute(select(Conversation).where(Conversation.id == cid))).scalar_one_or_none()
    if not conv or conv.tenant_id != user.tenant_id:
        return error("Thread not found", 404)
    msgs = (await db.execute(
        select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at)
    )).scalars().all()
    return success({
        "thread": _serialize_thread(conv),
        # Don't ship attachments back — they're huge base64 PNGs and the
        # UI doesn't need them. Backend re-loads them on every turn.
        "messages": [_serialize_message(m) for m in msgs],
    })


@router.post("/threads/{thread_id}/suggest-agents")
async def suggest_agents(
    thread_id: str,
    body: dict,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Ask the BPM analyst to emit a STRUCTURED list of agent specs ready"""
    try:
        cid = uuid.UUID(thread_id)
    except ValueError:
        return error("Invalid thread id", 400)
    conv = (await db.execute(select(Conversation).where(Conversation.id == cid))).scalar_one_or_none()
    if not conv or conv.tenant_id != user.tenant_id:
        return error("Thread not found", 404)

    agent = await _get_agent(db)
    if not agent:
        return error(f"Agent {AGENT_SLUG} not seeded", 503)

    history = (await db.execute(
        select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at)
    )).scalars().all()
    attachments: list[dict[str, Any]] = []
    for m in history:
        if m.role == "user" and m.attachments:
            attachments = [a for a in m.attachments if isinstance(a, dict)]
            break
    if not attachments:
        return error("No source artifact on this thread", 400)

    extraction_prompt = (
        "Re-read the process artifact you just analyzed. Now output ONLY a "
        "single JSON object (no prose, no markdown fences, no JS-style "
        "`//` or `/* */` comments, no trailing commas) with this exact "
        "shape:\n\n"
        "{\n"
        '  "agents": [\n'
        "    {\n"
        '      "name": "Human-readable name (e.g. \\"Onboarding Risk Scorer\\")",\n'
        '      "slug": "kebab-case-unique-slug",\n'
        '      "category": "compliance | onboarding | finance | risk | operations | other",\n'
        '      "lane": "swim-lane or section the agent belongs to",\n'
        '      "why": "1-sentence justification — why an agent and not a tool/script",\n'
        '      "description": "1-2 sentence operator-facing description",\n'
        '      "system_prompt": "Full multi-paragraph system prompt for this agent. Include input shape, what it should do, output contract, and hard rules. Markdown OK.",\n'
        '      "model": "gemini-2.5-pro",\n'
        '      "tools": ["tool_slug_1", "tool_slug_2"]\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "Pick `model` from: gemini-2.5-pro, gemini-2.5-flash, "
        "claude-sonnet-4-5-20250929, claude-haiku-4-5-20251001. The `tools` "
        "array can be empty. Include ONE entry per agent you marked as Agent "
        "or Pipeline in your earlier matrix; skip steps you marked Tool / None. "
        "Reply with PURE JSON only. The first character of your reply must be "
        "`{` and the last must be `}`. Do NOT include any text before or after "
        "the JSON object."
    )

    model = (body or {}).get("model") or (agent.model_config_ or {}).get("model") or "gemini-2.5-pro"

    parsed: dict[str, Any] | None = None
    text: str = ""
    meta: dict[str, Any] = {}
    last_error: str | None = None
    attempts: list[tuple[str, bool]] = [
        (extraction_prompt, False),
        (extraction_prompt + (
            "\n\nIMPORTANT: Reply with PURE JSON only — no prose, no "
            "markdown fences, no JS-style comments. First character `{`, "
            "last character `}`."
        ), True),
    ]
    for prompt_text, force_json in attempts:
        try:
            anthro_msgs = _build_anthropic_messages(
                attachments, history_turns=history, new_user_question=prompt_text,
            )
            text, meta = await _run_vision_model(
                system_prompt=agent.system_prompt or "",
                messages=anthro_msgs,
                model=model,
                force_json=force_json,
            )
        except Exception as e:
            last_error = str(e)
            logger.warning("BPM suggest-agents attempt failed (force_json=%s): %s",
                           force_json, e)
            continue
        parsed = _parse_agent_specs(text)
        if parsed:
            break

    # Final attempt: show the model its own broken reply so it can
    # self-correct. Run only if both prior attempts produced text but
    # neither parsed.
    if not parsed and text:
        repair_prompt = (
            "Your previous reply could not be parsed as JSON. Below is "
            "the head of what you sent:\n\n"
            f"{(text or '')[:1500]}\n\n"
            "Re-emit the SAME content as a single valid JSON object "
            "matching this schema:\n\n"
            "{\n"
            '  "agents": [\n'
            '    {"name": "...", "slug": "...", "category": "...", "lane": "...",\n'
            '     "why": "...", "description": "...", "system_prompt": "...",\n'
            '     "model": "...", "tools": []}\n'
            "  ]\n"
            "}\n\n"
            "Reply with PURE JSON only — first character `{`, last "
            "character `}`. No prose. No fences. No comments."
        )
        try:
            anthro_msgs = _build_anthropic_messages(
                attachments, history_turns=history, new_user_question=repair_prompt,
            )
            text, meta = await _run_vision_model(
                system_prompt=agent.system_prompt or "",
                messages=anthro_msgs,
                model=model,
                force_json=True,
            )
            parsed = _parse_agent_specs(text)
        except Exception as e:
            last_error = str(e)
            logger.warning("BPM suggest-agents repair attempt failed: %s", e)

    if not parsed:
        logger.warning("BPM suggest-agents exhausted retries head=%r last_error=%s",
                       (text or "")[:300], last_error)
        return error(
            f"Agent could not produce parseable agent specs after 3 attempts on {model} — "
            f"try a different model or simplify the source artifact",
            502,
        )

    return success({
        "agents": parsed["agents"],
        "model": meta.get("model") or model,
        "cost": meta.get("cost", 0.0),
        "duration_ms": meta.get("duration_ms", 0),
    })


@router.post("/threads/{thread_id}/build-and-test")
async def build_and_test_agent(
    thread_id: str,
    body: dict,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """End-to-end orchestration for ONE suggested agent."""
    try:
        cid = uuid.UUID(thread_id)
    except ValueError:
        return error("Invalid thread id", 400)
    conv = (await db.execute(select(Conversation).where(Conversation.id == cid))).scalar_one_or_none()
    if not conv or conv.tenant_id != user.tenant_id:
        return error("Thread not found", 404)

    spec = body.get("spec") or {}
    if not spec.get("name") or not spec.get("system_prompt"):
        return error("spec.name and spec.system_prompt are required", 400)

    # Pull attachments off the thread for grounded synthetic data —
    # any modality (PDF, image, audio, video, text doc) is fine here.
    history = (await db.execute(
        select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at)
    )).scalars().all()
    attachments: list[dict[str, Any]] = []
    for m in history:
        if m.role == "user" and m.attachments:
            attachments = [a for a in m.attachments if isinstance(a, dict)]
            break

    bpm_agent = await _get_agent(db)
    bpm_model = (bpm_agent.model_config_ or {}).get("model") if bpm_agent else "gemini-2.5-pro"

    synth_prompt = (
        f"For the agent below, generate ONE realistic synthetic test "
        f"input grounded in the BPM diagram you analyzed. Output ONLY a "
        f"JSON object with this shape:\n"
        f'{{"description": "<what scenario this tests>", "input": "<the actual user message to send to the agent — string>"}}\n\n'
        f"Agent name: {spec.get('name')}\n"
        f"Lane: {spec.get('lane') or '?'}\n"
        f"Agent purpose:\n{(spec.get('description') or '')[:500]}\n\n"
        f"System prompt excerpt:\n{(spec.get('system_prompt') or '')[:1500]}\n\n"
        f"Make the input realistic — names, dates, amounts, document refs that "
        f"a real upstream step in this BPM would hand over. First char must be `{{`."
    )
    synth_input: dict[str, Any] | None = None
    try:
        if attachments and bpm_agent:
            anthro_msgs = _build_anthropic_messages(
                attachments, history_turns=history, new_user_question=synth_prompt
            )
            synth_text, _ = await _run_vision_model(
                system_prompt=bpm_agent.system_prompt or "",
                messages=anthro_msgs,
                model=bpm_model or "gemini-2.5-pro",
                force_json=True,
            )
            # Reuse the robust parser so smart quotes / fences / comments
            # / trailing commas don't break synthetic-input extraction.
            wrapped = _parse_agent_specs(
                '{"agents":[' + (synth_text or "").strip().lstrip("[").rstrip("]") + "]}"
            )
            if wrapped and wrapped.get("agents"):
                cand = wrapped["agents"][0]
                if isinstance(cand, dict) and cand.get("input"):
                    synth_input = cand
            if not synth_input:
                # Fall back to a direct parse — the synth shape is a
                # plain object {description, input}, not the {agents:[…]}
                # shape `_parse_agent_specs` requires.
                import json
                import re as _re
                cleaned = (synth_text or "").strip()
                mm = _re.search(r"```(?:json)?\s*\n?([\s\S]*?)```", cleaned)
                if mm:
                    cleaned = mm.group(1).strip()
                cleaned = (cleaned.replace("“", '"').replace("”", '"')
                                  .replace("‘", "'").replace("’", "'"))
                cleaned = _re.sub(r",(\s*[}\]])", r"\1", cleaned)
                cleaned = _re.sub(r"/\*[\s\S]*?\*/", "", cleaned)
                try:
                    synth_input = json.loads(cleaned)
                except Exception:
                    s, e = cleaned.find("{"), cleaned.rfind("}")
                    if s != -1 and e > s:
                        try:
                            synth_input = json.loads(cleaned[s:e + 1])
                        except Exception:
                            synth_input = None
    except Exception as e:
        logger.warning("Synthetic data generation failed: %s", e)

    if not synth_input or not synth_input.get("input"):
        synth_input = {
            "description": "Generic smoke test (synthetic data generator failed — re-run for grounded input)",
            "input": "Hello, this is a smoke-test message. Respond per your system prompt.",
        }

    sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))
    from models.agent import Agent as AgentModel, AgentStatus, AgentType  # type: ignore

    base_slug = (spec.get("slug") or spec.get("name") or "").strip().lower().replace(" ", "-") or "untitled-agent"
    slug = base_slug
    suffix = 0
    while True:
        existing = (await db.execute(select(AgentModel).where(AgentModel.slug == slug))).scalar_one_or_none()
        if not existing: break
        suffix += 1
        slug = f"{base_slug}-{suffix}"

    new_agent = AgentModel(
        id=uuid.uuid4(),
        tenant_id=user.tenant_id,
        creator_id=user.id,
        name=(spec.get("name") or "Untitled Agent")[:200],
        slug=slug,
        description=(spec.get("description") or "")[:1000],
        system_prompt=spec.get("system_prompt") or "",
        agent_type=AgentType.CUSTOM if hasattr(AgentType, "CUSTOM") else AgentType.OOB,
        status=AgentStatus.DRAFT,
        category=(spec.get("category") or "other")[:50],
        version="1.0.0",
        is_published=False,
        model_config_={
            "model": spec.get("model") or "gemini-2.5-pro",
            "temperature": 0.2,
            "max_iterations": 12,
            "max_tokens": 4000,
            "tools": spec.get("tools") or [],
        },
    )
    db.add(new_agent)
    await db.commit()
    await db.refresh(new_agent)

    try:
        from abenix_sdk import Abenix  # type: ignore
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "sdk" / "python"))
        from abenix_sdk import Abenix  # type: ignore

    api_key = os.environ.get("ABENIX_PLATFORM_API_KEY") or os.environ.get("ABENIX_API_KEY", "")
    api_base = os.environ.get("ABENIX_INTERNAL_URL", "http://localhost:8000")

    test_result: dict[str, Any] = {"ok": False}
    if not api_key:
        test_result = {"ok": False, "error": "ABENIX_API_KEY not set on this pod — agent created but smoke test skipped"}
    else:
        try:
            async with Abenix(api_key=api_key, base_url=api_base, timeout=180.0) as forge:
                exec_result = await forge.execute(new_agent.slug, str(synth_input["input"]))
            test_result = {
                "ok": True,
                "output": (exec_result.output or "")[:4000],
                "model": exec_result.model,
                "input_tokens": getattr(exec_result, "input_tokens", 0),
                "output_tokens": getattr(exec_result, "output_tokens", 0),
                "cost": float(exec_result.cost or 0.0),
                "duration_ms": int(exec_result.duration_ms or 0),
                "tool_calls": len(exec_result.tool_calls or []),
            }
        except Exception as e:
            logger.exception("Smoke-test execution failed")
            test_result = {"ok": False, "error": str(e)[:500]}

    return success({
        "agent": {
            "id": str(new_agent.id),
            "slug": new_agent.slug,
            "name": new_agent.name,
            "status": new_agent.status.value if hasattr(new_agent.status, "value") else str(new_agent.status),
            "model": (new_agent.model_config_ or {}).get("model"),
            "tools": (new_agent.model_config_ or {}).get("tools"),
        },
        "synthetic_input": synth_input,
        "test_result": test_result,
    })


@router.post("/threads/{thread_id}/create-agent")
async def create_suggested_agent(
    thread_id: str,
    body: dict,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Create one of the suggested agents. Body is a single spec from"""
    try:
        cid = uuid.UUID(thread_id)
    except ValueError:
        return error("Invalid thread id", 400)
    conv = (await db.execute(select(Conversation).where(Conversation.id == cid))).scalar_one_or_none()
    if not conv or conv.tenant_id != user.tenant_id:
        return error("Thread not found", 404)

    sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))
    from models.agent import Agent as AgentModel, AgentStatus, AgentType  # type: ignore

    name = (body.get("name") or "").strip()
    if not name:
        return error("name is required", 400)
    slug = (body.get("slug") or "").strip().lower().replace(" ", "-")
    if not slug:
        return error("slug is required", 400)

    # De-dupe slug
    suffix = 0
    base_slug = slug
    while True:
        existing = (await db.execute(select(AgentModel).where(AgentModel.slug == slug))).scalar_one_or_none()
        if not existing:
            break
        suffix += 1
        slug = f"{base_slug}-{suffix}"

    new_agent = AgentModel(
        id=uuid.uuid4(),
        tenant_id=user.tenant_id,
        creator_id=user.id,
        name=name[:200],
        slug=slug,
        description=(body.get("description") or "")[:1000],
        system_prompt=body.get("system_prompt") or "",
        agent_type=AgentType.CUSTOM if hasattr(AgentType, "CUSTOM") else AgentType.OOB,
        status=AgentStatus.DRAFT,
        category=(body.get("category") or "other")[:50],
        version="1.0.0",
        is_published=False,
        model_config_={
            "model": body.get("model") or "gemini-2.5-pro",
            "temperature": 0.2,
            "max_iterations": 12,
            "max_tokens": 4000,
            "tools": body.get("tools") or [],
        },
    )
    db.add(new_agent)
    await db.commit()
    await db.refresh(new_agent)

    return success({
        "id": str(new_agent.id),
        "slug": new_agent.slug,
        "name": new_agent.name,
        "status": new_agent.status.value if hasattr(new_agent.status, "value") else str(new_agent.status),
    })


_PDF_CSS = """
* { font-family: sans-serif; }
body { color: #1f2937; line-height: 1.5; }
h1 { font-size: 22pt; color: #4c1d95; margin-top: 20pt; margin-bottom: 8pt;
     border-bottom: 1pt solid #6d28d9; padding-bottom: 4pt; }
h2 { font-size: 16pt; color: #5b21b6; margin-top: 14pt; margin-bottom: 5pt; }
h3 { font-size: 13pt; color: #6d28d9; margin-top: 12pt; margin-bottom: 4pt; }
h4 { font-size: 11pt; color: #7c3aed; margin-top: 10pt; margin-bottom: 3pt; }
p  { font-size: 10.5pt; margin: 4pt 0; }
ul, ol { margin: 4pt 0 4pt 16pt; padding-left: 4pt; }
li { font-size: 10.5pt; margin: 2pt 0; }
table { border-collapse: collapse; margin: 8pt 0; width: 100%; }
th { background-color: #ede9fe; color: #4c1d95;
     border: 0.5pt solid #c4b5fd; padding: 4pt 6pt;
     font-size: 9.5pt; text-align: left; font-weight: bold; }
td { border: 0.5pt solid #e5e7eb; padding: 4pt 6pt;
     font-size: 9.5pt; vertical-align: top; color: #1f2937; }
code { background-color: #f3f4f6; color: #be185d;
       font-family: monospace; font-size: 9.5pt;
       padding: 1pt 3pt; border-radius: 2pt; }
pre { background-color: #1f2937; color: #f9fafb;
      padding: 8pt; font-family: monospace; font-size: 9pt;
      margin: 6pt 0; border-radius: 2pt; }
pre code { background: transparent; color: #f9fafb; padding: 0; }
blockquote { border-left: 2pt solid #c4b5fd;
             padding-left: 8pt; margin: 6pt 0;
             color: #4b5563; font-style: italic; }
b, strong { color: #111827; font-weight: bold; }
i, em { font-style: italic; }
a { color: #4f46e5; text-decoration: underline; }
hr { border: 0; border-top: 0.5pt solid #d1d5db; margin: 8pt 0; }
.cover { text-align: center; padding: 60pt 20pt 30pt 20pt; }
.cover-title { color: #4c1d95; font-size: 30pt; font-weight: bold;
               margin-bottom: 12pt; border: none; padding: 0; }
.cover-sub { color: #6d28d9; font-size: 13pt;
             font-style: italic; margin-bottom: 24pt; }
.cover-meta { color: #6b7280; font-size: 10pt; margin: 3pt 0; }
.divider { border-top: 1pt solid #c4b5fd; margin: 16pt 0; }
.msg-meta { color: #7c3aed; font-size: 9pt; margin: 12pt 0 2pt 0;
            text-transform: uppercase; letter-spacing: 0.6pt;
            font-weight: bold; }
.msg-user { background-color: #f5f3ff;
            padding: 8pt 10pt; margin: 4pt 0 8pt 0;
            border-left: 2pt solid #7c3aed; border-radius: 2pt; }
.msg-asst { background-color: #ffffff;
            padding: 8pt 10pt; margin: 4pt 0 8pt 0;
            border: 0.5pt solid #e5e7eb; border-radius: 2pt; }
.msg-user p, .msg-asst p { margin: 3pt 0; }
"""


def _md_to_html(md: str) -> str:
    """Convert the analyst's markdown output to HTML for the PDF renderer."""
    import re
    import html as html_lib

    def render_inline(s: str) -> str:
        s = html_lib.escape(s)
        # Inline code first so its contents aren't reinterpreted.
        s = re.sub(r"`([^`]+?)`", r"<code>\1</code>", s)
        # Bold then italic. The negative lookbehind/ahead on italics
        # keeps `**bold**` from being mis-detected.
        s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
        s = re.sub(r"__(.+?)__", r"<b>\1</b>", s)
        s = re.sub(r"(?<!\*)\*([^*\n]+?)\*(?!\*)", r"<i>\1</i>", s)
        s = re.sub(r"(?<!_)_([^_\n]+?)_(?!_)", r"<i>\1</i>", s)
        s = re.sub(r"~~(.+?)~~", r"<s>\1</s>", s)
        s = re.sub(r"\[([^\]]+?)\]\(([^)]+?)\)", r'<a href="\2">\1</a>', s)
        return s

    out: list[str] = []
    in_list: str | None = None
    in_table = False
    table_rows: list[list[str]] = []
    in_code = False
    code_lang = ""
    code_buf: list[str] = []

    def flush_list() -> None:
        nonlocal in_list
        if in_list:
            out.append(f"</{in_list}>")
            in_list = None

    def flush_table() -> None:
        nonlocal in_table, table_rows
        if not table_rows:
            in_table = False
            table_rows = []
            return
        out.append("<table>")
        out.append("<tr>")
        for c in table_rows[0]:
            out.append(f"<th>{render_inline(c)}</th>")
        out.append("</tr>")
        for row in table_rows[1:]:
            out.append("<tr>")
            for c in row:
                out.append(f"<td>{render_inline(c)}</td>")
            out.append("</tr>")
        out.append("</table>")
        in_table = False
        table_rows = []

    lines = (md or "").split("\n")
    i = 0
    while i < len(lines):
        ln = lines[i]
        stripped = ln.strip()

        # Fenced code block
        if stripped.startswith("```"):
            if in_code:
                flush_list()
                flush_table()
                out.append(f'<pre><code class="lang-{html_lib.escape(code_lang)}">'
                           f'{html_lib.escape(chr(10).join(code_buf))}</code></pre>')
                code_buf = []
                code_lang = ""
                in_code = False
            else:
                flush_list()
                flush_table()
                code_lang = stripped[3:].strip()
                in_code = True
            i += 1
            continue
        if in_code:
            code_buf.append(ln)
            i += 1
            continue

        # GFM table row (and the alignment row)
        if stripped.startswith("|") and stripped.endswith("|") and len(stripped) > 2:
            flush_list()
            cells = [c.strip() for c in stripped[1:-1].split("|")]
            if not all(re.match(r"^:?-+:?$", c) for c in cells):
                table_rows.append(cells)
            in_table = True
            i += 1
            continue
        if in_table:
            flush_table()

        # Heading
        m = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if m:
            flush_list()
            level = len(m.group(1))
            out.append(f"<h{level}>{render_inline(m.group(2))}</h{level}>")
            i += 1
            continue

        # Unordered list
        m = re.match(r"^[-*]\s+(.+)$", stripped)
        if m:
            if in_list != "ul":
                flush_list()
                out.append("<ul>")
                in_list = "ul"
            out.append(f"<li>{render_inline(m.group(1))}</li>")
            i += 1
            continue

        # Ordered list
        m = re.match(r"^\d+\.\s+(.+)$", stripped)
        if m:
            if in_list != "ol":
                flush_list()
                out.append("<ol>")
                in_list = "ol"
            out.append(f"<li>{render_inline(m.group(1))}</li>")
            i += 1
            continue

        # Blockquote
        if stripped.startswith(">"):
            flush_list()
            out.append(f"<blockquote>{render_inline(stripped.lstrip('>').strip())}</blockquote>")
            i += 1
            continue

        # Horizontal rule
        if re.match(r"^(\*\*\*+|---+|___+)$", stripped):
            flush_list()
            out.append("<hr/>")
            i += 1
            continue

        # Empty line
        if stripped == "":
            flush_list()
            i += 1
            continue

        # Paragraph
        flush_list()
        out.append(f"<p>{render_inline(stripped)}</p>")
        i += 1

    flush_list()
    flush_table()
    if in_code and code_buf:
        out.append(f"<pre><code>{html_lib.escape(chr(10).join(code_buf))}</code></pre>")
    return "\n".join(out)


def _safe_filename(s: str) -> str:
    """Make a thread title safe for a `Content-Disposition` filename."""
    import re
    s = re.sub(r"[^A-Za-z0-9._\- ]+", "", s).strip().replace(" ", "_")
    return (s or "bpm-analysis")[:80]


@router.post("/threads/{thread_id}/export-pdf")
async def export_thread_pdf(
    thread_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Render the full BPM thread as a beautifully formatted PDF."""
    try:
        cid = uuid.UUID(thread_id)
    except ValueError:
        return error("Invalid thread id", 400)

    conv = (await db.execute(select(Conversation).where(Conversation.id == cid))).scalar_one_or_none()
    if not conv or conv.tenant_id != user.tenant_id:
        return error("Thread not found", 404)

    msgs = (await db.execute(
        select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at)
    )).scalars().all()

    import html as html_lib

    parts: list[str] = []
    parts.append('<div class="cover">')
    parts.append(f'<div class="cover-title">{html_lib.escape(conv.title or "BPM Analysis")}</div>')
    parts.append('<div class="cover-sub">Detailed Agentification Report</div>')
    parts.append(f'<div class="cover-meta">Generated by Abenix BPM Process Analyst</div>')
    parts.append(f'<div class="cover-meta">{datetime.now(timezone.utc).strftime("%B %d, %Y")}</div>')
    parts.append(f'<div class="cover-meta">{conv.message_count or 0} messages · ${float(conv.total_cost or 0):.4f} run cost</div>')
    if conv.model_used:
        parts.append(f'<div class="cover-meta">Model: {html_lib.escape(conv.model_used)}</div>')
    parts.append('</div>')
    parts.append('<div class="divider"></div>')

    for m in msgs:
        if m.role == "user":
            parts.append('<div class="msg-meta">User</div>')
            parts.append(f'<div class="msg-user">{_md_to_html(m.content or "")}</div>')
        else:
            label = "BPM Analyst"
            if m.model_used:
                label += f" · {html_lib.escape(m.model_used)}"
            parts.append(f'<div class="msg-meta">{label}</div>')
            parts.append(f'<div class="msg-asst">{_md_to_html(m.content or "")}</div>')

    full_html = (
        '<!DOCTYPE html><html><head><meta charset="utf-8"/></head>'
        f'<body>{"".join(parts)}</body></html>'
    )

    try:
        import fitz  # PyMuPDF
    except ImportError:
        return error("PyMuPDF not installed on this pod", 503)

    buf = io.BytesIO()
    try:
        story = fitz.Story(html=full_html, user_css=_PDF_CSS)
        writer = fitz.DocumentWriter(buf)
        mediabox = fitz.paper_rect("A4")
        where = mediabox + (40, 40, -40, -40)
        more = 1
        page_count = 0
        while more:
            dev = writer.begin_page(mediabox)
            more, _ = story.place(where)
            story.draw(dev)
            writer.end_page()
            page_count += 1
            if page_count > 300:  # safety net for runaway content
                break
        writer.close()
    except Exception as e:
        logger.exception("BPM PDF export failed")
        return error(f"PDF rendering failed: {e}", 500)

    pdf_bytes = buf.getvalue()
    fname = _safe_filename(conv.title or "bpm-analysis") + ".pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.delete("/threads/{thread_id}")
async def delete_thread(
    thread_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    try:
        cid = uuid.UUID(thread_id)
    except ValueError:
        return error("Invalid thread id", 400)
    conv = (await db.execute(select(Conversation).where(Conversation.id == cid))).scalar_one_or_none()
    if not conv or conv.tenant_id != user.tenant_id:
        return error("Thread not found", 404)
    await db.delete(conv)
    await db.commit()
    return success({"deleted": True})
