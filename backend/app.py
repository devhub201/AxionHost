"""AxionHost backend — auth + email verification, orders, free claims, renewals, SMTP mail, panel/VPS integrations."""
import os, re, json, time, hashlib, hmac, secrets, threading, functools
from flask import Flask, request, jsonify, send_from_directory, g
import jwt
import db, mailer, emails, integrations as ig

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
app = Flask(__name__, static_folder=None)
SECRET = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
PLANS = json.load(open(os.path.join(os.path.dirname(__file__), "plans.json")))
DISC = {1: 0, 3: .05, 12: .2}; CN = {1: "monthly", 3: "quarterly", 12: "yearly"}
COUPONS = {"LAUNCH10": .10, "WELCOME5": .05, "YEARLY15": .15}
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")

def err(msg, code=400): return jsonify({"ok": False, "error": msg}), code
def hash_pw(p, salt=None):
    salt = salt or secrets.token_hex(8); return salt + "$" + hashlib.scrypt(p.encode(), salt=salt.encode(), n=2**14, r=8, p=1).hex()
def check_pw(p, h):
    try: salt, _ = h.split("$"); return hmac.compare_digest(hash_pw(p, salt), h)
    except ValueError: return False
def user_by_email(e): return next((u for u in db.load()["users"] if u["email"] == e.lower()), None)
def pub_user(u): return {k: u[k] for k in ("id", "name", "email", "role", "verified")}
def find(coll, id): return next((x for x in db.load()[coll] if x["id"] == id), None)
def settings(): return db.load()["settings"]
def site_url(): return settings()["site"]["url"].rstrip("/")

def notify(uid, title, body="", kind="info"):
    d = db.load(); d["notifications"].insert(0, {"id": db.nid("n"), "uid": uid, "ts": db.now(), "title": title, "body": body, "kind": kind, "read": False}); db.save()

# ---------- rate limit ----------
_hits = {}
def limited(key, n, per):
    now = time.time(); L = [t for t in _hits.get(key, []) if now - t < per]
    if len(L) >= n: _hits[key] = L; return True
    L.append(now); _hits[key] = L; return False
def ip(): return (request.headers.get("X-Forwarded-For", request.remote_addr) or "?").split(",")[0].strip()

# ---------- auth ----------
def make_token(u): return jwt.encode({"sub": u["id"], "exp": int(time.time()) + 7 * 86400}, SECRET, algorithm="HS256")
def auth(admin=False, verified=False):
    def deco(fn):
        @functools.wraps(fn)
        def w(*a, **k):
            h = request.headers.get("Authorization", "")
            if not h.startswith("Bearer "): return err("Login required", 401)
            try: uid = jwt.decode(h[7:], SECRET, algorithms=["HS256"])["sub"]
            except jwt.PyJWTError: return err("Session expired — log in again", 401)
            u = find("users", uid)
            if not u: return err("Account not found", 401)
            if admin and u["role"] != "admin": return err("Admins only", 403)
            if verified and not u["verified"] and u["role"] != "admin": return err("Verify your email first", 403)
            g.user = u; return fn(*a, **k)
        return w
    return deco

def issue_token(u, kind, ttl):
    d = db.load(); t = db.token()
    d["tokens"] = [x for x in d["tokens"] if x["exp"] > db.now() and not (x["uid"] == u["id"] and x["kind"] == kind)]
    d["tokens"].append({"t": hashlib.sha256(t.encode()).hexdigest(), "uid": u["id"], "kind": kind, "exp": db.now() + ttl}); db.save(); return t
def use_token(t, kind):
    d = db.load(); h = hashlib.sha256(t.encode()).hexdigest()
    x = next((x for x in d["tokens"] if x["t"] == h and x["kind"] == kind and x["exp"] > db.now()), None)
    if x: d["tokens"].remove(x); db.save()
    return find("users", x["uid"]) if x else None

def send_verify(u):
    t = issue_token(u, "verify", 86400)
    return mailer.send(u["email"], "verify_email", {"name": u["name"], "verify_url": f"{site_url()}/verify.html?token={t}"})

@app.post("/api/auth/register")
def register():
    j = request.get_json(silent=True) or {}; name, email, pw = (j.get("name") or "").strip()[:60], (j.get("email") or "").strip().lower(), j.get("password") or ""
    if limited("reg" + ip(), 5, 3600): return err("Too many sign-ups from this network — try later", 429)
    if len(name) < 2: return err("Enter your name")
    if not EMAIL_RE.match(email): return err("Enter a valid email")
    if len(pw) < 8: return err("Password must be at least 8 characters")
    if user_by_email(email): return err("An account with this email already exists", 409)
    d = db.load(); u = {"id": db.nid("u"), "name": name, "email": email, "pw": hash_pw(pw), "role": "customer", "verified": False, "created": db.now(), "suspended": False}
    d["users"].append(u); db.save()
    r = send_verify(u); notify(u["id"], "Welcome to AxionHost", "Verify your email to unlock free servers and ordering.")
    return jsonify({"ok": True, "needVerify": True, "emailSent": r["ok"], "emailError": r.get("error", "")}), 201

@app.post("/api/auth/verify")
def verify():
    u = use_token((request.get_json(silent=True) or {}).get("token", ""), "verify")
    if not u: return err("This verification link is invalid or has expired")
    u["verified"] = True; db.save(); mailer.send(u["email"], "welcome", {"name": u["name"]}); notify(u["id"], "Email verified ✓", "You can now claim free servers and place orders.", "ok")
    return jsonify({"ok": True, "token": make_token(u), "user": pub_user(u)})

@app.post("/api/auth/resend")
def resend():
    email = ((request.get_json(silent=True) or {}).get("email") or "").lower(); u = user_by_email(email)
    if limited("rs" + ip() + email, 3, 3600): return err("Please wait before requesting again", 429)
    if u and not u["verified"]: send_verify(u)
    return jsonify({"ok": True})  # same answer either way — don't reveal which emails exist

@app.post("/api/auth/login")
def login():
    j = request.get_json(silent=True) or {}; email = (j.get("email") or "").lower(); u = user_by_email(email)
    if limited("lg" + ip(), 20, 600): return err("Too many attempts — wait a few minutes", 429)
    if not u or not check_pw(j.get("password") or "", u["pw"]): return err("Wrong email or password", 401)
    if u.get("suspended"): return err("This account is suspended", 403)
    if not u["verified"] and u["role"] != "admin": return jsonify({"ok": False, "error": "Please verify your email first", "needVerify": True}), 403
    return jsonify({"ok": True, "token": make_token(u), "user": pub_user(u)})

@app.post("/api/auth/forgot")
def forgot():
    email = ((request.get_json(silent=True) or {}).get("email") or "").lower(); u = user_by_email(email)
    if limited("fg" + ip(), 5, 3600): return err("Too many requests", 429)
    if u: mailer.send(u["email"], "password_reset", {"name": u["name"], "reset_url": f"{site_url()}/reset.html?token={issue_token(u, 'reset', 3600)}"})
    return jsonify({"ok": True})

@app.post("/api/auth/reset")
def reset_pw():
    j = request.get_json(silent=True) or {}
    if len(j.get("password") or "") < 8: return err("Password must be at least 8 characters")
    u = use_token(j.get("token", ""), "reset")
    if not u: return err("This reset link is invalid or has expired")
    u["pw"] = hash_pw(j["password"]); db.save(); return jsonify({"ok": True})

@app.get("/api/me")
@auth()
def me(): return jsonify({"ok": True, "user": pub_user(g.user), "unread": sum(1 for n in db.load()["notifications"] if n["uid"] == g.user["id"] and not n["read"])})

@app.get("/api/notifications")
@auth()
def notifs(): return jsonify({"ok": True, "items": [n for n in db.load()["notifications"] if n["uid"] == g.user["id"]][:50]})

@app.post("/api/notifications/read")
@auth()
def notifs_read():
    for n in db.load()["notifications"]:
        if n["uid"] == g.user["id"]: n["read"] = True
    db.save(); return jsonify({"ok": True})

# ---------- catalog / orders ----------
@app.get("/api/plans")
def plans(): return jsonify({"ok": True, "plans": PLANS, "free": {k: settings()["free"][k] for k in ("vps_enabled", "mc_enabled", "renew_days")}})

def price(cat, plan, cycle, coupon):
    p = next((x for x in PLANS.get(cat, {}).get("plans", []) if x["name"] == plan), None)
    if not p or cycle not in DISC: return None
    sub = round(p["price"] * cycle * (1 - DISC[cycle])); cp = COUPONS.get((coupon or "").upper(), 0)
    return {"sub": sub, "discount": round(sub * cp), "total": sub - round(sub * cp), "coupon": (coupon or "").upper() if cp else ""}

@app.post("/api/orders")
@auth(verified=True)
def create_order():
    j = request.get_json(silent=True) or {}; cat, plan, cycle = j.get("cat"), j.get("plan"), int(j.get("cycle") or 1)
    pr = price(cat, plan, cycle, j.get("coupon"))
    if not pr: return err("Unknown plan or billing cycle")
    d = db.load(); st = settings()
    o = {"id": db.nid("ORD"), "uid": g.user["id"], "cat": cat, "product": PLANS[cat]["name"], "plan": plan, "cycle": cycle, "total": pr["total"], "coupon": pr["coupon"], "status": "pending", "created": db.now(), "service_id": None}
    d["orders"].append(o); db.save()
    note = st["payments"]["note"] + (f" UPI: {st['payments']['upi_id']}" if st["payments"].get("upi_id") else "")
    mailer.send(g.user["email"], "order_confirmed", {"name": g.user["name"], "order_id": o["id"], "product": o["product"], "plan": plan, "cycle": CN[cycle], "total": o["total"], "status": "Awaiting payment", "pay_note": note})
    if st["notify"].get("order_admin_copy"):
        for a in [u for u in d["users"] if u["role"] == "admin"]: mailer.send(a["email"], "admin_new_order", {"name": g.user["name"], "email": g.user["email"], "order_id": o["id"], "product": o["product"], "plan": plan, "cycle": CN[cycle], "total": o["total"]})
    notify(g.user["id"], f"Order {o['id']} received", f"{o['product']} {plan} · ₹{o['total']} · awaiting payment")
    return jsonify({"ok": True, "order": o}), 201

@app.get("/api/orders")
@auth()
def my_orders(): return jsonify({"ok": True, "items": [o for o in db.load()["orders"] if o["uid"] == g.user["id"]][::-1]})

def plan_ram(cat, plan):
    p = next(x for x in PLANS[cat]["plans"] if x["name"] == plan)
    m = re.search(r"(\d+) GB RAM", " ".join(p["features"]))
    return int(m.group(1)) if m else 2

def new_service(u, cat, product, plan, kind, ram_gb, days, name, extra=None):
    d = db.load(); sid = db.nid("SVC")
    s = {"id": sid, "uid": u["id"], "cat": cat, "product": product, "plan": plan, "kind": kind, "name": name or f"{cat}-{sid[-4:]}", "status": "provisioning", "ram_gb": ram_gb, "created": db.now(), "expires": db.now() + days * 86400, "warned": [], "address": "", "meta": {}, **(extra or {})}
    d["services"].append(s); db.save(); return s

def provision(s, u):
    """Create the actual server on the right backend. Returns (ok, message). Sets service status."""
    st = settings()
    try:
        if s["cat"] == "vps" or s["kind"] == "free-vps":
            cfg = st["vps"]
            if not cfg["enabled"]: raise ig.IntegrationError("VPS node is not connected yet")
            ram, cpu, disk = (cfg["free_ram_gb"], cfg["free_cpu"], cfg["free_disk_gb"]) if s["kind"] == "free-vps" else (s["ram_gb"], max(1, s["ram_gb"] // 2), s["ram_gb"] * 10)
            r = ig.vps_provision(cfg, s["name"], ram, cpu, disk)
            s["address"] = r["ip"]; s["meta"] = {"ssh_port": r["port"], "sshx_url": r["sshx_url"], "node_name": r["name"]}; secret_pw = r["password"]
        else:
            free = s["kind"] == "free-mc"; cfg = st["free_panel"] if free else st["paid_panel"]
            if not cfg["enabled"]: raise ig.IntegrationError("Game panel is not connected yet")
            ram = cfg["ram_mb"] if free else s["ram_gb"] * 1024; disk = cfg["disk_mb"] if free else s["ram_gb"] * 10240; cpu = cfg["cpu_percent"] if free else s["ram_gb"] * 50
            r = ig.panel_create_server(cfg, u["email"], u["name"], s["name"], ram, disk, cpu)
            s["address"] = f"{s['name']}.{re.sub(r'^https?://', '', site_url()).split(':')[0]}" if st["site"]["url"].startswith("http") and "localhost" not in st["site"]["url"] else f"{r['ip']}:{r['port']}"
            s["meta"] = {"remote_id": r["remote_id"], "identifier": r["identifier"], "ip": r["ip"], "port": r["port"]}; secret_pw = ""
        s["status"] = "online"; db.save()
    except ig.IntegrationError as e:
        s["status"] = "pending-setup"; s["meta"]["error"] = str(e); db.save()
        notify(u["id"], "Server is being set up", "Our team will finish your setup shortly.")
        return False, str(e)
    panel = {"vps": "vps-panel.html"}.get(s["cat"], "mc-panel.html"); purl = f"{site_url()}/{panel}?id={s['id']}"
    base = {"name": u["name"], "product": s["product"], "plan": s["plan"], "service_name": s["name"], "address": s["address"], "panel_url": purl, "renew_days": st["free"]["renew_days"]}
    if s["kind"] == "free-vps":
        sx = f"**Web terminal (SSHX):** {s['meta']['sshx_url']}" if s["meta"].get("sshx_url") else ""
        mailer.send(u["email"], "free_vps_ready", {**base, "password": secret_pw, "sshx": sx})
    elif s["kind"] == "free-mc": mailer.send(u["email"], "free_mc_ready", base)
    else:
        cred = f"**SSH:** `ssh root@{s['address']}`\n**Root password:** `{secret_pw}`" if secret_pw else ""
        mailer.send(u["email"], "service_ready", {**base, "credentials": cred})
    notify(u["id"], f"{s['product']} is ready 🚀", s["address"], "ok"); return True, "ok"

@app.post("/api/free/claim")
@auth(verified=True)
def free_claim():
    typ = (request.get_json(silent=True) or {}).get("type"); st = settings()
    if typ not in ("vps", "minecraft"): return err("Unknown free plan")
    f = st["free"]
    if not f["vps_enabled" if typ == "vps" else "mc_enabled"]: return err("This free plan is currently sold out — check back soon", 409)
    kind = "free-vps" if typ == "vps" else "free-mc"
    d = db.load()
    if any(s["uid"] == g.user["id"] and s["kind"] == kind and s["status"] != "deleted" for s in d["services"]): return err("You already have this free plan", 409)
    day = db.now() // 86400
    d["ipclaims"] = [c for c in d["ipclaims"] if c["day"] == day]
    if sum(1 for c in d["ipclaims"] if c["ip"] == ip()) >= f["max_per_ip_per_day"]: return err("Free-plan limit reached for your network today", 429)
    d["ipclaims"].append({"ip": ip(), "day": day}); db.save()
    s = new_service(g.user, "vps" if typ == "vps" else "minecraft", "Free VPS" if typ == "vps" else "Free Minecraft", "Free 8 GB" if typ == "vps" else "Free 4 GB", kind, 8 if typ == "vps" else 4, f["renew_days"], f"free-{typ[:2]}-{secrets.token_hex(2)}")
    ok, msg = provision(s, g.user)
    return jsonify({"ok": True, "service": s, "provisioned": ok, "note": "" if ok else "Queued — an admin will finish setup. You'll get an email."}), 201

@app.get("/api/services")
@auth()
def my_services(): return jsonify({"ok": True, "items": [s for s in db.load()["services"] if s["uid"] == g.user["id"] and s["status"] != "deleted"]})

@app.post("/api/services/<sid>/renew")
@auth()
def renew(sid):
    s = find("services", sid)
    if not s or (s["uid"] != g.user["id"] and g.user["role"] != "admin"): return err("Not found", 404)
    if not s["kind"].startswith("free"): return err("Paid services renew via invoice", 400)
    s["expires"] = db.now() + settings()["free"]["renew_days"] * 86400; s["warned"] = []
    if s["status"] == "suspended": s["status"] = "online"; _unsuspend(s)
    db.save(); notify(s["uid"], f"{s['name']} renewed", "Good for another " + str(settings()["free"]["renew_days"]) + " days.", "ok")
    return jsonify({"ok": True, "service": s})

@app.post("/api/services/<sid>/power")
@auth()
def power(sid):
    s = find("services", sid); a = (request.get_json(silent=True) or {}).get("action")
    if not s or (s["uid"] != g.user["id"] and g.user["role"] != "admin"): return err("Not found", 404)
    if s["status"] not in ("online",): return err("Service is not active")
    try:
        if s["cat"] == "vps": ig.vps_power(settings()["vps"], s["meta"].get("node_name", s["name"]), a)
        else: ig.panel_power(settings()["free_panel" if s["kind"] == "free-mc" else "paid_panel"], s["meta"].get("identifier", ""), a)
    except ig.IntegrationError as e: return err(str(e), 502)
    return jsonify({"ok": True})

def _unsuspend(s):
    try:
        if s["cat"] != "vps" and s["meta"].get("remote_id"): ig.panel_suspend(settings()["free_panel" if s["kind"] == "free-mc" else "paid_panel"], s["meta"]["remote_id"], False)
    except ig.IntegrationError: pass

# ---------- admin ----------
def mask(cfg_all):
    out = json.loads(json.dumps(cfg_all))
    for sec, keys in db.SECRET_FIELDS.items():
        for k in keys:
            if out[sec].get(k): out[sec][k] = "••••••••"
    return out

@app.get("/api/admin/settings")
@auth(admin=True)
def a_settings(): return jsonify({"ok": True, "settings": mask(settings())})

@app.put("/api/admin/settings")
@auth(admin=True)
def a_settings_put():
    j = request.get_json(silent=True) or {}; cur = settings()
    for sec, vals in j.items():
        if sec not in cur or not isinstance(vals, dict): continue
        for k, v in vals.items():
            if k not in db.DEFAULT_SETTINGS[sec]: continue
            if v == "••••••••" and k in db.SECRET_FIELDS.get(sec, []): continue
            want = type(db.DEFAULT_SETTINGS[sec][k])
            try:
                if want is bool: v = bool(v)
                elif want is int: v = int(v)
                elif want is str: v = str(v)
            except (TypeError, ValueError): return err(f"Bad value for {sec}.{k}")
            cur[sec][k] = v
    db.save(); return jsonify({"ok": True, "settings": mask(cur)})

@app.post("/api/admin/test/<what>")
@auth(admin=True)
def a_test(what):
    st = settings(); j = request.get_json(silent=True) or {}
    try:
        if what == "smtp":
            mailer.test_connection(st["smtp"]); msg = "SMTP login OK"
            to = (j.get("to") or "").strip()
            if to:
                r = mailer.send(to, "welcome", {"name": "there"}, raw=("Test email from " + st["site"]["name"], "SMTP is working.", "<p>✅ SMTP is working. This is a test email.</p>"))
                if not r["ok"]: return err(r["error"], 502)
                msg += f" · test email sent to {to}"
            return jsonify({"ok": True, "message": msg})
        if what in ("paid", "free"): return jsonify({"ok": True, **ig.panel_test(st["paid_panel" if what == "paid" else "free_panel"])})
        if what == "vps": return jsonify({"ok": True, **ig.vps_test(st["vps"])})
    except (mailer.MailError, ig.IntegrationError) as e: return err(str(e), 502)
    return err("Unknown test", 404)

@app.get("/api/admin/templates")
@auth(admin=True)
def a_tpl(): return jsonify({"ok": True, "items": [{"key": k, "label": emails.LABELS[k], "subject": emails.get(k)[0], "body": emails.get(k)[1], "custom": k in db.load()["templates"]} for k in emails.DEFAULTS]})

@app.put("/api/admin/templates/<key>")
@auth(admin=True)
def a_tpl_put(key):
    if key not in emails.DEFAULTS: return err("Unknown template", 404)
    j = request.get_json(silent=True) or {}
    if j.get("reset"): db.load()["templates"].pop(key, None)
    else:
        if not (j.get("subject") or "").strip() or not (j.get("body") or "").strip(): return err("Subject and body can't be empty")
        db.load()["templates"][key] = {"subject": j["subject"][:200], "body": j["body"][:6000]}
    db.save(); return jsonify({"ok": True})

SAMPLE = {"name": "Rahul", "email": "rahul@example.com", "verify_url": "https://example.com/verify", "reset_url": "https://example.com/reset", "order_id": "ORD-1001", "product": "Minecraft", "plan": "Iron", "cycle": "monthly", "total": 349, "status": "Awaiting payment", "pay_note": "Pay via UPI.", "invoice_id": "INV-1042", "service_name": "survival-smp", "address": "survival-smp.axionhost.net", "credentials": "", "panel_url": "https://example.com/panel", "password": "S3cretPass", "sshx": "", "renew_days": 7, "days": 3, "date": "Nov 12, 2026", "reason": "non-payment", "subject": "Server lag", "ticket_id": "1042", "message": "We've increased your RAM."}
@app.post("/api/admin/templates/preview")
@auth(admin=True)
def a_tpl_prev():
    j = request.get_json(silent=True) or {}; k = j.get("key")
    if k not in emails.DEFAULTS: return err("Unknown template")
    old = db.load()["templates"].get(k); db.load()["templates"][k] = {"subject": j.get("subject", ""), "body": j.get("body", "")}
    try: s, t, h = emails.render(k, SAMPLE)
    finally:
        if old: db.load()["templates"][k] = old
        else: db.load()["templates"].pop(k, None)
    return jsonify({"ok": True, "subject": s, "html": h})

@app.post("/api/admin/templates/send-test")
@auth(admin=True)
def a_tpl_send():
    j = request.get_json(silent=True) or {}
    if j.get("key") not in emails.DEFAULTS or not EMAIL_RE.match(j.get("to", "")): return err("Pick a template and enter a valid email")
    r = mailer.send(j["to"], j["key"], SAMPLE); return (jsonify({"ok": True}) if r["ok"] else err(r["error"], 502))

@app.get("/api/admin/emaillog")
@auth(admin=True)
def a_log(): return jsonify({"ok": True, "items": db.load()["emaillog"][:200]})

@app.get("/api/admin/overview")
@auth(admin=True)
def a_over():
    d = db.load(); return jsonify({"ok": True, "users": len(d["users"]), "orders": len(d["orders"]), "pending": sum(1 for o in d["orders"] if o["status"] == "pending"), "services": len([s for s in d["services"] if s["status"] != "deleted"]), "revenue": sum(o["total"] for o in d["orders"] if o["status"] == "paid"), "mail_failed": sum(1 for m in d["emaillog"] if m["status"] == "failed")})

@app.get("/api/admin/orders")
@auth(admin=True)
def a_orders():
    d = db.load(); em = {u["id"]: u["email"] for u in d["users"]}
    return jsonify({"ok": True, "items": [{**o, "email": em.get(o["uid"], "?")} for o in d["orders"][::-1]]})

@app.post("/api/admin/orders/<oid>/approve")
@auth(admin=True)
def a_approve(oid):
    o = find("orders", oid)
    if not o: return err("Order not found", 404)
    if o["status"] == "paid": return err("Already approved", 409)
    u = find("users", o["uid"]); o["status"] = "paid"; db.save()
    inv = db.nid("INV"); mailer.send(u["email"], "payment_received", {"name": u["name"], "invoice_id": inv, "order_id": o["id"], "total": o["total"]})
    s = new_service(u, o["cat"], o["product"], o["plan"], "paid", plan_ram(o["cat"], o["plan"]), 30 * o["cycle"], f"{o['cat']}-{o['id'][-4:]}", {"price": round(o["total"] / o["cycle"])})
    o["service_id"] = s["id"]; db.save(); ok, msg = provision(s, u)
    return jsonify({"ok": True, "service": s, "provisioned": ok, "note": "" if ok else msg})

@app.post("/api/admin/services/<sid>/provision")
@auth(admin=True)
def a_reprov(sid):
    s = find("services", sid)
    if not s: return err("Not found", 404)
    u = find("users", s["uid"]); ok, msg = provision(s, u); return jsonify({"ok": ok, "message": msg, "service": s}), (200 if ok else 502)

@app.get("/api/admin/services")
@auth(admin=True)
def a_services(): return jsonify({"ok": True, "items": [s for s in db.load()["services"] if s["status"] != "deleted"]})

@app.get("/api/admin/users")
@auth(admin=True)
def a_users(): return jsonify({"ok": True, "items": [pub_user(u) | {"created": u["created"], "suspended": u.get("suspended", False)} for u in db.load()["users"]]})

# ---------- renewals / expiry (runs daily; also callable via admin for tests) ----------
def run_renewals(now=None):
    now = now or db.now(); st = settings(); d = db.load(); sent = 0
    for s in d["services"]:
        if s["status"] not in ("online", "pending-setup"): continue
        u = find("users", s["uid"]); left = (s["expires"] - now) / 86400
        if not u: continue
        free = s["kind"].startswith("free"); marks = st["notify"]["renewal_days"] if not free else [2, 1]
        for m in sorted(marks, reverse=True):
            if 0 < left <= m and m not in s["warned"]:
                days = max(1, round(left)); date = time.strftime("%b %d, %Y", time.gmtime(s["expires"]))
                v = {"name": u["name"], "product": s["product"], "plan": s["plan"], "service_name": s["name"], "days": days, "date": date, "total": s.get("price", 0), "panel_url": f"{site_url()}/{'vps-panel.html' if s['cat']=='vps' else 'mc-panel.html'}"}
                mailer.send(u["email"], "free_renewal_reminder" if free else "renewal_reminder", v); notify(u["id"], f"{s['name']} expires in {days} day(s)", "Renew to keep it online.", "warn"); s["warned"].append(m); sent += 1; break
        if left <= 0:
            s["status"] = "suspended"
            try:
                if s["cat"] != "vps" and s["meta"].get("remote_id"): ig.panel_suspend(st["free_panel" if s["kind"] == "free-mc" else "paid_panel"], s["meta"]["remote_id"], True)
            except ig.IntegrationError as e: s["meta"]["suspend_error"] = str(e)
            mailer.send(u["email"], "service_suspended", {"name": u["name"], "service_name": s["name"], "reason": "free plan expired — not renewed" if free else "payment overdue"}); notify(u["id"], f"{s['name']} suspended", "Renew or pay to bring it back.", "bad"); sent += 1
    db.save(); return sent

@app.post("/api/admin/run-renewals")
@auth(admin=True)
def a_run(): return jsonify({"ok": True, "sent": run_renewals()})

def cron():
    while True:
        time.sleep(3600)
        try: run_renewals()
        except Exception as e: print("renewal job failed:", e)

# ---------- static site ----------
@app.get("/")
def home(): return send_from_directory(ROOT, "index.html")
@app.get("/<path:p>")
def static_files(p):
    if p.startswith(("backend", ".git", "shots")) or p.endswith(".py"): return err("Not found", 404)
    return send_from_directory(ROOT, p) if os.path.isfile(os.path.join(ROOT, p)) else (err("Not found", 404))

@app.after_request
def hdr(r):
    r.headers["X-Content-Type-Options"] = "nosniff"; r.headers["X-Frame-Options"] = "DENY"; r.headers["Referrer-Policy"] = "same-origin"
    return r

def bootstrap():
    d = db.load(); e, p = os.environ.get("ADMIN_EMAIL"), os.environ.get("ADMIN_PASSWORD")
    if e and p and not user_by_email(e):
        d["users"].append({"id": db.nid("u"), "name": "Admin", "email": e.lower(), "pw": hash_pw(p), "role": "admin", "verified": True, "created": db.now(), "suspended": False}); db.save(); print("Admin created:", e)

if __name__ == "__main__":
    bootstrap(); threading.Thread(target=cron, daemon=True).start()
    app.run(host=os.environ.get("HOST", "0.0.0.0"), port=int(os.environ.get("PORT", 8080)))
