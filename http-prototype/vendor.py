"""Simulated AGP-conformant vendor.

This script plays the role of an agent runtime (think: Anthropic's
backend, your in-house agent platform) that has implemented L2 AGP
support. It:

  1. Receives a signed policy from the customer (Flow B).
  2. Runs a sequence of simulated agent actions.
  3. Evaluates each action against the active policy locally.
  4. Constructs a signed canonical event for each action.
  5. POSTs the event to the customer's plane (Flow A).

Run:  python vendor.py            # uses default plane URL http://127.0.0.1:8000
      python vendor.py --burst N  # send N actions instead of the default sequence
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone

from openagp import evaluate, sign

from policy import POLICY_BODY, POLICY_HASH
from shared_keys import (
    CUSTOMER_KEY_ID,
    CUSTOMER_PRIVATE_KEY_B64,
    VENDOR_KEY_ID,
    VENDOR_PRIVATE_KEY_B64,
)


VENDOR_NAME = "vendor.example"
AGENT_ID = "agt_prototype_v1"
# user_hash schema: ^user_hash_[0-9a-f]{16,64}$ — 32 hex chars chosen for the demo
HUMAN_PRINCIPAL = "user_hash_4a7c2d8f9b1e5036"


# ─── Simulated agent action sequence ────────────────────────────────────────
# Mix of internal/external/database/competitor actions to exercise the policy.

DEFAULT_ACTIONS = [
    ("tool_call", "browser.navigate", "https://acme.com/dashboard",
     "Open the Q3 dashboard"),
    ("tool_call", "email.send", "boss@acme.com",
     "Internal weekly update"),
    ("tool_call", "email.send", "external@bigclient.com",
     "Q3 financial summary"),
    ("tool_call", "database.write_users", "user/42",
     "Add new user account"),
    ("tool_call", "browser.navigate", "https://competitor1.com/pricing",
     "Research competitor pricing"),
    ("tool_call", "database.read_orders", "orders/recent",
     "Pull last week's orders"),
    ("model_response", None, None,
     "Drafted a summary of the recent orders"),
    ("tool_call", "email.send", "team@acme.com",
     "Friday wrap-up email"),
    ("tool_call", "database.write_audit_log", "audit/ev42",
     "Log the previous action"),
    ("tool_call", "browser.navigate", "https://news.ycombinator.com",
     "Read industry news"),
]


# ─── HTTP helpers ──────────────────────────────────────────────────────────


def http_post_json(url: str, payload: dict, timeout: float = 5.0) -> tuple[int, dict]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json", "User-Agent": "openagp-prototype-vendor/0.0.1"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


def now_iso(offset_seconds: int = 0) -> str:
    t = datetime.now(tz=timezone.utc) + timedelta(seconds=offset_seconds)
    return t.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def ulid_like() -> str:
    """Quick-and-dirty ULID-shaped string for the prototype. Not RFC-correct
    but matches the schema regex."""
    alpha = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford base32
    return "".join(random.choice(alpha) for _ in range(26))


# ─── Step 1: push policy to the plane ──────────────────────────────────────


def push_policy(plane_url: str) -> str:
    print(f"\n→ pushing policy to {plane_url}/agp/v0/policy ...")
    signed_policy = sign(
        POLICY_BODY,
        private_key_b64=CUSTOMER_PRIVATE_KEY_B64,
        key_id=CUSTOMER_KEY_ID,
        kind="policy",
    )
    code, body = http_post_json(f"{plane_url}/agp/v0/policy", signed_policy)
    if code != 200:
        print(f"  ✗ plane rejected policy: HTTP {code} {body}")
        sys.exit(1)
    print(f"  ✓ accepted: policy_hash={body['policy_hash']}")
    return body["policy_hash"]


# ─── Step 2: emit events for each agent action ─────────────────────────────


COLOR_BY_DECISION = {"allowed": "\033[32m", "blocked": "\033[31m", "logged_only": "\033[33m"}
RESET = "\033[0m"


def emit_action(plane_url: str, idx: int, action_type: str, tool_name, target, summary) -> None:
    skeleton = {
        "agp_version": "0.1",
        "schema_version": "1.0",
        "actor": {"vendor": VENDOR_NAME, "agent_id": AGENT_ID, "human_principal": HUMAN_PRINCIPAL},
        "action": {"type": action_type, "input_summary": summary},
    }
    if tool_name:
        skeleton["action"]["tool_name"] = tool_name
    if target:
        skeleton["action"]["target_resource"] = target

    decision = evaluate(POLICY_BODY, skeleton)

    full_event = {
        **skeleton,
        "event_id": f"evt_{ulid_like()}",
        "occurred_at": now_iso(),
        "policy": decision.to_event_policy_block(policy_hash=POLICY_HASH),
        "lineage": {"trace_id": f"trc_{ulid_like()}", "parent_event_id": None},
    }
    signed_event = sign(
        full_event,
        private_key_b64=VENDOR_PRIVATE_KEY_B64,
        key_id=VENDOR_KEY_ID,
        kind="event",
    )

    color = COLOR_BY_DECISION.get(decision.decision, "")
    print(
        f"  [{idx:02d}] {color}{decision.decision:11s}{RESET}  "
        f"{action_type:14s}  {tool_name or '—':22s}  "
        f"target={target or '—'}  rule={decision.rule_id}"
    )

    code, body = http_post_json(f"{plane_url}/agp/v0/events", signed_event)
    if code != 200:
        print(f"       ✗ plane rejected event: HTTP {code} {body}")
        return
    if not body.get("signature_verified"):
        print(f"       ⚠ plane reports signature_verified=False ({body})")


def emit_forged_event(plane_url: str, idx: int) -> None:
    """Demo: send an event with a tampered field after signing. The plane
    will accept it (records all attempts) but flag signature_verified=False
    on the dashboard."""
    skeleton = {
        "agp_version": "0.1",
        "schema_version": "1.0",
        "actor": {"vendor": VENDOR_NAME, "agent_id": AGENT_ID},
        "action": {
            "type": "tool_call",
            "tool_name": "email.send",
            "target_resource": "boss@acme.com",
            "input_summary": "FORGED ATTEMPT — tampered after signing",
        },
        "event_id": f"evt_{ulid_like()}",
        "occurred_at": now_iso(),
    }
    signed = sign(skeleton, private_key_b64=VENDOR_PRIVATE_KEY_B64, key_id=VENDOR_KEY_ID, kind="event")
    # Tamper: change tool_name AFTER signing so the signature won't verify.
    signed["action"]["tool_name"] = "wire.transfer"
    print(f"  [{idx:02d}] \033[31mFORGED\033[0m       attempting to deliver tampered event ...")
    code, body = http_post_json(f"{plane_url}/agp/v0/events", signed)
    print(f"       plane response: HTTP {code}, signature_verified={body.get('signature_verified')}")


# ─── Main ──────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description="AGP HTTP prototype vendor (action emitter)")
    parser.add_argument("--plane", default="http://127.0.0.1:8000",
                        help="Plane base URL (default: http://127.0.0.1:8000)")
    parser.add_argument("--burst", type=int, default=0,
                        help="Send N random extra actions (in addition to the default sequence)")
    parser.add_argument("--delay", type=float, default=0.6,
                        help="Seconds between actions (default: 0.6)")
    parser.add_argument("--include-forged", action="store_true",
                        help="Also send one tampered event to demonstrate signature rejection")
    args = parser.parse_args()

    print(f"\n\033[1mAGP HTTP prototype — vendor\033[0m")
    print(f"  plane       : {args.plane}")
    print(f"  vendor key  : {VENDOR_KEY_ID}")
    print(f"  customer    : {CUSTOMER_KEY_ID}")

    push_policy(args.plane)

    actions = list(DEFAULT_ACTIONS)
    for _ in range(args.burst):
        # random extras to make the dashboard feel alive
        if random.random() < 0.5:
            actions.append(("tool_call", "database.read_logs", f"logs/{random.randint(1, 1000)}", "log read"))
        else:
            actions.append(("tool_call", "browser.navigate",
                            random.choice([
                                "https://acme.com/x", "https://news.ycombinator.com",
                                "https://competitor2.com", "https://docs.acme.com",
                            ]),
                            "browse"))

    print(f"\n→ emitting {len(actions)} signed events ...")
    for i, (action_type, tool, target, summary) in enumerate(actions, start=1):
        emit_action(args.plane, i, action_type, tool, target, summary)
        time.sleep(args.delay)

    if args.include_forged:
        print()
        emit_forged_event(args.plane, len(actions) + 1)

    print(f"\n\033[1m✓ done.\033[0m  Open the dashboard: {args.plane}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
