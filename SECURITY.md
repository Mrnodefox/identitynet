# Security Configuration Guide

This document explains the security features implemented in IdentityNet and how to configure them.

## Priority 2 (High) Security Features

### 1. Database Encryption (SQLCipher)

The database is now encrypted using SQLCipher via pysqlcipher3.

**Configuration:**
- Set the `DB_ENCRYPTION_KEY` environment variable to use a specific encryption key
- If not set, a random key will be generated on startup (not recommended for production)
- Store the key securely in production environments

**Example:**
```bash
export DB_ENCRYPTION_KEY="your-secure-64-character-hex-key"
```

**Requirements:**
- pysqlcipher3==1.2.0 (already in requirements.txt)

### 2. Secure Headers (fastapi-secure-headers)

Comprehensive security headers are configured to protect against various attacks.

**Implemented Headers:**
- **HSTS (HTTP Strict Transport Security)**: Enforces HTTPS connections
  - Max age: 1 year
  - Include subdomains: Yes
  - Preload: Yes
- **Content Security Policy (CSP)**: Restricts resource loading
  - Default source: 'self'
  - Script source: 'self'
  - Style source: 'self'
  - Image source: 'self' and data:
  - Frame ancestors: 'none'
  - Block mixed content: Yes
  - Upgrade insecure requests: Yes
- **X-Frame-Options**: DENY (prevents clickjacking)
- **X-Content-Type-Options**: nosniff (prevents MIME sniffing)
- **X-XSS-Protection**: 1; mode=block (XSS filter)
- **Referrer-Policy**: strict-origin-when-cross-origin
- **Permissions Policy**: Restricts browser features
  - Geolocation: 'self'
  - Microphone: 'none'
  - Camera: 'none'
- **Server Header**: Custom server header (IdentityNet)

**Requirements:**
- fastapi-secure-headers==0.4.5 (already in requirements.txt)

### 3. HTTPS/TLS with Let's Encrypt

The application supports HTTPS/TLS using Let's Encrypt certificates.

**Configuration:**
```bash
# Enable HTTPS enforcement
export FORCE_HTTPS=true

# Set paths to Let's Encrypt certificates
export SSL_CERT_PATH="/etc/letsencrypt/live/yourdomain.com/fullchain.pem"
export SSL_KEY_PATH="/etc/letsencrypt/live/yourdomain.com/privkey.pem"
```

**To obtain Let's Encrypt certificates:**
```bash
# Install certbot
sudo apt-get install certbot

# Obtain certificate (replace with your domain)
sudo certbot certonly --standalone -d yourdomain.com

# Certificates will be stored in /etc/letsencrypt/live/yourdomain.com/
```

**Auto-renewal:**
Certbot automatically renews certificates. Set up a cron job:
```bash
sudo crontab -e
# Add: 0 0 * * * certbot renew --quiet
```

**Note:** The application will run in HTTP mode if certificates are not found or FORCE_HTTPS is false.

### 4. Request Signing with Private Keys

All sensitive API endpoints now require request signatures using HMAC-SHA256.

**Protected Endpoints:**
- POST /users/create
- POST /users/{user_id}/attestations
- POST /users/{user_id}/tokens
- POST /verify
- POST /system/update

**Configuration:**
```bash
export API_PRIVATE_KEY="your-secure-64-character-hex-key"
```

**How to Sign Requests:**

1. Generate a timestamp in ISO format:
```python
from datetime import datetime
timestamp = datetime.utcnow().isoformat()
```

2. Create the signature string:
```
{METHOD}\n{URL}\n{TIMESTAMP}\n{CONTENT_TYPE}\n{BODY}
```

3. Generate HMAC-SHA256 signature:
```python
import hmac
import hashlib

signature_string = f"{method}\n{url}\n{timestamp}\n{content_type}\n{body}"
signature = hmac.new(
    private_key.encode(),
    signature_string.encode(),
    hashlib.sha256
).hexdigest()
```

4. Add headers to your request:
```
X-Signature: {signature}
X-Timestamp: {timestamp}
```

**Example Python Client:**
```python
import hmac
import hashlib
from datetime import datetime
import requests

def make_signed_request(url, method, data=None, private_key="your-key"):
    timestamp = datetime.utcnow().isoformat()
    content_type = "application/json"
    body = json.dumps(data) if data else ""
    
    signature_string = f"{method}\n{url}\n{timestamp}\n{content_type}\n{body}"
    signature = hmac.new(
        private_key.encode(),
        signature_string.encode(),
        hashlib.sha256
    ).hexdigest()
    
    headers = {
        "X-Signature": signature,
        "X-Timestamp": timestamp,
        "Content-Type": content_type
    }
    
    if method == "POST":
        return requests.post(url, json=data, headers=headers)
    elif method == "GET":
        return requests.get(url, headers=headers)
```

**Security Notes:**
- Signatures are valid for 5 minutes (configurable via SIGNATURE_TOLERANCE_SECONDS)
- Timestamp validation prevents replay attacks
- Constant-time comparison prevents timing attacks
- Keep your API_PRIVATE_KEY secret and never expose it in client-side code

## Environment Variables Summary

Create a `.env` file or set these environment variables:

```bash
# Database Encryption
DB_ENCRYPTION_KEY="your-64-character-hex-key"

# HTTPS/TLS
FORCE_HTTPS=true
SSL_CERT_PATH="/etc/letsencrypt/live/yourdomain.com/fullchain.pem"
SSL_KEY_PATH="/etc/letsencrypt/live/yourdomain.com/privkey.pem"

# Request Signing
API_PRIVATE_KEY="your-64-character-hex-key"

# Database (optional)
DATABASE_URL="sqlite:///./identitynet.db"
```

## Security Best Practices

1. **Generate strong encryption keys:**
```python
import secrets
key = secrets.token_hex(32)  # 64-character hex string
```

2. **Never commit keys to version control** - Add `.env` to `.gitignore`

3. **Use different keys** for database encryption and API signing

4. **Rotate keys periodically** in production environments

5. **Monitor logs** for signature verification failures

6. **Use HTTPS in production** - Never expose the API over HTTP in production

7. **Keep dependencies updated** - Regularly update security packages

8. **Implement rate limiting** - Add rate limiting to prevent brute force attacks

9. **Use a reverse proxy** - Consider using nginx or Apache as a reverse proxy for additional security

10. **Regular security audits** - Periodically review and audit the security implementation
