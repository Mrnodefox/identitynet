"""
ITN (IdentityNet Token) — file-based coin storage bound to user Ed25519 keys.

- data/ITN/{did}.itn       Wallet snapshot signed by the user's private key
- data/balance/{did}.balance.json   Full history: earned, transferred, received
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from crypto_utils import canonical_json, verify_payload

COIN_SYMBOL = "ITN"
ITN_VERSION = 1

ITN_DIR = Path(os.getenv("ITN_DIR", "data/ITN"))
BALANCE_DIR = Path(os.getenv("BALANCE_DIR", "data/balance"))

EARN_TYPES = frozenset({"earn", "verification", "credit", "referral"})
OUT_TYPES = frozenset({"spend", "debit", "transfer"})
IN_TYPES = frozenset({"receive", "transfer_in"})


def _ensure_dirs() -> None:
    ITN_DIR.mkdir(parents=True, exist_ok=True)
    BALANCE_DIR.mkdir(parents=True, exist_ok=True)


def _safe_did_filename(did: str) -> str:
    return did.replace(":", "_")


def itn_wallet_path(did: str) -> Path:
    return ITN_DIR / f"{_safe_did_filename(did)}.itn"


def balance_file_path(did: str) -> Path:
    return BALANCE_DIR / f"{_safe_did_filename(did)}.balance.json"


def wallet_binding_payload(
    did: str, public_key: str, balance: float, last_tx_id: Optional[str]
) -> Dict[str, Any]:
    return {
        "coin": COIN_SYMBOL,
        "did": did,
        "public_key": public_key,
        "balance": round(balance, 8),
        "last_tx_id": last_tx_id,
        "updated_at": datetime.utcnow().isoformat(),
    }


def ledger_type_to_balance_entry(transaction_type: str, did: str, counterparty: Optional[str]) -> str:
    """Map ledger transaction_type to balance file entry type."""
    if transaction_type in EARN_TYPES:
        return "earned"
    if transaction_type in IN_TYPES or (
        transaction_type == "transfer" and counterparty
    ):
        return "received"
    if transaction_type in OUT_TYPES:
        return "transferred"
    return "earned"


def _empty_balance_doc(did: str, public_key: str) -> Dict[str, Any]:
    return {
        "coin": COIN_SYMBOL,
        "version": ITN_VERSION,
        "did": did,
        "public_key": public_key,
        "summary": {
            "earned": 0.0,
            "transferred": 0.0,
            "received": 0.0,
            "balance": 0.0,
        },
        "entries": [],
        "updated_at": datetime.utcnow().isoformat(),
    }


def load_balance_file(did: str, public_key: str) -> Dict[str, Any]:
    _ensure_dirs()
    path = balance_file_path(did)
    if not path.exists():
        return _empty_balance_doc(did, public_key)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_itn_wallet(did: str, public_key: str) -> Dict[str, Any]:
    _ensure_dirs()
    path = itn_wallet_path(did)
    if not path.exists():
        return {
            "coin": COIN_SYMBOL,
            "version": ITN_VERSION,
            "did": did,
            "public_key": public_key,
            "balance": 0.0,
            "last_tx_id": None,
            "updated_at": datetime.utcnow().isoformat(),
            "binding": None,
        }
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def verify_itn_binding(wallet: Dict[str, Any]) -> bool:
    binding = wallet.get("binding")
    if not binding:
        return wallet.get("balance", 0) == 0
    payload = binding.get("payload")
    signature = binding.get("signature")
    pub = wallet.get("public_key")
    if not payload or not signature or not pub:
        return False
    return verify_payload(pub, payload, signature)


def _recompute_summary(entries: List[Dict[str, Any]]) -> Dict[str, float]:
    earned = transferred = received = 0.0
    for e in entries:
        amt = float(e.get("amount", 0))
        t = e.get("type")
        if t == "earned":
            earned += amt
        elif t == "transferred":
            transferred += amt
        elif t == "received":
            received += amt
    balance = earned + received - transferred
    return {
        "earned": round(earned, 8),
        "transferred": round(transferred, 8),
        "received": round(received, 8),
        "balance": round(balance, 8),
    }


def append_balance_entry(
    did: str,
    public_key: str,
    entry_type: str,
    amount: float,
    tx_id: str,
    signature: str,
    timestamp: str,
    counterparty_did: Optional[str] = None,
    description: Optional[str] = None,
) -> Dict[str, Any]:
    """Append earned / transferred / received row to balance file."""
    _ensure_dirs()
    doc = load_balance_file(did, public_key)
    entry = {
        "tx_id": tx_id,
        "type": entry_type,
        "amount": round(float(amount), 8),
        "counterparty_did": counterparty_did,
        "description": description,
        "timestamp": timestamp,
        "signature": signature,
    }
    if any(e.get("tx_id") == tx_id and e.get("type") == entry_type for e in doc["entries"]):
        return doc
    doc["entries"].append(entry)
    doc["summary"] = _recompute_summary(doc["entries"])
    doc["updated_at"] = datetime.utcnow().isoformat()
    path = balance_file_path(did)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2)
    return doc


def update_itn_balance_unsealed(
    did: str, public_key: str, balance: float, last_tx_id: Optional[str]
) -> Dict[str, Any]:
    """Update balance on .itn file when user has not yet re-sealed with wallet_signature."""
    _ensure_dirs()
    wallet = load_itn_wallet(did, public_key)
    wallet["balance"] = round(balance, 8)
    wallet["last_tx_id"] = last_tx_id
    wallet["updated_at"] = datetime.utcnow().isoformat()
    wallet["binding_status"] = "pending_seal"
    path = itn_wallet_path(did)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(wallet, f, indent=2)
    return wallet


def write_itn_wallet(
    did: str,
    public_key: str,
    balance: float,
    last_tx_id: Optional[str],
    binding_signature: str,
    binding_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Write .itn wallet file with balance bound to user's private key via Ed25519 signature.
    binding_payload must be the exact object that was signed (timestamps must match).
    """
    _ensure_dirs()
    payload = binding_payload or wallet_binding_payload(
        did, public_key, balance, last_tx_id
    )
    if not verify_payload(public_key, payload, binding_signature):
        raise ValueError("Invalid ITN wallet binding signature")

    wallet = {
        "coin": COIN_SYMBOL,
        "version": ITN_VERSION,
        "did": did,
        "public_key": public_key,
        "balance": round(balance, 8),
        "last_tx_id": last_tx_id,
        "updated_at": payload["updated_at"],
        "binding_status": "sealed",
        "binding": {
            "payload": payload,
            "signature": binding_signature,
            "algorithm": "ed25519",
        },
    }
    path = itn_wallet_path(did)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(wallet, f, indent=2)
    return wallet


def record_itn_transaction(
    did: str,
    public_key: str,
    balance: float,
    transaction_type: str,
    amount: float,
    tx_id: str,
    signature: str,
    timestamp: str,
    counterparty_did: Optional[str] = None,
    description: Optional[str] = None,
    wallet_binding: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Update ITN wallet + balance file after a ledger event.
    wallet_binding: {payload, signature} from GET /itn/wallet-payload signed by private key.
    If omitted, balance file is updated but .itn stays pending_seal until POST /itn/seal.
    """
    entry_type = ledger_type_to_balance_entry(
        transaction_type, did, counterparty_did
    )
    if transaction_type == "transfer" and counterparty_did:
        entry_type = "transferred"
    if transaction_type == "receive":
        entry_type = "received"

    balance_doc = append_balance_entry(
        did=did,
        public_key=public_key,
        entry_type=entry_type,
        amount=amount,
        tx_id=tx_id,
        signature=signature,
        timestamp=timestamp,
        counterparty_did=counterparty_did,
        description=description,
    )
    if wallet_binding and wallet_binding.get("payload") and wallet_binding.get("signature"):
        wallet = write_itn_wallet(
            did=did,
            public_key=public_key,
            balance=balance,
            last_tx_id=tx_id,
            binding_signature=wallet_binding["signature"],
            binding_payload=wallet_binding["payload"],
        )
    else:
        wallet = update_itn_balance_unsealed(
            did, public_key, balance, tx_id
        )
    return {"wallet": wallet, "balance": balance_doc}


def init_itn_files(did: str, public_key: str) -> None:
    """Create empty ITN + balance files for a new user."""
    _ensure_dirs()
    load_balance_file(did, public_key)
    wallet_path = itn_wallet_path(did)
    if not wallet_path.exists():
        wallet = {
            "coin": COIN_SYMBOL,
            "version": ITN_VERSION,
            "did": did,
            "public_key": public_key,
            "balance": 0.0,
            "last_tx_id": None,
            "updated_at": datetime.utcnow().isoformat(),
            "binding": None,
        }
        with open(wallet_path, "w", encoding="utf-8") as f:
            json.dump(wallet, f, indent=2)


def get_itn_summary(did: str, public_key: str) -> Dict[str, Any]:
    wallet = load_itn_wallet(did, public_key)
    balance_doc = load_balance_file(did, public_key)
    return {
        "coin": COIN_SYMBOL,
        "did": did,
        "wallet_file": str(itn_wallet_path(did)),
        "balance_file": str(balance_file_path(did)),
        "wallet": wallet,
        "balance": balance_doc,
        "binding_valid": verify_itn_binding(wallet),
    }
