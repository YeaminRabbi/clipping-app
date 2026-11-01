"""Reading clip rows (with their per-aspect framing) into the shape the API returns."""

import json
import sqlite3
from typing import Any

DEFAULT_AUDIO = {"level": 100, "muted": False}


def audio_settings(row: sqlite3.Row) -> dict[str, Any]:
    """Normalized per-clip output audio settings from the extensible edit_json column."""
    raw = json.loads(row["edit_json"] or "{}").get("audio") or {}
    try:
        level = int(raw.get("level", DEFAULT_AUDIO["level"]))
    except (TypeError, ValueError):
        level = DEFAULT_AUDIO["level"]
    return {"level": min(200, max(0, level)), "muted": bool(raw.get("muted", False))}


def _formats(conn: sqlite3.Connection, clips: list[sqlite3.Row]) -> dict[int, dict[str, Any]]:
    if not clips:
        return {}
    ranges = {c["id"]: (c["start_ms"], c["end_ms"]) for c in clips}
    placeholders = ",".join("?" * len(ranges))
    rows = conn.execute(f"SELECT * FROM clip_formats WHERE clip_id IN ({placeholders})", list(ranges)).fetchall()
    out: dict[int, dict[str, Any]] = {}
    for r in rows:
        keyframes = json.loads(r["crop_keyframes_json"])
        options = json.loads(r["options_json"] or "{}")
        fmt: dict[str, Any] = {
            "id": r["id"],
            "mode": r["mode"],
            # Manual: one static crop. Smart: the tracked path (source times), and its first point as `crop`.
            "crop": {k: keyframes[0][k] for k in ("x", "y", "w", "h")} if keyframes else None,
            "options": options,
        }
        if r["mode"] == "smart":
            start, end = ranges[r["clip_id"]]
            fmt["keyframes"] = keyframes
            # The clip was extended past the tracked part (or never tracked): needs tracking again.
            fmt["stale"] = not (len(keyframes) >= 2 and keyframes[0]["t"] <= start and keyframes[-1]["t"] >= end)
        out.setdefault(r["clip_id"], {})[r["aspect"]] = fmt
    return out


def _to_dict(row: sqlite3.Row, formats: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "source_id": row["source_id"],
        "start_ms": row["start_ms"],
        "end_ms": row["end_ms"],
        "title": row["title"],
        "status": row["status"],
        "score": row["score"],
        "reasons": json.loads(row["score_reasons_json"] or "[]"),
        "tighten": json.loads(row["edit_json"] or "{}").get("tighten"),
        "audio": audio_settings(row),
        "sort_order": row["sort_order"],
        "formats": formats,
    }


def _many(conn: sqlite3.Connection, rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    formats = _formats(conn, rows)
    return [_to_dict(r, formats.get(r["id"], {})) for r in rows]


def get(conn: sqlite3.Connection, clip_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM clips WHERE id = ?", (clip_id,)).fetchone()
    return _many(conn, [row])[0] if row else None


def list_for_source(conn: sqlite3.Connection, source_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM clips WHERE source_id = ? ORDER BY start_ms, id", (source_id,)
    ).fetchall()
    return _many(conn, rows)


def list_for_project(conn: sqlite3.Connection, project_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT c.* FROM clips c JOIN sources s ON s.id = c.source_id
           WHERE s.project_id = ? ORDER BY s.id, c.start_ms, c.id""",
        (project_id,),
    ).fetchall()
    return _many(conn, rows)
