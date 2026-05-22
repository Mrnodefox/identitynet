"""Persist Agent Parliament state to SQLite."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from database import (
    Agent,
    AgentContract,
    AgentParliamentMessage,
    AgentWitness,
    User,
)
from agent_parliament import agent_parliament


def persist_agent(db: Session, record: Dict[str, Any]) -> Agent:
    existing = (
        db.query(Agent).filter(Agent.agent_did == record["agent_did"]).first()
    )
    if existing:
        if record.get("court_enrolled"):
            existing.court_enrolled = True
            db.commit()
        return existing
    owner = db.query(User).filter(User.did == record["owner_did"]).first()
    row = Agent(
        agent_did=record["agent_did"],
        owner_did=record["owner_did"],
        name=record["name"],
        public_key=record["public_key"],
        signature=record["signature"],
        reputation_score=record.get("reputation_score", 50.0),
        contracts_completed=record.get("contracts_completed", 0),
        court_enrolled=bool(record.get("court_enrolled")),
        debate_wins=int(record.get("debate_wins", 0)),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def persist_contract(db: Session, contract: Dict[str, Any]) -> AgentContract:
    row = db.query(AgentContract).filter(
        AgentContract.contract_id == contract["contract_id"]
    ).first()
    terms_json = json.dumps(contract.get("terms") or {})
    delivery_json = (
        json.dumps(contract["delivery_log"])
        if contract.get("delivery_log") is not None
        else None
    )
    if row:
        row.status = contract["status"]
        row.responder_agent_did = contract.get("responder_agent_did")
        row.responder_owner_did = contract.get("responder_owner_did")
        row.escrow_amount = contract.get("escrow_amount", 0.0)
        row.terms_json = terms_json
        row.delivery_log_json = delivery_json
        row.updated_at = datetime.utcnow()
    else:
        row = AgentContract(
            contract_id=contract["contract_id"],
            proposer_agent_did=contract["proposer_agent_did"],
            proposer_owner_did=contract["proposer_owner_did"],
            responder_agent_did=contract.get("responder_agent_did"),
            responder_owner_did=contract.get("responder_owner_did"),
            intent=contract["intent"],
            escrow_amount=contract.get("escrow_amount", 0.0),
            terms_json=terms_json,
            witness_quorum=contract.get("witness_quorum", 1),
            witness_reward=contract.get("witness_reward", 0.05),
            status=contract["status"],
            delivery_log_json=delivery_json,
        )
        db.add(row)
    db.commit()
    db.refresh(row)
    return row


def persist_message(
    db: Session,
    contract_id: str,
    message_type: str,
    agent_did: str,
    body: Dict[str, Any],
    signature: str,
    timestamp: str,
) -> None:
    exists = (
        db.query(AgentParliamentMessage)
        .filter(
            AgentParliamentMessage.contract_id == contract_id,
            AgentParliamentMessage.signature == signature,
        )
        .first()
    )
    if exists:
        return
    db.add(
        AgentParliamentMessage(
            contract_id=contract_id,
            message_type=message_type,
            agent_did=agent_did,
            body_json=json.dumps(body),
            signature=signature,
            timestamp=timestamp,
        )
    )
    db.commit()


def persist_witness_record(db: Session, record: Dict[str, Any]) -> None:
    exists = (
        db.query(AgentWitness)
        .filter(
            AgentWitness.contract_id == record["contract_id"],
            AgentWitness.witness_did == record["witness_did"],
        )
        .first()
    )
    if exists:
        return
    db.add(
        AgentWitness(
            contract_id=record["contract_id"],
            witness_did=record["witness_did"],
            witness_public_key=record["witness_public_key"],
            event=record.get("event", "contract_delivered"),
            contract_hash=record["contract_hash"],
            signature=record["signature"],
            timestamp=record["timestamp"],
        )
    )
    db.commit()


def bootstrap_parliament_from_db(db: Session) -> None:
    agents = db.query(Agent).all()
    contracts = db.query(AgentContract).all()
    messages = db.query(AgentParliamentMessage).all()
    witnesses = db.query(AgentWitness).all()
    agent_parliament.load_from_db(agents, contracts, messages, witnesses)


def apply_remote_parliament(db: Session, message: Dict[str, Any]) -> None:
    kind = message.get("parliament_kind")
    data = message.get("data", message)

    if kind == "agent_register":
        try:
            record = agent_parliament.register_agent(
                owner_did=data["owner_did"],
                name=data["name"],
                public_key_hex=data["public_key"],
                signature=data["signature"],
                timestamp=data["timestamp"],
            )
            persist_agent(db, record)
        except ValueError:
            pass
    elif kind == "contract_offer":
        try:
            contract = agent_parliament.create_offer(
                proposer_agent_did=data["proposer_agent_did"],
                public_key_hex=data["public_key"],
                intent=data["intent"],
                escrow_amount=float(data["escrow_amount"]),
                signature=data["signature"],
                timestamp=data["timestamp"],
                responder_agent_did=data.get("responder_agent_did"),
                terms=data.get("terms"),
                witness_quorum=data.get("witness_quorum"),
            )
            persist_contract(db, contract)
            msgs = agent_parliament.messages.get(contract["contract_id"], [])
            if msgs:
                m = msgs[-1]
                persist_message(
                    db,
                    contract["contract_id"],
                    m["message_type"],
                    m["agent_did"],
                    m["body"],
                    m["signature"],
                    m["timestamp"],
                )
        except ValueError:
            pass
    elif kind == "contract_message":
        try:
            contract = agent_parliament.post_message(
                contract_id=data["contract_id"],
                message_type=data["message_type"],
                agent_did=data["agent_did"],
                public_key_hex=data["public_key"],
                body=data.get("body", {}),
                signature=data["signature"],
                timestamp=data["timestamp"],
            )
            persist_contract(db, contract)
            msgs = agent_parliament.messages.get(data["contract_id"], [])
            if msgs:
                m = msgs[-1]
                persist_message(
                    db,
                    data["contract_id"],
                    m["message_type"],
                    m["agent_did"],
                    m["body"],
                    m["signature"],
                    m["timestamp"],
                )
        except ValueError:
            pass
    elif kind == "contract_witness":
        try:
            contract, _ = agent_parliament.add_witness(
                contract_id=data["contract_id"],
                witness_did=data["witness_did"],
                witness_public_key=data["witness_public_key"],
                event=data.get("event", "contract_delivered"),
                signature=data["signature"],
                timestamp=data["timestamp"],
            )
            persist_contract(db, contract)
            wlist = agent_parliament.witnesses.get(data["contract_id"], [])
            if wlist:
                persist_witness_record(db, wlist[-1])
        except ValueError:
            pass
