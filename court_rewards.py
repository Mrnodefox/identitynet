"""
Pay ITN debate win rewards from chamber treasury to the player's owner DID wallet.
"""

from __future__ import annotations

import os
import secrets
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from crypto_utils import ledger_payload, sign_payload, transfer_payload
from database import Agent, TokenTransaction, User
from debate_engine import get_case, poll_option_favors_side
from debate_orchestrator import _load_or_create_chamber_keys
from distributed_ledger import distributed_ledger
from itn import record_itn_transaction

DEBATE_WIN_REWARD = float(os.getenv("DEBATE_WIN_REWARD", "1.0"))
TREASURY_BOOTSTRAP = float(os.getenv("CHAMBER_TREASURY_ITN", "10000"))


def _ensure_treasury_balance() -> tuple:
    chamber_did, chamber_pub, chamber_priv = _load_or_create_chamber_keys()
    distributed_ledger.register_identity(chamber_did, chamber_pub)
    bal = distributed_ledger.get_balance(chamber_did)
    if bal < DEBATE_WIN_REWARD:
        ts = datetime.utcnow().isoformat()
        tx_id = secrets.token_hex(16)
        amount = TREASURY_BOOTSTRAP
        payload = ledger_payload(
            tx_id, chamber_did, "credit", amount, "Chamber treasury bootstrap", ts
        )
        sig = sign_payload(chamber_priv, payload)
        try:
            distributed_ledger.submit_transaction(
                did=chamber_did,
                public_key_hex=chamber_pub,
                transaction_type="credit",
                amount=amount,
                description=payload["description"],
                signature=sig,
                timestamp=ts,
                tx_id=tx_id,
            )
        except ValueError:
            pass
    return chamber_did, chamber_pub, chamber_priv


def award_debate_win(
    db: Session,
    session: Dict[str, Any],
    option_id: str,
) -> Dict[str, Any]:
    case = get_case(session.get("case_id", ""))
    if not case:
        raise ValueError("Case not found")

    player_owner = session.get("player_owner_did")
    player_side = session.get("player_side")
    player_agent = session.get("player_agent_did")

    if not player_owner or not player_side:
        return {
            "won": False,
            "reward_itn": 0.0,
            "reason": "No player counsel registered for this session",
        }

    favors = poll_option_favors_side(case, option_id)
    if favors not in ("proposer", "responder"):
        return {
            "won": False,
            "reward_itn": 0.0,
            "reason": "Poll option does not declare a winning side",
            "favors_side": favors,
        }

    if favors != player_side:
        return {
            "won": False,
            "reward_itn": 0.0,
            "reason": f"Chamber ruled for {favors}; you represented {player_side}",
            "favors_side": favors,
            "player_side": player_side,
        }

    winner = db.query(User).filter(User.did == player_owner).first()
    if not winner:
        raise ValueError("Winner DID not found")

    chamber_did, chamber_pub, chamber_priv = _ensure_treasury_balance()
    if distributed_ledger.get_balance(chamber_did) < DEBATE_WIN_REWARD:
        raise ValueError("Chamber treasury insufficient for reward")

    ts = datetime.utcnow().isoformat()
    tx_id = f"win-{session.get('session_id', '')[:8]}-{secrets.token_hex(4)}"
    payload = transfer_payload(
        tx_id, chamber_did, player_owner, DEBATE_WIN_REWARD, ts
    )
    sig = sign_payload(chamber_priv, payload)

    result = distributed_ledger.submit_transfer(
        from_did=chamber_did,
        from_public_key=chamber_pub,
        to_did=player_owner,
        to_public_key=winner.public_key,
        amount=DEBATE_WIN_REWARD,
        signature=sig,
        timestamp=ts,
        tx_id=tx_id,
    )
    in_tx = result["incoming"]
    winner.token_balance = distributed_ledger.get_balance(player_owner)

    db.add(
        TokenTransaction(
            tx_id=in_tx["tx_id"],
            user_id=winner.id,
            signer_did=player_owner,
            transaction_type="receive",
            amount=DEBATE_WIN_REWARD,
            description=f"Debate win: {case.get('title', session.get('case_id'))}",
            signature=sig,
            network_synced=False,
        )
    )

    if player_agent:
        row = db.query(Agent).filter(Agent.agent_did == player_agent).first()
        if row:
            row.debate_wins = (row.debate_wins or 0) + 1
            from agent_parliament import agent_parliament

            if player_agent in agent_parliament.agents:
                agent_parliament.agents[player_agent]["debate_wins"] = row.debate_wins
                agent_parliament.agents[player_agent]["contracts_completed"] = (
                    agent_parliament.agents[player_agent].get("contracts_completed", 0) + 1
                )

    record_itn_transaction(
        did=player_owner,
        public_key=winner.public_key,
        balance=winner.token_balance,
        transaction_type="receive",
        amount=DEBATE_WIN_REWARD,
        tx_id=in_tx["tx_id"],
        signature=sig,
        timestamp=ts,
        counterparty_did=chamber_did,
        description=in_tx.get("description"),
    )
    db.commit()

    return {
        "won": True,
        "reward_itn": DEBATE_WIN_REWARD,
        "winner_did": player_owner,
        "player_agent_did": player_agent,
        "player_side": player_side,
        "favors_side": favors,
        "tx_id": tx_id,
        "new_balance": winner.token_balance,
        "reason": "Chamber ruled in your favor — ITN credited to your wallet",
    }
