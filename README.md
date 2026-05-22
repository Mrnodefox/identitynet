# IdentityNet - Decentralized Identity & Reputation System

A revolutionary decentralized identity and reputation system where users own and control their digital identity. Like Bitcoin was to money, IdentityNet is to identity - a global, P2P network for identity verification and reputation management.

## Features

- **Decentralized Identity (DID)**: Create unique, cryptographically secure identities
- **IPFS Integration**: Identity data stored on decentralized IPFS network
- **Local SQLite Database**: Each user controls their own local database
- **Reputation System**: Build and track reputation across platforms
- **Attestations**: Get verified by trusted sources
- **Token Economy**: Earn tokens for identity verification and reputation data
- **Privacy**: Selective data sharing with zero-knowledge proofs
- **Mobile-Friendly**: Optimized for Termux and mobile devices
- **True Decentralization**: No central server - data distributed across IPFS

## Installation

### Termux (Android)

```bash
curl -sL https://raw.githubusercontent.com/Mrnodefox/identitynet/main/install.sh | bash
```

### Manual Installation

```bash
# Install dependencies
pkg update -y
pkg install -y python git

# Clone or download files
mkdir -p ~/identitynet
cd ~/identitynet

# Install Python dependencies
pip install -r requirements.txt

# Initialize database
python -c "from database import init_db; init_db()"

# Start server
python main.py
```

### Linux/Mac/Windows

```bash
# Install Python 3.8+
# Install dependencies
pip install -r requirements.txt

# Initialize database
python -c "from database import init_db; init_db()"

# Start server
python main.py
```

## Usage

### Start the Server

```bash
python main.py
```

The server will start on `http://localhost:8000`

### API Documentation

Interactive API documentation available at: `http://localhost:8000/docs`

### API Endpoints

#### Create User (Ed25519 signed, IPFS canonical)
```bash
# 1. GET /generate-keys → public_key, private_key (DID is created on registration)
# 2. Sign registration_payload with private_key (see /crypto/sign-payload)
POST /users/create
Content-Type: application/json

{
  "username": "john_doe",
  "email": "john@example.com",
  "public_key": "<ed25519_public_hex>",
  "registration_signature": "<hex>",
  "timestamp": "2024-01-01T12:00:00"
}
```

#### Get User by ID
```bash
GET /users/{user_id}
```

#### Get User by DID
```bash
GET /users/did/{did}
```

#### Get Reputation
```bash
GET /users/{user_id}/reputation
```

#### Create Attestation (attester must sign with their Ed25519 key)
```bash
POST /users/{user_id}/attestations
Content-Type: application/json

{
  "attester_did": "did:identitynet:...",
  "attester_public_key": "<hex>",
  "attestation_type": "identity_verification",
  "data": "verification_data",
  "signature": "<hex>",
  "timestamp": "2024-01-01T12:00:00"
}
```

#### Get Attestations
```bash
GET /users/{user_id}/attestations
```

#### Create Token Transaction (signed, replicated on P2P ledger)
```bash
POST /users/{user_id}/tokens
Content-Type: application/json

{
  "transaction_type": "earn",
  "amount": 1.0,
  "description": "Identity verification reward",
  "signature": "<hex of ledger_payload>",
  "timestamp": "2024-01-01T12:00:00"
}
```

#### Zero-Knowledge Proofs
```bash
POST /zk/commit          # Store attribute commitment on user
POST /zk/prove           # Schnorr proof of knowledge (no reveal)
POST /zk/disclose        # Selective disclosure with signature
POST /zk/verify          # Verify proof (mode: knowledge | disclosure)
GET  /ledger/{did}/balance
GET  /ledger/{did}/transactions
GET  /users/{id}/profile # Canonical IPFS identity document
```

#### ITN coin files (IdentityNet Token)
Each user gets on-disk files under `data/ITN/` and `data/balance/`:

| File | Purpose |
|------|---------|
| `data/ITN/{did}.itn` | Wallet snapshot bound to your **private key** (Ed25519 `binding.signature`) |
| `data/balance/{did}.balance.json` | Full history: **earned**, **transferred**, **received** |

```bash
GET  /users/{id}/itn                 # ITN wallet + balance summary
GET  /users/{id}/balance             # Balance history file
GET  /users/{id}/itn/wallet-payload  # Payload to sign for wallet binding
POST /users/{id}/itn/seal            # Seal .itn after receives (wallet_binding)
POST /users/{id}/itn/transfer        # Transfer ITN to another DID
```

#### Get Token Transactions
```bash
GET /users/{user_id}/tokens
```

#### Verify Identity
```bash
POST /verify
Content-Type: application/json

{
  "did": "did:identitynet:abc123...",
  "verification_type": "kyc"
}
```

#### Get Statistics
```bash
GET /stats
```

#### Update System
```bash
POST /system/update
```

## Updating

### Via API

```bash
POST http://localhost:8000/system/update
```

### Via Command Line (Termux)

```bash
cd ~/identitynet
bash update.sh
```

### Via Git (Manual)

```bash
cd ~/identitynet
git pull origin main
pip install -r requirements.txt --upgrade
```

## Agent Parliament (agent-to-agent + human witnesses)

Agents bound to user DIDs negotiate signed contracts over PubSub; humans **witness** delivery; the proposer **settles** ITN to responder and witnesses.

| Step | Endpoint |
|------|----------|
| Register agent | `POST /agents/register` |
| Open offer | `POST /agents/contracts` |
| Negotiate | `POST /agents/contracts/{id}/messages` (`counter`, `accept`, `deliver`) |
| Witness | `POST /agents/contracts/{id}/witness` |
| Settlement plan | `GET /agents/contracts/{id}/settlement-plan` |
| Pay out | `POST /agents/contracts/{id}/settle` |

```bash
python main.py
# Open http://localhost:8000/docs — Agent Parliament chamber
# Select a case (justice, governance, climate, AI, crypto, etc.) → Open session
```

### Court enrollment (DID required)

1. `POST /users/create` — create identity (DID + ITN wallet auto-init)
2. `POST /agents/court/enroll` — sign with your identity key; registers court agent + links wallet
3. `POST /agents/debate/start` — include `player_owner_did` and `player_side` (`proposer` | `responder`)
4. `POST /agents/debate/sessions/{id}/verdict` — poll outcome; winners get `DEBATE_WIN_REWARD` ITN (default 1.0)

API:
- `GET /agents/court/status/{did}` — enrollment + wallet status
- `GET /agents/debate/cases` — list real-world debate cases
- `POST /agents/debate/start` — run signed debate (`{"case_id": "climate_2035", "player_owner_did": "...", "player_side": "proposer"}`)
- `POST /agents/debate/sessions/{id}/verdict` — citizen poll + ITN reward (`claim_reward: true`)

Optional: `OPENAI_API_KEY` rewrites arguments; `DEBATE_LLM_MODEL=gpt-4o-mini`

Env: `AGENT_WITNESS_QUORUM=1`, `AGENT_WITNESS_REWARD=0.05`, `AGENT_PLATFORM_FEE_RATE=0.02`

## Earning Potential

Users can earn tokens through:

1. **Identity Verification**: Earn 1.0 token per verification
2. **Reputation Building**: Higher reputation scores unlock earning opportunities
3. **Attestations**: Provide attestations for other users
4. **Referrals**: Earn tokens for referring new users (coming soon)
5. **Agent Parliament witnesses**: Earn ITN witness fees when you attest delivered agent contracts (`POST /agents/contracts/{id}/witness`)



## Architecture

- **Framework**: FastAPI (modern, async)
- **Storage**: IPFS (InterPlanetary File System) for decentralized data storage
- **Database**: Local SQLite with SQLAlchemy ORM (user-controlled)
- **Authentication**: Cryptographic keys (public/private key pairs)
- **Identity Standard**: DID (Decentralized Identifier)
- **Token System**: Built-in token economy for monetization
- **Distributed Network**: IPFS PubSub for real-time node communication
- **Global Registry**: Shared username and DID registry across all nodes
- **Node Discovery**: Automatic peer discovery via IPFS pubsub
- **Data Synchronization**: Real-time sync of user data across nodes

### Distributed Architecture (v2)

**Storage model:** IPFS is the canonical identity store; SQLite is a local cache. Nodes are peers, not authorities.

**Key Features:**
- **Global Username/DID registry** via IPFS PubSub (`identitynet-global-registry`)
- **Incoming message processing** — username, user sync, attestations, ledger txs applied to local cache
- **Ed25519 signatures** on registration, attestations, verification, and token txs
- **Network token ledger** — signed transactions replicated; balance = sum of verified network txs
- **ZK proofs** — Schnorr proofs (PyNaCl) + selective disclosure with commitments

**How It Works:**
1. `ipfs daemon --enable-pubsub-experiment` on each peer
2. User created → profile pinned to IPFS → pubsub broadcast
3. Other nodes receive pubsub messages and upsert local cache
4. Token/attestation events broadcast and merged into `distributed_ledger`
5. Clients prove attributes via `/zk/*` without sharing full profiles

**Setup Requirements:**
- IPFS daemon must be running with pubsub enabled: `ipfs daemon --enable-pubsub-experiment`
- Nodes must be able to communicate via IPFS
- Network connectivity between nodes required

**API Endpoints:**
- `GET /node/info` - Get node information and peer list
- `GET /node/registry` - Get global username and DID registry

**Database Schema Updates:**
- `node_id` - Tracks which node created the user
- `synced` - Indicates if user data is synced to global registry

## Security

- All identities are cryptographically secured
- Public/private key pair authentication
- Selective data sharing
- Zero-knowledge proofs for privacy
- No central authority controls your identity
- IPFS provides content-addressable storage (tamper-proof)
- Local database ensures user control over data
- **Request Signature Verification**: All POST endpoints require HMAC-SHA256 signature verification

### Request Signature Verification

All POST endpoints except `/users/create`, `/verify`, and `/users/{user_id}/tokens` require signature verification to ensure request authenticity. Clients must include the following headers:

- `X-Signature`: HMAC-SHA256 signature of the request
- `X-Timestamp`: ISO format timestamp (e.g., `2024-01-01T12:00:00`)

#### Setup

Set the `API_PRIVATE_KEY` environment variable:

```bash
export API_PRIVATE_KEY="your_private_key_here"
```

Or generate a new key:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

#### Generating Signatures

Use the `/generate-keys` endpoint to get a key pair, or use the helper function:

```python
import hmac
import hashlib
from datetime import datetime

def generate_request_signature(method: str, url: str, body: str, private_key: str) -> tuple:
    timestamp = datetime.utcnow().isoformat()
    content_type = "application/json"
    
    signature_string = f"{method}\n{url}\n{timestamp}\n{content_type}\n{body}"
    signature = hmac.new(
        private_key.encode(),
        signature_string.encode(),
        hashlib.sha256
    ).hexdigest()
    
    return signature, timestamp
```

#### Example Request with Signature

```bash
# Generate signature and timestamp
PRIVATE_KEY="your_private_key"
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%S")
BODY='{"username":"john_doe","email":"john@example.com","public_key":"your_public_key"}'
SIGNATURE_STRING="POST\nhttp://localhost:8000/users/create\n${TIMESTAMP}\napplication/json\n${BODY}"
SIGNATURE=$(echo -n "$SIGNATURE_STRING" | openssl dgst -sha256 -hmac "$PRIVATE_KEY" | awk '{print $2}')

# Make request with signature headers
curl -X POST http://localhost:8000/users/create \
  -H "Content-Type: application/json" \
  -H "X-Signature: $SIGNATURE" \
  -H "X-Timestamp: $TIMESTAMP" \
  -d "$BODY"
```

**Note**: Signatures have a 5-minute tolerance window to prevent replay attacks.

## Roadmap

- [ ] Mobile app (Android/iOS)
- [ ] Cross-platform login integration
- [ ] Advanced reputation algorithms
- [ ] Token exchange integration
- [ ] Zero-knowledge proof implementation
- [ ] Mobile wallet integration

## License

MIT License

## Contributing

Contributions welcome! Please open an issue or submit a pull request.

## Support

For issues and questions, please open a GitHub issue.
