#!/bin/bash

# Automated Worker Setup Script for Distributed Ollama
# This script helps donors set up their worker client

set -e

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}================================================${NC}"
echo -e "${BLUE}  Distributed Ollama Worker Setup${NC}"
echo -e "${BLUE}================================================${NC}"
echo ""

# Check OS
OS="unknown"
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    OS="linux"
elif [[ "$OSTYPE" == "darwin"* ]]; then
    OS="mac"
fi

echo -e "${GREEN}✓${NC} Detected OS: $OS"

# Check Python
echo ""
echo -e "${BLUE}Checking Python installation...${NC}"
if command -v python3 &> /dev/null; then
    python_version=$(python3 --version | grep -oP '\d+\.\d+')
    echo -e "${GREEN}✓${NC} Python $python_version found"
else
    echo -e "${RED}✗${NC} Python 3 not found"
    echo ""
    echo "Please install Python 3.8 or newer:"
    echo "  Linux: sudo apt install python3 python3-pip"
    echo "  Mac:   brew install python3"
    echo "  Windows: https://python.org/downloads"
    exit 1
fi

# Check pip
if ! command -v pip3 &> /dev/null; then
    echo -e "${YELLOW}⚠${NC} pip not found, installing..."
    if [[ "$OS" == "linux" ]]; then
        sudo apt install -y python3-pip
    else
        echo "Please install pip manually"
        exit 1
    fi
fi

# Check Ollama
echo ""
echo -e "${BLUE}Checking Ollama installation...${NC}"
if command -v ollama &> /dev/null; then
    echo -e "${GREEN}✓${NC} Ollama is installed"
else
    echo -e "${RED}✗${NC} Ollama not found"
    echo ""
    echo "Installing Ollama..."
    if [[ "$OS" == "linux" ]] || [[ "$OS" == "mac" ]]; then
        curl -fsSL https://ollama.ai/install.sh | sh
        echo -e "${GREEN}✓${NC} Ollama installed"
    else
        echo "Please install Ollama from: https://ollama.ai/download"
        exit 1
    fi
fi

# Check if Ollama is running
echo ""
echo -e "${BLUE}Checking if Ollama is running...${NC}"
if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo -e "${GREEN}✓${NC} Ollama is running"
else
    echo -e "${YELLOW}⚠${NC} Ollama is not running"
    echo "Starting Ollama..."
    ollama serve > /dev/null 2>&1 &
    sleep 3
    if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
        echo -e "${GREEN}✓${NC} Ollama started"
    else
        echo -e "${RED}✗${NC} Failed to start Ollama"
        echo "Please start it manually: ollama serve"
        exit 1
    fi
fi

# Check installed models
echo ""
echo -e "${BLUE}Checking installed models...${NC}"
models=$(ollama list 2>/dev/null | tail -n +2 | awk '{print $1}' | grep -v "^$" || echo "")
model_count=$(echo "$models" | grep -c . || echo "0")

if [ "$model_count" -gt 0 ]; then
    echo -e "${GREEN}✓${NC} Found $model_count model(s):"
    echo "$models" | while read -r model; do
        echo "  - $model"
    done
else
    echo -e "${YELLOW}⚠${NC} No models installed"
    echo ""
    echo "Downloading recommended models (this will take a while)..."
    echo ""
    
    read -p "Install llama2 (~4GB)? [Y/n] " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Nn]$ ]]; then
        ollama pull llama2
    fi
    
    read -p "Install mistral (~4GB)? [Y/n] " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Nn]$ ]]; then
        ollama pull mistral
    fi
    
    read -p "Install phi (small, ~2GB)? [Y/n] " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Nn]$ ]]; then
        ollama pull phi
    fi
fi

# Create worker directory
WORKER_DIR="$HOME/ollama-worker"
echo ""
echo -e "${BLUE}Setting up worker directory...${NC}"

if [ -d "$WORKER_DIR" ]; then
    echo -e "${YELLOW}⚠${NC} Directory already exists: $WORKER_DIR"
    read -p "Overwrite? [y/N] " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        rm -rf "$WORKER_DIR"
    else
        cd "$WORKER_DIR"
    fi
fi

if [ ! -d "$WORKER_DIR" ]; then
    mkdir -p "$WORKER_DIR"
    echo -e "${GREEN}✓${NC} Created directory: $WORKER_DIR"
fi

cd "$WORKER_DIR"

# Copy worker files
echo ""
echo -e "${BLUE}Setting up worker files...${NC}"

# Check if we're in the distributed-ollama directory
if [ -f "../worker/client.py" ]; then
    cp ../worker/client.py .
    cp ../requirements.txt .
    echo -e "${GREEN}✓${NC} Copied worker files"
else
    echo -e "${YELLOW}⚠${NC} Worker files not found in parent directory"
    echo "Please ensure client.py and requirements.txt are in $WORKER_DIR"
    echo "You can download them from the distributed-ollama package"
    exit 1
fi

# Install Python dependencies
echo ""
echo -e "${BLUE}Installing Python dependencies...${NC}"
pip3 install -q -r requirements.txt
echo -e "${GREEN}✓${NC} Dependencies installed"

# Get coordinator URL
echo ""
echo -e "${BLUE}Coordinator Configuration${NC}"
echo ""
read -p "Enter coordinator URL (e.g., http://your-server.com:8080): " coordinator_url

if [ -z "$coordinator_url" ]; then
    echo -e "${RED}✗${NC} Coordinator URL required"
    exit 1
fi

# Test connection to coordinator
echo ""
echo -e "${BLUE}Testing connection to coordinator...${NC}"
if curl -s "$coordinator_url/api/status" > /dev/null 2>&1; then
    echo -e "${GREEN}✓${NC} Coordinator is reachable"
else
    echo -e "${YELLOW}⚠${NC} Cannot reach coordinator"
    echo "The coordinator might be down or the URL is incorrect"
    read -p "Continue anyway? [y/N] " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Create start script
echo ""
echo -e "${BLUE}Creating start script...${NC}"

cat > "$WORKER_DIR/start-worker.sh" << EOF
#!/bin/bash
cd "$WORKER_DIR"
python3 client.py --coordinator "$coordinator_url"
EOF

chmod +x "$WORKER_DIR/start-worker.sh"
echo -e "${GREEN}✓${NC} Created start-worker.sh"

# Print success
echo ""
echo -e "${GREEN}================================================${NC}"
echo -e "${GREEN}  Setup Complete! ✓${NC}"
echo -e "${GREEN}================================================${NC}"
echo ""
echo -e "${BLUE}Your worker is ready to start donating!${NC}"
echo ""
echo -e "${YELLOW}To start the worker:${NC}"
echo "  cd $WORKER_DIR"
echo "  ./start-worker.sh"
echo ""
echo -e "Or directly:"
echo "  python3 client.py --coordinator $coordinator_url"
echo ""
echo -e "${YELLOW}What happens next:${NC}"
echo "1. The worker will register with the coordinator"
echo "2. It will share your GPU/CPU resources"
echo "3. When requests come in, they'll be processed"
echo "4. Press Ctrl+C to stop anytime"
echo ""
echo -e "${YELLOW}System Resources:${NC}"

# Show system info
if command -v nvidia-smi &> /dev/null; then
    gpu_info=$(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits | head -1)
    echo "  GPU: $gpu_info"
fi

total_ram=$(free -h 2>/dev/null | awk '/^Mem:/ {print $2}' || echo "Unknown")
echo "  RAM: $total_ram"

cpu_count=$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo "Unknown")
echo "  CPU: $cpu_count cores"

echo ""
echo -e "${YELLOW}Installed Models:${NC}"
ollama list 2>/dev/null | tail -n +2 | awk '{print "  - " $1}'

echo ""
echo -e "${YELLOW}Optional: Run as background service${NC}"
echo "See docs/SYSTEMD_SERVICES.md for instructions"
echo ""
echo -e "${GREEN}Thank you for contributing! 🙏${NC}"
echo -e "${GREEN}================================================${NC}"
