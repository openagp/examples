# Acme walkthrough — end-to-end AGP in 6 steps

A runnable demo of [§9 Appendix A](https://github.com/openagp/spec/blob/main/concept-and-spec.md#9-appendix-a--worked-example) of the spec. Acme uses a plane to govern an external vendor (Anthropic). An employee asks the agent to email an external recipient. AGP catches it.

## Run

```bash
make demo
```

Or directly:

```bash
pip install openagp
python demo.py
```

About 0.2 seconds. No network, no external services. The demo is deliberately in-memory so the cryptographic flow is visible without HTTP/RPC noise.

## What you get

After running, `output/` contains three signed artifacts:

| File | What it is |
|---|---|
| `policy.signed.json` | The customer's policy, signed by Acme's plane key |
| `event.signed.json` | The blocked action, recorded as a signed canonical event |
| `ledger.append.json` | The plane's ledger entry: hash + decision + anchored timestamp |

Open each one in your editor. Every byte is auditable, every signature is verifiable independently.

## The flow

```
┌─────────────────────────┐                          ┌──────────────────────────┐
│  Acme (customer plane)  │                          │  Anthropic (vendor)      │
└─────────────────────────┘                          └──────────────────────────┘
            │                                                   │
            │ 1. POST /agp/v0/policy   (Flow B, signed)          │
            ├──────────────────────────────────────────────────►│
            │                                                   │
            │                                          2. verify signature
            │                                             apply policy
            │                                                   │
            │            (later: Claude tries email.send)       │
            │                                                   │
            │                                          3. agent attempts
            │                                                   │
            │                                          4. evaluate(policy, action)
            │                                             → blocked
            │                                                   │
            │   5. POST /agp/v0/events  (Flow A, signed)        │
            │◄──────────────────────────────────────────────────┤
            │                                                   │
       6. verify signature
          anchor into ledger
            │
```

## What it proves

- **L1 (events):** Every action — even blocked ones — produces a signed canonical event. The customer has cryptographic evidence of every attempt.
- **L2 (policy):** The customer authors policy once. The vendor enforces it inside its own runtime. The customer never sees the agent's internal state, only the auditable outcomes.
- **Signatures end-to-end:** Both the policy and the event are Ed25519-signed per [ADR 0001](https://github.com/openagp/spec/blob/main/decisions/0001-signature-canonicalization.md). An auditor verifies them independently of either party — and that's the entire point.
- **Compliance evidence is mechanical:** The `ledger.append.json` is what an EU AI Act Article 14 (Human Oversight) conformity report cites. No tickets, no spreadsheet, no after-the-fact reconstruction.

## Step-by-step output

The demo prints colored section headers for each of the 6 steps:

```
STEP 0 — Bootstrap: actors generate keypairs
STEP 1 — Acme authors policy and pushes to Vendor (Flow B)
STEP 2 — Vendor verifies the policy signature against Acme's registered key
STEP 3 — Claude attempts a tool call (email.send)
STEP 4 — Vendor evaluates the action against the active policy
STEP 5 — Vendor emits a signed canonical event (Flow A)
STEP 6 — Plane (Acme) verifies the event and anchors it into the ledger
```

For each step, the relevant fields and the resulting artifact are printed to stdout.

## Inspect the artifacts

```bash
# Pretty-print the signed event
jq . output/event.signed.json

# Verify the event signature manually using the openagp CLI:
python -m openagp.tools.validate \
  --schema ../../spec/schemas/event.json \
  --instance output/event.signed.json
```

## Variations to try

The demo is < 250 lines of Python. Modify it to see what changes:

- Change `target_resource` from `external@customer.com` to `boss@acme.com` — the rule no longer fires, fallback (`allow_with_log`) applies, the event records `decision: logged_only`.
- Add a second rule to the policy and see first-match-wins in action.
- Tamper with one byte of `event.signed.json` and re-run `verify(...)` — `InvalidSignature` is raised.
- Replace `acme.public_key_b64` with a different key — verification fails immediately, no policy is applied.

## What's NOT in this demo (but should be in production)

- **HTTP transport.** Real vendors and planes communicate over HTTPS with mTLS or bearer tokens. The protocol is the same; the demo just skips the transport.
- **AGP Registry.** Real verifiers look up `signature.key_id` against the registry, not against a key the same actor handed them. The demo uses ephemeral keys directly for clarity.
- **Hash-chained ledger.** The demo writes one append-only line. In production, each event extends a hash-chain making history tamper-evident at the customer side. See ZAK Action Ledger (PRD 01) for the production design.
- **Real-time L3 decisions.** This is L2 only. L3 (Flow C) involves the vendor calling back to the plane synchronously for high-stakes actions; that demo lives in `examples/realtime-decision/` *(coming)*.

## License

Apache-2.0. Use, fork, ship in your own demo.
