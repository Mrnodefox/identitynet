#!/bin/bash

set -e

echo "Installing IdentityNet..."

# Load .env file if it exists
if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | xargs)
fi

# Check Android API level
if [ -n "$TERMUX_VERSION" ]; then
    if [ -n "$ANDROID_API_LEVEL" ] && [ -n "$ANDROID_VERSION" ]; then
        API_LEVEL=$ANDROID_API_LEVEL
        ANDROID_VERSION=$ANDROID_VERSION
        echo "Using Android configuration from .env: Android $ANDROID_VERSION (API level $API_LEVEL)"
    else
        API_LEVEL=$(getprop ro.build.version.sdk 2>/dev/null || echo "0")
        ANDROID_VERSION=$(getprop ro.build.version.release 2>/dev/null || echo "unknown")
        echo "Detected Android $ANDROID_VERSION (API level $API_LEVEL)"
    fi
    
    if [ "$API_LEVEL" -lt 21 ]; then
        echo "ERROR: Android API level $API_LEVEL is not supported."
        echo "Minimum required: Android 5.0 (API level 21)"
        echo "Please update your Android version or use a newer device."
        echo "Or set ANDROID_API_LEVEL in .env file if detection failed."
        exit 1
    elif [ "$API_LEVEL" -lt 23 ]; then
        echo "WARNING: Android API level $API_LEVEL may have compatibility issues."
        echo "Recommended: Android 6.0 (API level 23) or higher"
        echo "Continuing installation..."
    else
        echo "Android version is compatible."
    fi
else
    echo "Not running in Termux. Skipping Android API level check."
fi

# Update packages
pkg update -y

# Install Python and required packages
pkg install -y python git curl

# Install IPFS
echo "Installing IPFS..."
pkg install -y ipfs

# Initialize IPFS
echo "Checking IPFS initialization..."
if [ -d ~/.ipfs ]; then
    echo "IPFS already initialized. Skipping initialization to preserve existing keys."
else
    echo "Initializing IPFS..."
    ipfs init
fi

# Clone repository
echo "Cloning repository..."
if [ -d "~/identitynet/.git" ]; then
    echo "Repository already exists. Pulling updates..."
    cd ~/identitynet
    git pull origin main
else
    git clone https://github.com/Mrnodefox/identitynet.git ~/identitynet
    cd ~/identitynet
fi

# Install Python dependencies
echo "Installing Python dependencies..."
pip install -r requirements.txt

# Initialize database
echo "Initializing database..."
python -c "from database import init_db; init_db()"

# Start IPFS daemon in background
echo "Starting IPFS daemon..."
ipfs daemon > /dev/null 2>&1 &

echo "Installation complete!"
echo ""
echo "To start the server, run:"
echo "cd ~/identitynet && python main.py"
echo ""
echo "The server will start on http://localhost:8000"
echo "API documentation: http://localhost:8000/docs"
echo ""
echo "Note: IPFS daemon is running in background"
