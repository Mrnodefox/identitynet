"""
Zero-knowledge proofs (Schnorr on Ed25519) and selective disclosure commitments.
Uses PyNaCl curve25519 primitives — lightweight for Termux/mobile.
"""

from __future__ import annotations

import hashlib
import os
import secrets
from typing import Any, Dict, Optional

try:
    import nacl.bindings as ed

    NACL_AVAILABLE = True
except ImportError:
    NACL_AVAILABLE = False


def _require_nacl() -> None:
    if not NACL_AVAILABLE:
        raise RuntimeError("PyNaCl is required for zero-knowledge proofs. pip install pynacl")


def _scalar_reduce(data: bytes) -> bytes:
    _require_nacl()
    return ed.crypto_core_ed25519_scalar_reduce(data)


def _hash_to_scalar(*parts: bytes) -> bytes:
    # Ed25519 scalar reduction requires a 64-byte non-reduced scalar
    h = hashlib.sha512(b"".join(parts)).digest()
    return _scalar_reduce(h)


def _point_base(scalar: bytes) -> bytes:
    return ed.crypto_scalarmult_ed25519_base_noclamp(scalar)


def _point_add(p: bytes, q: bytes) -> bytes:
    return ed.crypto_core_ed25519_add(p, q)


def create_commitment(value: str, salt: Optional[str] = None) -> Dict[str, str]:
    """SHA-256 commitment for selective disclosure."""
    if salt is None:
        salt = secrets.token_hex(16)
    raw = f"{value}:{salt}".encode("utf-8")
    commitment = hashlib.sha256(raw).hexdigest()
    return {"commitment": commitment, "salt": salt}


def create_schnorr_proof(secret: str, salt: str) -> Dict[str, str]:
    """
    Non-interactive Schnorr proof of knowledge of (value, salt) for commitment C = x*B
    where x = H(value:salt) mapped to a scalar. Verifier checks without learning secret.
    """
    _require_nacl()
    witness = _hash_to_scalar(secret.encode("utf-8"), salt.encode("utf-8"))
    commitment_point = _point_base(witness)

    nonce = os.urandom(64)
    r_scalar = _scalar_reduce(nonce)
    r_point = _point_base(r_scalar)

    challenge = _hash_to_scalar(r_point, commitment_point, b"identitynet-zk-v1")
    # s = r + c*x (mod L) via scalar addition
    s_scalar = ed.crypto_core_ed25519_scalar_add(
        r_scalar, ed.crypto_core_ed25519_scalar_mul(challenge, witness)
    )

    return {
        "commitment": commitment_point.hex(),
        "r_point": r_point.hex(),
        "s_scalar": s_scalar.hex(),
        "challenge": challenge.hex(),
        "version": "schnorr-v1",
    }


def verify_schnorr_proof(proof: Dict[str, str]) -> bool:
    """Verify s*B == R + c*C (Ed25519 Schnorr)."""
    _require_nacl()
    try:
        if proof.get("version") != "schnorr-v1":
            return False
        r_point = bytes.fromhex(proof["r_point"])
        commitment_point = bytes.fromhex(proof["commitment"])
        s_scalar = bytes.fromhex(proof["s_scalar"])
        challenge = bytes.fromhex(proof["challenge"])

        lhs = _point_base(s_scalar)
        rhs = _point_add(
            r_point,
            ed.crypto_scalarmult_ed25519_noclamp(challenge, commitment_point),
        )
        recomputed = _hash_to_scalar(r_point, commitment_point, b"identitynet-zk-v1")
        return lhs == rhs and recomputed == challenge
    except (KeyError, ValueError):
        return False


def selective_disclosure_proof(
    private_key_hex: str,
    attribute: str,
    value: str,
    salt: str,
    public_key_hex: str,
) -> Dict[str, Any]:
    """
    Prove ownership of an attribute: commitment + Ed25519 signature over reveal payload.
    Verifier learns only the disclosed attribute.
    """
    from crypto_utils import sign_payload, verify_payload

    commitment_data = create_commitment(value, salt)
    payload = {
        "action": "disclose",
        "attribute": attribute,
        "commitment": commitment_data["commitment"],
        "public_key": public_key_hex,
    }
    signature = sign_payload(private_key_hex, payload)
    return {
        **commitment_data,
        "attribute": attribute,
        "value": value,
        "signature": signature,
        "payload": payload,
    }


def verify_selective_disclosure(proof: Dict[str, Any]) -> bool:
    from crypto_utils import verify_payload

    try:
        expected = create_commitment(proof["value"], proof["salt"])
        if expected["commitment"] != proof["commitment"]:
            return False
        return verify_payload(
            proof["payload"]["public_key"],
            proof["payload"],
            proof["signature"],
        )
    except (KeyError, TypeError):
        return False
