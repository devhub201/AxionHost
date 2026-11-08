import smtplib, ssl, socket, time, db, emails
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

class MailError(Exception): pass

PROVIDERS = {"gmail.com": ("smtp.gmail.com", 587, "starttls"), "googlemail.com": ("smtp.gmail.com", 587, "starttls"),
 "outlook.com": ("smtp-mail.outlook.com", 587, "starttls"), "hotmail.com": ("smtp-mail.outlook.com", 587, "starttls"), "live.com": ("smtp-mail.outlook.com", 587, "starttls"),
 "yahoo.com": ("smtp.mail.yahoo.com", 587, "starttls"), "yahoo.in": ("smtp.mail.yahoo.com", 587, "starttls"), "icloud.com": ("smtp.mail.me.com", 587, "starttls"),
 "zoho.com": ("smtp.zoho.com", 465, "ssl"), "zoho.in": ("smtp.zoho.in", 465, "ssl"), "proton.me": ("smtp.protonmail.ch", 587, "starttls")}

MX_MAP = [("google.com", "smtp.gmail.com"), ("googlemail.com", "smtp.gmail.com"), ("outlook.com", "smtp.office365.com"), ("protection.outlook.com", "smtp.office365.com"),
 ("zoho.in", "smtp.zoho.in"), ("zoho.eu", "smtp.zoho.eu"), ("zoho.com", "smtp.zoho.com"), ("privateemail.com", "mail.privateemail.com"), ("hostinger.com", "smtp.hostinger.com"),
 ("titan.email", "smtp.titan.email"), ("secureserver.net", "smtpout.secureserver.net"), ("yandex.net", "smtp.yandex.com"), ("yandex.ru", "smtp.yandex.com"),
 ("mailgun.org", "smtp.mailgun.org"), ("ovh.net", "ssl0.ovh.net"), ("migadu.com", "smtp.migadu.com"), ("fastmail.com", "smtp.fastmail.com"), ("messagingengine.com", "smtp.fastmail.com")]

def mx_hosts(domain):
    """MX lookup via DNS-over-HTTPS (no extra packages). Returns [] if offline."""
    import urllib.request, json
    try:
        r = urllib.request.Request(f"https://cloudflare-dns.com/dns-query?name={domain}&type=MX", headers={"accept": "application/dns-json"})
        with urllib.request.urlopen(r, timeout=5) as f:
            return [a["data"].split()[-1].rstrip(".").lower() for a in json.load(f).get("Answer", []) if a.get("type") == 15]
    except Exception: return []

def candidates(c):
    """Ordered list of (host, port, security) to try for an email-only SMTP setup."""
    em = (c.get("user") or "")
    if "@" not in em: return []
    dom = em.split("@")[-1].lower(); out = []
    if dom in PROVIDERS: out.append(PROVIDERS[dom])
    else:
        for mx in mx_hosts(dom):
            for suf, host in MX_MAP:
                if mx == suf or mx.endswith("." + suf):
                    out += [(host, 587, "starttls"), (host, 465, "ssl")]; break
        hosts = [h for h in ("smtp." + dom, "mail." + dom)] + [h for mx in mx_hosts(dom)[:1] for h in ("smtp." + ".".join(mx.split(".")[-2:]),)]
        for h in dict.fromkeys(hosts): out += [(h, 587, "starttls"), (h, 465, "ssl")]
    return list(dict.fromkeys(out))

def resolve(c):
    """Fill from_email, and (when host is empty) a quick offline guess for known providers."""
    c = dict(c)
    if not c.get("from_email") and "@" in (c.get("user") or ""): c["from_email"] = c["user"]
    if not c.get("host") and "@" in (c.get("user") or ""):
        p = PROVIDERS.get(c["user"].split("@")[-1].lower())
        if p: c["host"], c["port"], c["security"] = p
    return c

def _connect(c, timeout=15):
    c = resolve(c)
    if c.get("host"): return _connect_one(c, timeout)
    cands = candidates(c)
    if not cands: raise MailError("Enter your full email address (and app password)")
    last = None
    for host, port, sec in cands:
        try:
            s = _connect_one({**c, "host": host, "port": port, "security": sec}, 8)
            st = db.load()["settings"]["smtp"]; st.update(host=host, port=port, security=sec); db.save()   # remember what worked
            return s
        except MailError as e:
            last = e
            if "login failed" in str(e): raise   # server reached but credentials wrong — stop guessing
    raise MailError("Couldn't auto-detect your mail server for " + c["user"].split("@")[-1] + " — open Advanced and enter the SMTP host. (" + str(last) + ")")

def _connect_one(c, timeout=15):
    host, port, sec = c["host"], int(c["port"] or 587), c.get("security", "starttls")
    try:
        if sec == "ssl": s = smtplib.SMTP_SSL(host, port, timeout=timeout, context=ssl.create_default_context())
        else:
            s = smtplib.SMTP(host, port, timeout=timeout); s.ehlo()
            if sec == "starttls": s.starttls(context=ssl.create_default_context()); s.ehlo()
        if c.get("user"): s.login(c["user"], c["password"])
        return s
    except smtplib.SMTPAuthenticationError as e: raise MailError(f"SMTP login failed: {e.smtp_code} {e.smtp_error.decode(errors='ignore')[:120]}")
    except (OSError, smtplib.SMTPException, socket.timeout) as e: raise MailError(f"SMTP connection failed: {e}")

def test_connection(c):
    s = _connect(c); s.quit(); return True

def _log(to, key, subject, status, error=""):
    d = db.load()
    d["emaillog"].insert(0, {"id": db.nid("m"), "ts": db.now(), "to": to, "template": key, "subject": subject, "status": status, "error": error})
    del d["emaillog"][500:]; db.save()

def send(to, key, vars, raw=None):
    """Send a templated email. Never raises — failures are logged and returned so signup/orders don't break."""
    c = resolve(db.load()["settings"]["smtp"])
    subject, text, h = raw or emails.render(key, vars)
    if not c.get("enabled") or not c.get("user"):
        _log(to, key, subject, "skipped", "SMTP not configured/enabled"); return {"ok": False, "error": "SMTP not configured"}
    msg = EmailMessage(); msg["Subject"] = subject; msg["To"] = to
    msg["From"] = formataddr((c.get("from_name") or "AxionHost", c.get("from_email") or c.get("user"))); msg["Message-ID"] = make_msgid()
    msg.set_content(text); msg.add_alternative(h, subtype="html")
    try:
        s = _connect(c); s.send_message(msg); s.quit()
        _log(to, key, subject, "sent"); return {"ok": True}
    except (MailError, smtplib.SMTPException, OSError) as e:
        _log(to, key, subject, "failed", str(e)); return {"ok": False, "error": str(e)}
