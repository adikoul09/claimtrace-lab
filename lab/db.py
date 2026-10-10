"""Supabase access for the Python side (service role). Settings come from the process environment, then the
repo-root .env. The .env is read into a dict, never into os.environ, so child processes cannot inherit keys."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from supabase import Client, create_client

ROOT = Path(__file__).resolve().parents[1]


@lru_cache(maxsize=1)
def _dotenv() -> dict[str, str]:
    path = ROOT / ".env"
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip().removeprefix("export ").strip()] = v.strip().strip('"').strip("'")
    return out


def setting(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name) or _dotenv().get(name) or default


def client() -> Client:
    """A new service-role client. Use one per thread."""
    url, key = setting("SUPABASE_URL"), setting("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set (env or .env)")
    return create_client(url, key)


def emit(db: Client, type: str, message: str, reason: str, *, project_id=None, agent_id=None, task_id=None,
         data: dict | None = None) -> dict:
    """Write an events row. Every decision has a reason (CLAUDE.md); the schema rejects empty ones."""
    if not message or not reason:
        raise ValueError("events need a non-empty message and reason")
    row = {"type": type, "message": message, "reason": reason, "project_id": project_id, "agent_id": agent_id,
           "task_id": task_id, "data": data or {}}
    return db.table("events").insert(row).execute().data[0]
