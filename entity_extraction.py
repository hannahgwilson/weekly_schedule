"""Drain the Open Brain entity_extraction_queue via the entity-extraction-worker.

Used by the web UI ("Process thoughts" button) for on-demand processing.
The nightly drain runs via pg_cron in Supabase — see supabase/sql/entity_drain.sql.

Both paths call the same Edge Function. This module just adds an HTTP-side loop
so a single click drains the queue rather than processing 3 thoughts and stopping.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse, parse_qs

import httpx


def _worker_url_and_key() -> tuple[str, str]:
    """Derive the worker URL + access key from OPEN_BRAIN_MCP_URL.

    OPEN_BRAIN_MCP_URL is shaped like:
      https://<ref>.supabase.co/functions/v1/open-brain-mcp?key=<KEY>

    The worker sits at the sibling path /entity-extraction-worker on the same
    host and uses the same MCP_ACCESS_KEY, so we reuse the parsed values.
    """
    mcp_url = os.getenv("OPEN_BRAIN_MCP_URL")
    if not mcp_url:
        raise RuntimeError("OPEN_BRAIN_MCP_URL not set in environment")

    parsed = urlparse(mcp_url)
    key_values = parse_qs(parsed.query).get("key", [])
    if not key_values:
        raise RuntimeError("OPEN_BRAIN_MCP_URL is missing the ?key=... access key")
    key = key_values[0]

    base = f"{parsed.scheme}://{parsed.netloc}"
    # Strip /open-brain-mcp -> /functions/v1, then append the worker name.
    path_parts = parsed.path.rstrip("/").split("/")
    if not path_parts or path_parts[-1] != "open-brain-mcp":
        raise RuntimeError(f"Unexpected OPEN_BRAIN_MCP_URL shape: {parsed.path!r}")
    worker_path = "/".join(path_parts[:-1] + ["entity-extraction-worker"])
    return f"{base}{worker_path}", key


def drain_entity_queue(
    max_iterations: int = 20,
    per_call_limit: int = 3,
    request_timeout_s: float = 180.0,
) -> dict:
    """Repeatedly invoke the worker until it reports an empty queue.

    Returns a totals dict — number of iterations actually run, plus summed
    processed/succeeded/failed/entities_created counts from the worker.
    """
    worker_url, key = _worker_url_and_key()

    totals = {
        "iterations": 0,
        "processed": 0,
        "succeeded": 0,
        "failed": 0,
        "entities_created": 0,
        "edges_created": 0,
        "stopped_reason": "queue_empty",
    }

    with httpx.Client(timeout=request_timeout_s) as client:
        for _ in range(max_iterations):
            totals["iterations"] += 1
            resp = client.post(
                worker_url,
                params={"limit": per_call_limit},
                headers={"x-brain-key": key},
            )
            resp.raise_for_status()
            data = resp.json()

            totals["processed"] += data.get("processed", 0) or 0
            totals["succeeded"] += data.get("succeeded", 0) or 0
            totals["failed"] += data.get("failed", 0) or 0
            totals["entities_created"] += data.get("entities_created", 0) or 0
            totals["edges_created"] += data.get("edges_created", 0) or 0

            if (data.get("processed", 0) or 0) == 0:
                break
            if data.get("truncated"):
                # Worker hit its wall-clock or call-cap — keep looping; it's
                # legitimate to call again, but record why we exited the loop.
                totals["stopped_reason"] = data.get("truncated_reason") or "truncated"
        else:
            totals["stopped_reason"] = "max_iterations"

    return totals
