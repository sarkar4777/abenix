"""Shared utilities for parsing Abenix agent responses."""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

_sdk_path = str(Path(__file__).resolve().parent.parent.parent / "sdk")
if _sdk_path not in sys.path:
    sys.path.insert(0, _sdk_path)

from abenix_sdk import Abenix, ActingSubject


def get_forge(user, timeout: float = 300.0) -> tuple[Abenix, ActingSubject]:
    """Create an Abenix client + ActingSubject for the given user."""
    api_key = os.environ["SAUDITOURISM_ABENIX_API_KEY"]
    forge = Abenix(
        api_key=api_key,
        base_url=os.environ.get("ABENIX_API_URL", "http://localhost:8000"),
        timeout=timeout,
    )
    subject = ActingSubject(
        subject_type="sauditourism",
        subject_id=str(user.id),
        email=user.email,
        display_name=user.full_name,
        metadata={"organization": getattr(user, 'organization', None)},
    )
    return forge, subject


def parse_agent_json(output: str) -> dict:
    """Robustly extract JSON from agent output."""
    if not output or not output.strip():
        return {"text": "Empty agent response"}

    # 1. Try direct parse first (agent returned pure JSON)
    stripped = output.strip()
    if stripped.startswith('{'):
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass

    # 2. Extract from ```json ... ``` code blocks
    json_blocks = re.findall(r'```(?:json)?\s*\n?(.*?)```', output, re.DOTALL)
    for block in sorted(json_blocks, key=len, reverse=True):  # try largest first
        block = block.strip()
        if block.startswith('{'):
            try:
                return json.loads(block)
            except json.JSONDecodeError:
                continue

    # 3. Find the largest {...} block in the text using brace matching
    best_json = None
    best_len = 0
    i = 0
    while i < len(output):
        if output[i] == '{':
            depth = 0
            start = i
            in_string = False
            escape = False
            for j in range(i, len(output)):
                c = output[j]
                if escape:
                    escape = False
                    continue
                if c == '\\' and in_string:
                    escape = True
                    continue
                if c == '"' and not escape:
                    in_string = not in_string
                    continue
                if in_string:
                    continue
                if c == '{':
                    depth += 1
                elif c == '}':
                    depth -= 1
                    if depth == 0:
                        candidate = output[start:j+1]
                        if len(candidate) > best_len:
                            try:
                                parsed = json.loads(candidate)
                                best_json = parsed
                                best_len = len(candidate)
                            except json.JSONDecodeError:
                                pass
                        break
            i = j + 1 if depth == 0 else i + 1
        else:
            i += 1

    if best_json is not None:
        return best_json

    # 4. Last resort — return as text
    return {"text": output}
