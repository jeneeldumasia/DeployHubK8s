# Cloudflare Tunnel Setup — HTTPS for DeployHub

> **Status: NOT YET DONE**
> Complete these steps once. After that, every new lab session gets HTTPS
> automatically when the pipeline runs — no manual work needed.

---

## Why this is needed

KodeKloud destroys all AWS infra at the end of every lab session, so the EC2
IP changes every time. Let's Encrypt / Certbot require a stable domain pointing
at a stable IP — impossible here.

Cloudflare Tunnel solves this by running a `cloudflared` pod inside k3s that
dials **out** to Cloudflare's edge. Your DNS records point at Cloudflare
permanently and never need to change, regardless of what IP the EC2 instance
gets.

```
Browser → HTTPS → Cloudflare Edge → Tunnel (outbound) → cloudflared pod → k8s services
```

---

## One-time setup (do this once, ever)

### Step 1 — Add jeneeldumasia.codes to Cloudflare

1. Go to https://dash.cloudflare.com
2. Click **Add a site** → enter `jeneeldumasia.codes` → select **Free plan**
3. Cloudflare will show you two nameservers, e.g.:
   - `aria.ns.cloudflare.com`
   - `bob.ns.cloudflare.com`
4. Log in to your domain registrar (wherever you bought `jeneeldumasia.codes`)
5. Replace the existing nameservers with Cloudflare's two nameservers
6. Wait 5–30 minutes for propagation — Cloudflare will email you when active

### Step 2 — Install cloudflared on Windows

```powershell
winget install Cloudflare.cloudflared
```

Or download the installer from:
https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/

### Step 3 — Authenticate cloudflared

```bash
cloudflared tunnel login
```

This opens a browser. Select `jeneeldumasia.codes` and authorise.
A certificate file is saved to `C:\Users\<you>\.cloudflared\cert.pem`.

### Step 4 — Create the tunnel

```bash
cloudflared tunnel create deployhub
```

Output will look like:
```
Created tunnel deployhub with id xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

**Save the tunnel ID** — you'll need it in Step 6.

A credentials file is saved to:
```
C:\Users\<you>\.cloudflared\xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx.json
```

### Step 5 — Create DNS routes (permanent)

These CNAME records point at Cloudflare's edge and never need to change.

```bash
cloudflared tunnel route dns deployhub deployhub.jeneeldumasia.codes
cloudflared tunnel route dns deployhub api.jeneeldumasia.codes
cloudflared tunnel route dns deployhub grafana.jeneeldumasia.codes
```

Verify in Cloudflare dashboard → DNS → you should see three CNAME records
pointing at `<tunnel-id>.cfargotunnel.com`.

### Step 6 — Add GitHub Secrets

Go to: https://github.com/<your-repo>/settings/secrets/actions

Add two secrets:

| Secret Name | Value |
|---|---|
| `CLOUDFLARE_TUNNEL_ID` | The tunnel ID from Step 4 (e.g. `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`) |
| `CLOUDFLARE_TUNNEL_CREDENTIALS` | The **entire contents** of `C:\Users\<you>\.cloudflared\<tunnel-id>.json` |

To get the credentials file contents on Windows:
```powershell
Get-Content "C:\Users\<you>\.cloudflared\<tunnel-id>.json"
```
Copy the entire JSON output and paste it as the secret value.

---

## What happens after setup

Every time the GitHub Actions pipeline runs (on push to main or manual trigger):

1. Pipeline reads `CLOUDFLARE_TUNNEL_ID` and `CLOUDFLARE_TUNNEL_CREDENTIALS` secrets
2. Creates a k8s secret `cloudflared-credentials` in the `deployhub` namespace
3. Deploys the `cloudflared` pod (2 replicas for HA) from `k8s_deploy/cloudflared.yaml`
4. `cloudflared` dials out to Cloudflare's edge using the credentials
5. Your sites are live at:

| URL | Service |
|---|---|
| https://deployhub.jeneeldumasia.codes | DeployHub UI |
| https://api.jeneeldumasia.codes | Backend API |
| https://grafana.jeneeldumasia.codes | Grafana monitoring |

No DNS changes needed. No IP changes matter. Certs are handled by Cloudflare.

---

## Verification after a new session

After the pipeline completes, verify the tunnel is up:

```bash
# Check cloudflared pods are running
kubectl get pods -n deployhub -l app=cloudflared

# Check tunnel is connected (should show 2 connections)
kubectl logs -n deployhub -l app=cloudflared --tail=20

# Test HTTPS
curl -I https://deployhub.jeneeldumasia.codes
```

---

## Troubleshooting

**Pipeline skips cloudflared** — secrets not set. Check
`CLOUDFLARE_TUNNEL_ID` and `CLOUDFLARE_TUNNEL_CREDENTIALS` exist in GitHub
repo secrets.

**Pod crashes with "failed to unmarshal credentials"** — the credentials JSON
in the secret is malformed. Re-copy the contents of the `.json` file and
update the GitHub secret.

**DNS not resolving** — check Cloudflare dashboard → DNS tab. The three CNAME
records should exist. If not, re-run the `cloudflared tunnel route dns` commands
from Step 5.

**Tunnel shows 0 connections** — the tunnel ID in the config doesn't match the
credentials. Make sure `CLOUDFLARE_TUNNEL_ID` matches the ID in the credentials
JSON file (`"TunnelID"` field).
