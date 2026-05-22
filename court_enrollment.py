"""
Court enrollment — user DID must exist; links ITN wallet to a court agent for debate rewards.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from sqlalchemy.orm import Session

from agent_parliament import agent_parliament
from agent_persistence import persist_agent
from crypto_utils import (
    court_enroll_payload,
    verify_payload,
)
from database import Agent, User
from distributed_ledger import distributed_ledger
from itn import get_itn_summary, init_itn_files


def get_court_agent_for_owner(owner_did: str) -> Optional[Dict[str, Any]]:
    for agent in agent_parliament.agents.values():
        if agent.get("owner_did") == owner_did and agent.get("court_enrolled"):
            return agent
    return None


def enroll_in_court(
    db: Session,
    owner_did: str,
    agent_name: str,
    public_key_hex: str,
    signature: str,
    timestamp: str,
) -> Dict[str, Any]:
    user = db.query(User).filter(User.did == owner_did).first()
    if not user:
        raise ValueError("Create your identity first (POST /users/create)")

    if user.public_key != public_key_hex:
        raise ValueError("public_key must match your registered identity key")

    enroll_pl = court_enroll_payload(owner_did, agent_name, public_key_hex, timestamp)
    if not verify_payload(public_key_hex, enroll_pl, signature):
        raise ValueError("Invalid court enrollment signature")

    existing = db.query(Agent).filter(
        Agent.owner_did == owner_did, Agent.court_enrolled == True
    ).first()
    if existing:
        agent = agent_parliament.get_agent(existing.agent_did)
        if not agent:
            agent = {
                "agent_did": existing.agent_did,
                "owner_did": owner_did,
                "name": existing.name,
                "public_key": existing.public_key,
                "court_enrolled": True,
            }
        return _enrollment_response(db, user, agent, already_enrolled=True)

    record = agent_parliament.register_court_agent(
        owner_did=owner_did,
        name=agent_name,
        public_key_hex=public_key_hex,
        court_signature=signature,
        timestamp=timestamp,
    )

    distributed_ledger.register_identity(owner_did, user.public_key)
    distributed_ledger.register_identity(record["agent_did"], public_key_hex)
    init_itn_files(owner_did, user.public_key)

    row = persist_agent(db, record)
    row.court_enrolled = True
    db.commit()
    db.refresh(row)

    return _enrollment_response(db, user, record, already_enrolled=False)


def _enrollment_response(
    db: Session,
    user: User,
    agent: Dict[str, Any],
    already_enrolled: bool = False,
) -> Dict[str, Any]:
    user.token_balance = distributed_ledger.get_balance(user.did)
    db.commit()
    wallet = get_itn_summary(user.did, user.public_key)
    return {
        "owner_did": user.did,
        "user_id": user.id,
        "username": user.username,
        "agent_did": agent["agent_did"],
        "agent_name": agent["name"],
        "court_enrolled": True,
        "already_enrolled": already_enrolled,
        "wallet": wallet,
        "ledger_balance": user.token_balance,
        "message": "Your DID is linked to your court agent and ITN wallet.",
    }


def court_status(db: Session, owner_did: str) -> Dict[str, Any]:
    user = db.query(User).filter(User.did == owner_did).first()
    if not user:
        raise ValueError("DID not found — create identity first")

    row = db.query(Agent).filter(
        Agent.owner_did == owner_did, Agent.court_enrolled == True
    ).first()
    agent = None
    if row:
        agent = agent_parliament.get_agent(row.agent_did) or {
            "agent_did": row.agent_did,
            "name": row.name,
            "debate_wins": row.debate_wins or 0,
        }

    init_itn_files(user.did, user.public_key)
    wallet = get_itn_summary(user.did, user.public_key)
    return {
        "owner_did": user.did,
        "user_id": user.id,
        "has_identity": True,
        "court_enrolled": row is not None,
        "agent_did": row.agent_did if row else None,
        "agent_name": row.name if row else None,
        "debate_wins": row.debate_wins if row else 0,
        "wallet": wallet,
        "ledger_balance": distributed_ledger.get_balance(user.did),
    }
