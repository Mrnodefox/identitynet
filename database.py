from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean, Text, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
import os

# SQLCipher database encryption
DB_ENCRYPTION_KEY = os.getenv("DB_ENCRYPTION_KEY", os.urandom(32).hex())
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./identitynet.db")

# Use pysqlcipher3 for encrypted SQLite
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
    # Fallback to regular SQLite if pysqlcipher3 not available
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
    node_id = Column(String(32), index=True)  # Node that created this user
    synced = Column(Boolean, default=False)  # Whether synced to global registry
    
    reputation = relationship("Reputation", back_populates="user", uselist=False)
    attestations = relationship("Attestation", back_populates="user")
    tokens = relationship("TokenTransaction", back_populates="user")

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
    attester_did = Column(String(255), nullable=False)
    attestation_type = Column(String(100), nullable=False)
    data = Column(Text)
    signature = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_valid = Column(Boolean, default=True)
    
    user = relationship("User", back_populates="attestations")

class TokenTransaction(Base):
    __tablename__ = "token_transactions"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    transaction_type = Column(String(50), nullable=False)
    amount = Column(Float, nullable=False)
    description = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User", back_populates="tokens")

def init_db():
    Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
