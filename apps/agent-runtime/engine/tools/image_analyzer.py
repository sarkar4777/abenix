"""Image Analysis Tool — AI-powered image understanding via Claude Vision or OpenAI"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any

from engine.tools.base import BaseTool, ToolResult


class ImageAnalyzerTool(BaseTool):
    name = "image_analyzer"
    description = (
        "Analyze images using AI vision models. Capabilities: describe content, "
        "extract text (OCR), read charts/graphs, detect objects, analyze diagrams, "
        "compare images. Supports URLs and local file paths."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "image_url": {
                "type": "string",
                "description": "URL or local file path to the image (PNG, JPG, GIF, WebP)",
            },
            "operation": {
                "type": "string",
                "enum": ["describe", "ocr", "chart_data", "objects", "diagram", "compare", "question"],
                "description": "Type of analysis to perform",
                "default": "describe",
            },
            "question": {
                "type": "string",
                "description": "Specific question to answer about the image",
            },
            "compare_url": {
                "type": "string",
                "description": "Second image URL for comparison (only for 'compare' operation)",
            },
        },
        "required": ["image_url"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        image_url = arguments.get("image_url", "")
        operation = arguments.get("operation", "describe")
        question = arguments.get("question", "")
        compare_url = arguments.get("compare_url", "")

        if not image_url:
            return ToolResult(content="Error: image_url is required", is_error=True)

        # Build the prompt based on operation
        prompts = {
            "describe": "Describe this image in detail. Include: main subjects, colors, composition, text visible, and overall context.",
            "ocr": "Extract ALL text visible in this image. Return the text exactly as it appears, preserving layout where possible. If no text is found, say so.",
            "chart_data": "This image contains a chart or graph. Extract the data: identify the chart type, axes labels, data series, and all data points. Return as structured data.",
            "objects": "Identify and list all distinct objects in this image. For each object, provide: name, approximate position (top-left, center, etc.), size relative to image, and any notable attributes.",
            "diagram": "This image contains a diagram, flowchart, or architectural drawing. Describe the structure: nodes/boxes, connections/arrows, labels, and the overall flow or hierarchy.",
            "compare": "Compare these two images. Describe: similarities, differences, changes between them, and which elements are added/removed/modified.",
            "question": question or "What do you see in this image?",
        }

        prompt = prompts.get(operation, prompts["describe"])
        if question and operation != "question":
            prompt += f"\n\nAlso answer this specific question: {question}"

        # Try Claude Vision first, then OpenAI
        result = await self._analyze_with_claude(image_url, prompt, compare_url)
        if result:
            return ToolResult(content=json.dumps({
                "status": "success",
                "operation": operation,
                "analysis": result,
                "model": "claude-vision",
            }))

        result = await self._analyze_with_openai(image_url, prompt, compare_url)
        if result:
            return ToolResult(content=json.dumps({
                "status": "success",
                "operation": operation,
                "analysis": result,
                "model": "openai-vision",
            }))

        return ToolResult(
            content="Error: No vision API available. Set ANTHROPIC_API_KEY or OPENAI_API_KEY.",
            is_error=True,
        )

    async def _load_image_base64(self, url: str) -> tuple[str, str] | None:
        """Load image as base64. Returns (base64_data, media_type) or None."""
        try:
            if url.startswith(("http://", "https://")):
                import httpx
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.get(url)
                    if resp.status_code != 200:
                        return None
                    content_type = resp.headers.get("content-type", "image/png")
                    media_type = content_type.split(";")[0].strip()
                    return base64.b64encode(resp.content).decode(), media_type
            else:
                # Local file
                path = Path(url)
                if not path.exists():
                    return None
                ext = path.suffix.lower()
                media_types = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}
                media_type = media_types.get(ext, "image/png")
                data = base64.b64encode(path.read_bytes()).decode()
                return data, media_type
        except Exception:
            return None

    async def _analyze_with_claude(self, image_url: str, prompt: str, compare_url: str = "") -> str | None:
        """Analyze image using Anthropic Claude Vision API."""
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            return None

        try:
            import anthropic
            client = anthropic.AsyncAnthropic(api_key=api_key)

            content: list[dict[str, Any]] = []

            # Load primary image
            img = await self._load_image_base64(image_url)
            if not img:
                return None
            b64_data, media_type = img

            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": media_type, "data": b64_data},
            })

            # Load comparison image if provided
            if compare_url:
                img2 = await self._load_image_base64(compare_url)
                if img2:
                    b64_2, mt_2 = img2
                    content.append({
                        "type": "image",
                        "source": {"type": "base64", "media_type": mt_2, "data": b64_2},
                    })

            content.append({"type": "text", "text": prompt})

            resp = await client.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=4096,
                messages=[{"role": "user", "content": content}],
            )

            return resp.content[0].text if resp.content else None

        except Exception as e:
            return None

    async def _analyze_with_openai(self, image_url: str, prompt: str, compare_url: str = "") -> str | None:
        """Analyze image using OpenAI Vision API."""
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            return None

        try:
            import openai
            client = openai.AsyncOpenAI(api_key=api_key)

            content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]

            # For URLs, pass directly. For local files, convert to base64.
            if image_url.startswith(("http://", "https://")):
                content.append({"type": "image_url", "image_url": {"url": image_url}})
            else:
                img = await self._load_image_base64(image_url)
                if not img:
                    return None
                b64_data, media_type = img
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{media_type};base64,{b64_data}"},
                })

            if compare_url:
                if compare_url.startswith(("http://", "https://")):
                    content.append({"type": "image_url", "image_url": {"url": compare_url}})

            resp = await client.chat.completions.create(
                model="gpt-4o",
                max_tokens=4096,
                messages=[{"role": "user", "content": content}],
            )

            return resp.choices[0].message.content if resp.choices else None

        except Exception:
            return None
