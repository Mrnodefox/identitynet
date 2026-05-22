from pydantic import BaseModel, Field
from datetime import datetime
from typing import Any, Dict, List, Optional


class UserCreate(BaseModel):
    username: str
    email: Optional[str] = None
    public_key: str
    registration_signature: str
    timestamp: str = Field(..., description="ISO timestamp used when signing registration")


class UserResponse(BaseModel):
    id: int
    did: str
    username: str
    email: Optional[str] = None
    ipfs_hash: Optional[str] = None
    created_at: datetime
    is_verified: bool
    token_balance: float = 0.0

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
    attester_did: str
    attester_public_key: str
    attestation_type: str
    data: Optional[str] = None
    signature: str
    timestamp: str


class AttestationResponse(BaseModel):
    id: int
    user_id: int
    subject_did: Optional[str] = None
    attester_did: str
    attestation_type: str
    data: Optional[str] = None
    created_at: datetime
    is_valid: bool
    network_synced: bool = False

    class Config:
        from_attributes = True


class WalletBinding(BaseModel):
    """Signed ITN wallet state from GET /users/{id}/itn/wallet-payload."""
    payload: Dict[str, Any]
    signature: str


class TokenTransactionCreate(BaseModel):
    transaction_type: str
    amount: float
    description: Optional[str] = None
    signature: str
    timestamp: str
    wallet_binding: Optional[WalletBinding] = None


class ITNTransferCreate(BaseModel):
    to_did: str
    amount: float
    signature: str
    timestamp: str
    wallet_binding: Optional[WalletBinding] = None


class ITNSealRequest(BaseModel):
    wallet_binding: WalletBinding


class ITNWalletResponse(BaseModel):
    coin: str = "ITN"
    did: str
    wallet_file: str
    balance_file: str
    wallet: Dict[str, Any]
    balance: Dict[str, Any]
    binding_valid: bool


class TokenTransactionResponse(BaseModel):
    id: int
    tx_id: Optional[str] = None
    user_id: int
    signer_did: Optional[str] = None
    transaction_type: str
    amount: float
    description: Optional[str] = None
    created_at: datetime
    network_synced: bool = False

    class Config:
        from_attributes = True


class IdentityVerificationRequest(BaseModel):
    did: str
    verification_type: str
    signature: str
    timestamp: str
    wallet_binding: Optional[WalletBinding] = None


class ZKCommitRequest(BaseModel):
    attribute: str
    value: str
    salt: Optional[str] = None


class ZKCommitResponse(BaseModel):
    attribute: str
    commitment: str
    salt: str


class ZKProofKnowledgeRequest(BaseModel):
    value: str
    salt: str


class ZKProofKnowledgeResponse(BaseModel):
    proof: Dict[str, str]
    verified: bool = False


class ZKSelectiveDisclosureRequest(BaseModel):
    private_key: str
    public_key: str
    attribute: str
    value: str
    salt: str


class ZKVerifyRequest(BaseModel):
    proof: Dict[str, Any]
    mode: str = Field("knowledge", description="knowledge | disclosure")


class LedgerBalanceResponse(BaseModel):
    did: str
    balance: float
    source: str


class AgentRegister(BaseModel):
    owner_did: str
    name: str
    public_key: str
    signature: str
    timestamp: str


class AgentResponse(BaseModel):
    agent_did: str
    owner_did: str
    name: str
    public_key: str
    reputation_score: float = 50.0
    contracts_completed: int = 0


class AgentOfferCreate(BaseModel):
    proposer_agent_did: str
    public_key: str
    intent: str
    escrow_amount: float = Field(..., ge=0)
    signature: str
    timestamp: str
    responder_agent_did: Optional[str] = None
    terms: Optional[Dict[str, Any]] = None
    witness_quorum: Optional[int] = Field(None, ge=1, le=20)


class AgentMessageCreate(BaseModel):
    message_type: str = Field(..., description="counter | accept | deliver | reject | cancel")
    agent_did: str
    public_key: str
    body: Dict[str, Any] = Field(default_factory=dict)
    signature: str
    timestamp: str


class AgentWitnessCreate(BaseModel):
    witness_did: str
    witness_public_key: str
    event: str = "contract_delivered"
    signature: str
    timestamp: str


class AgentSettlePlanResponse(BaseModel):
    contract_id: str
    payer_did: str
    responder_payout: Dict[str, Any]
    witness_payouts: List[Dict[str, Any]]
    platform_fee: float
    total_debit: float


class AgentSettleCreate(BaseModel):
    payer_did: str
    signature: str
    timestamp: str
    transfers: List[Dict[str, Any]] = Field(
        ...,
        description="List of {to_did, amount, tx_id, signature} signed transfer payloads",
    )


class CourtEnrollRequest(BaseModel):
    owner_did: str
    agent_name: str
    public_key: str
    signature: str
    timestamp: str


class CourtEnrollResponse(BaseModel):
    owner_did: str
    user_id: int
    username: str
    agent_did: str
    agent_name: str
    court_enrolled: bool
    already_enrolled: bool = False
    wallet: Dict[str, Any]
    ledger_balance: float
    message: str


class CourtStatusResponse(BaseModel):
    owner_did: str
    user_id: int
    has_identity: bool
    court_enrolled: bool
    agent_did: Optional[str] = None
    agent_name: Optional[str] = None
    debate_wins: int = 0
    wallet: Dict[str, Any]
    ledger_balance: float


class DebateCaseSummary(BaseModel):
    id: str
    title: str
    category: str
    summary: str
    proposer_role: str
    responder_role: str


class DebateStartRequest(BaseModel):
    case_id: str
    use_llm: bool = False
    player_owner_did: Optional[str] = None
    player_side: Optional[str] = Field(
        None, description="proposer or responder — your counsel's side"
    )


class DebateSessionResponse(BaseModel):
    session_id: str
    case_id: str
    contract_id: str
    started_at: str
    case: Dict[str, Any]
    proposer_role: str
    responder_role: str
    proposer_agent_did: str = ""
    responder_agent_did: str = ""
    status: str
    transcript: List[Dict[str, Any]]
    poll: Dict[str, Any]
    player_owner_did: Optional[str] = None
    player_agent_did: Optional[str] = None
    player_side: Optional[str] = None
    player_counsel_name: Optional[str] = None


class DebateVerdictRequest(BaseModel):
    option_id: str
    claim_reward: bool = True


class AgentContractResponse(BaseModel):
    contract_id: str
    proposer_agent_did: str
    proposer_owner_did: str
    responder_agent_did: Optional[str] = None
    responder_owner_did: Optional[str] = None
    intent: str
    escrow_amount: float
    terms: Dict[str, Any] = Field(default_factory=dict)
    witness_quorum: int
    witness_reward: float
    status: str
    contract_hash: Optional[str] = None
    witness_count: int = 0
    messages: Optional[List[Dict[str, Any]]] = None
    witnesses: Optional[List[Dict[str, Any]]] = None
