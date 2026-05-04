"""End-to-end AGP worked example — Acme blocks an external email.

Runs the full §9 Appendix A flow from openagp/spec end-to-end against the
reference Python SDK. Produces signed artifacts in ./output/ that you can
inspect or hand to an auditor.

Six steps. No HTTP — that's deliberate. AGP is a *protocol*, not a network
library; the same flow works over HTTPS, gRPC, a queue, or in-memory. This
demo runs in-memory so the cryptographic story is visible without
transport noise.

Run:    python demo.py
Output: output/policy.signed.json, output/event.signed.json,
        output/ledger.append.json
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from openagp import (
    Decision,
    InvalidSignature,
    evaluate,
    generate_keypair,
    sign,
    verify,
)
from openagp._canonical import canonicalize


HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "output"


def section(title: str) -> None:
    print()
    print("\033[1m" + "─" * 78 + "\033[0m")
    print(f"\033[1m  {title}\033[0m")
    print("\033[1m" + "─" * 78 + "\033[0m")


def kv(label: str, value: object, *, indent: int = 4) -> None:
    pad = " " * indent
    if isinstance(value, str) and len(value) > 70:
        value = value[:67] + "…"
    print(f"{pad}\033[2m{label:24}\033[0m {value}")


def write_json(name: str, obj: object) -> Path:
    OUTPUT.mkdir(exist_ok=True)
    path = OUTPUT / name
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


# === Actors ==================================================================
# Acme is the customer (plane). Anthropic is the vendor. In production each
# would manage its own keys via a KMS; here we generate ephemeral keys.

ACME_KEY_ID = "acme-2026-q2"
VENDOR_KEY_ID = "anthropic-2026-q2"


def main() -> int:
    section("STEP 0 — Bootstrap: actors generate keypairs")
    acme = generate_keypair()
    vendor = generate_keypair()
    kv("Acme (plane) public key", acme.public_key_b64)
    kv("Vendor public key", vendor.public_key_b64)
    print(
        "\n    These public keys would be published in each actor's "
        "/.well-known/agp\n    document and registered in the AGP Registry. "
        "Verifiers resolve key_id\n    against the registry — not against an "
        "embedded key — so key rotation is a\n    registry update, not a "
        "protocol-level event."
    )

    # === STEP 1 — Acme authors and signs a policy ============================
    section("STEP 1 — Acme authors policy and pushes to Vendor (Flow B)")

    policy = {
        "agp_policy_version": "0.1",
        "policy_id": "acme-block-external-email",
        "policy_hash": "sha256:placeholder",  # recomputed below
        "issuer": "acme.example.com",
        "issued_at": now_iso(),
        "applies_to": {
            "vendors": ["*"],
            "agents": ["*"],
            "actions": ["tool_call"],
        },
        "rules": [
            {
                "id": "rule_external_email_blocked",
                "when": {
                    "action.tool_name": "email.send",
                    "action.target_resource": {
                        "domain_not_in": ["acme.com", "*.acme.com"],
                    },
                },
                "then": {
                    "decision": "blocked",
                    "reason": "external email recipient requires human review",
                },
            },
        ],
        "fallback": {"decision": "allow_with_log"},
        "metadata": {
            "description": "Block any email.send tool_call where the recipient is "
            "outside acme.com.",
            "contact": "security@acme.example.com",
        },
    }

    # Compute policy_hash over the policy body (without signature) — this is
    # what events will reference to prove which policy was in force.
    body_for_hash = {k: v for k, v in policy.items() if k != "signature"}
    import hashlib

    policy["policy_hash"] = (
        "sha256:" + hashlib.sha256(canonicalize(body_for_hash)).hexdigest()
    )
    POLICY_HASH = policy["policy_hash"]

    signed_policy = sign(
        policy,
        private_key_b64=acme.private_key_b64,
        key_id=ACME_KEY_ID,
        kind="policy",
    )
    policy_path = write_json("policy.signed.json", signed_policy)
    kv("policy_id", policy["policy_id"])
    kv("policy_hash", POLICY_HASH)
    kv("rules", len(policy["rules"]))
    kv("artifact", policy_path)
    print(
        "\n    Acme signs with its plane key and POSTs to the vendor's "
        "/agp/v0/policy.\n    The vendor responds 202 Accepted and applies "
        "the policy within the SLA\n    (default 60 seconds)."
    )

    # === STEP 2 — Vendor verifies the policy =================================
    section("STEP 2 — Vendor verifies the policy signature against Acme's registered key")
    try:
        verify(signed_policy, public_key_b64=acme.public_key_b64, kind="policy")
    except InvalidSignature as exc:
        print(f"    ERROR: policy did not verify: {exc}")
        return 1
    kv("verification", "OK")
    print(
        "\n    Real vendors lookup the public key by key_id from the AGP "
        "Registry —\n    they don't trust whatever key the policy claims to "
        "have been signed with."
    )

    # === STEP 3 — Agent attempts an action ===================================
    section("STEP 3 — Claude attempts a tool call (email.send)")
    proposed_action = {
        "type": "tool_call",
        "tool_name": "email.send",
        "target_resource": "external@customer.com",
        "input_summary": "Quarterly report summary attached",
        "input_hash": "sha256:7b8d1f2e9c4a6035b1d89427fe5a3c0fa1b94d6e827340c5fe1b6a9d8c742031",
    }
    kv("tool_name", proposed_action["tool_name"])
    kv("target_resource", proposed_action["target_resource"])
    kv("input_summary", proposed_action["input_summary"])

    proposed_event_skeleton = {
        "agp_version": "0.1",
        "schema_version": "1.0",
        "actor": {
            "vendor": "anthropic.com",
            "agent_id": "agt_claude_sonnet_4_6",
            "human_principal": "user_hash_2d4f8c1a9e3b7d50",
        },
        "action": proposed_action,
    }

    # === STEP 4 — Vendor evaluates against active policy =====================
    section("STEP 4 — Vendor evaluates the action against the active policy")
    decision: Decision = evaluate(signed_policy, proposed_event_skeleton)
    kv("decision", decision.decision)
    kv("rule_id", decision.rule_id)
    kv("reason", decision.reason or "(none)")
    if decision.decision == "blocked":
        print(
            "\n    \033[33m✗ The action is blocked. Claude does NOT execute "
            "email.send.\033[0m"
        )
    elif decision.decision == "logged_only":
        print("\n    \033[36m• The action is logged but proceeds.\033[0m")
    else:
        print("\n    \033[32m✓ The action proceeds normally.\033[0m")

    # === STEP 5 — Vendor emits a signed event (Flow A) ========================
    section("STEP 5 — Vendor emits a signed canonical event (Flow A)")
    event = {
        **proposed_event_skeleton,
        "event_id": "evt_01JFXY8C7N4PZQ3HMR2K0DXTGF",
        "occurred_at": now_iso(),
        "policy": decision.to_event_policy_block(policy_hash=POLICY_HASH),
        "lineage": {
            "trace_id": "trc_01JFXY7P0KZ8ME6X4WCBVQHRGD",
            "parent_event_id": None,
        },
    }
    signed_event = sign(
        event,
        private_key_b64=vendor.private_key_b64,
        key_id=VENDOR_KEY_ID,
        kind="event",
    )
    event_path = write_json("event.signed.json", signed_event)
    kv("event_id", signed_event["event_id"])
    kv("occurred_at", signed_event["occurred_at"])
    kv("policy.decision", signed_event["policy"]["decision"])
    kv("policy.policy_hash", signed_event["policy"]["policy_hash"])
    kv("signature.key_id", signed_event["signature"]["key_id"])
    kv("artifact", event_path)
    print(
        "\n    Note: even though the action was blocked, the event is still "
        "emitted.\n    The customer's ledger needs evidence of attempts, "
        "not just successes."
    )

    # === STEP 6 — Plane verifies and anchors into the ledger =================
    section("STEP 6 — Plane (Acme) verifies the event and anchors it into the ledger")
    try:
        verify(signed_event, public_key_b64=vendor.public_key_b64, kind="event")
    except InvalidSignature as exc:
        print(f"    ERROR: event did not verify: {exc}")
        return 1
    kv("signature verification", "OK")

    # The "ledger" here is a single-line append. In ZAK / production, the
    # ledger is a hash-chained, append-only store (see Action Ledger PRD).
    canonical_event = canonicalize(signed_event)
    event_hash = "sha256:" + hashlib.sha256(canonical_event).hexdigest()
    ledger_entry = {
        "event_id": signed_event["event_id"],
        "event_hash": event_hash,
        "policy_hash": signed_event["policy"]["policy_hash"],
        "decision": signed_event["policy"]["decision"],
        "vendor": signed_event["actor"]["vendor"],
        "anchored_at": now_iso(),
    }
    ledger_path = write_json("ledger.append.json", ledger_entry)
    kv("event_hash", event_hash)
    kv("ledger artifact", ledger_path)

    # === Summary =============================================================
    section("End-to-end complete")
    print(
        "\n    Acme's compliance lead can now generate, e.g., an EU AI Act\n"
        "    Article 14 (Human Oversight) report citing this event as evidence\n"
        "    that automated policy enforcement blocked an external data "
        "transfer.\n\n"
        "    The auditor verifies the evidence WITHOUT trusting Acme or the\n"
        "    vendor: they verify the signature against the vendor's "
        "registered\n    key, recompute the canonical hash, and check the "
        "policy_hash matches\n    a policy entry in their archive.\n"
    )
    print("    Artifacts:")
    for p in (policy_path, event_path, ledger_path):
        print(f"      {p}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
