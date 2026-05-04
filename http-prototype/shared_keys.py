"""Deterministic test keypairs for the HTTP prototype.

Both plane.py and vendor.py import from here so they agree on which keys
are "registered" without needing a real AGP Registry.

In production: vendor keys come from the AGP Registry (via .well-known/agp
discovery and registry mirror); customer keys come from the customer's
KMS. NEVER use these test keys for any real AGP traffic — they're
hardcoded and public.
"""

# Vendor key: 32-byte seed, base64-encoded. Same seed = same keypair, every
# run, every machine. Lets the plane and vendor coordinate without a registry.
import base64
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

VENDOR_SEED = b"AGP_HTTP_PROTOTYPE_VENDOR_KEY_32"
assert len(VENDOR_SEED) == 32

VENDOR_KEY_ID = "vendor.example-2026-q2"

_sk = Ed25519PrivateKey.from_private_bytes(VENDOR_SEED)
VENDOR_PRIVATE_KEY_B64 = base64.b64encode(VENDOR_SEED).decode("ascii")
VENDOR_PUBLIC_KEY_B64 = base64.b64encode(_sk.public_key().public_bytes_raw()).decode("ascii")

# Customer (plane operator) key — used to sign outbound policies.
CUSTOMER_SEED = b"AGP_HTTP_PROTOTYPE_CUSTOMER_KEY!"
assert len(CUSTOMER_SEED) == 32

CUSTOMER_KEY_ID = "acme.example-2026-q2"

_csk = Ed25519PrivateKey.from_private_bytes(CUSTOMER_SEED)
CUSTOMER_PRIVATE_KEY_B64 = base64.b64encode(CUSTOMER_SEED).decode("ascii")
CUSTOMER_PUBLIC_KEY_B64 = base64.b64encode(_csk.public_key().public_bytes_raw()).decode("ascii")

# The plane's "registry": every key_id it knows how to verify.
REGISTERED_PUBLIC_KEYS = {
    VENDOR_KEY_ID: VENDOR_PUBLIC_KEY_B64,
    CUSTOMER_KEY_ID: CUSTOMER_PUBLIC_KEY_B64,
}
