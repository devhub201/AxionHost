# AxionHost — hosting website

Storefront, client area, admin panel, **in-site VPS panel** and **in-site Minecraft panel**, plus a Flask backend
(SMTP email, email verification, orders, free-plan claims, renewal reminders, game-panel + VPS-over-SSH/SSHX provisioning).

```
index.html … *.html     static front-end (no build step)
core.js net.js …        shared UI, API client (falls back to demo mode when backend is offline)
panels.js               VPS panel + Minecraft panel UIs
admin2.js               Admin → Integrations + Emails
backend/                Flask API (app.py) + tests
```

## Run it
```bash
cd backend
pip install -r requirements.txt
export SECRET_KEY="$(python3 -c 'import secrets;print(secrets.token_hex(32))')"
export ADMIN_EMAIL=you@yourdomain.com ADMIN_PASSWORD='choose-a-strong-one'
python3 app.py            # http://localhost:8080  (serves the website + /api)
```
Open `/login.html`, sign in as the admin, then **Admin → Integrations**:

| Card | What to enter | Used for |
|---|---|---|
| **SMTP** | host / port / user / app-password / from | verify email, order confirmed, credentials, renewals |
| **Paid game panel** | URL, Application API key, Client API key, node/egg IDs | paid Minecraft / Rust / Bots servers |
| **Free Minecraft panel** | same, separate node + 4 GB limits | free 4 GB servers |
| **VPS node (SSH / SSHX)** | host, SSH key, provision command | paid + free VPS. SSHX mode also emails a web-terminal link |

Each card has **Test connection** (real SMTP login + optional test mail, real panel API call, real SSH).
Customers never see the game panel — they use `mc-panel.html`; the backend talks to the panel with your admin key.
Set `site.url` (Admin → Settings / `db.json`) to your public https URL so email links work.

## Emails (Admin → Emails)
13 templates: verify email, welcome, password reset, order confirmed, payment received, paid service ready (credentials),
free VPS ready, free Minecraft ready, renewal reminder, free plan expiring, service suspended, ticket reply, new order (admins).
Edit, live-preview, send a test, view the delivery log. A background job (hourly) sends reminders and suspends expired services.

## Tests
```bash
cd backend && python3 -m unittest discover -s tests
```
Covers verify flow, SMTP (against a local SMTP server incl. AUTH failure), order → provision (mock panel API), paid/free VPS over a fake `ssh`,
free-plan limits, renewals/suspension, templates (HTML-escaping), admin-only routes, password reset, shell-injection safety.

## Honest limits — read before going live
- **Payments are manual.** Orders are created as *pending*; you approve them in Admin (UPI/bank). Add Razorpay/Stripe webhooks to automate — not included.
- **VPS provisioning runs *your* command** on *your* node over SSH (`provision_cmd`). The default `axion-vps …` is a placeholder; point it at your own script (LXD/Proxmox/Docker). SSH needs the `ssh` client installed where the backend runs.
- **In-site panels** (`vps-panel.html`, `mc-panel.html`) are still demo data in the browser; the backend already exposes power/renew endpoints (`/api/services/<id>/power|renew`) — wire the rest of the tabs the same way.
- Data is a JSON file (`backend/data/db.json`, chmod 600; contains SMTP/panel secrets). Use a proper DB + secrets manager for production, run behind HTTPS, and back it up.
- Free plans attract abuse: keep email verification on, keep the per-IP limit, and add a captcha.
