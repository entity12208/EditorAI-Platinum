# Free Hosting Guide - Deploy for $0

This guide shows you how to run Distributed Ollama **completely free** using various platforms.

---

## 🎯 Quick Comparison

| Platform | Cost | Always On? | Setup Time | Best For |
|----------|------|------------|------------|----------|
| **Render** | FREE | No (sleeps) | 5 min | Easiest |
| **Fly.io** | FREE* | YES | 10 min | Best free |
| **Oracle Cloud** | FREE | YES | 20 min | Long-term |
| **Railway** | Trial only | YES | 5 min | Testing |

*$5/month credit covers 2 small services

---

## 🚀 Option 1: Render.com (Easiest & Free)

### Pros:
✅ Completely free
✅ No credit card needed
✅ Git-based deployment (auto-deploy on push)
✅ Simple dashboard

### Cons:
⚠️ Apps sleep after 15 minutes of inactivity
⚠️ Wake time: ~30 seconds on first request

### Perfect for:
- Personal use
- Low-traffic EditorAI setups
- Testing

### Setup:

**Step 1: Prepare Repository**
```bash
# Add render.yaml to your repo (already included)
git add render.yaml
git commit -m "Add Render config"
git push
```

**Step 2: Deploy to Render**
1. Go to https://render.com
2. Sign up (free, no credit card)
3. Click "New" → "Blueprint"
4. Connect your GitHub repository
5. Select the repository with distributed-ollama
6. Click "Apply"

**Done!** Render will:
- Deploy coordinator at: `https://ollama-coordinator.onrender.com`
- Deploy proxy at: `https://ollama-proxy.onrender.com`

### Your URLs:
- **Coordinator**: `https://ollama-coordinator.onrender.com:8080`
- **Public API**: `https://ollama-proxy.onrender.com`

**Note:** First request after inactivity takes ~30 seconds (cold start)

---

## 🔥 Option 2: Fly.io (Best Free Option)

### Pros:
✅ $5/month free credit (forever)
✅ No sleep mode (always on!)
✅ Global edge network
✅ Docker support

### Cons:
⚠️ Slightly more complex setup
⚠️ Credit card required for signup

### Perfect for:
- Production use
- 24/7 availability
- Multiple contributors

### Setup:

**Step 1: Install Fly CLI**
```bash
# Mac/Linux
curl -L https://fly.io/install.sh | sh

# Windows (PowerShell)
iwr https://fly.io/install.ps1 -useb | iex
```

**Step 2: Sign Up**
```bash
fly auth signup
# Or if you have an account:
fly auth login
```

**Step 3: Deploy**
```bash
cd distributed-ollama

# Launch coordinator
fly launch --name ollama-coordinator
# Choose region closest to you
# Say YES to deploy now

# Launch proxy
fly launch --name ollama-proxy
# Choose same region
# Say YES to deploy now
```

**Step 4: Open Ports**
```bash
fly ips allocate-v4 --app ollama-coordinator
fly ips allocate-v4 --app ollama-proxy
```

### Your URLs:
- **Coordinator**: `http://ollama-coordinator.fly.dev:8080`
- **Public API**: `http://ollama-proxy.fly.dev:11434`

### Cost Breakdown:
- Coordinator (256MB): ~$2/month
- Proxy (256MB): ~$2/month
- **Total: ~$4/month → FREE (within $5 credit)**

---

## 👑 Option 3: Oracle Cloud (Best for Long-term)

See main setup guide - this is truly free forever with no sleep mode!

---

## 🎨 Getting a Free Domain

### Option A: DuckDNS (Recommended)

**Steps:**
1. Go to https://duckdns.org
2. Sign in with GitHub/Google
3. Create subdomain: `yourname.duckdns.org`
4. Point to your server IP

**Result:**
```
http://yourname.duckdns.org:11434
```

### Option B: Freenom

**Steps:**
1. Go to https://freenom.com
2. Search for available .tk, .ml, .ga domains
3. Register (free for 1 year)
4. Point to your server

**Result:**
```
http://yoursite.tk:11434
```

---

## 🔄 Recommended Setup (Completely Free)

**For Maximum Uptime:**

1. **Coordinator + Proxy**: Fly.io ($0 - within free credit)
2. **Domain**: DuckDNS ($0)
3. **Workers**: Donated by community ($0)

**Total cost: $0/month** 🎉

---

## ⚡ Quick Deploy Commands

### Render (Easiest)
```bash
# Just connect GitHub repo in Render dashboard
# Everything automatic!
```

### Fly.io (Best Performance)
```bash
# Install Fly CLI
curl -L https://fly.io/install.sh | sh

# Login
fly auth login

# Deploy
cd distributed-ollama
fly launch --name ollama-coordinator
fly launch --name ollama-proxy
```

### Oracle Cloud (Forever Free)
```bash
# See main setup guide
# Use install-server.sh script
```

---

## 🧪 Testing Your Deployment

### Check Health
```bash
# Replace with your actual URL
curl https://ollama-proxy.onrender.com/health
```

Should return:
```json
{
  "status": "healthy",
  "coordinator": "connected",
  "active_workers": 0
}
```

### Test Generation
```bash
curl -X POST https://ollama-proxy.onrender.com/api/generate \
  -H "Content-Type: application/json" \
  -d '{
    "model": "llama2",
    "prompt": "Hello!",
    "stream": false
  }'
```

---

## 📊 Platform Comparison Details

### Render.com
**Best for:** Beginners, casual use
**Deployment:** Git push → Auto deploy
**Limitation:** 15min inactivity = sleep
**Workaround:** Use a cron job to ping every 10 minutes

### Fly.io
**Best for:** Production, always-on
**Deployment:** CLI-based
**Limitation:** $5 credit (covers ~2 small apps)
**Benefit:** No sleep mode!

### Oracle Cloud
**Best for:** Long-term, high-traffic
**Deployment:** Traditional VPS
**Limitation:** Takes longer to set up
**Benefit:** True forever-free tier

---

## 🎯 What to Share

### With EditorAI Users:

**Render:**
```
Change Ollama URL to:
https://ollama-proxy.onrender.com

Note: First request may take 30 seconds (cold start)
```

**Fly.io:**
```
Change Ollama URL to:
http://ollama-proxy.fly.dev:11434

No delays - always on!
```

### With Donors:

```
Connect your worker to:
http://ollama-coordinator.fly.dev:8080

Or:
https://ollama-coordinator.onrender.com:8080
```

---

## 💡 Pro Tips

### Keeping Render Awake
Create a free account on UptimeRobot.com and ping your app every 5 minutes:
```
https://ollama-proxy.onrender.com/health
```

### Monitoring
All platforms provide:
- Built-in logs
- Metrics dashboard
- Email alerts (optional)

### Scaling
Start free, upgrade if needed:
- Render: $7/month for always-on
- Fly.io: Add more credit as needed
- Oracle: Already includes plenty

---

## 🐛 Troubleshooting

### "Service Unavailable"
- **Render**: App is sleeping, wait 30 seconds
- **Fly.io**: Check `fly status`
- Check coordinator logs

### "No Workers Available"
- Ensure at least one donor is running
- Check worker registration: `curl .../api/status`

### High Latency
- Choose server region close to users
- Fly.io: Use global regions
- Consider multiple deployments

---

## 📝 Summary

**Best Choices:**

1. **Just testing?** → Render (5 min setup)
2. **Want it always on?** → Fly.io ($0 within credit)
3. **Long-term serious?** → Oracle Cloud (true free forever)

**All are completely free!** Pick based on your needs.

---

## 🔗 Quick Links

- Render: https://render.com
- Fly.io: https://fly.io
- Oracle Cloud: https://cloud.oracle.com
- DuckDNS: https://duckdns.org

---

Ready to deploy? Choose a platform above and follow the steps! 🚀
