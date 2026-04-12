"""Open Brain MCP integration for the weekly schedule generator.

Connects to the Open Brain MCP server (Supabase Edge Function) via
StreamableHTTP transport to fetch recent thoughts and search for
content relevant to the upcoming week.
"""

from __future__ import annotations

import asyncio
import datetime
import os
import re
from typing import Any


async def _fetch_all(mcp_url: str, week_monday: datetime.date) -> list[Any]:
    """Connect once and run all Open Brain queries in a single session."""
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    week_end = week_monday + datetime.timedelta(days=6)
    week_label = f"{week_monday.strftime('%B %d')} - {week_end.strftime('%B %d, %Y')}"

    results = []
    async with streamablehttp_client(mcp_url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            # Query 1: Recent thoughts (last 7 days)
            try:
                result = await session.call_tool("list_thoughts", {"days": 7, "limit": 20})
                results.append(result)
            except Exception as exc:
                print(f"  Warning: list_thoughts failed: {exc}")

            # Query 2+: Semantic searches for upcoming week content
            search_queries = [
                f"week of {week_label}",
                "meal plan dinner recipes",
                "schedule changes travel visitors events",
            ]
            for query in search_queries:
                try:
                    result = await session.call_tool(
                        "search_thoughts", {"query": query, "limit": 10}
                    )
                    results.append(result)
                except Exception as exc:
                    print(f"  Warning: search '{query}' failed: {exc}")

    return results


def _parse_thoughts(result: Any) -> list[dict]:
    """Extract individual thoughts from an MCP tool result.

    Handles two Open Brain response formats:

    list_thoughts format:
        7 recent thought(s):
        1. [4/11/2026] (task - topics)
           Content here...

    search_thoughts format:
        Found 1 thought(s):
        --- Result 1 (52.6% match) ---
        Captured: 4/11/2026
        Type: task
        Topics: meal planning
        Content here...
    """
    thoughts = []
    if not result or not hasattr(result, "content"):
        return thoughts

    for block in result.content:
        if not hasattr(block, "text"):
            continue
        text = block.text.strip()

        if "--- Result" in text:
            # search_thoughts format: split on "--- Result N ---"
            parts = re.split(r'---\s*Result\s+\d+\s*\([^)]*\)\s*---', text)
            for part in parts:
                part = part.strip()
                if not part or re.match(r'(?:Found|No)\s+\d*\s*thought', part, re.IGNORECASE):
                    continue
                # Extract content after metadata lines (Captured/Type/Topics/People/Actions)
                lines = part.split("\n")
                content_lines = []
                for line in lines:
                    line = line.strip()
                    if not line:
                        continue
                    if re.match(r'^(Captured|Type|Topics|People|Actions):', line):
                        continue
                    content_lines.append(line)
                if content_lines:
                    thoughts.append({"text": "\n".join(content_lines)})
        else:
            # list_thoughts format: split on "1. ", "2. ", etc.
            parts = re.split(r'(?:^|\n)\d+\.\s+', text)
            for part in parts:
                part = part.strip()
                if not part or re.match(r'^\d+\s+(recent\s+)?thought', part, re.IGNORECASE):
                    continue
                if "no thoughts" in part.lower() or "no results" in part.lower():
                    continue
                thoughts.append({"text": part})

    return thoughts


def fetch_open_brain_notes(week_monday: datetime.date) -> list[dict]:
    """Fetch relevant thoughts from Open Brain for the upcoming week.

    Uses a single MCP session to run all queries:
      1. list_thoughts — everything captured in the last 7 days
      2. search_thoughts — semantic searches for upcoming week content

    Returns a deduplicated list of thought dicts with 'text' keys.
    """
    mcp_url = os.getenv("OPEN_BRAIN_MCP_URL")
    if not mcp_url:
        return []

    all_thoughts: list[dict] = []
    seen_texts: set[str] = set()

    def _content_key(text: str) -> str:
        """Extract a dedup key by stripping metadata prefix."""
        # Remove "[date] (type - topics)\n   " prefix from list_thoughts format
        stripped = re.sub(r'^\[[\d/]+\]\s*\([^)]*\)\s*', '', text).strip()
        return stripped[:100]

    def add_unique(thoughts: list[dict]) -> None:
        for t in thoughts:
            text = t.get("text", "").strip()
            if not text:
                continue
            key = _content_key(text)
            if key not in seen_texts:
                seen_texts.add(key)
                all_thoughts.append(t)

    results = asyncio.run(_fetch_all(mcp_url, week_monday))
    for result in results:
        add_unique(_parse_thoughts(result))

    # Filter out thoughts that are about the schedule generator itself
    # (meta/technical notes, not actual family schedule content)
    filtered = [
        t for t in all_thoughts
        if not _is_meta_note(t["text"])
    ]

    return filtered


def _is_meta_note(text: str) -> bool:
    """Check if a thought is about the schedule tool itself rather than family life."""
    meta_patterns = [
        r"Weekly Schedule Generator",
        r"testing status and next steps",
        r"technical architecture",
        r"household context for the .* family",  # system dump, not a real note
        r"Phase \d+ MVP",
        r"weekly schedule generator config",
        r"Share .* work calendar",
        r"Install launchd plist",
        r"Set recurring Sunday.*phone alarm",
        r"Test with different weeks",
        r"Validate output against",
    ]
    for pattern in meta_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


def display_open_brain_notes(thoughts: list[dict]) -> None:
    """Print Open Brain thoughts for the user to review."""
    if not thoughts:
        print("\n  No recent Open Brain notes found.")
        return
    print(f"\n  Open Brain notes ({len(thoughts)} found):")
    for i, t in enumerate(thoughts, 1):
        # Truncate long thoughts for display
        text = t["text"]
        if len(text) > 200:
            text = text[:200] + "..."
        # Indent and number
        lines = text.split("\n")
        print(f"    {i}. {lines[0]}")
        for line in lines[1:]:
            print(f"       {line}")


def format_open_brain_for_prompt(thoughts: list[dict]) -> str:
    """Format Open Brain thoughts as a prompt section."""
    if not thoughts:
        return "OPEN BRAIN NOTES: None found.\n"
    parts = ["OPEN BRAIN NOTES (recent captures from your personal knowledge base):"]
    for t in thoughts:
        parts.append(f"  - {t['text']}")
    parts.append("  Use these notes to inform dinner assignments, flag events, or add context to the schedule.")
    parts.append("")
    return "\n".join(parts)
