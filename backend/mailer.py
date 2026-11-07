import smtplib, ssl, socket, time, db, emails
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

class MailError(Exception): pass

def _connect(c, timeout=15):
    host, port, sec = c["host"], int(c["port"] or 587), c.get("security", "starttls")
    if not host: raise MailError("SMTP host is not set")
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
    c = db.load()["settings"]["smtp"]
    subject, text, h = raw or emails.render(key, vars)
    if not c.get("enabled") or not c.get("host"):
        _log(to, key, subject, "skipped", "SMTP not configured/enabled"); return {"ok": False, "error": "SMTP not configured"}
    msg = EmailMessage(); msg["Subject"] = subject; msg["To"] = to
    msg["From"] = formataddr((c.get("from_name") or "AxionHost", c.get("from_email") or c.get("user"))); msg["Message-ID"] = make_msgid()
    msg.set_content(text); msg.add_alternative(h, subtype="html")
    try:
        s = _connect(c); s.send_message(msg); s.quit()
        _log(to, key, subject, "sent"); return {"ok": True}
    except (MailError, smtplib.SMTPException, OSError) as e:
        _log(to, key, subject, "failed", str(e)); return {"ok": False, "error": str(e)}
