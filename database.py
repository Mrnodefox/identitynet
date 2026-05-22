from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean, Text, ForeignKey, inspect, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
import os

DB_ENCRYPTION_KEY = os.getenv("DB_ENCRYPTION_KEY", os.urandom(32).hex())
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./identitynet.db")

try:
    from pysqlcipher3 import dbapi2 as sqlite
    engine = create_engine(
        f"sqlite+pysqlcipher3:///{DATABASE_URL.replace('sqlite:///', '')}",
        connect_args={
            "check_same_thread": False,
            "key": DB_ENCRYPTION_KEY
        }
    )
except ImportError:
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {})

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    did = Column(String(255), unique=True, index=True, nullable=False)
    username = Column(String(100), unique=True, index=True, nullable=False)
    email = Column(String(255), unique=True, index=True)
    public_key = Column(Text, nullable=False)
    ipfs_hash = Column(String(255), unique=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_verified = Column(Boolean, default=False)
    node_id = Column(String(32), index=True)
    synced = Column(Boolean, default=False)
    token_balance = Column(Float, default=0.0)
    disclosure_commitments = Column(Text)  # JSON map attribute -> commitment

    reputation = relationship("Reputation", back_populates="user", uselist=False)
    attestations = relationship("Attestation", back_populates="user")
    tokens = relationship("TokenTransaction", back_populates="user")
    agents = relationship("Agent", back_populates="owner")


class Agent(Base):
    __tablename__ = "agents"

    id = Column(Integer, primary_key=True, index=True)
    agent_did = Column(String(255), unique=True, index=True, nullable=False)
    owner_did = Column(String(255), ForeignKey("users.did"), index=True, nullable=False)
    name = Column(String(120), nullable=False)
    public_key = Column(Text, nullable=False)
    signature = Column(Text, nullable=False)
    reputation_score = Column(Float, default=50.0)
    contracts_completed = Column(Integer, default=0)
    court_enrolled = Column(Boolean, default=False)
    debate_wins = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    owner = relationship("User", back_populates="agents", foreign_keys=[owner_did])


class AgentContract(Base):
    __tablename__ = "agent_contracts"

    id = Column(Integer, primary_key=True, index=True)
    contract_id = Column(String(64), unique=True, index=True, nullable=False)
    proposer_agent_did = Column(String(255), index=True, nullable=False)
    proposer_owner_did = Column(String(255), index=True, nullable=False)
    responder_agent_did = Column(String(255), index=True)
    responder_owner_did = Column(String(255), index=True)
    intent = Column(String(500), nullable=False)
    escrow_amount = Column(Float, default=0.0)
    terms_json = Column(Text)
    witness_quorum = Column(Integer, default=1)
    witness_reward = Column(Float, default=0.05)
    status = Column(String(50), default="open")
    delivery_log_json = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


class AgentParliamentMessage(Base):
    __tablename__ = "agent_parliament_messages"

    id = Column(Integer, primary_key=True, index=True)
    contract_id = Column(String(64), index=True, nullable=False)
    message_type = Column(String(32), nullable=False)
    agent_did = Column(String(255), nullable=False)
    body_json = Column(Text)
    signature = Column(Text, nullable=False)
    timestamp = Column(String(64), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class AgentWitness(Base):
    __tablename__ = "agent_witnesses"

    id = Column(Integer, primary_key=True, index=True)
    contract_id = Column(String(64), index=True, nullable=False)
    witness_did = Column(String(255), index=True, nullable=False)
    witness_public_key = Column(Text, nullable=False)
    event = Column(String(64), default="contract_delivered")
    contract_hash = Column(String(128), nullable=False)
    signature = Column(Text, nullable=False)
    timestamp = Column(String(64), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Reputation(Base):
    __tablename__ = "reputation"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    score = Column(Float, default=0.0)
    total_reviews = Column(Integer, default=0)
    positive_reviews = Column(Integer, default=0)
    negative_reviews = Column(Integer, default=0)
    last_updated = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="reputation")


class Attestation(Base):
    __tablename__ = "attestations"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    subject_did = Column(String(255), index=True)
    attester_did = Column(String(255), nullable=False)
    attester_public_key = Column(Text)
    attestation_type = Column(String(100), nullable=False)
    data = Column(Text)
    signature = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_valid = Column(Boolean, default=True)
    network_synced = Column(Boolean, default=False)

    user = relationship("User", back_populates="attestations")


class TokenTransaction(Base):
    __tablename__ = "token_transactions"

    id = Column(Integer, primary_key=True, index=True)
    tx_id = Column(String(64), unique=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    signer_did = Column(String(255), index=True)
    transaction_type = Column(String(50), nullable=False)
    amount = Column(Float, nullable=False)
    description = Column(Text)
    signature = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    network_synced = Column(Boolean, default=False)

    user = relationship("User", back_populates="tokens")


def _migrate_columns():
    """Add new columns to existing SQLite databases."""
    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        return
    user_cols = {c["name"] for c in inspector.get_columns("users")}
    with engine.begin() as conn:
        if "token_balance" not in user_cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN token_balance FLOAT DEFAULT 0.0"))
        if "disclosure_commitments" not in user_cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN disclosure_commitments TEXT"))

    if "attestations" in inspector.get_table_names():
        att_cols = {c["name"] for c in inspector.get_columns("attestations")}
        with engine.begin() as conn:
            if "subject_did" not in att_cols:
                conn.execute(text("ALTER TABLE attestations ADD COLUMN subject_did VARCHAR(255)"))
            if "attester_public_key" not in att_cols:
                conn.execute(text("ALTER TABLE attestations ADD COLUMN attester_public_key TEXT"))
            if "network_synced" not in att_cols:
                conn.execute(text("ALTER TABLE attestations ADD COLUMN network_synced BOOLEAN DEFAULT 0"))

    if "agents" in inspector.get_table_names():
        agent_cols = {c["name"] for c in inspector.get_columns("agents")}
        with engine.begin() as conn:
            if "court_enrolled" not in agent_cols:
                conn.execute(text("ALTER TABLE agents ADD COLUMN court_enrolled BOOLEAN DEFAULT 0"))
            if "debate_wins" not in agent_cols:
                conn.execute(text("ALTER TABLE agents ADD COLUMN debate_wins INTEGER DEFAULT 0"))

    if "token_transactions" in inspector.get_table_names():
        tok_cols = {c["name"] for c in inspector.get_columns("token_transactions")}
        with engine.begin() as conn:
            for col, ddl in [
                ("tx_id", "ALTER TABLE token_transactions ADD COLUMN tx_id VARCHAR(64)"),
                ("signer_did", "ALTER TABLE token_transactions ADD COLUMN signer_did VARCHAR(255)"),
                ("signature", "ALTER TABLE token_transactions ADD COLUMN signature TEXT"),
                ("network_synced", "ALTER TABLE token_transactions ADD COLUMN network_synced BOOLEAN DEFAULT 0"),
            ]:
                if col not in tok_cols:
                    conn.execute(text(ddl))


def init_db():
    Base.metadata.create_all(bind=engine)
    _migrate_columns()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
