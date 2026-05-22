"""
Apply P2P messages to local SQLite cache (IPFS remains canonical source).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from database import User, Reputation, Attestation, TokenTransaction
from distributed_ledger import distributed_ledger

logger = logging.getLogger(__name__)


def upsert_user_from_network(db: Session, user_data: Dict[str, Any]) -> Optional[User]:
    did = user_data.get("did")
    if not did:
        return None

    user = db.query(User).filter(User.did == did).first()
    if user:
        user.synced = True
        if user_data.get("ipfs_hash"):
            user.ipfs_hash = user_data["ipfs_hash"]
        db.commit()
        return user

    username = user_data.get("username")
    if not username:
        return None
    if db.query(User).filter(User.username == username).first():
        logger.warning("Skipping network user sync — username taken locally: %s", username)
        return None

    user = User(
        did=did,
        username=username,
        email=user_data.get("email"),
        public_key=user_data["public_key"],
        ipfs_hash=user_data.get("ipfs_hash"),
        node_id=user_data.get("node_id"),
        synced=True,
        is_verified=user_data.get("is_verified", False),
    )
    db.add(user)
    db.add(Reputation(user=user))
    db.commit()
    db.refresh(user)
    distributed_ledger.register_identity(did, user.public_key)
    return user


def persist_attestation_from_network(db: Session, data: Dict[str, Any]) -> None:
    subject_did = data.get("subject_did")
    user = db.query(User).filter(User.did == subject_did).first()
    if not user:
        return
    existing = (
        db.query(Attestation)
        .filter(
            Attestation.user_id == user.id,
            Attestation.attester_did == data.get("attester_did"),
            Attestation.attestation_type == data.get("attestation_type"),
            Attestation.signature == data.get("signature"),
        )
        .first()
    )
    if existing:
        return

    att = Attestation(
        user_id=user.id,
        subject_did=subject_did,
        attester_did=data["attester_did"],
        attester_public_key=data.get("attester_public_key"),
        attestation_type=data["attestation_type"],
        data=data.get("data"),
        signature=data["signature"],
        network_synced=True,
    )
    db.add(att)
    reputation = db.query(Reputation).filter(Reputation.user_id == user.id).first()
    if reputation:
        reputation.total_reviews += 1
        reputation.positive_reviews += 1
        if reputation.total_reviews:
            reputation.score = (
                reputation.positive_reviews / reputation.total_reviews
            ) * 100
        reputation.last_updated = datetime.utcnow()
    db.commit()


def persist_ledger_tx(db: Session, tx: Dict[str, Any]) -> None:
    did = tx.get("did")
    user = db.query(User).filter(User.did == did).first()
    if not user:
        return
    if tx.get("tx_id") and db.query(TokenTransaction).filter(
        TokenTransaction.tx_id == tx["tx_id"]
    ).first():
        return

    record = TokenTransaction(
        tx_id=tx.get("tx_id"),
        user_id=user.id,
        signer_did=did,
        transaction_type=tx["transaction_type"],
        amount=float(tx["amount"]),
        description=tx.get("description"),
        signature=tx.get("signature"),
        network_synced=True,
    )
    db.add(record)
    user.token_balance = distributed_ledger.get_balance(did)
    db.commit()


def store_commitment(db: Session, user_id: int, attribute: str, commitment: str, salt: str) -> None:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return
    existing = {}
    if user.disclosure_commitments:
        try:
            existing = json.loads(user.disclosure_commitments)
        except json.JSONDecodeError:
            existing = {}
    existing[attribute] = {"commitment": commitment, "salt": salt}
    user.disclosure_commitments = json.dumps(existing)
    db.commit()
