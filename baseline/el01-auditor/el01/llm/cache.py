"""The LLM cache: one JSON file per call under .cache/llm/<agent>/<key>.json, holding only real responses.

Cache key = sha256 of (agent name, prompt, schema, model alias, sha256 of each input), as MASTER_PROMPT section 5 says.
An input is anything the agent can read besides the prompt: a file's sha256, or a snapshot's git tree sha (which hashes
every file in it). The prompt text is stored next to the response, so a replayed call can be read and checked."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Optional


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(p: Path) -> str:
    return sha256_bytes(Path(p).read_bytes())


def cache_key(agent: str, prompt: str, schema: Optional[dict], model: str, inputs: dict[str, str]) -> str:
    """inputs: name -> sha256 (or git object id). Order-independent."""
    payload = json.dumps({"agent": agent, "prompt": prompt, "schema": schema, "model": model,
                          "inputs": sorted(inputs.items())}, sort_keys=True, ensure_ascii=False)
    return sha256_bytes(payload.encode("utf-8"))


class Cache:
    def __init__(self, root: Path):
        self.root = Path(root)

    def path(self, agent: str, key: str) -> Path:
        return self.root / agent / f"{key}.json"

    def get(self, agent: str, key: str) -> Optional[dict]:
        p = self.path(agent, key)
        return json.loads(p.read_text()) if p.exists() else None

    def put(self, agent: str, key: str, record: dict) -> Path:
        p = self.path(agent, key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(record, indent=1, ensure_ascii=False) + "\n")
        tmp.replace(p)
        return p
