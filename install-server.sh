#!/bin/bash

# Automated Distributed Ollama Server Installer
# This script sets up the coordinator and proxy on a fresh Ubuntu server

set -e

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}================================================${NC}"
echo -e "${BLUE}  Distributed Ollama Server Installer${NC}"
echo -e "${BLUE}================================================${NC}"
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo -e "${RED}Please run as root (use sudo)${NC}"
    exit 1
fi

echo -e "${GREEN}✓${NC} Running as root"

# Check Ubuntu version
if [ -f /etc/os-release ]; then
    . /etc/os-release
    if [[ "$ID" != "ubuntu" ]] && [[ "$ID" != "debian" ]]; then
        echo -e "${YELLOW}Warning: This script is designed for Ubuntu/Debian${NC}"
        read -p "Continue anyway? (y/n) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    fi
    echo -e "${GREEN}✓${NC} OS: $PRETTY_NAME"
fi

# Update system
echo ""
echo -e "${BLUE}Updating system packages...${NC}"
apt update -qq
apt upgrade -y -qq
echo -e "${GREEN}✓${NC} System updated"

# Install dependencies
echo ""
echo -e "${BLUE}Installing dependencies...${NC}"
apt install -y python3 python3-pip git curl ufw > /dev/null 2>&1
echo -e "${GREEN}✓${NC} Dependencies installed"

# Check Python version
python_version=$(python3 --version | grep -oP '\d+\.\d+')
echo -e "${GREEN}✓${NC} Python $python_version detected"

# Create installation directory
INSTALL_DIR="/opt/distributed-ollama"
echo ""
echo -e "${BLUE}Creating installation directory...${NC}"
mkdir -p $INSTALL_DIR
cd $INSTALL_DIR
echo -e "${GREEN}✓${NC} Directory: $INSTALL_DIR"

# Check if project already exists
if [ -d "$INSTALL_DIR/distributed-ollama" ]; then
    echo ""
    echo -e "${YELLOW}Installation already exists at $INSTALL_DIR/distributed-ollama${NC}"
    read -p "Reinstall? This will stop services and overwrite files. (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        systemctl stop ollama-coordinator 2>/dev/null || true
        systemctl stop ollama-proxy 2>/dev/null || true
        rm -rf $INSTALL_DIR/distributed-ollama
    else
        echo "Installation cancelled"
        exit 0
    fi
fi

# Get project files
echo ""
echo -e "${BLUE}How would you like to install?${NC}"
echo "1. From local zip file"
echo "2. From Git repository"
read -p "Choose (1 or 2): " install_method

if [ "$install_method" == "1" ]; then
    read -p "Enter path to distributed-ollama.zip: " zip_path
    if [ ! -f "$zip_path" ]; then
        echo -e "${RED}File not found: $zip_path${NC}"
        exit 1
    fi
    unzip -q "$zip_path" -d $INSTALL_DIR
    echo -e "${GREEN}✓${NC} Extracted from zip"
elif [ "$install_method" == "2" ]; then
    read -p "Enter Git repository URL: " git_url
    git clone "$git_url" $INSTALL_DIR/distributed-ollama
    echo -e "${GREEN}✓${NC} Cloned from Git"
else
    echo -e "${RED}Invalid choice${NC}"
    exit 1
fi

cd $INSTALL_DIR/distributed-ollama

# Install Python dependencies
echo ""
echo -e "${BLUE}Installing Python packages...${NC}"
pip3 install -q -r requirements.txt
echo -e "${GREEN}✓${NC} Python packages installed"

# Configure firewall
echo ""
echo -e "${BLUE}Configuring firewall...${NC}"
ufw --force enable > /dev/null 2>&1
ufw allow 22/tcp > /dev/null 2>&1   # SSH
ufw allow 8080/tcp > /dev/null 2>&1 # Coordinator
ufw allow 11434/tcp > /dev/null 2>&1 # Proxy
echo -e "${GREEN}✓${NC} Firewall configured (ports 22, 8080, 11434 open)"

# Create systemd service for coordinator
echo ""
echo -e "${BLUE}Creating systemd services...${NC}"

cat > /etc/systemd/system/ollama-coordinator.service << EOF
[Unit]
Description=Distributed Ollama Coordinator
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR/distributed-ollama
ExecStart=/usr/bin/python3 coordinator/server.py --host 0.0.0.0 --port 8080
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

echo -e "${GREEN}✓${NC} Created ollama-coordinator.service"

# Create systemd service for proxy
cat > /etc/systemd/system/ollama-proxy.service << EOF
[Unit]
Description=Distributed Ollama Proxy
After=network.target ollama-coordinator.service
Wants=network-online.target
Requires=ollama-coordinator.service

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR/distributed-ollama
ExecStart=/usr/bin/python3 proxy/server.py --coordinator http://localhost:8080 --host 0.0.0.0 --port 11434
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

echo -e "${GREEN}✓${NC} Created ollama-proxy.service"

# Reload systemd
systemctl daemon-reload
echo -e "${GREEN}✓${NC} Systemd reloaded"

# Enable services
echo ""
echo -e "${BLUE}Enabling services...${NC}"
systemctl enable ollama-coordinator > /dev/null 2>&1
systemctl enable ollama-proxy > /dev/null 2>&1
echo -e "${GREEN}✓${NC} Services enabled (will start on boot)"

# Start services
echo ""
echo -e "${BLUE}Starting services...${NC}"
systemctl start ollama-coordinator
sleep 2
systemctl start ollama-proxy
sleep 2

# Check service status
if systemctl is-active --quiet ollama-coordinator; then
    echo -e "${GREEN}✓${NC} Coordinator is running"
else
    echo -e "${RED}✗${NC} Coordinator failed to start"
    echo "Check logs: journalctl -u ollama-coordinator -n 50"
    exit 1
fi

if systemctl is-active --quiet ollama-proxy; then
    echo -e "${GREEN}✓${NC} Proxy is running"
else
    echo -e "${RED}✗${NC} Proxy failed to start"
    echo "Check logs: journalctl -u ollama-proxy -n 50"
    exit 1
fi

# Get server IP
SERVER_IP=$(curl -s ifconfig.me 2>/dev/null || curl -s icanhazip.com 2>/dev/null || echo "YOUR-SERVER-IP")

# Test the installation
echo ""
echo -e "${BLUE}Testing installation...${NC}"
sleep 3

if curl -s http://localhost:11434/health > /dev/null; then
    echo -e "${GREEN}✓${NC} Health check passed"
else
    echo -e "${YELLOW}⚠${NC} Health check failed (this might be OK if no workers connected yet)"
fi

# Print success message
echo ""
echo -e "${GREEN}================================================${NC}"
echo -e "${GREEN}  Installation Complete! ✓${NC}"
echo -e "${GREEN}================================================${NC}"
echo ""
echo -e "${BLUE}Your Distributed Ollama server is running!${NC}"
echo ""
echo -e "Coordinator: ${GREEN}http://$SERVER_IP:8080${NC}"
echo -e "Public API:  ${GREEN}http://$SERVER_IP:11434${NC}"
echo ""
echo -e "${YELLOW}Next Steps:${NC}"
echo "1. Share the coordinator URL with donors:"
echo -e "   ${GREEN}http://$SERVER_IP:8080${NC}"
echo ""
echo "2. Share the public API with EditorAI users:"
echo -e "   ${GREEN}http://$SERVER_IP:11434${NC}"
echo ""
echo "3. Get workers connected (see DONOR_GUIDE.md)"
echo ""
echo -e "${YELLOW}Useful Commands:${NC}"
echo "  View status:      systemctl status ollama-coordinator"
echo "  View logs:        journalctl -u ollama-coordinator -f"
echo "  Restart:          systemctl restart ollama-coordinator"
echo "  Check workers:    curl http://localhost:8080/api/status"
echo ""
echo -e "${YELLOW}Documentation:${NC}"
echo "  Full docs:        $INSTALL_DIR/distributed-ollama/README.md"
echo "  Setup guide:      $INSTALL_DIR/distributed-ollama/docs/SETUP_WALKTHROUGH.md"
echo "  Donor guide:      $INSTALL_DIR/distributed-ollama/DONOR_GUIDE.md"
echo ""
echo -e "${GREEN}================================================${NC}"
