# http-prototype — AGP plane + vendor over real HTTP

A 2-process working prototype showing AGP in production-shaped form. Goes beyond [`acme-walkthrough`](../acme-walkthrough) (which is in-memory) by adding:

- A **FastAPI plane** that accepts events at `POST /agp/v0/events` and policies at `POST /agp/v0/policy`
- A **hash-chained SQLite ledger** that makes history tamper-evident
- A **live HTML dashboard** with auto-refresh and per-decision color coding
- A **simulated vendor** that pushes policy, then emits ~10 signed events through the policy evaluator
- A **forged-event injection** demonstrating the plane catching a tampered signature

Total Python: ~600 lines across 4 files. Read it end-to-end in 15 minutes.

## Run

```bash
make demo
```

You'll see:

1. The plane starts on `http://127.0.0.1:8000`
2. Vendor pushes a policy → plane verifies and stores it
3. Vendor emits 10 signed events (different action types, mixed decisions) → plane verifies, anchors, stores
4. Vendor sends one **forged** event (tampered after signing) → plane records it but flags `signature_verified=False`
5. Plane stays up for 30 seconds so you can poke at the dashboard, then shuts down

**Open http://127.0.0.1:8000/ in a browser** as soon as you see "plane up".

## What you'll see on the dashboard

A dark-mode live table updating every 2 seconds. Per-row info:

- `occurred_at` — wall clock from the vendor
- `vendor / agent` — the actor identity (FQDN + agent_id)
- `action` — type, tool_name, target_resource
- `decision` — color-coded: green `allowed`, red `blocked`, amber `logged_only`
- `rule` — which policy rule fired (or `fallback` if none)
- `sig` — ✓ if the signature verified, ✗ FORGED if not
- `chain_hash` — first 12 hex chars of the chain hash, hover for full

Top stats strip shows: total events, allowed count, blocked count, logged_only count, and (if any) forged count in red.

## What the policy blocks

Pushed once at startup ([`policy.py`](policy.py)):

- **Block** any `email.send` to a non-`acme.com` recipient
- **Logged-only** for any `database.write*` tool call (with SCF tags `DATA-08`, `AUDIT-12`)
- **Block** any `browser.navigate` to `competitor1.com` or `competitor2.com`
- **Fallback:** `allow_with_log` for anything not matched

The vendor emits actions that exercise each branch, so you'll see a mix.

## Run modes

```bash
# Plane only, foreground (for poking at the dashboard yourself):
make plane                    # then in another terminal: make vendor

# Vendor only (against an already-running plane):
make vendor

# Stress-test: 20 extra random actions
make burst

# Reset
make clean
```

## What this prototype proves

1. **AGP works over real HTTP between two real processes.** Not just in-memory.
2. **Cryptographic provenance is a runtime property, not a docs claim.** Tamper with one byte of any event in flight, the plane flags it instantly.
3. **The ledger is tamper-evident.** Every row's `chain_hash` covers the previous row's hash; modifying a past event invalidates every subsequent row. SQLite query:

   ```sql
   SELECT row_id, event_hash, chain_hash, prev_chain_hash FROM events;
   ```

   You can verify the chain manually — recompute `sha256(prev_chain_hash || event_hash)` for each row and confirm it matches `chain_hash`.

4. **The protocol's separation of concerns is real.** The plane doesn't know what the vendor's agent is. The vendor doesn't know what the plane does with the events. They agree only on the canonical event schema and ADR 0001's signing rules — that's the entire interop surface.

## What this prototype is NOT

- **Not production-ready.** SQLite is fine for a demo, not for a multi-tenant plane handling 1000 events/sec. Use Postgres + a real append-only or transparency log for production.
- **Not key-management-correct.** Both processes import keys from `shared_keys.py`. In production, vendor keys come from the AGP Registry; customer keys come from a KMS or HSM.
- **Not registered.** The "registry" here is a hardcoded dict in `shared_keys.py`. The real registry at `openagp/registry` will replace this.
- **No L3 (real-time decisions).** This is L2 only. L3 (Flow C) would have the vendor calling back to the plane synchronously for high-stakes actions; that's a different prototype.

## Files

| File | Purpose |
|---|---|
| [`plane.py`](plane.py) | FastAPI server + SQLite ledger + dashboard HTML |
| [`vendor.py`](vendor.py) | Simulated agent runtime with action sequence |
| [`policy.py`](policy.py) | The policy the customer pushes to the vendor |
| [`shared_keys.py`](shared_keys.py) | Deterministic test keypairs (vendor + customer) |
| [`Makefile`](Makefile) | `make demo` / `make plane` / `make vendor` / `make burst` |

## Inspect the ledger after a run

```bash
sqlite3 ledger.db "SELECT row_id, vendor, action_type, decision, rule_id FROM events ORDER BY row_id;"
sqlite3 ledger.db "SELECT policy_id, policy_hash FROM active_policies;"
```

Or with `dig`-like inspection of a specific event:

```bash
curl -s http://127.0.0.1:8000/events/evt_XXXXXXXXXXXXXXXX | jq .
```

## License

Apache-2.0.
