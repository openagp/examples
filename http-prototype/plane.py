"""AGP Plane — the customer's governance control plane.

A FastAPI server that:
  - Receives signed events at POST /agp/v0/events  (Flow A)
  - Receives signed policies at POST /agp/v0/policy (Flow B)
  - Persists events into a hash-chained SQLite ledger
  - Verifies every signature against a known set of public keys
  - Surfaces a live HTML dashboard at /

In production: the registry of public keys would come from openagp/registry
(GitOps), not a hardcoded dict. The ledger would be Postgres with a real
hash-chain commit-or-rollback discipline. This file is small enough to
read end-to-end in one sitting — that's the point.

Run:  uvicorn plane:app --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from openagp import InvalidSignature, SchemaValidationError, verify
from openagp._canonical import canonicalize

from shared_keys import REGISTERED_PUBLIC_KEYS

DB_PATH = Path(__file__).parent / "ledger.db"
GENESIS = "sha256:" + "0" * 64

app = FastAPI(title="AGP Plane (prototype)", version="0.0.1")


# === SQLite ledger ===========================================================

def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, isolation_level=None)  # autocommit
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _init_db() -> None:
    with _connect() as c:
        c.execute("""
        CREATE TABLE IF NOT EXISTS events (
          row_id            INTEGER PRIMARY KEY AUTOINCREMENT,
          event_id          TEXT UNIQUE NOT NULL,
          occurred_at       TEXT NOT NULL,
          anchored_at       TEXT NOT NULL,
          vendor            TEXT NOT NULL,
          agent_id          TEXT NOT NULL,
          action_type       TEXT NOT NULL,
          tool_name         TEXT,
          target_resource   TEXT,
          decision          TEXT,
          rule_id           TEXT,
          policy_hash       TEXT,
          rationale         TEXT,
          raw_event         TEXT NOT NULL,
          event_hash        TEXT NOT NULL,
          prev_chain_hash   TEXT NOT NULL,
          chain_hash        TEXT NOT NULL UNIQUE,
          signature_ok      INTEGER NOT NULL
        )
        """)
        c.execute("""
        CREATE TABLE IF NOT EXISTS active_policies (
          policy_id    TEXT PRIMARY KEY,
          policy_hash  TEXT NOT NULL,
          issuer       TEXT NOT NULL,
          received_at  TEXT NOT NULL,
          raw_policy   TEXT NOT NULL,
          signature_ok INTEGER NOT NULL
        )
        """)


_init_db()


@contextmanager
def db():
    conn = _connect()
    try:
        yield conn
    finally:
        conn.close()


def _last_chain_hash(conn: sqlite3.Connection) -> str:
    row = conn.execute(
        "SELECT chain_hash FROM events ORDER BY row_id DESC LIMIT 1"
    ).fetchone()
    return row["chain_hash"] if row else GENESIS


# === Endpoints ===============================================================

@app.post("/agp/v0/events")
async def receive_event(request: Request) -> JSONResponse:
    """Flow A — vendor pushes a signed canonical event."""
    raw_bytes = await request.body()
    try:
        event = json.loads(raw_bytes)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid JSON")

    sig_obj = event.get("signature") or {}
    key_id = sig_obj.get("key_id")
    public_key = REGISTERED_PUBLIC_KEYS.get(key_id)
    if not public_key:
        raise HTTPException(status_code=403, detail=f"unknown key_id {key_id!r}")

    # Verify; if it fails, we still anchor the event but flag signature_ok=0.
    # This is a deliberate plane-side policy: we record attempts to deliver
    # forged events too, so the ledger captures attacks as well as successes.
    sig_ok = True
    try:
        verify(event, public_key_b64=public_key, kind="event")
    except (InvalidSignature, SchemaValidationError):
        sig_ok = False

    event_hash = "sha256:" + hashlib.sha256(canonicalize(event)).hexdigest()

    with db() as conn:
        prev = _last_chain_hash(conn)
        chain_hash = "sha256:" + hashlib.sha256((prev + event_hash).encode()).hexdigest()
        try:
            conn.execute("""
              INSERT INTO events (
                event_id, occurred_at, anchored_at, vendor, agent_id,
                action_type, tool_name, target_resource,
                decision, rule_id, policy_hash, rationale,
                raw_event, event_hash, prev_chain_hash, chain_hash, signature_ok
              ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                event["event_id"],
                event["occurred_at"],
                datetime.now(tz=timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                event["actor"]["vendor"],
                event["actor"]["agent_id"],
                event["action"]["type"],
                event["action"].get("tool_name"),
                event["action"].get("target_resource"),
                (event.get("policy") or {}).get("decision"),
                (event.get("policy") or {}).get("rule_id"),
                (event.get("policy") or {}).get("policy_hash"),
                (event.get("policy") or {}).get("rationale"),
                json.dumps(event, ensure_ascii=False),
                event_hash,
                prev,
                chain_hash,
                int(sig_ok),
            ))
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail=f"event already anchored: {exc}")

    return JSONResponse({
        "status": "accepted",
        "event_hash": event_hash,
        "chain_hash": chain_hash,
        "signature_verified": sig_ok,
    })


@app.post("/agp/v0/policy")
async def receive_policy(request: Request) -> JSONResponse:
    """Flow B — customer pushes a signed policy. We accept, verify, and
    return the policy_hash so the customer can confirm activation."""
    raw_bytes = await request.body()
    try:
        policy = json.loads(raw_bytes)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid JSON")

    sig_obj = policy.get("signature") or {}
    key_id = sig_obj.get("key_id")
    public_key = REGISTERED_PUBLIC_KEYS.get(key_id)
    if not public_key:
        raise HTTPException(status_code=403, detail=f"unknown key_id {key_id!r}")

    sig_ok = True
    try:
        verify(policy, public_key_b64=public_key, kind="policy")
    except (InvalidSignature, SchemaValidationError) as exc:
        sig_ok = False

    if not sig_ok:
        raise HTTPException(status_code=403, detail="policy signature did not verify")

    with db() as conn:
        conn.execute("""
          INSERT OR REPLACE INTO active_policies
            (policy_id, policy_hash, issuer, received_at, raw_policy, signature_ok)
          VALUES (?, ?, ?, ?, ?, ?)
        """, (
            policy["policy_id"],
            policy["policy_hash"],
            policy["issuer"],
            datetime.now(tz=timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            json.dumps(policy, ensure_ascii=False),
            int(sig_ok),
        ))

    return JSONResponse({
        "status": "accepted",
        "policy_id": policy["policy_id"],
        "policy_hash": policy["policy_hash"],
    })


@app.get("/events")
async def list_events(limit: int = 100) -> list[dict]:
    """JSON list of recent events for the dashboard's auto-refresh."""
    with db() as conn:
        rows = conn.execute("""
          SELECT * FROM events ORDER BY row_id DESC LIMIT ?
        """, (limit,)).fetchall()
    return [dict(r) for r in rows]


@app.get("/events/{event_id}")
async def get_event(event_id: str) -> dict:
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM events WHERE event_id = ?", (event_id,)
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="event not found")
    return dict(row)


@app.get("/policies")
async def list_policies() -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            "SELECT policy_id, policy_hash, issuer, received_at FROM active_policies"
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/", response_class=HTMLResponse)
async def dashboard() -> str:
    """Live HTML dashboard. Auto-refreshes every 2 seconds."""
    return _DASHBOARD_HTML


# === Dashboard HTML ==========================================================

_DASHBOARD_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>AGP Plane — live ledger</title>
  <style>
    :root {
      --bg: #0a0e1a; --fg: #e5e8f0; --muted: #7a8499; --accent: #3b82f6;
      --allowed: #22c55e; --blocked: #ef4444; --logged: #f59e0b;
      --border: #1a2032;
    }
    body {
      font-family: ui-sans-serif, -apple-system, system-ui, sans-serif;
      background: var(--bg); color: var(--fg);
      margin: 0; padding: 2rem;
    }
    h1 { margin: 0 0 .5em 0; font-weight: 700; letter-spacing: -.02em; }
    h1 span { color: var(--accent); }
    .meta { color: var(--muted); font-size: .9rem; margin-bottom: 2rem; }
    .meta b { color: var(--fg); }
    table { width: 100%; border-collapse: collapse; font-size: .9rem; }
    th, td { padding: .6rem .8rem; border-bottom: 1px solid var(--border); text-align: left; vertical-align: top; }
    th { background: #11172a; font-weight: 600; color: var(--muted); text-transform: uppercase; font-size: .7rem; letter-spacing: .1em; }
    tr:hover td { background: #11172a; }
    code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .85em; color: var(--fg); }
    .muted { color: var(--muted); font-size: .85em; }
    .allowed { color: var(--allowed); font-weight: 600; }
    .blocked { color: var(--blocked); font-weight: 600; }
    .logged_only { color: var(--logged); font-weight: 600; }
    .ok { color: var(--allowed); }
    .fail { color: var(--blocked); font-weight: 700; }
    .empty { color: var(--muted); padding: 3rem; text-align: center; }
    .stats { display: flex; gap: 2rem; margin-bottom: 2rem; }
    .stat { background: #11172a; padding: 1rem 1.5rem; border-radius: 8px; border: 1px solid var(--border); flex: 0 1 auto; }
    .stat-label { color: var(--muted); font-size: .7rem; text-transform: uppercase; letter-spacing: .1em; }
    .stat-value { font-size: 1.6rem; font-weight: 700; margin-top: .2rem; }
  </style>
</head>
<body>
  <h1>AGP Plane <span>·</span> live ledger</h1>
  <div class="meta">
    Receiving signed events at <code>POST /agp/v0/events</code>.
    Each row is <b>cryptographically signed</b> by the vendor and chained into a
    tamper-evident hash chain. Auto-refreshes every 2 s.
  </div>
  <div class="stats" id="stats"></div>
  <table>
    <thead>
      <tr>
        <th>occurred_at</th>
        <th>vendor / agent</th>
        <th>action</th>
        <th>decision</th>
        <th>rule</th>
        <th>sig</th>
        <th>chain_hash</th>
      </tr>
    </thead>
    <tbody id="events">
      <tr><td colspan="7" class="empty">(no events yet — start the vendor)</td></tr>
    </tbody>
  </table>

<script>
async function refresh() {
  try {
    const events = await (await fetch('/events?limit=50')).json();
    const tbody = document.getElementById('events');
    if (!events.length) {
      tbody.innerHTML = '<tr><td colspan="7" class="empty">(no events yet — start the vendor)</td></tr>';
    } else {
      tbody.innerHTML = events.map(e => `
        <tr>
          <td><code>${e.occurred_at}</code></td>
          <td>${e.vendor}<br><span class="muted">${e.agent_id}</span></td>
          <td>
            <code>${e.action_type}${e.tool_name ? ' · ' + e.tool_name : ''}</code>
            <div class="muted">${(e.target_resource || '')}</div>
          </td>
          <td class="${e.decision || ''}">${e.decision || '<span class="muted">—</span>'}</td>
          <td><code>${e.rule_id || ''}</code></td>
          <td class="${e.signature_ok ? 'ok' : 'fail'}">${e.signature_ok ? '✓' : '✗ FORGED'}</td>
          <td><code title="${e.chain_hash}">${e.chain_hash.slice(7, 19)}…</code></td>
        </tr>
      `).join('');
    }

    const stats = document.getElementById('stats');
    const total = events.length;
    const blocked = events.filter(e => e.decision === 'blocked').length;
    const allowed = events.filter(e => e.decision === 'allowed').length;
    const logged = events.filter(e => e.decision === 'logged_only').length;
    const forged = events.filter(e => !e.signature_ok).length;
    stats.innerHTML = `
      <div class="stat"><div class="stat-label">events</div><div class="stat-value">${total}</div></div>
      <div class="stat"><div class="stat-label">allowed</div><div class="stat-value allowed">${allowed}</div></div>
      <div class="stat"><div class="stat-label">blocked</div><div class="stat-value blocked">${blocked}</div></div>
      <div class="stat"><div class="stat-label">logged</div><div class="stat-value logged_only">${logged}</div></div>
      ${forged ? `<div class="stat"><div class="stat-label">forged</div><div class="stat-value fail">${forged}</div></div>` : ''}
    `;
  } catch (e) {
    document.getElementById('events').innerHTML = `<tr><td colspan="7" class="empty">refresh error: ${e}</td></tr>`;
  }
}
refresh();
setInterval(refresh, 2000);
</script>
</body>
</html>"""
