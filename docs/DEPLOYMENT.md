# Deployment Guide

This guide covers different deployment scenarios for the Distributed Ollama Network.

## Table of Contents

1. [Local Testing](#local-testing)
2. [VPS Deployment](#vps-deployment)
3. [Docker Deployment](#docker-deployment)
4. [Cloud Deployment (AWS/GCP/Azure)](#cloud-deployment)
5. [Worker Deployment](#worker-deployment)

---

## Local Testing

Perfect for development and testing on your local machine.

### Prerequisites
- Python 3.8+
- Ollama installed (for workers)

### Steps

1. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Terminal 1 - Start Coordinator**:
   ```bash
   python3 coordinator/server.py --host 127.0.0.1 --port 8080
   ```

3. **Terminal 2 - Start Proxy**:
   ```bash
   python3 proxy/server.py \
     --coordinator http://127.0.0.1:8080 \
     --host 127.0.0.1 \
     --port 11434
   ```

4. **Terminal 3 - Start Ollama** (if testing worker):
   ```bash
   ollama serve
   ```

5. **Terminal 4 - Start Worker** (optional):
   ```bash
   python3 worker/client.py \
     --coordinator http://127.0.0.1:8080
   ```

6. **Test**:
   ```bash
   curl http://127.0.0.1:11434/health
   ```

---

## VPS Deployment

Deploy on a cloud VPS (DigitalOcean, Linode, Vultr, etc.)

### Prerequisites
- VPS with Ubuntu 20.04+ or similar
- Public IP address
- Root or sudo access

### Setup Steps

1. **Connect to VPS**:
   ```bash
   ssh root@your-vps-ip
   ```

2. **Install Python and dependencies**:
   ```bash
   apt update
   apt install -y python3 python3-pip git
   ```

3. **Clone or upload the project**:
   ```bash
   git clone https://github.com/yourusername/distributed-ollama.git
   cd distributed-ollama
   pip3 install -r requirements.txt
   ```

4. **Create systemd service for Coordinator**:
   ```bash
   sudo nano /etc/systemd/system/ollama-coordinator.service
   ```

   Add:
   ```ini
   [Unit]
   Description=Distributed Ollama Coordinator
   After=network.target

   [Service]
   Type=simple
   User=root
   WorkingDirectory=/root/distributed-ollama
   ExecStart=/usr/bin/python3 coordinator/server.py --host 0.0.0.0 --port 8080
   Restart=always
   RestartSec=10

   [Install]
   WantedBy=multi-user.target
   ```

5. **Create systemd service for Proxy**:
   ```bash
   sudo nano /etc/systemd/system/ollama-proxy.service
   ```

   Add:
   ```ini
   [Unit]
   Description=Distributed Ollama Proxy
   After=network.target ollama-coordinator.service
   Requires=ollama-coordinator.service

   [Service]
   Type=simple
   User=root
   WorkingDirectory=/root/distributed-ollama
   ExecStart=/usr/bin/python3 proxy/server.py --coordinator http://localhost:8080 --host 0.0.0.0 --port 11434
   Restart=always
   RestartSec=10

   [Install]
   WantedBy=multi-user.target
   ```

6. **Enable and start services**:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable ollama-coordinator
   sudo systemctl enable ollama-proxy
   sudo systemctl start ollama-coordinator
   sudo systemctl start ollama-proxy
   ```

7. **Check status**:
   ```bash
   sudo systemctl status ollama-coordinator
   sudo systemctl status ollama-proxy
   ```

8. **Configure firewall**:
   ```bash
   ufw allow 8080/tcp  # Coordinator
   ufw allow 11434/tcp # Proxy
   ufw enable
   ```

9. **Test from outside**:
   ```bash
   curl http://your-vps-ip:11434/health
   ```

### Optional: Setup TLS with Caddy

1. **Install Caddy**:
   ```bash
   apt install -y debian-keyring debian-archive-keyring apt-transport-https
   curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
   curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
   apt update
   apt install caddy
   ```

2. **Configure Caddy**:
   ```bash
   sudo nano /etc/caddy/Caddyfile
   ```

   Add:
   ```
   ollama.yourdomain.com {
       reverse_proxy localhost:11434
   }
   ```

3. **Restart Caddy**:
   ```bash
   sudo systemctl restart caddy
   ```

Now you have HTTPS access at `https://ollama.yourdomain.com`!

---

## Docker Deployment

Easiest way to deploy everything at once.

### Prerequisites
- Docker installed
- Docker Compose installed

### Steps

1. **Clone the repository**:
   ```bash
   git clone https://github.com/yourusername/distributed-ollama.git
   cd distributed-ollama
   ```

2. **Start services**:
   ```bash
   docker-compose up -d
   ```

3. **Check logs**:
   ```bash
   docker-compose logs -f
   ```

4. **Check status**:
   ```bash
   docker-compose ps
   ```

5. **Stop services**:
   ```bash
   docker-compose down
   ```

### Custom Configuration

Edit `docker-compose.yml` to change ports or settings:

```yaml
services:
  coordinator:
    ports:
      - "8080:8080"  # Change left number for external port
  
  proxy:
    ports:
      - "11434:11434"  # Change left number for external port
```

---

## Cloud Deployment

### AWS EC2

1. **Launch EC2 Instance**:
   - AMI: Ubuntu 20.04
   - Instance Type: t3.small or larger
   - Security Group: Open ports 8080, 11434

2. **Connect and deploy**:
   ```bash
   ssh -i your-key.pem ubuntu@ec2-instance-ip
   ```
   Then follow VPS deployment steps above.

3. **Use Elastic IP** for a static IP address.

### Google Cloud Platform

1. **Create Compute Engine VM**:
   ```bash
   gcloud compute instances create ollama-coordinator \
     --image-family=ubuntu-2004-lts \
     --image-project=ubuntu-os-cloud \
     --machine-type=e2-small \
     --tags=http-server,https-server
   ```

2. **Configure firewall**:
   ```bash
   gcloud compute firewall-rules create ollama-proxy \
     --allow tcp:11434 \
     --target-tags=http-server
   ```

3. **SSH and deploy**:
   ```bash
   gcloud compute ssh ollama-coordinator
   ```
   Then follow VPS deployment steps.

### Azure

1. **Create Virtual Machine**:
   - OS: Ubuntu 20.04
   - Size: B1s or larger
   - Networking: Open ports 8080, 11434

2. **Connect**:
   ```bash
   ssh azureuser@vm-public-ip
   ```

3. Follow VPS deployment steps above.

---

## Worker Deployment

How to set up workers to donate resources.

### On Windows

1. **Install Python**:
   - Download from python.org
   - Make sure to check "Add Python to PATH"

2. **Install Ollama**:
   - Download from ollama.ai
   - Install and run `ollama serve`

3. **Download Worker Script**:
   - Download `worker/client.py` and `requirements.txt`

4. **Install Dependencies**:
   ```cmd
   pip install -r requirements.txt
   ```

5. **Run Worker**:
   ```cmd
   python worker/client.py --coordinator http://coordinator-url:8080
   ```

### On Linux

1. **Install dependencies**:
   ```bash
   pip3 install -r requirements.txt
   ```

2. **Install Ollama**:
   ```bash
   curl https://ollama.ai/install.sh | sh
   ollama serve &
   ```

3. **Pull models**:
   ```bash
   ollama pull llama2
   ollama pull mistral
   ```

4. **Run worker**:
   ```bash
   python3 worker/client.py --coordinator http://coordinator-url:8080
   ```

### As a Service (Linux)

1. **Create service file**:
   ```bash
   sudo nano /etc/systemd/system/ollama-worker.service
   ```

2. **Add**:
   ```ini
   [Unit]
   Description=Ollama Worker
   After=network.target

   [Service]
   Type=simple
   User=youruser
   WorkingDirectory=/home/youruser/distributed-ollama
   ExecStart=/usr/bin/python3 worker/client.py --coordinator http://coordinator-url:8080
   Restart=always
   RestartSec=10

   [Install]
   WantedBy=multi-user.target
   ```

3. **Enable and start**:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable ollama-worker
   sudo systemctl start ollama-worker
   ```

---

## Monitoring and Maintenance

### Check Coordinator Status

```bash
curl http://coordinator-url:8080/api/status | jq
```

### View Logs

**Docker**:
```bash
docker-compose logs -f coordinator
docker-compose logs -f proxy
```

**Systemd**:
```bash
sudo journalctl -u ollama-coordinator -f
sudo journalctl -u ollama-proxy -f
```

### Restart Services

**Docker**:
```bash
docker-compose restart
```

**Systemd**:
```bash
sudo systemctl restart ollama-coordinator
sudo systemctl restart ollama-proxy
```

---

## Scaling

### Horizontal Scaling

Run multiple coordinator instances behind a load balancer:

1. Deploy multiple coordinators
2. Use nginx or HAProxy to load balance
3. Workers can register with any coordinator

### Vertical Scaling

- Increase VPS resources (CPU/RAM)
- No code changes needed

---

## Troubleshooting

### Coordinator won't start

```bash
# Check if port is in use
sudo lsof -i :8080

# Check logs
sudo journalctl -u ollama-coordinator -n 50
```

### Workers can't connect

```bash
# Test coordinator accessibility
curl http://coordinator-url:8080/api/status

# Check firewall
sudo ufw status

# Verify worker config
python3 worker/client.py --coordinator http://coordinator-url:8080
```

### Requests timing out

- Verify at least one worker is active
- Check if requested model is available
- Increase proxy timeout

---

## Production Checklist

- [ ] TLS/SSL enabled (use Caddy or nginx)
- [ ] Firewall configured (only necessary ports open)
- [ ] Services set to auto-restart
- [ ] Monitoring/alerting set up
- [ ] Backups configured (if storing any data)
- [ ] Rate limiting implemented (optional)
- [ ] Authentication added (optional)
- [ ] Log rotation configured
- [ ] DNS configured (if using domain)
- [ ] Documentation updated with your URLs

---

## Getting Help

If you encounter issues:

1. Check logs first
2. Review troubleshooting section
3. Open an issue on GitHub
4. Include logs and error messages
