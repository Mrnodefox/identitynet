from fastapi import FastAPI, Depends, HTTPException, status, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.httpsredirect import HTTPSRedirectMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy.orm import Session
from datetime import datetime
import hashlib
import secrets
import json
import os
import hmac
import ssl
from typing import List, Optional

from database import engine, get_db, init_db, User, Reputation, Attestation, TokenTransaction
from schemas import (
    UserCreate, UserResponse, ReputationResponse,
    AttestationCreate, AttestationResponse,
    TokenTransactionCreate, TokenTransactionResponse,
    IdentityVerificationRequest
)

try:
    import ipfshttpclient
    IPFS_AVAILABLE = True
except ImportError:
    IPFS_AVAILABLE = False

try:
    from fastapi_secure_headers import SecureHeaders, secure_headers
    SECURE_HEADERS_AVAILABLE = True
except ImportError:
    SECURE_HEADERS_AVAILABLE = False

app = FastAPI(title="IdentityNet API", version="1.0.0")

if SECURE_HEADERS_AVAILABLE:
    secure_headers = SecureHeaders(
        hsts=True,
        hsts_include_subdomains=True,
        hsts_preload=True,
        hsts_max_age=31536000,
        csp=True,
        csp_default-src="'self'",
        csp_img-src="'self' data:",
        csp_script-src="'self'",
        csp_style-src="'self'",
        csp_connect-src="'self'",
        csp_font-src="'self'",
        csp_object-src="'none'",
        csp_media-src="'self'",
        csp_form_action="'self'",
        csp_frame_ancestors="'none'",
        csp_base_uri="'self'",
        csp_block_all_mixed_content=True,
        csp_upgrade_insecure_requests=True,
        referrer_policy=True,
        referrer="strict-origin-when-cross-origin",
        permissions_policy=True,
        permissions_geolocation="'self'",
        permissions_microphone="'none'",
        permissions_camera="'none'",
        x_content_type_options=True,
        x_frame_options=True,
        x_frame_options_option="DENY",
        x_xss_protection=True,
        x_xss_protection_option="1; mode=block",
        server=True,
        server_header="IdentityNet"
    )
    app.add_middleware(
        BaseHTTPMiddleware,
        dispatch=secure_headers
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# HTTPS/TLS Configuration with Let's Encrypt
SSL_CERT_PATH = os.getenv("SSL_CERT_PATH", "/etc/letsencrypt/live/yourdomain.com/fullchain.pem")
SSL_KEY_PATH = os.getenv("SSL_KEY_PATH", "/etc/letsencrypt/live/yourdomain.com/privkey.pem")
FORCE_HTTPS = os.getenv("FORCE_HTTPS", "false").lower() == "true"

if FORCE_HTTPS and os.path.exists(SSL_CERT_PATH) and os.path.exists(SSL_KEY_PATH):
    app.add_middleware(HTTPSRedirectMiddleware)

# Request Signing Configuration
API_PRIVATE_KEY = os.getenv("API_PRIVATE_KEY", secrets.token_hex(32))
SIGNATURE_HEADER = "X-Signature"
TIMESTAMP_HEADER = "X-Timestamp"
SIGNATURE_TOLERANCE_SECONDS = 300  # 5 minutes

@app.on_event("startup")
async def startup_event():
    init_db()

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

def generate_did(public_key: str) -> str:
    hash_input = f"did:identitynet:{public_key}:{datetime.utcnow().isoformat()}"
    return f"did:identitynet:{hashlib.sha256(hash_input.encode()).hexdigest()[:32]}"

def verify_request_signature(request: Request) -> bool:
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
    if not verify_request_signature(request):
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
        "version": "1.0.0"
    }

@app.post("/users/create", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(user: UserCreate, db: Session = Depends(get_db), _: bool = Depends(verify_signature_dependency)):
    existing_user = db.query(User).filter(User.username == user.username).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Username already exists")
    
    if user.email:
        existing_email = db.query(User).filter(User.email == user.email).first()
        if existing_email:
            raise HTTPException(status_code=400, detail="Email already exists")
    
    did = generate_did(user.public_key)
    
    user_data = {
        "did": did,
        "username": user.username,
        "email": user.email,
        "public_key": user.public_key,
        "created_at": datetime.utcnow().isoformat()
    }
    
    ipfs_hash = upload_to_ipfs(user_data)
    
    new_user = User(
        did=did,
        username=user.username,
        email=user.email,
        public_key=user.public_key,
        ipfs_hash=ipfs_hash
    )
    
    new_reputation = Reputation(user=new_user)
    
    db.add(new_user)
    db.add(new_reputation)
    db.commit()
    db.refresh(new_user)
    
    return new_user

@app.get("/users/{user_id}", response_model=UserResponse)
async def get_user(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

@app.get("/users/did/{did}", response_model=UserResponse)
async def get_user_by_did(did: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.did == did).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

@app.get("/users/{user_id}/reputation", response_model=ReputationResponse)
async def get_reputation(user_id: int, db: Session = Depends(get_db)):
    reputation = db.query(Reputation).filter(Reputation.user_id == user_id).first()
    if not reputation:
        raise HTTPException(status_code=404, detail="Reputation not found")
    return reputation

@app.post("/users/{user_id}/attestations", response_model=AttestationResponse, status_code=status.HTTP_201_CREATED)
async def create_attestation(user_id: int, attestation: AttestationCreate, db: Session = Depends(get_db), _: bool = Depends(verify_signature_dependency)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    new_attestation = Attestation(
        user_id=user_id,
        attester_did="did:identitynet:system",
        attestation_type=attestation.attestation_type,
        data=attestation.data,
        signature=attestation.signature
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
    
    return new_attestation

@app.get("/users/{user_id}/attestations", response_model=List[AttestationResponse])
async def get_attestations(user_id: int, db: Session = Depends(get_db)):
    attestations = db.query(Attestation).filter(Attestation.user_id == user_id).all()
    return attestations

@app.post("/users/{user_id}/tokens", response_model=TokenTransactionResponse, status_code=status.HTTP_201_CREATED)
async def create_token_transaction(user_id: int, transaction: TokenTransactionCreate, db: Session = Depends(get_db), _: bool = Depends(verify_signature_dependency)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    new_transaction = TokenTransaction(
        user_id=user_id,
        transaction_type=transaction.transaction_type,
        amount=transaction.amount,
        description=transaction.description
    )
    
    db.add(new_transaction)
    db.commit()
    db.refresh(new_transaction)
    
    return new_transaction

@app.get("/users/{user_id}/tokens", response_model=List[TokenTransactionResponse])
async def get_token_transactions(user_id: int, db: Session = Depends(get_db)):
    transactions = db.query(TokenTransaction).filter(TokenTransaction.user_id == user_id).order_by(TokenTransaction.created_at.desc()).all()
    return transactions

@app.post("/verify", status_code=status.HTTP_200_OK)
async def verify_identity(request: IdentityVerificationRequest, db: Session = Depends(get_db), _: bool = Depends(verify_signature_dependency)):
    user = db.query(User).filter(User.did == request.did).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    verification_amount = 1.0
    
    new_transaction = TokenTransaction(
        user_id=user.id,
        transaction_type="verification",
        amount=verification_amount,
        description=f"Identity verification: {request.verification_type}"
    )
    
    user.is_verified = True
    db.add(new_transaction)
    db.commit()
    
    return {
        "did": user.did,
        "verification_type": request.verification_type,
        "verified": True,
        "tokens_earned": verification_amount
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

@app.post("/system/update")
async def update_system(_: bool = Depends(verify_signature_dependency)):
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
    ssl_context = None
    if FORCE_HTTPS and os.path.exists(SSL_CERT_PATH) and os.path.exists(SSL_KEY_PATH):
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_context.load_cert_chain(SSL_CERT_PATH, SSL_KEY_PATH)
    
    uvicorn.run(
        app, 
        host="0.0.0.0", 
        port=8000,
        ssl=ssl_context
    )
