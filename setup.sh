#!/bin/bash

# Distributed Ollama Setup Script

set -e

echo "================================================"
echo "  Distributed Ollama Network Setup"
echo "================================================"
echo ""

# Check Python version
echo "Checking Python version..."
python_version=$(python3 --version 2>&1 | awk '{print $2}')
required_version="3.8"

if ! python3 -c "import sys; exit(0 if sys.version_info >= (3,8) else 1)"; then
    echo "❌ Error: Python 3.8 or higher is required"
    echo "   Current version: $python_version"
    exit 1
fi

echo "✓ Python $python_version detected"
echo ""

# Install dependencies
echo "Installing dependencies..."
if [ -f requirements.txt ]; then
    pip3 install -r requirements.txt
    echo "✓ Dependencies installed"
else
    echo "❌ Error: requirements.txt not found"
    exit 1
fi

echo ""
echo "================================================"
echo "  Setup Complete!"
echo "================================================"
echo ""
echo "What would you like to run?"
echo ""
echo "1. Coordinator Server (manages workers)"
echo "   python3 coordinator/server.py --host 0.0.0.0 --port 8080"
echo ""
echo "2. Public Proxy (provides public URL)"
echo "   python3 proxy/server.py --coordinator http://localhost:8080 --port 11434"
echo ""
echo "3. Worker Client (donate resources)"
echo "   python3 worker/client.py --coordinator http://coordinator-url:8080"
echo ""
echo "4. All at once with Docker"
echo "   docker-compose up -d"
echo ""
echo "================================================"
echo ""
echo "For detailed instructions, see README.md"
echo ""
