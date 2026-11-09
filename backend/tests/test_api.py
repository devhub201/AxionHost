import os, sys, json, threading, socket, socketserver, tempfile, time, base64, unittest, stat, re
from http.server import BaseHTTPRequestHandler, HTTPServer
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["DATA_DIR"] = tempfile.mkdtemp(); os.environ["SECRET_KEY"] = "test"
import db, app as A

import email, email.policy
def decode(raw):
    m = email.message_from_string(raw, policy=email.policy.default)
    parts = [m["Subject"] or "", "Reply-To: " + str(m["Reply-To"] or ""), "From: " + str(m["From"] or "")] + [p.get_content() for p in m.walk() if p.get_content_type() in ("text/plain", "text/html")]
    return "\n".join(parts)
# ---- local SMTP sink with AUTH (user/pw) ----
MAILS = []
class SMTP(socketserver.StreamRequestHandler):
    def handle(self):
        w = lambda s: self.wfile.write((s + "\r\n").encode())
        w("220 sink ESMTP"); data = False; buf = []; frm = to = ""
        for raw in self.rfile:
            l = raw.decode(errors="ignore").rstrip("\r\n")
            if data:
                if l == ".": MAILS.append({"from": frm, "to": to, "data": decode("\n".join(buf))}); data = False; buf = []; w("250 OK"); continue
                buf.append(l[1:] if l.startswith("..") else l); continue
            u = l.upper()
            if u.startswith("EHLO"): self.wfile.write(b"250-sink\r\n250 AUTH PLAIN LOGIN\r\n")
            elif u.startswith("AUTH PLAIN"):
                cred = base64.b64decode(l.split()[2]).split(b"\0"); w("235 ok" if cred[1:] == [b"user", b"pw"] else "535 5.7.8 bad credentials")
            elif u.startswith("MAIL FROM"): frm = l; w("250 OK")
            elif u.startswith("RCPT TO"): to = l; w("250 OK")
            elif u == "DATA": data = True; w("354 go")
            elif u == "QUIT": w("221 bye"); return
            else: w("250 OK")
class Srv(socketserver.ThreadingTCPServer): allow_reuse_address = True; daemon_threads = True

# ---- mock game panel (Application API) ----
CALLS = []
class Ptero(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, o, c=200): b = json.dumps(o).encode(); self.send_response(c); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def _auth(self): return self.headers.get("Authorization") == "Bearer KEY123"
    def do_GET(self):
        if not self._auth(): return self._send({"errors": [{"detail": "unauth"}]}, 401)
        if self.path.startswith("/api/application/nodes/1/allocations"): return self._send({"data": [{"attributes": {"id": 5, "ip": "10.0.0.5", "port": 25570, "assigned": True}}, {"attributes": {"id": 6, "ip": "10.0.0.5", "port": 25571, "assigned": False}}]})
        if self.path.startswith("/api/application/nodes"): return self._send({"data": [{"attributes": {"id": 1, "name": "Mumbai-1"}}]})
        if self.path.startswith("/api/application/users"): return self._send({"data": []})
        self._send({}, 404)
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}"); CALLS.append((self.path, body))
        if not self._auth(): return self._send({}, 401)
        if self.path == "/api/application/users": return self._send({"attributes": {"id": 77}}, 201)
        if self.path == "/api/application/servers": return self._send({"attributes": {"id": 900 + len(CALLS), "uuid": "u-1", "identifier": "abcd1234"}}, 201)
        self._send({}, 204 if "suspend" in self.path else 200)

def fake_ssh():
    p = os.path.join(os.environ["DATA_DIR"], "fakessh"); open(p, "w").write("""#!/bin/sh
LAST="${@: -1}"
echo "$LAST" >> "$(dirname "$0")/ssh.log"
case "$LAST" in
 *"echo axion-ok"*) echo axion-ok; echo "Linux 6.8";;
 *sshx*) echo "link: https://sshx.io/s/abc123#key";;
 *"axion-vps create"*) echo '{"ip":"203.0.113.9","port":22}';;
 *) echo done;;
esac
""".replace('"${@: -1}"', '"$(eval echo \\${$#})"'))
    os.chmod(p, 0o755); return p

class T(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.smtp = Srv(("127.0.0.1", 0), SMTP); threading.Thread(target=cls.smtp.serve_forever, daemon=True).start()
        cls.pt = HTTPServer(("127.0.0.1", 0), Ptero); threading.Thread(target=cls.pt.serve_forever, daemon=True).start()
        A.app.config["TESTING"] = True; cls.c = A.app.test_client()
    def setUp(self):
        (os.path.exists(db.PATH()) and os.remove(db.PATH())); db.reset(); MAILS.clear(); CALLS.clear(); A._hits.clear()
        d = db.load(); d["users"].append({"id": "u-admin", "name": "Admin", "email": "admin@x.io", "pw": A.hash_pw("adminpass1"), "role": "admin", "verified": True, "created": 0, "suspended": False}); db.save()
        self.adm = self.login("admin@x.io", "adminpass1")
        s = db.load()["settings"]
        s["site"]["url"] = "https://axion.test"
        s["smtp"].update(host="127.0.0.1", port=self.smtp.server_address[1], security="none", user="user", password="pw", from_email="no-reply@axion.test", enabled=True)
        for k in ("paid_panel", "free_panel"): s[k].update(url=f"http://127.0.0.1:{self.pt.server_address[1]}", api_key="KEY123", client_key="KEY123", node_id=1, enabled=True)
        s["vps"].update(host="203.0.113.9", private_key="KEY", ssh_bin=fake_ssh(), enabled=True, mode="sshx"); db.save()
    def j(self, m, url, body=None, tok=None):
        r = getattr(self.c, m)(url, json=body, headers={"Authorization": "Bearer " + tok} if tok else {}); return r.status_code, r.get_json()
    def login(self, e, p): return self.c.post("/api/auth/login", json={"email": e, "password": p}).get_json()["token"]
    def signup(self, e="rahul@x.io"):
        self.j("post", "/api/auth/register", {"name": "Rahul S", "email": e, "password": "password123"})
        m = [x for x in MAILS if e in x["to"]][-1]; tok = re.search(r"verify\.html\?token=([\w-]+)", m["data"]).group(1)
        return self.j("post", "/api/auth/verify", {"token": tok})[1]["token"]

    def test_verify_flow(self):
        c, r = self.j("post", "/api/auth/register", {"name": "Rahul S", "email": "rahul@x.io", "password": "password123"}); self.assertEqual(c, 201); self.assertTrue(r["emailSent"])
        self.assertEqual(len(MAILS), 1); self.assertIn("Verify your AxionHost email", MAILS[0]["data"]); self.assertIn("https://axion.test/verify.html?token=", MAILS[0]["data"])
        c, r = self.j("post", "/api/auth/login", {"email": "rahul@x.io", "password": "password123"}); self.assertEqual(c, 403); self.assertTrue(r["needVerify"])
        tok = self.signup("two@x.io"); self.assertEqual(self.j("get", "/api/me", tok=tok)[0], 200)
        self.assertEqual(self.j("post", "/api/auth/verify", {"token": "bad"})[0], 400)
        self.assertTrue(any("Welcome to AxionHost" in m["data"] for m in MAILS))   # welcome mail after verify
        self.assertEqual(self.j("post", "/api/auth/register", {"name": "x", "email": "rahul@x.io", "password": "password123"})[0], 400)
        self.assertEqual(self.j("post", "/api/auth/register", {"name": "Rahul S", "email": "rahul@x.io", "password": "password123"})[0], 409)
    def test_verify_token_single_use(self):
        self.j("post", "/api/auth/register", {"name": "Rahul S", "email": "a@x.io", "password": "password123"}); t = re.search(r"token=([\w-]+)", MAILS[0]["data"]).group(1)
        self.assertEqual(self.j("post", "/api/auth/verify", {"token": t})[0], 200); self.assertEqual(self.j("post", "/api/auth/verify", {"token": t})[0], 400)
    def test_smtp_settings_and_test(self):
        c, r = self.j("post", "/api/admin/test/smtp", {"to": "me@x.io"}, self.adm); self.assertEqual(c, 200, r); self.assertIn("test email sent", r["message"]); self.assertEqual(MAILS[-1]["to"].lower(), "rcpt to:<me@x.io>")
        c, r = self.j("get", "/api/admin/settings", tok=self.adm); self.assertEqual(r["settings"]["smtp"]["password"], "••••••••"); self.assertNotIn("KEY123", json.dumps(r))
        self.j("put", "/api/admin/settings", {"smtp": {"password": "••••••••", "host": "127.0.0.1"}}, self.adm); self.assertEqual(db.load()["settings"]["smtp"]["password"], "pw")  # mask keeps secret
        self.j("put", "/api/admin/settings", {"smtp": {"password": "wrong"}}, self.adm); c, r = self.j("post", "/api/admin/test/smtp", {}, self.adm); self.assertEqual(c, 502); self.assertIn("login failed", r["error"])
    def test_smtp_email_and_key_only(self):
        import mailer
        c = mailer.resolve({"host": "", "user": "me@gmail.com", "password": "k", "port": 587, "security": "starttls", "from_email": ""})
        self.assertEqual((c["host"], c["port"], c["security"], c["from_email"]), ("smtp.gmail.com", 587, "starttls", "me@gmail.com"))
        orig = mailer.mx_hosts
        try:
            mailer.mx_hosts = lambda d: ["aspmx.l.google.com"]; self.assertEqual(mailer.candidates({"user": "info@mybrand.com"})[0], ("smtp.gmail.com", 587, "starttls"))   # Google Workspace custom domain
            mailer.mx_hosts = lambda d: ["mx.zoho.in"]; self.assertEqual(mailer.candidates({"user": "a@brand.in"})[0][0], "smtp.zoho.in")
            mailer.mx_hosts = lambda d: []; self.assertEqual(mailer.candidates({"user": "a@mybrand.com"})[0][0], "smtp.mybrand.com")
        finally: mailer.mx_hosts = orig
    def test_smtp_autodiscovery_custom_domain(self):
        import mailer
        s = db.load()["settings"]["smtp"]; s.update(host="", user="user", password="pw")   # email-only config, no host
        port = self.smtp.server_address[1]; orig = mailer.candidates
        try:
            mailer.candidates = lambda c: [("127.0.0.1", 1, "starttls"), ("127.0.0.1", port, "none")]   # first guess is dead, second works
            c, r = self.j("post", "/api/admin/test/smtp", {"to": "me@x.io"}, self.adm); self.assertEqual(c, 200, r)
            self.assertEqual(db.load()["settings"]["smtp"]["port"], port)   # remembered
            mailer.candidates = lambda c: [("127.0.0.1", 1, "starttls")]; s.update(host="", port=587)
            c, r = self.j("post", "/api/admin/test/smtp", {}, self.adm); self.assertEqual(c, 502); self.assertIn("auto-detect", r["error"])
            mailer.candidates = lambda c: [("127.0.0.1", port, "none")]; s.update(host="", password="WRONG")
            c, r = self.j("post", "/api/admin/test/smtp", {}, self.adm); self.assertEqual(c, 502); self.assertIn("login failed", r["error"])   # stops guessing on bad credentials
        finally: mailer.candidates = orig
    def test_from_noreply_and_reply_to(self):
        s = db.load()["settings"]["smtp"]; s.update(from_email="no-reply@axion.test", reply_to="support@axion.test", from_name="AxionHost")
        self.j("post", "/api/auth/register", {"name": "Rahul S", "email": "nr@x.io", "password": "password123"})
        d = MAILS[-1]["data"]; self.assertIn("from:<no-reply@axion.test>", MAILS[-1]["from"].lower()); self.assertIn("Reply-To: support@axion.test", d); self.assertIn("From: AxionHost <no-reply@axion.test>", d)
    def test_manual_vps_delivery_by_email(self):
        db.load()["settings"]["vps"]["enabled"] = False; t = self.signup(); o = self.j("post", "/api/orders", {"cat": "vps", "plan": "Mini", "cycle": 1}, t)[1]["order"]
        c, r = self.j("post", f"/api/admin/orders/{o['id']}/approve", tok=self.adm); self.assertFalse(r["provisioned"]); sid = r["service"]["id"]; self.assertEqual(r["service"]["status"], "pending-setup")
        MAILS.clear(); self.assertEqual(self.j("post", f"/api/admin/services/{sid}/deliver", {"ip": "bad ip;"}, self.adm)[0], 400); self.assertEqual(self.j("post", f"/api/admin/services/{sid}/deliver", {"ip": "1.2.3.4", "web_url": "http://x"}, self.adm)[0], 400)
        c, r = self.j("post", f"/api/admin/services/{sid}/deliver", {"ip": "198.51.100.7", "port": 2222, "username": "root", "password": "Pa55w0rd!", "notes": "Reboot via panel."}, self.adm); self.assertEqual(c, 200, r); self.assertTrue(r["emailed"])
        m = MAILS[-1]["data"]; self.assertIn("198.51.100.7", m); self.assertIn("-p 2222", m); self.assertIn("Pa55w0rd!", m); self.assertIn("Reboot via panel.", m); self.assertIn("rahul@x.io", MAILS[-1]["to"])
        self.assertEqual(A.find("services", sid)["status"], "online"); self.assertNotIn("Pa55w0rd!", json.dumps(db.load()["services"]))   # password not stored
        self.assertEqual(self.j("post", f"/api/admin/services/{sid}/deliver", {"ip": "1.1.1.1"}, t)[0], 403)
    def test_admin_only(self):
        t = self.signup(); 
        for m, u in [("get", "/api/admin/settings"), ("get", "/api/admin/emaillog"), ("post", "/api/admin/test/smtp"), ("get", "/api/admin/users")]: self.assertEqual(self.j(m, u, tok=t)[0], 403, u)
        self.assertEqual(self.j("get", "/api/admin/settings")[0], 401)
    def test_order_to_provision_game(self):
        t = self.signup(); c, r = self.j("post", "/api/orders", {"cat": "minecraft", "plan": "Iron", "cycle": 3, "coupon": "LAUNCH10"}, t); self.assertEqual(c, 201)
        o = r["order"]; self.assertEqual(o["total"], round(349 * 3 * .95) - round(round(349 * 3 * .95) * .1)); self.assertTrue(any("Order " + o["id"] in m["data"] for m in MAILS))
        self.assertTrue(any("[New order]" in m["data"] for m in MAILS))
        c, r = self.j("post", f"/api/admin/orders/{o['id']}/approve", tok=self.adm); self.assertEqual(c, 200, r); self.assertTrue(r["provisioned"])
        srv = [b for p, b in CALLS if p == "/api/application/servers"][0]; self.assertEqual(srv["limits"]["memory"], 6 * 1024); self.assertEqual(srv["allocation"]["default"], 6)
        self.assertTrue(any("is ready" in m["data"] for m in MAILS)); self.assertTrue(any("payment of" in m["data"] for m in MAILS))
        self.assertEqual(self.j("post", f"/api/admin/orders/{o['id']}/approve", tok=self.adm)[0], 409)
        self.assertEqual(self.j("post", "/api/orders", {"cat": "minecraft", "plan": "Nope", "cycle": 1}, t)[0], 400)
    def test_paid_vps_credentials_by_email(self):
        t = self.signup(); o = self.j("post", "/api/orders", {"cat": "vps", "plan": "Mini", "cycle": 1}, t)[1]["order"]
        c, r = self.j("post", f"/api/admin/orders/{o['id']}/approve", tok=self.adm); self.assertEqual(c, 200, r); self.assertEqual(r["service"]["address"], "203.0.113.9")
        m = [x for x in MAILS if "Root password" in x["data"]][0]; self.assertIn("ssh root@203.0.113.9", m["data"])
    def test_free_claims(self):
        t = self.signup(); c, r = self.j("post", "/api/free/claim", {"type": "minecraft"}, t); self.assertEqual(c, 201, r); self.assertTrue(r["provisioned"])
        srv = [b for p, b in CALLS if p == "/api/application/servers"][0]; self.assertEqual(srv["limits"]["memory"], 4096)
        self.assertEqual(self.j("post", "/api/free/claim", {"type": "minecraft"}, t)[0], 409)
        c, r = self.j("post", "/api/free/claim", {"type": "vps"}, t); self.assertEqual(c, 201, r)
        m = [x for x in MAILS if "FREE 8 GB VPS" in x["data"]][0]; self.assertIn("sshx.io/s/abc123", m["data"]); self.assertIn("203.0.113.9", m["data"])
        log = open(os.path.join(os.environ["DATA_DIR"], "ssh.log")).read(); self.assertIn("--ram 8", log); self.assertIn("--cpu 2", log)
    def test_free_limits_and_unverified(self):
        self.j("post", "/api/auth/register", {"name": "Rahul S", "email": "u@x.io", "password": "password123"})
        d = db.load(); u = [x for x in d["users"] if x["email"] == "u@x.io"][0]; tok = A.make_token(u)
        self.assertEqual(self.j("post", "/api/free/claim", {"type": "vps"}, tok)[0], 403)
        db.load()["settings"]["free"]["max_per_ip_per_day"] = 1; t1 = self.signup("a1@x.io"); t2 = self.signup("a2@x.io")
        self.assertEqual(self.j("post", "/api/free/claim", {"type": "minecraft"}, t1)[0], 201); self.assertEqual(self.j("post", "/api/free/claim", {"type": "minecraft"}, t2)[0], 429)
    def test_unconfigured_panel_degrades(self):
        db.load()["settings"]["free_panel"]["enabled"] = False; t = self.signup(); c, r = self.j("post", "/api/free/claim", {"type": "minecraft"}, t)
        self.assertEqual(c, 201); self.assertFalse(r["provisioned"]); self.assertEqual(r["service"]["status"], "pending-setup")
        db.load()["settings"]["free_panel"]["enabled"] = True; c, r = self.j("post", f"/api/admin/services/{r['service']['id']}/provision", tok=self.adm); self.assertEqual(c, 200); self.assertEqual(r["service"]["status"], "online")
    def test_renewals(self):
        t = self.signup(); sid = self.j("post", "/api/free/claim", {"type": "minecraft"}, t)[1]["service"]["id"]; s = A.find("services", sid); MAILS.clear()
        s["expires"] = db.now() + 86400 * 1.5; self.assertEqual(A.run_renewals(), 1); self.assertIn("expires in", MAILS[0]["data"]); self.assertEqual(A.run_renewals(), 0)   # no duplicate
        s["expires"] = db.now() - 5; CALLS.clear(); A.run_renewals(); self.assertEqual(s["status"], "suspended"); self.assertTrue(any("suspend" in p for p, _ in CALLS)); self.assertTrue(any("suspended" in m["data"] for m in MAILS))
        c, r = self.j("post", f"/api/services/{sid}/renew", tok=t); self.assertEqual(c, 200); self.assertEqual(r["service"]["status"], "online")
    def test_paid_renewal_reminder(self):
        t = self.signup(); o = self.j("post", "/api/orders", {"cat": "minecraft", "plan": "Dirt", "cycle": 1}, t)[1]["order"]; sid = self.j("post", f"/api/admin/orders/{o['id']}/approve", tok=self.adm)[1]["service"]["id"]
        MAILS.clear(); A.find("services", sid)["expires"] = db.now() + 86400 * 2.5; A.run_renewals(); self.assertTrue(any("renews on" in m["data"] for m in MAILS))
    def test_templates_edit_preview_log(self):
        c, r = self.j("get", "/api/admin/templates", tok=self.adm); self.assertEqual(c, 200); self.assertEqual(len(r["items"]), 13)
        self.j("put", "/api/admin/templates/welcome", {"subject": "Hey {{name}}!", "body": "Custom body for {{name}} <script>alert(1)</script>"}, self.adm)
        c, r = self.j("post", "/api/admin/templates/preview", {"key": "welcome", "subject": "S {{name}}", "body": "Hi {{name}} {{order_id}}"}, self.adm); self.assertEqual(r["subject"], "S Rahul"); self.assertIn("Hi Rahul ORD-1001", r["html"])
        self.signup("w@x.io"); w = [m for m in MAILS if "Hey Rahul S!" in m["data"]]; self.assertTrue(w); self.assertNotIn("<script>", w[0]["data"].split("<div style")[1]); self.assertIn("&lt;script&gt;", w[0]["data"])
        self.j("put", "/api/admin/templates/welcome", {"reset": True}, self.adm); self.assertNotIn("welcome", db.load()["templates"])
        log = self.j("get", "/api/admin/emaillog", tok=self.adm)[1]["items"]; self.assertTrue(log and log[0]["status"] == "sent")
        self.assertEqual(self.j("post", "/api/admin/templates/send-test", {"key": "order_confirmed", "to": "t@x.io"}, self.adm)[0], 200)
    def test_mail_failure_logged_not_fatal(self):
        db.load()["settings"]["smtp"]["port"] = 1; c, r = self.j("post", "/api/auth/register", {"name": "Rahul S", "email": "z@x.io", "password": "password123"}); self.assertEqual(c, 201); self.assertFalse(r["emailSent"])
        self.assertEqual(db.load()["emaillog"][0]["status"], "failed"); db.load()["settings"]["smtp"]["enabled"] = False; self.j("post", "/api/auth/resend", {"email": "z@x.io"}); self.assertEqual(db.load()["emaillog"][0]["status"], "skipped")
    def test_integration_tests_endpoints(self):
        for w in ("paid", "free"): c, r = self.j("post", f"/api/admin/test/{w}", tok=self.adm); self.assertEqual(c, 200, r); self.assertIn("1 node", r["message"])
        c, r = self.j("post", "/api/admin/test/vps", tok=self.adm); self.assertEqual(c, 200, r); self.assertIn("SSH connected", r["message"])
        db.load()["settings"]["paid_panel"]["api_key"] = "bad"; c, r = self.j("post", "/api/admin/test/paid", tok=self.adm); self.assertEqual(c, 502); self.assertIn("401", r["error"])
    def test_password_reset(self):
        self.signup(); MAILS.clear(); self.j("post", "/api/auth/forgot", {"email": "rahul@x.io"}); t = re.search(r"reset\.html\?token=([\w-]+)", MAILS[0]["data"]).group(1)
        self.assertEqual(self.j("post", "/api/auth/reset", {"token": t, "password": "newpassword9"})[0], 200); self.login("rahul@x.io", "newpassword9")
        self.assertEqual(self.j("post", "/api/auth/reset", {"token": t, "password": "newpassword9"})[0], 400)
    def test_vps_name_not_injectable(self):
        import integrations as ig; cfg = db.load()["settings"]["vps"]; ig.vps_provision(cfg, "x; rm -rf / #", 1, 1, 1)
        log = open(os.path.join(os.environ["DATA_DIR"], "ssh.log")).read(); self.assertNotIn("rm -rf", log)
    def test_notifications(self):
        t = self.signup(); r = self.j("get", "/api/notifications", tok=t)[1]; self.assertTrue(r["items"]); self.assertGreater(self.j("get", "/api/me", tok=t)[1]["unread"], 0)
        self.j("post", "/api/notifications/read", tok=t); self.assertEqual(self.j("get", "/api/me", tok=t)[1]["unread"], 0)
    def test_nodes_ip_ports(self):
        node = {"name": "n1", "public_ip": "127.0.0.1", "ssh_port": 22, "port_start": 25000, "port_end": 25002}
        c, r = self.j("put", "/api/admin/nodes", {"items": [dict(node, public_ip="999.1.1.1")]}, tok=self.adm); self.assertEqual(c, 400); self.assertIn("not a valid IP", r["error"])
        c, r = self.j("put", "/api/admin/nodes", {"items": [dict(node, port_start=25005)]}, tok=self.adm); self.assertEqual(c, 400)
        c, r = self.j("put", "/api/admin/nodes", {"items": [dict(node, port_start=20, port_end=30)]}, tok=self.adm); self.assertEqual(c, 400)
        c, r = self.j("put", "/api/admin/nodes", {"items": [node]}, tok=self.adm); self.assertEqual(c, 200, r); self.assertEqual(r["items"][0]["free_ports"], 3)
        n = db.load()["nodes"][0]; self.assertEqual([A.alloc_port(n)], [25000]); db.load()["nodes"][0]["reserved"] = [25000, 25001]; self.assertEqual(A.alloc_port(n), 25002)
        db.load()["nodes"][0]["reserved"] = [25000, 25001, 25002]
        with self.assertRaises(A.ig.IntegrationError): A.alloc_port(n)
        db.load()["nodes"][0]["reserved"] = []
        c, r = self.j("get", "/api/admin/nodes?check=1", tok=self.adm); self.assertEqual(c, 200); self.assertIn("ok", r["items"][0]["status"])
        c, r = self.j("get", "/api/admin/nodes"); self.assertEqual(c, 401)
    def test_static_blocks_source(self):
        self.assertEqual(self.c.get("/backend/app.py").status_code, 404); self.assertEqual(self.c.get("/app.py").status_code, 404); self.assertEqual(self.c.get("/index.html").status_code, 200)
if __name__ == "__main__": unittest.main()
