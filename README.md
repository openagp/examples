# openagp/examples

**End-to-end worked examples for AGP — mock vendor, mock plane, and full traces.**

## Status

Scaffold. Examples tracked in [§4.2 Phase 1](https://github.com/openagp/spec/blob/main/concept-and-spec.md#42-build-order--what-claude-code-should-build-first) of the spec, fleshed out alongside the SDKs.

## Planned examples

- `mock-vendor/` — minimal Python service emitting AGP events to a configurable plane endpoint (L1)
- `mock-plane/` — minimal Python service receiving and verifying events (L1)
- `policy-roundtrip/` — plane pushes a policy, vendor accepts, vendor emits policy-stamped events (L2)
- `realtime-decision/` — vendor calls back to plane synchronously for a high-stakes action (L3)
- `acme-walkthrough/` — the §9 Appendix A scenario (Acme blocks external email) end-to-end with real signatures

## Running

Each example is self-contained with its own `docker-compose.yml` or `Makefile`. See each subdirectory for setup instructions.

## License

[Apache-2.0](LICENSE).
