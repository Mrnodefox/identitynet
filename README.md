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

#### Create User
```bash
POST /users/create
Content-Type: application/json

{
  "username": "john_doe",
  "email": "john@example.com",
  "public_key": "your_public_key_here"
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

#### Create Attestation
```bash
POST /users/{user_id}/attestations
Content-Type: application/json

{
  "attestation_type": "identity_verification",
  "data": "verification_data",
  "signature": "signature_here"
}
```

#### Get Attestations
```bash
GET /users/{user_id}/attestations
```

#### Create Token Transaction
```bash
POST /users/{user_id}/tokens
Content-Type: application/json

{
  "transaction_type": "earn",
  "amount": 1.0,
  "description": "Identity verification reward"
}
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

## Earning Potential

Users can earn tokens through:

1. **Identity Verification**: Earn 1.0 token per verification
2. **Reputation Building**: Higher reputation scores unlock earning opportunities
3. **Attestations**: Provide attestations for other users
4. **Referrals**: Earn tokens for referring new users (coming soon)



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

### Distributed Architecture

IdentityNet now uses a truly distributed architecture where all nodes share a global registry:

**Key Features:**
- **Global Username Namespace**: Usernames are unique across all nodes
- **Shared DID Registry**: DIDs are tracked globally to prevent conflicts
- **Real-time Sync**: User data is synchronized across all connected nodes
- **Node Discovery**: Automatic discovery of other nodes in the network
- **Peer-to-Peer Communication**: Direct node-to-node communication via IPFS pubsub

**How It Works:**
1. Each node runs an IPFS daemon with pubsub enabled
2. Nodes automatically discover peers via the pubsub topic
3. When a user is created, the username is checked against the global registry
4. User data is synchronized across all nodes in real-time
5. Each user record tracks which node created it and sync status

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
