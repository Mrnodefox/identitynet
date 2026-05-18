#!/bin/bash

set -e

echo "Installing IdentityNet..."

# Update packages
pkg update -y

# Install Python and required packages
pkg install -y python git curl

# Install IPFS
echo "Installing IPFS..."
pkg install -y ipfs

# Initialize IPFS
echo "Initializing IPFS..."
ipfs init

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
