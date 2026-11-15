"""SQLite 持久化：run / sub_q / evidence / claim / report / span。"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS run (
    id          TEXT PRIMARY KEY,
    question    TEXT NOT NULL,
    status      TEXT NOT NULL,
    mode        TEXT NOT NULL,
    config_json TEXT,
    tokens_in   INTEGER DEFAULT 0,
    tokens_out  INTEGER DEFAULT 0,
    cost_cny    REAL DEFAULT 0,
    steps       INTEGER DEFAULT 0,
    started_at  TEXT,
    ended_at    TEXT,
    error       TEXT
);
CREATE TABLE IF NOT EXISTS sub_q (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id   TEXT NOT NULL,
    text     TEXT NOT NULL,
    status   TEXT NOT NULL DEFAULT 'pending',
    order_no INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS evidence (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       TEXT NOT NULL,
    sub_q_id     INTEGER,
    url          TEXT NOT NULL,
    title        TEXT,
    domain       TEXT,
    snippet      TEXT,
    content      TEXT,
    content_hash TEXT,
    credibility  REAL DEFAULT 0.5,
    fetched_at   TEXT
);
CREATE TABLE IF NOT EXISTS claim (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id            TEXT NOT NULL,
    text              TEXT,
    evidence_ids_json TEXT,
    support           TEXT
);
CREATE TABLE IF NOT EXISTS report (
    run_id         TEXT PRIMARY KEY,
    markdown       TEXT,
    citations_json TEXT,
    created_at     TEXT
);
CREATE TABLE IF NOT EXISTS span (
    id        TEXT PRIMARY KEY,
    run_id    TEXT NOT NULL,
    parent_id TEXT,
    name      TEXT,
    kind      TEXT,
    ts_start  TEXT,
    ts_end    TEXT,
    dur_ms    INTEGER,
    tokens_in INTEGER DEFAULT 0,
    tokens_out INTEGER DEFAULT 0,
    cost_cny  REAL DEFAULT 0,
    status    TEXT,
    attrs     TEXT,
    error     TEXT
);
CREATE INDEX IF NOT EXISTS idx_evidence_run ON evidence(run_id);
CREATE INDEX IF NOT EXISTS idx_span_run ON span(run_id);
"""


class Store:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # ---------- run ----------
    def create_run(self, run_id: str, question: str, mode: str, config: dict[str, Any], started_at: str) -> None:
        self.conn.execute(
            "INSERT INTO run (id, question, status, mode, config_json, started_at) VALUES (?,?,?,?,?,?)",
            (run_id, question, "running", mode, json.dumps(config, ensure_ascii=False), started_at),
        )
        self.conn.commit()

    def finish_run(
        self,
        run_id: str,
        status: str,
        ended_at: str,
        tokens_in: int = 0,
        tokens_out: int = 0,
        cost_cny: float = 0.0,
        steps: int = 0,
        error: str | None = None,
    ) -> None:
        self.conn.execute(
            "UPDATE run SET status=?, ended_at=?, tokens_in=?, tokens_out=?, cost_cny=?, steps=?, error=? WHERE id=?",
            (status, ended_at, tokens_in, tokens_out, cost_cny, steps, error, run_id),
        )
        self.conn.commit()

    # ---------- sub_q ----------
    def add_subq(self, run_id: str, text: str, order_no: int) -> int:
        cur = self.conn.execute(
            "INSERT INTO sub_q (run_id, text, status, order_no) VALUES (?,?,?,?)",
            (run_id, text, "pending", order_no),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def set_subq_status(self, sub_q_id: int, status: str) -> None:
        self.conn.execute("UPDATE sub_q SET status=? WHERE id=?", (status, sub_q_id))
        self.conn.commit()

    def list_subqs(self, run_id: str) -> list[sqlite3.Row]:
        return list(self.conn.execute("SELECT * FROM sub_q WHERE run_id=? ORDER BY order_no", (run_id,)))

    # ---------- evidence ----------
    def add_evidence(
        self,
        run_id: str,
        sub_q_id: int,
        url: str,
        title: str,
        domain: str,
        snippet: str,
        content: str,
        content_hash: str,
        credibility: float,
        fetched_at: str,
    ) -> int:
        cur = self.conn.execute(
            """INSERT INTO evidence
               (run_id, sub_q_id, url, title, domain, snippet, content, content_hash, credibility, fetched_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (run_id, sub_q_id, url, title, domain, snippet, content, content_hash, credibility, fetched_at),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def list_evidence(self, run_id: str) -> list[sqlite3.Row]:
        return list(self.conn.execute("SELECT * FROM evidence WHERE run_id=? ORDER BY id", (run_id,)))

    def count_evidence(self, run_id: str) -> int:
        row = self.conn.execute("SELECT COUNT(*) AS c FROM evidence WHERE run_id=?", (run_id,)).fetchone()
        return int(row["c"]) if row else 0

    def existing_hashes(self, run_id: str) -> set[str]:
        rows = self.conn.execute("SELECT content_hash FROM evidence WHERE run_id=?", (run_id,))
        return {r["content_hash"] for r in rows}

    # ---------- claim ----------
    def add_claim(self, run_id: str, text: str, evidence_ids: list[int], support: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO claim (run_id, text, evidence_ids_json, support) VALUES (?,?,?,?)",
            (run_id, text, json.dumps(evidence_ids), support),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def list_claims(self, run_id: str) -> list[sqlite3.Row]:
        return list(self.conn.execute("SELECT * FROM claim WHERE run_id=? ORDER BY id", (run_id,)))

    # ---------- report ----------
    def save_report(self, run_id: str, markdown: str, citations: list[dict], created_at: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO report (run_id, markdown, citations_json, created_at) VALUES (?,?,?,?)",
            (run_id, markdown, json.dumps(citations, ensure_ascii=False), created_at),
        )
        self.conn.commit()

    # ---------- span ----------
    def add_span(self, record: dict[str, Any]) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO span
               (id, run_id, parent_id, name, kind, ts_start, ts_end, dur_ms,
                tokens_in, tokens_out, cost_cny, status, attrs, error)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                record["id"],
                record["run_id"],
                record.get("parent_id"),
                record.get("name"),
                record.get("kind"),
                record.get("ts_start"),
                record.get("ts_end"),
                record.get("dur_ms", 0),
                record.get("tokens_in", 0),
                record.get("tokens_out", 0),
                record.get("cost_cny", 0.0),
                record.get("status", "ok"),
                json.dumps(record.get("attrs", {}), ensure_ascii=False),
                record.get("error"),
            ),
        )
        self.conn.commit()

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass
