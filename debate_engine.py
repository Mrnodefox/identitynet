"""
Real-world debate cases and optional LLM-enhanced argument generation.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

CASES_PATH = Path(__file__).parent / "data" / "debate_cases.json"
_cases_cache: Optional[List[Dict[str, Any]]] = None
_sessions: Dict[str, Dict[str, Any]] = {}


def load_cases() -> List[Dict[str, Any]]:
    global _cases_cache
    if _cases_cache is not None:
        return _cases_cache
    if not CASES_PATH.exists():
        _cases_cache = []
        return _cases_cache
    with open(CASES_PATH, encoding="utf-8") as f:
        data = json.load(f)
    _cases_cache = data.get("cases", [])
    return _cases_cache


def _enrich_case(case: Dict[str, Any]) -> Dict[str, Any]:
    opts = case.get("poll", {}).get("options", [])
    for i, opt in enumerate(opts):
        if "favors_side" not in opt:
            opt["favors_side"] = "proposer" if i % 2 == 0 else "responder"
    return case


def get_case(case_id: str) -> Optional[Dict[str, Any]]:
    for c in load_cases():
        if c["id"] == case_id:
            return _enrich_case(c)
    return None


def poll_option_favors_side(case: Dict[str, Any], option_id: str) -> str:
    for opt in case.get("poll", {}).get("options", []):
        if opt["id"] == option_id:
            return opt.get("favors_side", "neutral")
    return "neutral"


def list_cases_public() -> List[Dict[str, Any]]:
    return [
        {
            "id": c["id"],
            "title": c["title"],
            "category": c.get("category", "general"),
            "summary": c.get("summary", ""),
            "proposer_role": c.get("proposer_role", "Proposer"),
            "responder_role": c.get("responder_role", "Responder"),
        }
        for c in load_cases()
    ]


def _maybe_llm_rewrite(text: str, case: Dict[str, Any], role: str) -> str:
    """Optional OpenAI polish — falls back to template text."""
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return text
    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model=os.getenv("DEBATE_LLM_MODEL", "gpt-4o-mini"),
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an agent in IdentityNet Agent Parliament. "
                        "Rewrite the argument in 2-3 sentences, formal parliamentary tone, "
                        "same legal position, no slurs, no graphic violence."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Case: {case['title']}\nRole: {role}\nDraft:\n{text}",
                },
            ],
            max_tokens=280,
            temperature=0.7,
        )
        out = (resp.choices[0].message.content or "").strip()
        return out if out else text
    except Exception as e:
        logger.debug("LLM debate rewrite skipped: %s", e)
        return text


def build_transcript_lines(case: Dict[str, Any], use_llm: bool = False) -> List[Dict[str, str]]:
    """Ordered lines for UI playback from case phases."""
    lines: List[Dict[str, str]] = []
    phases = case.get("phases", {})
    order = ["offer", "counter", "accept", "deliver", "poll_prompt"]

    for phase_key in order:
        phase = phases.get(phase_key, {})
        for key in ("proposer", "responder", "clerk"):
            text = phase.get(key)
            if not text:
                continue
            side = "clerk" if key == "clerk" else key
            speaker = case.get(f"{key}_role") if key != "clerk" else "Clerk of the Chamber"
            if key == "proposer":
                speaker = case.get("proposer_role", "Proposer")
            elif key == "responder":
                speaker = case.get("responder_role", "Responder")
            if use_llm and side != "clerk":
                text = _maybe_llm_rewrite(text, case, speaker)
            lines.append({"side": side, "speaker": speaker, "text": text, "phase": phase_key})

    return lines


def get_poll_from_case(case: Dict[str, Any]) -> Dict[str, Any]:
    poll = case.get("poll", {})
    return {
        "question": poll.get("question", "How should the chamber rule?"),
        "options": poll.get("options", []),
    }


def verdict_for_poll_option(case: Dict[str, Any], option_id: str) -> Dict[str, Any]:
    for opt in case.get("poll", {}).get("options", []):
        if opt["id"] == option_id:
            return {
                "title": opt.get("verdict_title", "Verdict recorded"),
                "steps": [
                    {"text": s, "api": "Chamber mandate — record in governance log"}
                    for s in opt.get("next_steps", [])
                ],
            }
    return {
        "title": "Verdict recorded",
        "steps": [{"text": "Clerk will record the citizen mandate.", "api": "GET /agents/debate/cases"}],
    }


def store_session(session_id: str, data: Dict[str, Any]) -> None:
    _sessions[session_id] = data
    if len(_sessions) > 200:
        oldest = sorted(_sessions.keys())[:50]
        for k in oldest:
            _sessions.pop(k, None)


def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    return _sessions.get(session_id)


def list_sessions(limit: int = 20) -> List[Dict[str, Any]]:
    items = list(_sessions.values())
    items.sort(key=lambda x: x.get("started_at", ""), reverse=True)
    return items[:limit]
