# Systemd Service Templates

Use these templates to run Distributed Ollama as system services.

## Coordinator Service

File: `/etc/systemd/system/ollama-coordinator.service`

```ini
[Unit]
Description=Distributed Ollama Coordinator
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=ollama
Group=ollama
WorkingDirectory=/opt/distributed-ollama
ExecStart=/usr/bin/python3 /opt/distributed-ollama/coordinator/server.py --host 0.0.0.0 --port 8080
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

# Security
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

## Proxy Service

File: `/etc/systemd/system/ollama-proxy.service`

```ini
[Unit]
Description=Distributed Ollama Proxy
After=network.target ollama-coordinator.service
Wants=network-online.target
Requires=ollama-coordinator.service

[Service]
Type=simple
User=ollama
Group=ollama
WorkingDirectory=/opt/distributed-ollama
ExecStart=/usr/bin/python3 /opt/distributed-ollama/proxy/server.py --coordinator http://localhost:8080 --host 0.0.0.0 --port 11434
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

# Security
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

## Worker Service

File: `/etc/systemd/system/ollama-worker.service`

```ini
[Unit]
Description=Distributed Ollama Worker
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=ollama
Group=ollama
WorkingDirectory=/opt/distributed-ollama
Environment="COORDINATOR_URL=http://coordinator-server.com:8080"
ExecStart=/usr/bin/python3 /opt/distributed-ollama/worker/client.py --coordinator ${COORDINATOR_URL}
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

# Security
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

## Installation Steps

1. **Create user**:
   ```bash
   sudo useradd -r -s /bin/false ollama
   ```

2. **Install application**:
   ```bash
   sudo mkdir -p /opt/distributed-ollama
   sudo cp -r . /opt/distributed-ollama/
   sudo chown -R ollama:ollama /opt/distributed-ollama
   ```

3. **Install Python dependencies**:
   ```bash
   sudo pip3 install -r /opt/distributed-ollama/requirements.txt
   ```

4. **Copy service files**:
   ```bash
   # For coordinator + proxy
   sudo cp systemd-templates/ollama-coordinator.service /etc/systemd/system/
   sudo cp systemd-templates/ollama-proxy.service /etc/systemd/system/
   
   # For worker
   sudo cp systemd-templates/ollama-worker.service /etc/systemd/system/
   # Edit the COORDINATOR_URL in /etc/systemd/system/ollama-worker.service
   ```

5. **Reload systemd**:
   ```bash
   sudo systemctl daemon-reload
   ```

6. **Enable services**:
   ```bash
   # For coordinator + proxy
   sudo systemctl enable ollama-coordinator
   sudo systemctl enable ollama-proxy
   
   # For worker
   sudo systemctl enable ollama-worker
   ```

7. **Start services**:
   ```bash
   # For coordinator + proxy
   sudo systemctl start ollama-coordinator
   sudo systemctl start ollama-proxy
   
   # For worker  
   sudo systemctl start ollama-worker
   ```

8. **Check status**:
   ```bash
   sudo systemctl status ollama-coordinator
   sudo systemctl status ollama-proxy
   sudo systemctl status ollama-worker
   ```

## Useful Commands

```bash
# View logs
sudo journalctl -u ollama-coordinator -f
sudo journalctl -u ollama-proxy -f
sudo journalctl -u ollama-worker -f

# Restart service
sudo systemctl restart ollama-coordinator
sudo systemctl restart ollama-proxy
sudo systemctl restart ollama-worker

# Stop service
sudo systemctl stop ollama-coordinator
sudo systemctl stop ollama-proxy
sudo systemctl stop ollama-worker

# Disable service (won't start on boot)
sudo systemctl disable ollama-coordinator
sudo systemctl disable ollama-proxy
sudo systemctl disable ollama-worker
```

## Notes

- Services run as the `ollama` user for security
- Logs go to systemd journal (view with `journalctl`)
- Services auto-restart on failure
- Adjust `WorkingDirectory` if you install elsewhere
- Edit `COORDINATOR_URL` in worker service to point to your coordinator
