"""
Network-wide signed token ledger replicated over IPFS PubSub.
Balances are derived from verified transactions, not local-only counters.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from crypto_utils import ledger_payload, transfer_payload, verify_payload

logger = logging.getLogger(__name__)


class DistributedLedger:
    def __init__(self) -> None:
        self.transactions: Dict[str, Dict[str, Any]] = {}  # tx_id -> tx
        self.balances: Dict[str, float] = {}  # did -> balance
        self.public_keys: Dict[str, str] = {}  # did -> public_key hex

    def register_identity(self, did: str, public_key_hex: str) -> None:
        self.public_keys[did] = public_key_hex

    def _tx_id(self, payload: Dict[str, Any], signature: str) -> str:
        raw = f"{payload['did']}:{payload['timestamp']}:{payload['amount']}:{signature}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    def compute_tx_id(
        self, did: str, transaction_type: str, amount: float, timestamp: str
    ) -> str:
        raw = f"{did}:{transaction_type}:{amount}:{timestamp}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    def submit_transaction(
        self,
        did: str,
        public_key_hex: str,
        transaction_type: str,
        amount: float,
        description: Optional[str],
        signature: str,
        timestamp: Optional[str] = None,
        tx_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        ts = timestamp or datetime.utcnow().isoformat()
        if did not in self.public_keys:
            self.register_identity(did, public_key_hex)

        computed_id = tx_id or self.compute_tx_id(
            did, transaction_type, amount, ts
        )
        payload = ledger_payload(
            computed_id,
            did,
            transaction_type,
            amount,
            description,
            ts,
        )

        if not verify_payload(public_key_hex, payload, signature):
            raise ValueError("Invalid ledger transaction signature")

        if computed_id in self.transactions:
            return self.transactions[computed_id]

        tx = {
            **payload,
            "signature": signature,
            "public_key": public_key_hex,
            "received_at": datetime.utcnow().isoformat(),
        }
        self.transactions[computed_id] = tx
        self._apply_balance(did, transaction_type, amount)
        return tx

    def _apply_balance(self, did: str, transaction_type: str, amount: float) -> None:
        current = self.balances.get(did, 0.0)
        if transaction_type in ("earn", "verification", "credit", "referral", "debate_win"):
            self.balances[did] = current + amount
        elif transaction_type in ("spend", "debit"):
            self.balances[did] = current - amount
        else:
            self.balances[did] = current + amount

    def apply_remote_transaction(self, tx: Dict[str, Any]) -> bool:
        """Apply transaction received from another node (already signed)."""
        try:
            tx_id = tx["tx_id"]
            if tx_id in self.transactions:
                return True
            did = tx["did"]
            pub = tx.get("public_key") or self.public_keys.get(did)
            if not pub:
                logger.warning("Unknown DID for ledger tx: %s", did)
                return False

            if tx.get("transaction_type") == "receive":
                self.register_identity(did, pub)
                self.transactions[tx_id] = tx
                self._apply_balance(did, "receive", float(tx["amount"]))
                return True

            self.submit_transaction(
                did=did,
                public_key_hex=pub,
                transaction_type=tx["transaction_type"],
                amount=float(tx["amount"]),
                description=tx.get("description"),
                signature=tx["signature"],
                timestamp=tx["timestamp"],
                tx_id=tx_id,
            )
            return True
        except (ValueError, KeyError) as e:
            logger.warning("Rejected remote ledger tx: %s", e)
            return False

    def get_balance(self, did: str) -> float:
        return self.balances.get(did, 0.0)

    def get_transactions(self, did: str) -> List[Dict[str, Any]]:
        return [t for t in self.transactions.values() if t.get("did") == did]

    def submit_transfer(
        self,
        from_did: str,
        from_public_key: str,
        to_did: str,
        to_public_key: str,
        amount: float,
        signature: str,
        timestamp: str,
        tx_id: str,
    ) -> Dict[str, Any]:
        if amount <= 0:
            raise ValueError("Transfer amount must be positive")
        if self.get_balance(from_did) < amount:
            raise ValueError("Insufficient ITN balance")

        payload = transfer_payload(tx_id, from_did, to_did, amount, timestamp)
        if not verify_payload(from_public_key, payload, signature):
            raise ValueError("Invalid transfer signature")

        out_id = f"{tx_id}-out"
        in_id = f"{tx_id}-in"
        if out_id in self.transactions:
            return {
                "outgoing": self.transactions[out_id],
                "incoming": self.transactions.get(in_id),
            }

        self.register_identity(to_did, to_public_key)
        out_tx = {
            **payload,
            "did": from_did,
            "transaction_type": "transfer",
            "description": f"transfer to {to_did}",
            "signature": signature,
            "public_key": from_public_key,
            "received_at": datetime.utcnow().isoformat(),
        }
        out_tx["tx_id"] = out_id
        self.transactions[out_id] = out_tx
        self._apply_balance(from_did, "transfer", amount)

        in_tx = {
            "action": "receive",
            "tx_id": in_id,
            "did": to_did,
            "transaction_type": "receive",
            "amount": amount,
            "description": f"transfer from {from_did}",
            "timestamp": timestamp,
            "from_did": from_did,
            "transfer_tx_id": tx_id,
            "signature": signature,
            "public_key": to_public_key,
            "received_at": datetime.utcnow().isoformat(),
        }
        self.transactions[in_id] = in_tx
        self._apply_balance(to_did, "receive", amount)
        return {"outgoing": out_tx, "incoming": in_tx}

    def to_broadcast(self, tx: Dict[str, Any]) -> Dict[str, Any]:
        return {k: tx[k] for k in tx if k != "received_at"}


distributed_ledger = DistributedLedger()
