# openagp/examples

**End-to-end worked examples for AGP.** Each example is self-contained, runnable, and produces signed artifacts you can inspect.

## Available examples

| Example | What it shows | Status |
|---|---|---|
| [`acme-walkthrough/`](acme-walkthrough) | The §9 Appendix A scenario — Acme blocks an external email end-to-end. Policy delivery (B) → action attempt → decision → signed event (A) → ledger anchor. | **Runnable** |
| `mock-vendor/` | Minimal HTTP service emitting AGP events to a configurable plane endpoint (L1) | *coming* |
| `mock-plane/` | Minimal HTTP service receiving and verifying events (L1) | *coming* |
| `policy-roundtrip/` | Plane pushes a policy via HTTP, vendor accepts and applies it, vendor emits policy-stamped events (L2) | *coming* |
| `realtime-decision/` | Vendor calls back to the plane synchronously for a high-stakes action (L3) | *coming* |

## Quick start

```bash
cd acme-walkthrough
make demo
```

About 0.2 seconds. The demo prints a 6-step narrative, signs every artifact end-to-end, and writes three inspectable JSON files into `output/`.

## What every example demonstrates

Different examples emphasize different parts of the protocol, but every example is faithful to the canonical contract:

- **Schemas.** Every JSON message validates against the canonical schemas in [`openagp/spec`](https://github.com/openagp/spec/tree/main/schemas).
- **Signatures.** Every signed message follows [ADR 0001](https://github.com/openagp/spec/blob/main/decisions/0001-signature-canonicalization.md) — RFC 8785 JCS + Ed25519, with `key_id` and `alg` bound into the signed bytes.
- **Cross-language.** Examples can be ported to TypeScript without changing the bytes, fixtures, or test vectors. Interop is byte-for-byte.

## Running tests

```bash
pip install pytest openagp
pytest tests/
```

Examples have CI smoke tests that fail when the SDK or spec drift in a way that breaks the demo.

## Adding an example

New examples are welcome — they're often the clearest way for a new contributor to learn the protocol.

1. Pick a slot from the "*coming*" rows in the table above, or propose a new one via a [Feature request](https://github.com/openagp/examples/issues/new?template=feature_request.yml).
2. Make it self-contained: a `Makefile` with a `demo` target and a short README explaining the scenario.
3. Sign every artifact with the SDK (no hand-rolled crypto).
4. Add a smoke test under `tests/` that fails if the demo's output stops matching expectations.
5. Document which conformance level (L1 / L2 / L3) the example exercises.

## Contributing

See [CONTRIBUTING.md](https://github.com/openagp/.github/blob/main/CONTRIBUTING.md) at the org level for DCO sign-off and PR conventions, and [SUPPORT.md](https://github.com/openagp/.github/blob/main/SUPPORT.md) for where to ask questions or file bugs.

## License

[Apache-2.0](LICENSE).
