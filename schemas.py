from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class UserCreate(BaseModel):
    username: str
    email: Optional[str] = None
    public_key: str

class UserResponse(BaseModel):
    id: int
    did: str
    username: str
    email: Optional[str] = None
    ipfs_hash: Optional[str] = None
    created_at: datetime
    is_verified: bool
    
    class Config:
        from_attributes = True

class ReputationResponse(BaseModel):
    id: int
    user_id: int
    score: float
    total_reviews: int
    positive_reviews: int
    negative_reviews: int
    last_updated: datetime
    
    class Config:
        from_attributes = True

class AttestationCreate(BaseModel):
    attestation_type: str
    data: Optional[str] = None
    signature: str

class AttestationResponse(BaseModel):
    id: int
    user_id: int
    attester_did: str
    attestation_type: str
    data: Optional[str] = None
    created_at: datetime
    is_valid: bool
    
    class Config:
        from_attributes = True

class TokenTransactionCreate(BaseModel):
    transaction_type: str
    amount: float
    description: Optional[str] = None

class TokenTransactionResponse(BaseModel):
    id: int
    user_id: int
    transaction_type: str
    amount: float
    description: Optional[str] = None
    created_at: datetime
    
    class Config:
        from_attributes = True

class IdentityVerificationRequest(BaseModel):
    did: str
    verification_type: str
