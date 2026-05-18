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

Target: $10/day through identity verification services and reputation monetization.

## Architecture

- **Framework**: FastAPI (modern, async, better than Flask)
- **Storage**: IPFS (InterPlanetary File System) for decentralized data storage
- **Database**: Local SQLite with SQLAlchemy ORM (user-controlled)
- **Authentication**: Cryptographic keys (public/private key pairs)
- **Identity Standard**: DID (Decentralized Identifier)
- **Token System**: Built-in token economy for monetization
- **Decentralization**: Each user runs their own node with local database + IPFS sync

## Security

- All identities are cryptographically secured
- Public/private key pair authentication
- Selective data sharing
- Zero-knowledge proofs for privacy
- No central authority controls your identity
- IPFS provides content-addressable storage (tamper-proof)
- Local database ensures user control over data

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
