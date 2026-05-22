from fastapi import FastAPI, Depends, HTTPException, status, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.httpsredirect import HTTPSRedirectMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from starlette.templating import Jinja2Templates
from contextlib import asynccontextmanager
from sqlalchemy.orm import Session
from datetime import datetime
import hashlib
import secrets
import json
import os
import hmac
import ssl
from typing import List, Optional
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

from database import engine, get_db, init_db, SessionLocal, User, Reputation, Attestation, TokenTransaction
from schemas import (
    UserCreate, UserResponse, ReputationResponse,
    AttestationCreate, AttestationResponse,
    TokenTransactionCreate, TokenTransactionResponse,
    IdentityVerificationRequest,
    ZKCommitRequest, ZKCommitResponse,
    ZKProofKnowledgeRequest, ZKProofKnowledgeResponse,
    ZKSelectiveDisclosureRequest, ZKVerifyRequest,
    LedgerBalanceResponse,
    ITNTransferCreate,
    ITNSealRequest,
    ITNWalletResponse,
    WalletBinding,
    AgentRegister,
    AgentResponse,
    AgentOfferCreate,
    AgentMessageCreate,
    AgentWitnessCreate,
    AgentSettleCreate,
    AgentSettlePlanResponse,
    AgentContractResponse,
    DebateCaseSummary,
    DebateStartRequest,
    DebateSessionResponse,
    DebateVerdictRequest,
    CourtEnrollRequest,
    CourtEnrollResponse,
    CourtStatusResponse,
)
from debate_engine import (
    list_cases_public,
    get_case,
    get_session,
    list_sessions,
    verdict_for_poll_option,
    poll_option_favors_side,
)
from debate_orchestrator import run_debate
from court_enrollment import enroll_in_court, court_status
from court_rewards import award_debate_win, DEBATE_WIN_REWARD
from itn import (
    record_itn_transaction,
    init_itn_files,
    get_itn_summary,
    wallet_binding_payload,
    load_itn_wallet,
    load_balance_file,
)
from node_manager import node_manager
from crypto_utils import (
    generate_keypair,
    generate_did,
    verify_payload,
    sign_payload,
    registration_payload,
    attestation_payload,
    ledger_payload,
    transfer_payload,
    agent_settle_payload,
)
from agent_parliament import agent_parliament, WITNESS_QUORUM, WITNESS_REWARD
from agent_persistence import (
    bootstrap_parliament_from_db,
    persist_agent,
    persist_contract,
    persist_message,
    persist_witness_record,
    apply_remote_parliament,
)
from distributed_ledger import distributed_ledger
from zk_proofs import (
    create_commitment,
    create_schnorr_proof,
    verify_schnorr_proof,
    selective_disclosure_proof,
    verify_selective_disclosure,
    NACL_AVAILABLE,
)
from network_sync import (
    upsert_user_from_network,
    persist_attestation_from_network,
    persist_ledger_tx,
    store_commitment,
)

try:
    import ipfshttpclient
    IPFS_AVAILABLE = True
except ImportError:
    IPFS_AVAILABLE = False

class SecureHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        
        # Skip security headers for docs endpoint
        if request.url.path in ["/docs", "/openapi.json", "/redoc"]:
            return response
        
        # Security Headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Server"] = "IdentityNet"
        
        # Content Security Policy
        csp = (
            "default-src 'self'; "
            "img-src 'self' data:; "
            "script-src 'self'; "
            "style-src 'self'; "
            "connect-src 'self'; "
            "font-src 'self'; "
            "object-src 'none'; "
            "media-src 'self'; "
            "form-action 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "block-all-mixed-content; "
            "upgrade-insecure-requests"
        )
        response.headers["Content-Security-Policy"] = csp
        
        # Permissions Policy
        permissions_policy = (
            "geolocation=(self), "
            "microphone=(none), "
            "camera=(none)"
        )
        response.headers["Permissions-Policy"] = permissions_policy
        
        return response

# HTTPS/TLS Configuration with Let's Encrypt
SSL_CERT_PATH = os.getenv("SSL_CERT_PATH", "/etc/letsencrypt/live/yourdomain.com/fullchain.pem")
SSL_KEY_PATH = os.getenv("SSL_KEY_PATH", "/etc/letsencrypt/live/yourdomain.com/privkey.pem")
FORCE_HTTPS = os.getenv("FORCE_HTTPS", "false").lower() == "true"

# Request Signing Configuration
API_PRIVATE_KEY = os.getenv("API_PRIVATE_KEY", secrets.token_hex(32))
SIGNATURE_HEADER = "X-Signature"
TIMESTAMP_HEADER = "X-Timestamp"
SIGNATURE_TOLERANCE_SECONDS = 300  # 5 minutes

async def _on_user_sync(message: dict):
    db = SessionLocal()
    try:
        upsert_user_from_network(db, message.get("user_data", {}))
    finally:
        db.close()


async def _on_ledger_tx(message: dict):
    tx = message.get("transaction", {})
    if distributed_ledger.apply_remote_transaction(tx):
        db = SessionLocal()
        try:
            persist_ledger_tx(db, tx)
            _sync_itn_from_tx(db, tx)
        finally:
            db.close()


def _sync_itn_from_tx(db: Session, tx: dict) -> None:
    did = tx.get("did")
    user = db.query(User).filter(User.did == did).first() if did else None
    if not user:
        return
    balance = distributed_ledger.get_balance(did)
    counterparty = None
    desc = tx.get("description", "")
    if "transfer to" in (desc or ""):
        counterparty = desc.replace("transfer to ", "").strip()
    elif "transfer from" in (desc or ""):
        counterparty = tx.get("from_did")
    record_itn_transaction(
        did=user.did,
        public_key=user.public_key,
        balance=balance,
        transaction_type=tx.get("transaction_type", "earn"),
        amount=float(tx.get("amount", 0)),
        tx_id=tx.get("tx_id", ""),
        signature=tx.get("signature", ""),
        timestamp=tx.get("timestamp", datetime.utcnow().isoformat()),
        counterparty_did=counterparty,
        description=desc,
    )


async def _on_attestation_sync(message: dict):
    db = SessionLocal()
    try:
        persist_attestation_from_network(db, message.get("attestation", {}))
    finally:
        db.close()


async def _on_agent_parliament(message: dict):
    db = SessionLocal()
    try:
        apply_remote_parliament(db, message)
    finally:
        db.close()


def _bootstrap_ledger_from_db():
    db = SessionLocal()
    try:
        for user in db.query(User).all():
            distributed_ledger.register_identity(user.did, user.public_key)
            user.token_balance = distributed_ledger.get_balance(user.did)
        for tx in db.query(TokenTransaction).filter(TokenTransaction.tx_id.isnot(None)).all():
            u = db.query(User).filter(User.id == tx.user_id).first()
            if u and tx.signature:
                try:
                    distributed_ledger.submit_transaction(
                        did=u.did,
                        public_key_hex=u.public_key,
                        transaction_type=tx.transaction_type,
                        amount=tx.amount,
                        description=tx.description,
                        signature=tx.signature,
                        timestamp=tx.created_at.isoformat() if tx.created_at else None,
                        tx_id=tx.tx_id,
                    )
                except ValueError:
                    pass
        db.commit()
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    _bootstrap_ledger_from_db()
    db = SessionLocal()
    try:
        bootstrap_parliament_from_db(db)
    finally:
        db.close()
    node_manager.on("user_sync", _on_user_sync)
    node_manager.on("ledger_tx", _on_ledger_tx)
    node_manager.on("attestation_sync", _on_attestation_sync)
    node_manager.on("agent_parliament", _on_agent_parliament)
    await node_manager.initialize()
    yield
    await node_manager.shutdown()

app = FastAPI(title="IdentityNet API", version="1.0.0", lifespan=lifespan, docs_url=None, redoc_url=None)

# Mount static files
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Setup templates
templates_dir = Path(__file__).parent / "static"
templates = Jinja2Templates(directory=str(templates_dir))

app.add_middleware(SecureHeadersMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if FORCE_HTTPS and os.path.exists(SSL_CERT_PATH) and os.path.exists(SSL_KEY_PATH):
    app.add_middleware(HTTPSRedirectMiddleware)

def get_ipfs_client():
    if not IPFS_AVAILABLE:
        return None
    try:
        client = ipfshttpclient.connect('/ip4/127.0.0.1/tcp/5001')
        return client
    except Exception:
        return None

def upload_to_ipfs(data: dict) -> str:
    client = get_ipfs_client()
    if not client:
        return None
    try:
        json_data = json.dumps(data)
        res = client.add_bytes(json_data.encode())
        return res['Hash']
    except Exception:
        return None

def get_from_ipfs(ipfs_hash: str) -> dict:
    client = get_ipfs_client()
    if not client:
        return None
    try:
        data = client.cat(ipfs_hash)
        return json.loads(data.decode())
    except Exception:
        return None

def _wallet_binding_dict(binding: Optional[WalletBinding]) -> Optional[dict]:
    if not binding:
        return None
    return {"payload": binding.payload, "signature": binding.signature}


def _apply_itn_record(
    user: User,
    tx: dict,
    wallet_binding: Optional[WalletBinding] = None,
    counterparty_did: Optional[str] = None,
) -> None:
    balance = distributed_ledger.get_balance(user.did)
    user.token_balance = balance
    record_itn_transaction(
        did=user.did,
        public_key=user.public_key,
        balance=balance,
        transaction_type=tx.get("transaction_type", "earn"),
        amount=float(tx.get("amount", 0)),
        tx_id=tx.get("tx_id", ""),
        signature=tx.get("signature", ""),
        timestamp=tx.get("timestamp", datetime.utcnow().isoformat()),
        counterparty_did=counterparty_did,
        description=tx.get("description"),
        wallet_binding=_wallet_binding_dict(wallet_binding),
    )


def resolve_user_canonical(user: User) -> dict:
    """IPFS is canonical; SQLite is local cache."""
    if user.ipfs_hash:
        ipfs_data = get_from_ipfs(user.ipfs_hash)
        if ipfs_data:
            return ipfs_data
    return {
        "did": user.did,
        "username": user.username,
        "email": user.email,
        "public_key": user.public_key,
        "ipfs_hash": user.ipfs_hash,
    }


async def verify_request_signature(request: Request) -> bool:
    """Verify request signature using HMAC-SHA256"""
    try:
        signature = request.headers.get(SIGNATURE_HEADER)
        timestamp = request.headers.get(TIMESTAMP_HEADER)
        
        if not signature or not timestamp:
            return False
        
        # Check timestamp is within tolerance
        try:
            request_time = datetime.fromisoformat(timestamp)
            time_diff = abs((datetime.utcnow() - request_time).total_seconds())
            if time_diff > SIGNATURE_TOLERANCE_SECONDS:
                return False
        except (ValueError, TypeError):
            return False
        
        # Get request body for signature verification
        body = b""
        async for chunk in request.body_iterator:
            body += chunk
        
        # Reconstruct the request for signature verification
        method = request.method
        url = str(request.url)
        content_type = request.headers.get("content-type", "")
        
        # Create signature string
        signature_string = f"{method}\n{url}\n{timestamp}\n{content_type}\n{body.decode('utf-8', errors='ignore')}"
        
        # Calculate expected signature
        expected_signature = hmac.new(
            API_PRIVATE_KEY.encode(),
            signature_string.encode(),
            hashlib.sha256
        ).hexdigest()
        
        # Compare signatures
        return hmac.compare_digest(signature, expected_signature)
    except Exception:
        return False

async def verify_signature_dependency(request: Request):
    """Dependency to verify request signature on protected endpoints"""
    if not await verify_request_signature(request):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing request signature"
        )
    return True

def generate_request_signature(method: str, url: str, timestamp: str, content_type: str, body: str, private_key: str) -> str:
    """
    Generate request signature for clients to use when making API calls.
    
    Args:
        method: HTTP method (GET, POST, etc.)
        url: Full URL of the request
        timestamp: ISO format timestamp
        content_type: Content-Type header value
        body: Request body as string
        private_key: API private key for signing
    
    Returns:
        Hexadecimal signature string
    """
    signature_string = f"{method}\n{url}\n{timestamp}\n{content_type}\n{body}"
    signature = hmac.new(
        private_key.encode(),
        signature_string.encode(),
        hashlib.sha256
    ).hexdigest()
    return signature

@app.get("/")
async def root():
    return {
        "name": "IdentityNet",
        "description": "Decentralized Identity & Reputation System",
        "version": "2.0.0",
        "decentralized": node_manager._running,
        "zk_proofs": NACL_AVAILABLE,
        "architecture": "ipfs_canonical_sqlite_cache_p2p_ledger",
        "agent_parliament": True,
    }

@app.get("/docs", include_in_schema=False)
async def custom_docs():
    """Serve custom Swagger UI with Tailwind and Bootstrap styling"""
    static_dir = Path(__file__).parent / "static"
    docs_file = static_dir / "docs.html"
    
    if docs_file.exists():
        with open(docs_file, 'r', encoding='utf-8') as f:
            html_content = f.read()
        # Replace the template variable with the actual OpenAPI URL
        html_content = html_content.replace("{{ openapi_url }}", app.openapi_url)
        return HTMLResponse(content=html_content)
    else:
        # Fallback to default docs if custom template not found
        from fastapi.openapi.docs import get_swagger_ui_html
        return get_swagger_ui_html(openapi_url=app.openapi_url, title="IdentityNet API")

@app.post("/crypto/sign-payload")
async def sign_payload_endpoint(payload: dict, private_key: str = Header(..., alias="X-Private-Key")):
    """Helper for clients to sign canonical JSON payloads (development / Termux)."""
    return {"signature": sign_payload(private_key, payload)}


@app.get("/users/{user_id}/itn/wallet-payload")
async def get_wallet_binding_payload(user_id: int, db: Session = Depends(get_db)):
    """Return payload to sign with private key for ITN .itn wallet binding."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    balance = distributed_ledger.get_balance(user.did)
    last = (
        db.query(TokenTransaction)
        .filter(TokenTransaction.user_id == user_id)
        .order_by(TokenTransaction.created_at.desc())
        .first()
    )
    payload = wallet_binding_payload(
        user.did, user.public_key, balance, last.tx_id if last else None
    )
    return {"coin": "ITN", "payload": payload}


@app.get("/generate-keys")
async def generate_keys():
    """Generate Ed25519 public/private keypair only. DID is assigned on POST /users/create."""
    public_key, private_key = generate_keypair()
    return {
        "public_key": public_key,
        "private_key": private_key,
        "warning": "Save your private_key securely - it cannot be recovered. Your DID is created when you register with this public_key.",
    }

@app.post("/users/create", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(user: UserCreate, db: Session = Depends(get_db)):
    reg_payload = registration_payload(
        user.username, user.email, user.public_key, user.timestamp
    )
    if not verify_payload(user.public_key, reg_payload, user.registration_signature):
        raise HTTPException(status_code=401, detail="Invalid registration signature")

    if db.query(User).filter(User.username == user.username).first():
        raise HTTPException(status_code=400, detail="Username already exists")
    if user.email and db.query(User).filter(User.email == user.email).first():
        raise HTTPException(status_code=400, detail="Email already exists")

    if node_manager._running:
        if not await node_manager.check_username_available(user.username):
            raise HTTPException(status_code=400, detail="Username already taken globally")

    did = generate_did(user.public_key)
    user_data = {
        "did": did,
        "username": user.username,
        "email": user.email,
        "public_key": user.public_key,
        "created_at": datetime.utcnow().isoformat(),
        "node_id": node_manager.node_id if node_manager._running else None,
    }
    ipfs_hash = upload_to_ipfs(user_data)
    if not ipfs_hash:
        raise HTTPException(
            status_code=503,
            detail="IPFS required for decentralized identity storage. Start ipfs daemon.",
        )

    new_user = User(
        did=did,
        username=user.username,
        email=user.email,
        public_key=user.public_key,
        ipfs_hash=ipfs_hash,
        node_id=node_manager.node_id if node_manager._running else None,
        synced=node_manager._running,
    )
    db.add(new_user)
    db.add(Reputation(user=new_user))
    db.commit()
    db.refresh(new_user)

    distributed_ledger.register_identity(did, user.public_key)
    init_itn_files(did, user.public_key)

    if node_manager._running:
        await node_manager.register_username(user.username, did, user.public_key)
        await node_manager.sync_user_data(
            {
                **user_data,
                "ipfs_hash": ipfs_hash,
                "id": new_user.id,
            }
        )

    return new_user

@app.get("/users/{user_id}", response_model=UserResponse)
async def get_user(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.token_balance = distributed_ledger.get_balance(user.did)
    return user


@app.get("/users/{user_id}/profile")
async def get_user_profile(user_id: int, db: Session = Depends(get_db)):
    """Return canonical IPFS identity document (selective fields per commitments)."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {
        "source": "ipfs" if user.ipfs_hash else "local",
        "canonical": resolve_user_canonical(user),
        "cache": {"id": user.id, "synced": user.synced, "node_id": user.node_id},
    }


@app.get("/users/did/{did}", response_model=UserResponse)
async def get_user_by_did(did: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.did == did).first()
    if not user:
        registry = node_manager.global_did_registry.get(did)
        if registry and node_manager._running:
            raise HTTPException(
                status_code=404,
                detail="User on network but not cached locally. Wait for P2P sync.",
            )
        raise HTTPException(status_code=404, detail="User not found")
    user.token_balance = distributed_ledger.get_balance(user.did)
    return user

@app.get("/users/{user_id}/reputation", response_model=ReputationResponse)
async def get_reputation(user_id: int, db: Session = Depends(get_db)):
    reputation = db.query(Reputation).filter(Reputation.user_id == user_id).first()
    if not reputation:
        raise HTTPException(status_code=404, detail="Reputation not found")
    return reputation

@app.post("/users/{user_id}/attestations", response_model=AttestationResponse, status_code=status.HTTP_201_CREATED)
async def create_attestation(
    user_id: int,
    attestation: AttestationCreate,
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if attestation.attester_did != generate_did(attestation.attester_public_key):
        raise HTTPException(status_code=400, detail="attester_did does not match attester_public_key")

    payload = attestation_payload(
        user.did,
        attestation.attestation_type,
        attestation.data,
        attestation.attester_did,
        attestation.timestamp,
    )
    if not verify_payload(
        attestation.attester_public_key, payload, attestation.signature
    ):
        raise HTTPException(status_code=401, detail="Invalid attestation signature")

    new_attestation = Attestation(
        user_id=user_id,
        subject_did=user.did,
        attester_did=attestation.attester_did,
        attester_public_key=attestation.attester_public_key,
        attestation_type=attestation.attestation_type,
        data=attestation.data,
        signature=attestation.signature,
        network_synced=node_manager._running,
    )
    db.add(new_attestation)
    reputation = db.query(Reputation).filter(Reputation.user_id == user_id).first()
    if reputation:
        reputation.total_reviews += 1
        reputation.positive_reviews += 1
        reputation.score = (reputation.positive_reviews / reputation.total_reviews) * 100
        reputation.last_updated = datetime.utcnow()
    db.commit()
    db.refresh(new_attestation)

    if node_manager._running:
        await node_manager.broadcast_attestation(
            {
                "subject_did": user.did,
                "attester_did": attestation.attester_did,
                "attester_public_key": attestation.attester_public_key,
                "attestation_type": attestation.attestation_type,
                "data": attestation.data,
                "signature": attestation.signature,
            }
        )
    return new_attestation

@app.get("/users/{user_id}/attestations", response_model=List[AttestationResponse])
async def get_attestations(user_id: int, db: Session = Depends(get_db)):
    attestations = db.query(Attestation).filter(Attestation.user_id == user_id).all()
    return attestations

@app.post("/users/{user_id}/tokens", response_model=TokenTransactionResponse, status_code=status.HTTP_201_CREATED)
async def create_token_transaction(
    user_id: int, transaction: TokenTransactionCreate, db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    tx_id = distributed_ledger.compute_tx_id(
        user.did,
        transaction.transaction_type,
        transaction.amount,
        transaction.timestamp,
    )
    payload = ledger_payload(
        tx_id,
        user.did,
        transaction.transaction_type,
        transaction.amount,
        transaction.description,
        transaction.timestamp,
    )
    if not verify_payload(user.public_key, payload, transaction.signature):
        raise HTTPException(status_code=401, detail="Invalid transaction signature")

    try:
        tx = distributed_ledger.submit_transaction(
            did=user.did,
            public_key_hex=user.public_key,
            transaction_type=transaction.transaction_type,
            amount=transaction.amount,
            description=transaction.description,
            signature=transaction.signature,
            timestamp=transaction.timestamp,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    new_transaction = TokenTransaction(
        tx_id=tx["tx_id"],
        user_id=user_id,
        signer_did=user.did,
        transaction_type=transaction.transaction_type,
        amount=transaction.amount,
        description=transaction.description,
        signature=transaction.signature,
        network_synced=node_manager._running,
    )
    db.add(new_transaction)
    _apply_itn_record(user, tx, wallet_binding=transaction.wallet_binding)
    db.commit()
    db.refresh(new_transaction)

    if node_manager._running:
        await node_manager.broadcast_ledger_tx(distributed_ledger.to_broadcast(tx))
    return new_transaction


@app.post("/users/{user_id}/itn/transfer")
async def transfer_itn(
    user_id: int, body: ITNTransferCreate, db: Session = Depends(get_db)
):
    sender = db.query(User).filter(User.id == user_id).first()
    if not sender:
        raise HTTPException(status_code=404, detail="User not found")
    recipient = db.query(User).filter(User.did == body.to_did).first()
    if not recipient:
        raise HTTPException(status_code=404, detail="Recipient not found")

    tx_id = distributed_ledger.compute_tx_id(
        sender.did, "transfer", body.amount, body.timestamp
    )
    payload = transfer_payload(
        tx_id, sender.did, body.to_did, body.amount, body.timestamp
    )
    if not verify_payload(sender.public_key, payload, body.signature):
        raise HTTPException(status_code=401, detail="Invalid transfer signature")

    try:
        result = distributed_ledger.submit_transfer(
            from_did=sender.did,
            from_public_key=sender.public_key,
            to_did=recipient.did,
            to_public_key=recipient.public_key,
            amount=body.amount,
            signature=body.signature,
            timestamp=body.timestamp,
            tx_id=tx_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    out_tx = result["outgoing"]
    in_tx = result["incoming"]

    db.add(
        TokenTransaction(
            tx_id=out_tx["tx_id"],
            user_id=sender.id,
            signer_did=sender.did,
            transaction_type="transfer",
            amount=body.amount,
            description=out_tx.get("description"),
            signature=body.signature,
            network_synced=node_manager._running,
        )
    )
    db.add(
        TokenTransaction(
            tx_id=in_tx["tx_id"],
            user_id=recipient.id,
            signer_did=sender.did,
            transaction_type="receive",
            amount=body.amount,
            description=in_tx.get("description"),
            signature=body.signature,
            network_synced=node_manager._running,
        )
    )
    _apply_itn_record(
        sender,
        out_tx,
        wallet_binding=body.wallet_binding,
        counterparty_did=recipient.did,
    )
    _apply_itn_record(
        recipient,
        in_tx,
        counterparty_did=sender.did,
    )
    db.commit()

    if node_manager._running:
        await node_manager.broadcast_ledger_tx(distributed_ledger.to_broadcast(out_tx))
        await node_manager.broadcast_ledger_tx(distributed_ledger.to_broadcast(in_tx))

    return {
        "coin": "ITN",
        "tx_id": tx_id,
        "from_did": sender.did,
        "to_did": recipient.did,
        "amount": body.amount,
        "sender_balance": distributed_ledger.get_balance(sender.did),
        "recipient_balance": distributed_ledger.get_balance(recipient.did),
    }


@app.get("/users/{user_id}/itn", response_model=ITNWalletResponse)
async def get_user_itn(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    summary = get_itn_summary(user.did, user.public_key)
    return ITNWalletResponse(**summary)


@app.get("/users/{user_id}/balance")
async def get_user_balance_file(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return load_balance_file(user.did, user.public_key)


@app.post("/users/{user_id}/itn/seal")
async def seal_itn_wallet(
    user_id: int, body: ITNSealRequest, db: Session = Depends(get_db)
):
    """Re-seal .itn wallet with wallet_signature after received transfers."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    balance = distributed_ledger.get_balance(user.did)
    last_tx = (
        db.query(TokenTransaction)
        .filter(TokenTransaction.user_id == user_id)
        .order_by(TokenTransaction.created_at.desc())
        .first()
    )
    from itn import write_itn_wallet

    wallet = write_itn_wallet(
        user.did,
        user.public_key,
        balance,
        last_tx.tx_id if last_tx else None,
        body.wallet_binding.signature,
        binding_payload=body.wallet_binding.payload,
    )
    user.token_balance = balance
    db.commit()
    return {"coin": "ITN", "wallet": wallet, "binding_valid": True}


@app.get("/users/{user_id}/tokens", response_model=List[TokenTransactionResponse])
async def get_token_transactions(user_id: int, db: Session = Depends(get_db)):
    transactions = db.query(TokenTransaction).filter(TokenTransaction.user_id == user_id).order_by(TokenTransaction.created_at.desc()).all()
    return transactions

@app.post("/verify", status_code=status.HTTP_200_OK)
async def verify_identity(request: IdentityVerificationRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.did == request.did).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    verification_amount = 1.0
    ts = request.timestamp
    tx_id = distributed_ledger.compute_tx_id(
        user.did, "verification", verification_amount, ts
    )
    payload = ledger_payload(
        tx_id,
        user.did,
        "verification",
        verification_amount,
        f"Identity verification: {request.verification_type}",
        ts,
    )
    if not verify_payload(user.public_key, payload, request.signature):
        raise HTTPException(status_code=401, detail="Invalid verification signature")
    ledger_sig = request.signature

    tx = distributed_ledger.submit_transaction(
        did=user.did,
        public_key_hex=user.public_key,
        transaction_type="verification",
        amount=verification_amount,
        description=payload["description"],
        signature=ledger_sig,
        timestamp=ts,
    )
    user.is_verified = True
    db.add(
        TokenTransaction(
            tx_id=tx["tx_id"],
            user_id=user.id,
            signer_did=user.did,
            transaction_type="verification",
            amount=verification_amount,
            description=payload["description"],
            signature=ledger_sig,
            network_synced=node_manager._running,
        )
    )
    _apply_itn_record(user, tx, wallet_binding=request.wallet_binding)
    db.commit()
    if node_manager._running:
        await node_manager.broadcast_ledger_tx(distributed_ledger.to_broadcast(tx))

    return {
        "did": user.did,
        "verification_type": request.verification_type,
        "verified": True,
        "tokens_earned": verification_amount,
        "balance": user.token_balance,
        "coin": "ITN",
    }

@app.post("/zk/commit", response_model=ZKCommitResponse)
async def zk_create_commitment(
    user_id: int, body: ZKCommitRequest, db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    result = create_commitment(body.value, body.salt)
    store_commitment(db, user_id, body.attribute, result["commitment"], result["salt"])
    return ZKCommitResponse(
        attribute=body.attribute,
        commitment=result["commitment"],
        salt=result["salt"],
    )


@app.post("/zk/prove", response_model=ZKProofKnowledgeResponse)
async def zk_prove_knowledge(body: ZKProofKnowledgeRequest):
    if not NACL_AVAILABLE:
        raise HTTPException(status_code=503, detail="Install pynacl for ZK proofs")
    proof = create_schnorr_proof(body.value, body.salt)
    return ZKProofKnowledgeResponse(proof=proof)


@app.post("/zk/disclose")
async def zk_selective_disclose(body: ZKSelectiveDisclosureRequest):
    proof = selective_disclosure_proof(
        body.private_key,
        body.attribute,
        body.value,
        body.salt,
        body.public_key,
    )
    return {"proof": proof, "verified": verify_selective_disclosure(proof)}


@app.post("/zk/verify")
async def zk_verify(body: ZKVerifyRequest):
    if body.mode == "disclosure":
        ok = verify_selective_disclosure(body.proof)
    else:
        ok = verify_schnorr_proof(body.proof)
    return {"verified": ok, "mode": body.mode}


@app.get("/ledger/{did}/balance", response_model=LedgerBalanceResponse)
async def ledger_balance(did: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.did == did).first()
    balance = distributed_ledger.get_balance(did)
    source = "network_ledger"
    if user:
        user.token_balance = balance
        db.commit()
    return LedgerBalanceResponse(did=did, balance=balance, source=source)


@app.get("/ledger/{did}/transactions")
async def ledger_transactions(did: str):
    return {
        "did": did,
        "transactions": distributed_ledger.get_transactions(did),
        "balance": distributed_ledger.get_balance(did),
    }


# --- Agent Parliament (agent-to-agent contracts + human witnesses) ---


@app.post("/agents/court/enroll", response_model=CourtEnrollResponse)
async def court_enroll(body: CourtEnrollRequest, db: Session = Depends(get_db)):
    """Register your existing DID as a court agent; ITN wallet is linked automatically."""
    try:
        result = enroll_in_court(
            db,
            owner_did=body.owner_did,
            agent_name=body.agent_name,
            public_key_hex=body.public_key,
            signature=body.signature,
            timestamp=body.timestamp,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return CourtEnrollResponse(**result)


@app.get("/agents/court/status/{owner_did}", response_model=CourtStatusResponse)
async def court_status_endpoint(owner_did: str, db: Session = Depends(get_db)):
    try:
        result = court_status(db, owner_did)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return CourtStatusResponse(**result)


@app.post("/agents/register", response_model=AgentResponse)
async def register_agent(body: AgentRegister, db: Session = Depends(get_db)):
    owner = db.query(User).filter(User.did == body.owner_did).first()
    if not owner:
        raise HTTPException(status_code=404, detail="Owner DID not found — create user first")
    try:
        record = agent_parliament.register_agent(
            owner_did=body.owner_did,
            name=body.name,
            public_key_hex=body.public_key,
            signature=body.signature,
            timestamp=body.timestamp,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    persist_agent(db, record)
    if node_manager._running:
        await node_manager.broadcast_agent_parliament(
            agent_parliament.to_broadcast(
                "agent_register",
                {
                    "owner_did": body.owner_did,
                    "name": body.name,
                    "public_key": body.public_key,
                    "signature": body.signature,
                    "timestamp": body.timestamp,
                    "agent_did": record["agent_did"],
                },
            )
        )
    return AgentResponse(
        agent_did=record["agent_did"],
        owner_did=record["owner_did"],
        name=record["name"],
        public_key=record["public_key"],
        reputation_score=record.get("reputation_score", 50.0),
        contracts_completed=record.get("contracts_completed", 0),
    )


@app.get("/agents/{agent_did}", response_model=AgentResponse)
async def get_agent(agent_did: str):
    record = agent_parliament.get_agent(agent_did)
    if not record:
        raise HTTPException(status_code=404, detail="Agent not found")
    return AgentResponse(
        agent_did=record["agent_did"],
        owner_did=record["owner_did"],
        name=record["name"],
        public_key=record["public_key"],
        reputation_score=record.get("reputation_score", 50.0),
        contracts_completed=record.get("contracts_completed", 0),
    )


@app.get("/users/{user_id}/agents", response_model=List[AgentResponse])
async def list_user_agents(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    agents = agent_parliament.list_agents_for_owner(user.did)
    return [
        AgentResponse(
            agent_did=a["agent_did"],
            owner_did=a["owner_did"],
            name=a["name"],
            public_key=a["public_key"],
            reputation_score=a.get("reputation_score", 50.0),
            contracts_completed=a.get("contracts_completed", 0),
        )
        for a in agents
    ]


@app.post("/agents/contracts", response_model=AgentContractResponse)
async def create_agent_contract(body: AgentOfferCreate, db: Session = Depends(get_db)):
    try:
        contract = agent_parliament.create_offer(
            proposer_agent_did=body.proposer_agent_did,
            public_key_hex=body.public_key,
            intent=body.intent,
            escrow_amount=body.escrow_amount,
            signature=body.signature,
            timestamp=body.timestamp,
            responder_agent_did=body.responder_agent_did,
            terms=body.terms,
            witness_quorum=body.witness_quorum,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
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
    if node_manager._running:
        await node_manager.broadcast_agent_parliament(
            agent_parliament.to_broadcast(
                "contract_offer",
                body.model_dump(),
            )
        )
    full = agent_parliament.get_contract(contract["contract_id"])
    return AgentContractResponse(**full)


@app.get("/agents/contracts", response_model=List[AgentContractResponse])
async def list_agent_contracts(
    agent_did: Optional[str] = None,
    status: Optional[str] = None,
):
    items = agent_parliament.list_contracts(agent_did=agent_did, status=status)
    return [AgentContractResponse(**c) for c in items]


@app.get("/agents/contracts/{contract_id}", response_model=AgentContractResponse)
async def get_agent_contract(contract_id: str):
    full = agent_parliament.get_contract(contract_id)
    if not full:
        raise HTTPException(status_code=404, detail="Contract not found")
    return AgentContractResponse(**full)


@app.post("/agents/contracts/{contract_id}/messages", response_model=AgentContractResponse)
async def post_agent_contract_message(
    contract_id: str, body: AgentMessageCreate, db: Session = Depends(get_db)
):
    try:
        contract = agent_parliament.post_message(
            contract_id=contract_id,
            message_type=body.message_type,
            agent_did=body.agent_did,
            public_key_hex=body.public_key,
            body=body.body,
            signature=body.signature,
            timestamp=body.timestamp,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    persist_contract(db, contract)
    msgs = agent_parliament.messages.get(contract_id, [])
    if msgs:
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
    if node_manager._running:
        payload = body.model_dump()
        payload["contract_id"] = contract_id
        await node_manager.broadcast_agent_parliament(
            agent_parliament.to_broadcast("contract_message", payload)
        )
    full = agent_parliament.get_contract(contract_id)
    return AgentContractResponse(**full)


@app.post("/agents/contracts/{contract_id}/witness", response_model=AgentContractResponse)
async def witness_agent_contract(
    contract_id: str, body: AgentWitnessCreate, db: Session = Depends(get_db)
):
    witness_user = db.query(User).filter(User.did == body.witness_did).first()
    if not witness_user:
        raise HTTPException(status_code=404, detail="Witness DID must be a registered user")
    if witness_user.public_key != body.witness_public_key:
        raise HTTPException(status_code=400, detail="witness_public_key does not match DID")
    try:
        contract, quorum_met = agent_parliament.add_witness(
            contract_id=contract_id,
            witness_did=body.witness_did,
            witness_public_key=body.witness_public_key,
            event=body.event,
            signature=body.signature,
            timestamp=body.timestamp,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    persist_contract(db, contract)
    wlist = agent_parliament.witnesses.get(contract_id, [])
    if wlist:
        persist_witness_record(db, wlist[-1])
    if node_manager._running:
        payload = body.model_dump()
        payload["contract_id"] = contract_id
        await node_manager.broadcast_agent_parliament(
            agent_parliament.to_broadcast("contract_witness", payload)
        )
    full = agent_parliament.get_contract(contract_id)
    full["quorum_met"] = quorum_met
    return AgentContractResponse(**{k: v for k, v in full.items() if k != "quorum_met"})


@app.get(
    "/agents/contracts/{contract_id}/settlement-plan",
    response_model=AgentSettlePlanResponse,
)
async def get_settlement_plan(contract_id: str):
    try:
        plan = agent_parliament.settlement_plan(contract_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return AgentSettlePlanResponse(**plan)


@app.post("/agents/contracts/{contract_id}/settle")
async def settle_agent_contract(
    contract_id: str, body: AgentSettleCreate, db: Session = Depends(get_db)
):
    try:
        plan = agent_parliament.settlement_plan(contract_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if body.payer_did != plan["payer_did"]:
        raise HTTPException(status_code=400, detail="payer_did must be contract proposer owner")

    payer = db.query(User).filter(User.did == body.payer_did).first()
    if not payer:
        raise HTTPException(status_code=404, detail="Payer not found")

    settle_pl = agent_settle_payload(
        contract_id, body.payer_did, plan["total_debit"], body.timestamp
    )
    if not verify_payload(payer.public_key, settle_pl, body.signature):
        raise HTTPException(status_code=401, detail="Invalid settlement authorization signature")

    if distributed_ledger.get_balance(body.payer_did) < plan["total_debit"]:
        raise HTTPException(status_code=400, detail="Insufficient ITN for settlement")

    executed = []
    for t in body.transfers:
        to_did = t.get("to_did")
        amount = float(t.get("amount", 0))
        tx_id = t.get("tx_id")
        sig = t.get("signature")
        if not to_did or not tx_id or not sig:
            raise HTTPException(status_code=400, detail="Each transfer needs to_did, tx_id, signature")
        recipient = db.query(User).filter(User.did == to_did).first()
        if not recipient:
            raise HTTPException(status_code=404, detail=f"Recipient not found: {to_did}")
        try:
            result = distributed_ledger.submit_transfer(
                from_did=body.payer_did,
                from_public_key=payer.public_key,
                to_did=to_did,
                to_public_key=recipient.public_key,
                amount=amount,
                signature=sig,
                timestamp=body.timestamp,
                tx_id=tx_id,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        out_tx = result["outgoing"]
        in_tx = result["incoming"]
        for tx in (out_tx, in_tx):
            persist_ledger_tx(db, tx)
            _sync_itn_from_tx(db, tx)
        if node_manager._running:
            await node_manager.broadcast_ledger_tx(distributed_ledger.to_broadcast(out_tx))
            await node_manager.broadcast_ledger_tx(distributed_ledger.to_broadcast(in_tx))
        executed.append({"tx_id": tx_id, "to_did": to_did, "amount": amount})

    contract = agent_parliament.mark_settled(contract_id)
    persist_contract(db, contract)
    payer.token_balance = distributed_ledger.get_balance(body.payer_did)
    db.commit()

    return {
        "contract_id": contract_id,
        "status": "settled",
        "transfers_executed": executed,
        "total_debit": plan["total_debit"],
    }


@app.get("/agents/debate/cases", response_model=List[DebateCaseSummary])
async def list_debate_cases():
    """Real-world debate cases available in the chamber."""
    return [DebateCaseSummary(**c) for c in list_cases_public()]


@app.get("/agents/debate/cases/{case_id}")
async def get_debate_case(case_id: str):
    case = get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Debate case not found")
    from debate_engine import get_poll_from_case, build_transcript_lines

    return {
        "id": case["id"],
        "title": case["title"],
        "category": case.get("category"),
        "summary": case.get("summary"),
        "proposer_role": case.get("proposer_role"),
        "responder_role": case.get("responder_role"),
        "poll": get_poll_from_case(case),
        "preview_transcript": build_transcript_lines(case, use_llm=False),
    }


@app.post("/agents/debate/start", response_model=DebateSessionResponse)
async def start_debate(body: DebateStartRequest, db: Session = Depends(get_db)):
    """Run a real signed debate for the given case (creates agents + contract + messages)."""
    try:
        session = run_debate(
            db,
            body.case_id,
            use_llm=body.use_llm,
            player_owner_did=body.player_owner_did,
            player_side=body.player_side,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return DebateSessionResponse(**session)


@app.get("/agents/debate/sessions/{session_id}", response_model=DebateSessionResponse)
async def get_debate_session(session_id: str, db: Session = Depends(get_db)):
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    cid = session.get("contract_id")
    if cid:
        full = agent_parliament.get_contract(cid)
        if full:
            session["status"] = full.get("status", session.get("status"))
    return DebateSessionResponse(**session)


@app.get("/agents/debate/sessions")
async def list_debate_sessions():
    return list_sessions()


@app.post("/agents/debate/sessions/{session_id}/verdict")
async def debate_verdict(
    session_id: str, body: DebateVerdictRequest, db: Session = Depends(get_db)
):
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    case = get_case(session["case_id"])
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    verdict = verdict_for_poll_option(case, body.option_id)
    reward = None
    if body.claim_reward:
        try:
            reward = award_debate_win(db, session, body.option_id)
        except ValueError as e:
            reward = {"won": False, "error": str(e)}
    return {
        "session_id": session_id,
        "contract_id": session.get("contract_id"),
        "option_id": body.option_id,
        "verdict": verdict,
        "poll_question": case.get("poll", {}).get("question"),
        "favors_side": poll_option_favors_side(case, body.option_id),
        "reward": reward,
        "win_reward_itn": DEBATE_WIN_REWARD,
    }


@app.get("/agents/parliament/stats")
async def agent_parliament_stats():
    return {
        "agents": len(agent_parliament.agents),
        "contracts": len(agent_parliament.contracts),
        "witness_quorum_default": WITNESS_QUORUM,
        "witness_reward_default": WITNESS_REWARD,
        "open_contracts": sum(
            1 for c in agent_parliament.contracts.values() if c.get("status") == "open"
        ),
        "debate_cases": len(list_cases_public()),
    }


@app.get("/stats")
async def get_stats(db: Session = Depends(get_db)):
    total_users = db.query(User).count()
    total_attestations = db.query(Attestation).count()
    total_transactions = db.query(TokenTransaction).count()
    
    return {
        "total_users": total_users,
        "total_attestations": total_attestations,
        "total_transactions": total_transactions
    }

@app.get("/node/info")
async def get_node_info():
    """Get information about this node"""
    peers = await node_manager.get_peers() if node_manager._running else []
    
    return {
        "node_id": node_manager.node_id,
        "running": node_manager._running,
        "peers": peers,
        "peer_count": len(peers),
        "global_username_registry_size": len(node_manager.global_username_registry),
        "global_did_registry_size": len(node_manager.global_did_registry),
        "ledger_transactions": len(distributed_ledger.transactions),
        "zk_enabled": NACL_AVAILABLE,
        "storage_model": "ipfs_canonical_sqlite_cache",
    }

@app.get("/node/registry")
async def get_global_registry():
    """Get the global username registry"""
    return {
        "username_registry": node_manager.global_username_registry,
        "did_registry": node_manager.global_did_registry
    }

@app.post("/system/update")
async def update_system(signature_valid: bool = Depends(verify_signature_dependency)):
    import subprocess
    import os
    
    try:
        result = subprocess.run(
            ["bash", "update.sh"],
            capture_output=True,
            text=True,
            cwd=os.path.dirname(os.path.abspath(__file__))
        )
        
        return {
            "status": "success",
            "message": "Update completed successfully",
            "output": result.stdout
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }

if __name__ == "__main__":
    import uvicorn
    
    # SSL configuration for HTTPS/TLS with Let's Encrypt
    ssl_keyfile = None
    ssl_certfile = None
    if FORCE_HTTPS and os.path.exists(SSL_CERT_PATH) and os.path.exists(SSL_KEY_PATH):
        ssl_keyfile = SSL_KEY_PATH
        ssl_certfile = SSL_CERT_PATH
    
    uvicorn.run(
        app, 
        host="127.0.0.1", 
        port=8000,
        ssl_keyfile=ssl_keyfile,
        ssl_certfile=ssl_certfile
    )
