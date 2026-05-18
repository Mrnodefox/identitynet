#!/bin/bash

set -e

echo "Updating IdentityNet..."

# Navigate to project directory
cd ~/identitynet || { echo "IdentityNet not found. Please install first."; exit 1; }

# Backup current database
if [ -f "identitynet.db" ]; then
    echo "Backing up database..."
    cp identitynet.db identitynet.db.backup
fi

# Pull latest changes from git
echo "Pulling latest changes from repository..."
git pull origin main

# Update Python dependencies
echo "Updating Python dependencies..."
pip install -r requirements.txt --upgrade

# Run database migrations if needed
echo "Checking database migrations..."
python -c "from database import init_db; init_db()"

echo "Update complete!"
echo ""
echo "To restart the server, run:"
echo "cd ~/identitynet && python main.py"
