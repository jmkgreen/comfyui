#!/usr/bin/env python3
"""Register legacy output assets as generated assets.

ComfyUI's asset scanner indexes files found under the output directory, but
files discovered from disk do not have a prompt/job id. The frontend's
generated-assets view expects output assets to have a job id, so old outputs can
be invisible there until they are generated again in the current process.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path


LEGACY_NAMESPACE = uuid.UUID("5a045ea2-7de1-4a08-bf52-2a8f4a7b4c71")


def log(message: str) -> None:
    print(f"[asset-backfill] {message}", flush=True)


def request_json(url: str, payload: dict | None = None, timeout: int = 10) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    method = "GET" if payload is None else "POST"
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def wait_for_assets_api(base_url: str, timeout: int) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            request_json(f"{base_url}/api/assets?limit=1", timeout=5)
            return
        except Exception as exc:
            last_error = exc
            time.sleep(2)
    raise RuntimeError(f"Assets API did not become ready: {last_error}")


def seed_outputs(base_url: str, timeout: int) -> None:
    deadline = time.monotonic() + timeout
    last_conflict = ""

    while time.monotonic() < deadline:
        try:
            result = request_json(
                f"{base_url}/api/assets/seed?wait=true",
                {"roots": ["output"]},
                timeout=max(5, int(deadline - time.monotonic())),
            )
            log(f"Output asset seed completed: {result}")
            return
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            if exc.code == 409:
                last_conflict = body
                log("Asset scan already running; waiting before output backfill.")
                time.sleep(5)
                continue
            raise RuntimeError(f"Output asset seed failed: HTTP {exc.code}: {body}") from exc

    raise RuntimeError(f"Timed out waiting for output asset seed; last conflict: {last_conflict}")


def backfill_job_ids(db_path: Path, output_dir: Path, retries: int) -> int:
    output_prefix = str(output_dir.resolve())
    if not output_prefix.endswith("/"):
        output_prefix += "/"

    for attempt in range(1, retries + 1):
        try:
            with sqlite3.connect(db_path, timeout=30) as con:
                cur = con.cursor()
                rows = cur.execute(
                    """
                    select ar.id, ar.file_path
                    from asset_references ar
                    join asset_reference_tags art on art.asset_reference_id = ar.id
                    where art.tag_name = 'output'
                      and ar.job_id is null
                      and ar.deleted_at is null
                      and ar.is_missing = 0
                      and ar.file_path like ?
                    """,
                    (output_prefix + "%",),
                ).fetchall()

                for ref_id, file_path in rows:
                    legacy_job_id = str(uuid.uuid5(LEGACY_NAMESPACE, file_path))
                    cur.execute(
                        """
                        update asset_references
                        set job_id = ?, updated_at = CURRENT_TIMESTAMP
                        where id = ? and job_id is null
                        """,
                        (legacy_job_id, ref_id),
                    )
                con.commit()
                return len(rows)
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower() or attempt == retries:
                raise
            time.sleep(2)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default="8188")
    parser.add_argument("--user-dir", default="/workspace/user")
    parser.add_argument("--output-dir", default="/workspace/output")
    parser.add_argument("--api-timeout", type=int, default=300)
    parser.add_argument("--seed-timeout", type=int, default=900)
    parser.add_argument("--db-retries", type=int, default=30)
    args = parser.parse_args()

    base_url = f"http://{args.host}:{args.port}"
    db_path = Path(args.user_dir) / "comfyui.db"

    wait_for_assets_api(base_url, args.api_timeout)
    seed_outputs(base_url, args.seed_timeout)
    count = backfill_job_ids(db_path, Path(args.output_dir), args.db_retries)
    log(f"Backfilled legacy output job ids: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
