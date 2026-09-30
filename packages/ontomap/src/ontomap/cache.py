"""On-disk cache, keyed by the request.

Every response any remote service gives us is written here. Three reasons, and
the third is the one that matters: re-runs are free, the run is auditable after
the fact, and evidence an agent cited in its rationale can still be checked
weeks later. A judgement whose basis cannot be re-read is not reviewable.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

DEFAULT_DIR = Path(os.environ.get("ONTOMAP_CACHE", Path.home() / ".cache" / "ontomap"))


def _key(namespace: str, payload: str) -> str:
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:40]
    return f"{namespace}-{digest}"


class Cache:
    def __init__(self, directory: Path | str | None = None, *, enabled: bool = True):
        self.dir = Path(directory) if directory is not None else DEFAULT_DIR
        self.enabled = enabled
        if self.enabled:
            self.dir.mkdir(parents=True, exist_ok=True)

    def path_for(self, namespace: str, payload: str) -> Path:
        return self.dir / f"{_key(namespace, payload)}.json"

    def get(self, namespace: str, payload: str) -> Any | None:
        if not self.enabled:
            return None
        path = self.path_for(namespace, payload)
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))["response"]
        except (ValueError, KeyError):
            # A truncated write from an interrupted run. Refetch rather than
            # fail: a corrupt cache entry must never be able to stop a pipeline.
            return None

    def put(self, namespace: str, payload: str, response: Any) -> None:
        if not self.enabled:
            return
        path = self.path_for(namespace, payload)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps({"request": payload, "response": response}, indent=1),
            encoding="utf-8",
        )
        tmp.replace(path)  # atomic, so an interrupted run leaves no half-file
