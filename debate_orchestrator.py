"""
Orchestrate signed Agent Parliament debates from real-world case files.
"""

from __future__ import annotations

import json
import logging
import secrets
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from agent_parliament import agent_parliament, compute_contract_id
from agent_persistence import persist_agent, persist_contract, persist_message
from crypto_utils import (
    agent_message_payload,
    agent_register_payload,
    generate_agent_did,
    generate_did,
    generate_keypair,
    registration_payload,
    sign_payload,
)
from database import Agent, User, Reputation
from court_enrollment import get_court_agent_for_owner
from debate_engine import (
    build_transcript_lines,
    get_case,
    get_poll_from_case,
    store_session,
)

logger = logging.getLogger(__name__)

PARLIAMENT_USERNAME = "parliament_chamber"
CHAMBER_KEYS_PATH = Path(__file__).parent / "data" / "parliament_chamber.json"


def _load_or_create_chamber_keys() -> Tuple[str, str, str]:
    if CHAMBER_KEYS_PATH.exists():
        data = json.loads(CHAMBER_KEYS_PATH.read_text(encoding="utf-8"))
        return data["did"], data["public_key"], data["private_key"]
    pub, priv = generate_keypair()
    did = generate_did(pub)
    CHAMBER_KEYS_PATH.parent.mkdir(parents=True, exist_ok=True)
    CHAMBER_KEYS_PATH.write_text(
        json.dumps({"did": did, "public_key": pub, "private_key": priv}, indent=2),
        encoding="utf-8",
    )
    return did, pub, priv


def ensure_parliament_owner(db: Session) -> User:
    did, pub, _priv = _load_or_create_chamber_keys()
    user = db.query(User).filter(User.did == did).first()
    if user:
        return user

    ts = datetime.utcnow().isoformat()
    payload = registration_payload(PARLIAMENT_USERNAME, None, pub, ts)
    sig = sign_payload(_load_or_create_chamber_keys()[2], payload)

    user = User(
        did=did,
        username=PARLIAMENT_USERNAME,
        email=None,
        public_key=pub,
        is_verified=True,
        synced=False,
    )
    db.add(user)
    db.add(Reputation(user=user))
    db.commit()
    db.refresh(user)
    from distributed_ledger import distributed_ledger

    distributed_ledger.register_identity(did, pub)
    return user


def _sign_message(
    contract_id: str,
    message_type: str,
    agent_did: str,
    private_key: str,
    body: Dict[str, Any],
    timestamp: str,
) -> str:
    payload = agent_message_payload(
        contract_id, message_type, agent_did, body, timestamp
    )
    return sign_payload(private_key, payload)


def run_debate(
    db: Session,
    case_id: str,
    use_llm: bool = False,
    player_owner_did: Optional[str] = None,
    player_side: Optional[str] = None,
) -> Dict[str, Any]:
    case = get_case(case_id)
    if not case:
        raise ValueError(f"Unknown debate case: {case_id}")

    owner = ensure_parliament_owner(db)
    owner_did = owner.did

    proposer_pub, proposer_priv = generate_keypair()
    responder_pub, responder_priv = generate_keypair()
    ts = datetime.utcnow().isoformat()

    proposer_name = case.get("proposer_role", "Proposer")
    responder_name = case.get("responder_role", "Responder")

    for name, pub, priv in (
        (proposer_name, proposer_pub, proposer_priv),
        (responder_name, responder_pub, responder_priv),
    ):
        agent_did = generate_agent_did(pub)
        reg_pl = agent_register_payload(agent_did, owner_did, name, pub, ts)
        reg_sig = sign_payload(priv, reg_pl)
        record = agent_parliament.register_agent(
            owner_did=owner_did,
            name=name,
            public_key_hex=pub,
            signature=reg_sig,
            timestamp=ts,
        )
        persist_agent(db, record)

    proposer_did = generate_agent_did(proposer_pub)
    responder_did = generate_agent_did(responder_pub)
    intent = f"debate:{case_id}"
    escrow = float(case.get("escrow_amount", 0.1))

    terms = {
        "category": case.get("category"),
        "summary": case.get("summary"),
        "case_id": case_id,
        "debate_title": case["title"],
    }
    offer_body = {
        "intent": intent,
        "escrow_amount": round(escrow, 8),
        "responder_agent_did": responder_did,
        "terms": terms,
    }
    contract_id = compute_contract_id(proposer_did, ts, intent)
    offer_sig = _sign_message(
        contract_id, "offer", proposer_did, proposer_priv, offer_body, ts
    )

    contract = agent_parliament.create_offer(
        proposer_agent_did=proposer_did,
        public_key_hex=proposer_pub,
        intent=intent,
        escrow_amount=escrow,
        signature=offer_sig,
        timestamp=ts,
        responder_agent_did=responder_did,
        terms=terms,
    )
    player_agent_did = None
    player_counsel_name = None
    if player_owner_did:
        row = db.query(Agent).filter(
            Agent.owner_did == player_owner_did, Agent.court_enrolled == True
        ).first()
        court = get_court_agent_for_owner(player_owner_did)
        if not row and not court:
            raise ValueError(
                "Enroll your DID in court first (POST /agents/court/enroll)"
            )
        player_agent_did = (court or {}).get("agent_did") or row.agent_did
        player_counsel_name = (court or {}).get("name") or row.name
        player_side = player_side if player_side in ("proposer", "responder") else "proposer"
        if player_side == "proposer":
            contract["proposer_owner_did"] = player_owner_did
            proposer_name = f"{player_counsel_name} (Your counsel)"
        else:
            contract["responder_owner_did"] = player_owner_did
            contract["responder_agent_did"] = player_agent_did
            responder_name = f"{player_counsel_name} (Your counsel)"
        terms["player_owner_did"] = player_owner_did
        terms["player_agent_did"] = player_agent_did
        terms["player_side"] = player_side
        agent_parliament.contracts[contract_id].update(
            {
                "proposer_owner_did": contract.get("proposer_owner_did"),
                "responder_owner_did": contract.get("responder_owner_did"),
            }
        )

    contract["terms"] = {**terms, "poll": get_poll_from_case(case)}
    agent_parliament.contracts[contract_id]["terms"] = contract["terms"]
    persist_contract(db, contract)
    persist_message(
        db, contract_id, "offer", proposer_did, offer_body, offer_sig, ts
    )

    transcript: List[Dict[str, Any]] = []

    def post_turn(
        message_type: str,
        agent_did: str,
        pub: str,
        priv: str,
        body: Dict[str, Any],
        speaker: str,
        side: str,
    ) -> None:
        nonlocal ts
        ts = datetime.utcnow().isoformat()
        sig = _sign_message(contract_id, message_type, agent_did, priv, body, ts)
        agent_parliament.post_message(
            contract_id=contract_id,
            message_type=message_type,
            agent_did=agent_did,
            public_key_hex=pub,
            body=body,
            signature=sig,
            timestamp=ts,
        )
        c = agent_parliament.contracts[contract_id]
        persist_contract(db, c)
        msgs = agent_parliament.messages[contract_id]
        m = msgs[-1]
        persist_message(
            db,
            contract_id,
            m["message_type"],
            m["agent_did"],
            m["body"],
            m["signature"],
            m["timestamp"],
        )
        text = (
            body.get("argument")
            or body.get("accepted")
            or (body.get("delivery_log") or {}).get("resolution")
            or case["title"]
        )
        if isinstance(text, bool):
            text = "Motion accepted." if text else "Motion rejected."
        transcript.append(
            {
                "side": side,
                "speaker": speaker,
                "text": str(text),
                "message_type": message_type,
            }
        )

    phases = case.get("phases", {})
    counter = phases.get("counter", {})
    if counter.get("responder"):
        post_turn(
            "counter",
            responder_did,
            responder_pub,
            responder_priv,
            {"argument": counter["responder"], "case_id": case_id, "escrow_amount": escrow},
            responder_name,
            "responder",
        )
    if counter.get("proposer"):
        post_turn(
            "counter",
            proposer_did,
            proposer_pub,
            proposer_priv,
            {"argument": counter["proposer"], "case_id": case_id},
            proposer_name,
            "proposer",
        )

    accept = phases.get("accept", {})
    if accept.get("responder"):
        post_turn(
            "accept",
            responder_did,
            responder_pub,
            responder_priv,
            {"accepted": True, "argument": accept["responder"]},
            responder_name,
            "responder",
        )
    if accept.get("proposer"):
        post_turn(
            "accept",
            proposer_did,
            proposer_pub,
            proposer_priv,
            {"accepted": True, "argument": accept["proposer"]},
            proposer_name,
            "proposer",
        )

    deliver = phases.get("deliver", {})
    delivery_log = {
        "case_id": case_id,
        "title": case["title"],
        "resolution": deliver.get("proposer", "Chamber motion delivered."),
        "delivered_at": datetime.utcnow().isoformat(),
    }
    post_turn(
        "deliver",
        proposer_did,
        proposer_pub,
        proposer_priv,
        {"delivery_log": delivery_log, "argument": deliver.get("proposer", "")},
        proposer_name,
        "proposer",
    )

    full = agent_parliament.get_contract(contract_id)
    ui_lines = build_transcript_lines(case, use_llm=use_llm)

    session_id = secrets.token_hex(12)
    session = {
        "session_id": session_id,
        "case_id": case_id,
        "contract_id": contract_id,
        "started_at": datetime.utcnow().isoformat(),
        "case": {
            "id": case["id"],
            "title": case["title"],
            "category": case.get("category"),
            "summary": case.get("summary"),
        },
        "proposer_agent_did": proposer_did,
        "responder_agent_did": responder_did,
        "proposer_role": proposer_name,
        "responder_role": responder_name,
        "status": full.get("status") if full else "delivered",
        "transcript": ui_lines,
        "signed_messages": transcript,
        "poll": get_poll_from_case(case),
        "player_owner_did": player_owner_did,
        "player_agent_did": player_agent_did,
        "player_side": player_side,
        "player_counsel_name": player_counsel_name,
    }
    store_session(session_id, session)
    return session
