"""
Agent Parliament — signed agent-to-agent contracts with human witnesses.

Agents negotiate (offer → counter → accept → deliver); witnesses attest the
contract hash; the proposer settles ITN transfers to responder + witnesses.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from crypto_utils import (
    agent_message_payload,
    agent_register_payload,
    agent_settle_payload,
    agent_witness_payload,
    canonical_json,
    generate_agent_did,
    verify_payload,
)

logger = logging.getLogger(__name__)

WITNESS_QUORUM = int(os.getenv("AGENT_WITNESS_QUORUM", "1"))
WITNESS_REWARD = float(os.getenv("AGENT_WITNESS_REWARD", "0.05"))
PLATFORM_FEE_RATE = float(os.getenv("AGENT_PLATFORM_FEE_RATE", "0.02"))

VALID_MESSAGE_TYPES = frozenset(
    {"offer", "counter", "accept", "deliver", "reject", "cancel"}
)
TERMINAL_STATUSES = frozenset({"settled", "cancelled", "rejected"})


def contract_hash(contract: Dict[str, Any]) -> str:
    """Stable hash of binding contract terms for witnesses."""
    binding = {
        "contract_id": contract["contract_id"],
        "proposer_agent_did": contract["proposer_agent_did"],
        "responder_agent_did": contract.get("responder_agent_did"),
        "intent": contract.get("intent"),
        "escrow_amount": contract.get("escrow_amount"),
        "terms": contract.get("terms"),
        "status": contract.get("status"),
    }
    return hashlib.sha256(canonical_json(binding).encode()).hexdigest()


def compute_contract_id(proposer_agent_did: str, timestamp: str, intent: str) -> str:
    raw = f"{proposer_agent_did}:{timestamp}:{intent}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


class AgentParliament:
    def __init__(self) -> None:
        self.agents: Dict[str, Dict[str, Any]] = {}
        self.contracts: Dict[str, Dict[str, Any]] = {}
        self.messages: Dict[str, List[Dict[str, Any]]] = {}
        self.witnesses: Dict[str, List[Dict[str, Any]]] = {}

    def register_court_agent(
        self,
        owner_did: str,
        name: str,
        public_key_hex: str,
        court_signature: str,
        timestamp: str,
    ) -> Dict[str, Any]:
        """Register agent after court_enroll signature (same key as user identity)."""
        from crypto_utils import court_enroll_payload

        agent_did = generate_agent_did(public_key_hex)
        payload = court_enroll_payload(
            owner_did, name, public_key_hex, timestamp
        )
        if not verify_payload(public_key_hex, payload, court_signature):
            raise ValueError("Invalid court enrollment signature")

        record = {
            "agent_did": agent_did,
            "owner_did": owner_did,
            "name": name,
            "public_key": public_key_hex,
            "signature": court_signature,
            "timestamp": timestamp,
            "reputation_score": 50.0,
            "contracts_completed": 0,
            "court_enrolled": True,
            "debate_wins": 0,
            "registered_at": datetime.utcnow().isoformat(),
        }
        self.agents[agent_did] = record
        return record

    def register_agent(
        self,
        owner_did: str,
        name: str,
        public_key_hex: str,
        signature: str,
        timestamp: str,
    ) -> Dict[str, Any]:
        agent_did = generate_agent_did(public_key_hex)
        payload = agent_register_payload(
            agent_did, owner_did, name, public_key_hex, timestamp
        )
        if not verify_payload(public_key_hex, payload, signature):
            raise ValueError("Invalid agent registration signature")

        record = {
            **payload,
            "signature": signature,
            "reputation_score": 50.0,
            "contracts_completed": 0,
            "registered_at": datetime.utcnow().isoformat(),
        }
        self.agents[agent_did] = record
        return record

    def get_agent(self, agent_did: str) -> Optional[Dict[str, Any]]:
        return self.agents.get(agent_did)

    def list_agents_for_owner(self, owner_did: str) -> List[Dict[str, Any]]:
        return [a for a in self.agents.values() if a.get("owner_did") == owner_did]

    def create_offer(
        self,
        proposer_agent_did: str,
        public_key_hex: str,
        intent: str,
        escrow_amount: float,
        signature: str,
        timestamp: str,
        responder_agent_did: Optional[str] = None,
        terms: Optional[Dict[str, Any]] = None,
        witness_quorum: Optional[int] = None,
    ) -> Dict[str, Any]:
        agent = self.agents.get(proposer_agent_did)
        if not agent:
            raise ValueError("Unknown agent")
        if agent["public_key"] != public_key_hex:
            raise ValueError("public_key does not match registered agent")

        contract_id = compute_contract_id(proposer_agent_did, timestamp, intent)
        body = {
            "intent": intent,
            "escrow_amount": round(escrow_amount, 8),
            "responder_agent_did": responder_agent_did,
            "terms": terms or {},
        }
        payload = agent_message_payload(
            contract_id, "offer", proposer_agent_did, body, timestamp
        )
        if not verify_payload(public_key_hex, payload, signature):
            raise ValueError("Invalid offer signature")

        contract = {
            "contract_id": contract_id,
            "proposer_agent_did": proposer_agent_did,
            "proposer_owner_did": agent["owner_did"],
            "responder_agent_did": responder_agent_did,
            "responder_owner_did": None,
            "intent": intent,
            "escrow_amount": round(escrow_amount, 8),
            "terms": terms or {},
            "witness_quorum": witness_quorum or WITNESS_QUORUM,
            "witness_reward": WITNESS_REWARD,
            "status": "open",
            "created_at": timestamp,
            "updated_at": datetime.utcnow().isoformat(),
            "delivery_log": None,
        }
        self.contracts[contract_id] = contract
        self._append_message(contract_id, payload, signature)
        return contract

    def post_message(
        self,
        contract_id: str,
        message_type: str,
        agent_did: str,
        public_key_hex: str,
        body: Dict[str, Any],
        signature: str,
        timestamp: str,
    ) -> Dict[str, Any]:
        if message_type not in VALID_MESSAGE_TYPES:
            raise ValueError(f"Invalid message_type: {message_type}")

        contract = self.contracts.get(contract_id)
        if not contract:
            raise ValueError("Contract not found")
        if contract["status"] in TERMINAL_STATUSES:
            raise ValueError(f"Contract is {contract['status']}")

        agent = self.agents.get(agent_did)
        if not agent or agent["public_key"] != public_key_hex:
            raise ValueError("Unknown agent or key mismatch")

        payload = agent_message_payload(
            contract_id, message_type, agent_did, body, timestamp
        )
        if not verify_payload(public_key_hex, payload, signature):
            raise ValueError("Invalid message signature")

        self._append_message(contract_id, payload, signature)

        if message_type == "counter":
            if contract["status"] not in ("open", "negotiating"):
                raise ValueError("Cannot counter in current status")
            contract["status"] = "negotiating"
            if agent_did != contract["proposer_agent_did"]:
                contract["responder_agent_did"] = agent_did
                contract["responder_owner_did"] = agent["owner_did"]
            elif not contract.get("responder_agent_did"):
                contract["responder_agent_did"] = agent_did
                contract["responder_owner_did"] = agent["owner_did"]
            if body.get("escrow_amount") is not None:
                contract["escrow_amount"] = round(float(body["escrow_amount"]), 8)
            if body.get("terms"):
                contract["terms"] = {**contract.get("terms", {}), **body["terms"]}

        elif message_type == "accept":
            if contract["status"] not in ("open", "negotiating", "accepted"):
                raise ValueError("Cannot accept in current status")
            proposer = contract["proposer_agent_did"]
            responder = contract.get("responder_agent_did")
            if agent_did not in (proposer, responder):
                raise ValueError("Only contract parties may accept")
            if contract["status"] == "accepted":
                contract["updated_at"] = datetime.utcnow().isoformat()
                return contract
            contract["status"] = "accepted"
            if not contract.get("responder_agent_did"):
                contract["responder_agent_did"] = agent_did
                contract["responder_owner_did"] = agent["owner_did"]

        elif message_type == "deliver":
            if contract["status"] != "accepted":
                raise ValueError("Contract must be accepted before delivery")
            allowed = {
                contract["proposer_agent_did"],
                contract.get("responder_agent_did"),
            }
            if agent_did not in allowed:
                raise ValueError("Only contract parties may deliver")
            contract["status"] = "delivered"
            contract["delivery_log"] = body.get("delivery_log") or body

        elif message_type in ("reject", "cancel"):
            contract["status"] = "rejected" if message_type == "reject" else "cancelled"

        contract["updated_at"] = datetime.utcnow().isoformat()
        return contract

    def add_witness(
        self,
        contract_id: str,
        witness_did: str,
        witness_public_key: str,
        event: str,
        signature: str,
        timestamp: str,
    ) -> Tuple[Dict[str, Any], bool]:
        contract = self.contracts.get(contract_id)
        if not contract:
            raise ValueError("Contract not found")
        if contract["status"] != "delivered":
            raise ValueError("Contract must be delivered before witnessing")

        chash = contract_hash(contract)
        payload = agent_witness_payload(
            contract_id, witness_did, event, chash, timestamp
        )
        if not verify_payload(witness_public_key, payload, signature):
            raise ValueError("Invalid witness signature")

        existing = self.witnesses.get(contract_id, [])
        if any(w["witness_did"] == witness_did for w in existing):
            raise ValueError("Witness already attested this contract")

        record = {
            **payload,
            "signature": signature,
            "witness_public_key": witness_public_key,
            "witnessed_at": datetime.utcnow().isoformat(),
        }
        self.witnesses.setdefault(contract_id, []).append(record)

        quorum = int(contract.get("witness_quorum", WITNESS_QUORUM))
        quorum_met = len(self.witnesses[contract_id]) >= quorum
        if quorum_met:
            contract["status"] = "ready_to_settle"
            contract["updated_at"] = datetime.utcnow().isoformat()

        return contract, quorum_met

    def settlement_plan(self, contract_id: str) -> Dict[str, Any]:
        contract = self.contracts.get(contract_id)
        if not contract:
            raise ValueError("Contract not found")
        if contract["status"] != "ready_to_settle":
            raise ValueError("Contract not ready to settle (need delivery + witness quorum)")

        escrow = float(contract["escrow_amount"])
        reward = float(contract.get("witness_reward", WITNESS_REWARD))
        witnesses = self.witnesses.get(contract_id, [])
        witness_payouts = [
            {"to_did": w["witness_did"], "amount": reward, "reason": "witness_fee"}
            for w in witnesses
        ]
        platform_fee = round(escrow * PLATFORM_FEE_RATE, 8)
        responder_owner = contract.get("responder_owner_did")
        proposer_owner = contract["proposer_owner_did"]

        return {
            "contract_id": contract_id,
            "payer_did": proposer_owner,
            "responder_payout": {
                "to_did": responder_owner,
                "amount": escrow,
                "reason": "contract_escrow",
            },
            "witness_payouts": witness_payouts,
            "platform_fee": platform_fee,
            "total_debit": round(
                escrow + sum(w["amount"] for w in witness_payouts) + platform_fee, 8
            ),
        }

    def mark_settled(self, contract_id: str) -> Dict[str, Any]:
        contract = self.contracts.get(contract_id)
        if not contract:
            raise ValueError("Contract not found")
        contract["status"] = "settled"
        contract["updated_at"] = datetime.utcnow().isoformat()
        for did in (
            contract.get("proposer_agent_did"),
            contract.get("responder_agent_did"),
        ):
            if did and did in self.agents:
                self.agents[did]["contracts_completed"] = (
                    self.agents[did].get("contracts_completed", 0) + 1
                )
                self.agents[did]["reputation_score"] = min(
                    100.0, self.agents[did].get("reputation_score", 50) + 2.0
                )
        return contract

    def get_contract(self, contract_id: str) -> Optional[Dict[str, Any]]:
        c = self.contracts.get(contract_id)
        if not c:
            return None
        return {
            **c,
            "contract_hash": contract_hash(c),
            "messages": self.messages.get(contract_id, []),
            "witnesses": self.witnesses.get(contract_id, []),
        }

    def list_contracts(
        self,
        agent_did: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        out = []
        for cid, c in self.contracts.items():
            if agent_did and agent_did not in (
                c.get("proposer_agent_did"),
                c.get("responder_agent_did"),
            ):
                continue
            if status and c.get("status") != status:
                continue
            out.append(
                {
                    **c,
                    "contract_hash": contract_hash(c),
                    "witness_count": len(self.witnesses.get(cid, [])),
                }
            )
        return sorted(out, key=lambda x: x.get("created_at", ""), reverse=True)

    def _append_message(
        self, contract_id: str, payload: Dict[str, Any], signature: str
    ) -> None:
        self.messages.setdefault(contract_id, []).append(
            {**payload, "signature": signature}
        )

    def load_from_db(self, agents: List[Any], contracts: List[Any], messages: List[Any], witnesses: List[Any]) -> None:
        for a in agents:
            self.agents[a.agent_did] = {
                "agent_did": a.agent_did,
                "owner_did": a.owner_did,
                "name": a.name,
                "public_key": a.public_key,
                "timestamp": a.created_at.isoformat() if a.created_at else "",
                "signature": a.signature,
                "reputation_score": a.reputation_score,
                "contracts_completed": a.contracts_completed,
                "court_enrolled": getattr(a, "court_enrolled", False),
                "debate_wins": getattr(a, "debate_wins", 0) or 0,
                "registered_at": a.created_at.isoformat() if a.created_at else "",
            }
        for c in contracts:
            terms = {}
            if c.terms_json:
                try:
                    terms = json.loads(c.terms_json)
                except json.JSONDecodeError:
                    pass
            delivery = None
            if c.delivery_log_json:
                try:
                    delivery = json.loads(c.delivery_log_json)
                except json.JSONDecodeError:
                    pass
            self.contracts[c.contract_id] = {
                "contract_id": c.contract_id,
                "proposer_agent_did": c.proposer_agent_did,
                "proposer_owner_did": c.proposer_owner_did,
                "responder_agent_did": c.responder_agent_did,
                "responder_owner_did": c.responder_owner_did,
                "intent": c.intent,
                "escrow_amount": c.escrow_amount,
                "terms": terms,
                "witness_quorum": c.witness_quorum,
                "witness_reward": c.witness_reward,
                "status": c.status,
                "created_at": c.created_at.isoformat() if c.created_at else "",
                "updated_at": c.updated_at.isoformat() if c.updated_at else "",
                "delivery_log": delivery,
            }
        for m in messages:
            body = {}
            if m.body_json:
                try:
                    body = json.loads(m.body_json)
                except json.JSONDecodeError:
                    pass
            payload = agent_message_payload(
                m.contract_id,
                m.message_type,
                m.agent_did,
                body,
                m.timestamp,
            )
            self._append_message(m.contract_id, payload, m.signature)
        for w in witnesses:
            self.witnesses.setdefault(w.contract_id, []).append(
                {
                    "contract_id": w.contract_id,
                    "witness_did": w.witness_did,
                    "event": w.event,
                    "contract_hash": w.contract_hash,
                    "timestamp": w.timestamp,
                    "signature": w.signature,
                    "witness_public_key": w.witness_public_key,
                    "witnessed_at": w.created_at.isoformat() if w.created_at else "",
                }
            )

    def to_broadcast(
        self, kind: str, data: Dict[str, Any]
    ) -> Dict[str, Any]:
        return {"parliament_kind": kind, **data}


agent_parliament = AgentParliament()
