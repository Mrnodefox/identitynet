"""
Ed25519 identity cryptography for IdentityNet.
All network writes must be signed by the controlling private key.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Optional, Tuple

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)
from cryptography.exceptions import InvalidSignature


def generate_keypair() -> Tuple[str, str]:
    """Return (public_key_hex, private_key_hex)."""
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    private_bytes = private_key.private_bytes(
        Encoding.Raw, PrivateFormat.Raw, NoEncryption()
    )
    public_bytes = public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)
    return public_bytes.hex(), private_bytes.hex()


def _load_private(private_key_hex: str) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(bytes.fromhex(private_key_hex))


def _load_public(public_key_hex: str) -> Ed25519PublicKey:
    return Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex))


def canonical_json(data: Dict[str, Any]) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


def sign_payload(private_key_hex: str, payload: Dict[str, Any]) -> str:
    message = canonical_json(payload).encode("utf-8")
    signature = _load_private(private_key_hex).sign(message)
    return signature.hex()


def verify_payload(
    public_key_hex: str, payload: Dict[str, Any], signature_hex: str
) -> bool:
    try:
        message = canonical_json(payload).encode("utf-8")
        _load_public(public_key_hex).verify(
            bytes.fromhex(signature_hex), message
        )
        return True
    except (InvalidSignature, ValueError):
        return False


def generate_did(public_key_hex: str) -> str:
    """Deterministic DID from public key (stable across nodes)."""
    digest = hashlib.sha256(bytes.fromhex(public_key_hex)).hexdigest()[:32]
    return f"did:identitynet:{digest}"


def registration_payload(
    username: str, email: Optional[str], public_key_hex: str, timestamp: str
) -> Dict[str, Any]:
    return {
        "action": "register",
        "username": username,
        "email": email,
        "public_key": public_key_hex,
        "timestamp": timestamp,
    }


def attestation_payload(
    subject_did: str,
    attestation_type: str,
    data: Optional[str],
    attester_did: str,
    timestamp: str,
) -> Dict[str, Any]:
    return {
        "action": "attest",
        "subject_did": subject_did,
        "attestation_type": attestation_type,
        "data": data,
        "attester_did": attester_did,
        "timestamp": timestamp,
    }


def ledger_payload(
    tx_id: str,
    did: str,
    transaction_type: str,
    amount: float,
    description: Optional[str],
    timestamp: str,
) -> Dict[str, Any]:
    return {
        "action": "ledger",
        "tx_id": tx_id,
        "did": did,
        "transaction_type": transaction_type,
        "amount": amount,
        "description": description,
        "timestamp": timestamp,
    }


def transfer_payload(
    tx_id: str,
    from_did: str,
    to_did: str,
    amount: float,
    timestamp: str,
) -> Dict[str, Any]:
    return {
        "action": "transfer",
        "coin": "ITN",
        "tx_id": tx_id,
        "from_did": from_did,
        "to_did": to_did,
        "amount": amount,
        "timestamp": timestamp,
    }


def generate_agent_did(public_key_hex: str) -> str:
    digest = hashlib.sha256(bytes.fromhex(public_key_hex)).hexdigest()[:32]
    return f"did:identitynet:agent:{digest}"


def court_enroll_payload(
    owner_did: str,
    agent_name: str,
    public_key_hex: str,
    timestamp: str,
) -> Dict[str, Any]:
    return {
        "action": "court_enroll",
        "owner_did": owner_did,
        "agent_name": agent_name,
        "public_key": public_key_hex,
        "timestamp": timestamp,
    }


def agent_register_payload(
    agent_did: str,
    owner_did: str,
    name: str,
    public_key_hex: str,
    timestamp: str,
) -> Dict[str, Any]:
    return {
        "action": "agent_register",
        "agent_did": agent_did,
        "owner_did": owner_did,
        "name": name,
        "public_key": public_key_hex,
        "timestamp": timestamp,
    }


def agent_message_payload(
    contract_id: str,
    message_type: str,
    agent_did: str,
    body: Dict[str, Any],
    timestamp: str,
) -> Dict[str, Any]:
    return {
        "action": "agent_message",
        "contract_id": contract_id,
        "message_type": message_type,
        "agent_did": agent_did,
        "body": body,
        "timestamp": timestamp,
    }


def agent_witness_payload(
    contract_id: str,
    witness_did: str,
    event: str,
    contract_hash: str,
    timestamp: str,
) -> Dict[str, Any]:
    return {
        "action": "agent_witness",
        "contract_id": contract_id,
        "witness_did": witness_did,
        "event": event,
        "contract_hash": contract_hash,
        "timestamp": timestamp,
    }


def agent_settle_payload(
    contract_id: str,
    payer_did: str,
    total_amount: float,
    timestamp: str,
) -> Dict[str, Any]:
    return {
        "action": "agent_settle",
        "contract_id": contract_id,
        "payer_did": payer_did,
        "total_amount": total_amount,
        "timestamp": timestamp,
    }
