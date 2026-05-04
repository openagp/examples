"""The policy the customer (plane operator) pushes to the vendor.

In production this would be authored in YAML/JSON and signed at the
customer's key-management service. Here we author it inline for clarity.
"""

import hashlib
from openagp._canonical import canonicalize


POLICY_BODY = {
    "agp_policy_version": "0.1",
    "policy_id": "acme-prod-2026-q3",
    "policy_hash": "sha256:placeholder",  # recomputed below
    "issuer": "acme.example.com",
    "issued_at": "2026-08-01T00:00:00Z",
    "applies_to": {
        "vendors": ["*"],
        "agents": ["*"],
        "actions": ["tool_call", "model_response"],
    },
    "rules": [
        {
            "id": "rule_block_external_email",
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
        {
            "id": "rule_log_database_writes",
            "when": {
                "action.tool_name": {"starts_with": "database.write"},
            },
            "then": {
                "decision": "logged_only",
                "reason": "regulatory: every database mutation is audited",
                "annotate": {"scf_controls": ["DATA-08", "AUDIT-12"]},
            },
        },
        {
            "id": "rule_block_competitor_research",
            "when": {
                "action.tool_name": "browser.navigate",
                "action.target_resource": {
                    "domain_in": ["competitor1.com", "competitor2.com"],
                },
            },
            "then": {
                "decision": "blocked",
                "reason": "policy: no agent navigation to named competitors",
            },
        },
    ],
    "fallback": {"decision": "allow_with_log"},
    "metadata": {
        "description": "HTTP prototype policy: block external email, log DB writes, block competitor research.",
        "contact": "security@acme.example.com",
    },
}


def computed_policy_hash() -> str:
    """Compute the policy_hash over the canonicalized body (excluding the
    signature and the placeholder hash itself)."""
    body = {k: v for k, v in POLICY_BODY.items() if k != "signature"}
    body["policy_hash"] = "sha256:placeholder"  # canonicalize with the placeholder so hash is stable
    return "sha256:" + hashlib.sha256(canonicalize(body)).hexdigest()


POLICY_HASH = computed_policy_hash()
POLICY_BODY["policy_hash"] = POLICY_HASH
