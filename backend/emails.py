"""Email templates. Admin can override subject/body from the panel (stored in db.templates). {{vars}} are HTML-escaped."""
import html, re, db

LABELS = {
 "verify_email": "Verify your email", "welcome": "Welcome", "password_reset": "Password reset",
 "order_confirmed": "Order confirmed", "payment_received": "Payment received / invoice",
 "service_ready": "Paid service ready (credentials)", "free_vps_ready": "Free VPS ready", "free_mc_ready": "Free Minecraft ready",
 "renewal_reminder": "Renewal reminder (paid)", "free_renewal_reminder": "Free plan expiring", "service_suspended": "Service suspended",
 "ticket_reply": "Support ticket reply", "admin_new_order": "New order (to admin)",
}
DEFAULTS = {
 "verify_email": ("Verify your {{site}} email", "Hi {{name}},\n\nWelcome to {{site}}! Please confirm your email address to activate your account.\n\n[Verify my email]({{verify_url}})\n\nThis link expires in 24 hours. If you didn't sign up, ignore this email."),
 "welcome": ("Welcome to {{site}} 🎉", "Hi {{name}},\n\nYour email is verified and your account is ready.\n\n[Open client area]({{site_url}}/dashboard.html)\n\nNeed help? Reply to this email or open a ticket."),
 "password_reset": ("Reset your {{site}} password", "Hi {{name}},\n\nSomeone asked to reset your password.\n\n[Choose a new password]({{reset_url}})\n\nThe link expires in 1 hour. If this wasn't you, ignore this email."),
 "order_confirmed": ("Order {{order_id}} confirmed", "Hi {{name}},\n\nThanks for your order!\n\n**Order:** {{order_id}}\n**Plan:** {{product}} — {{plan}} ({{cycle}})\n**Total:** ₹{{total}}\n**Status:** {{status}}\n\n[View order]({{site_url}}/dashboard.html)\n\n{{pay_note}}"),
 "payment_received": ("Payment received — invoice {{invoice_id}}", "Hi {{name}},\n\nWe received your payment of ₹{{total}} for order {{order_id}}. Your service is being set up now."),
 "service_ready": ("Your {{product}} server is ready 🚀", "Hi {{name}},\n\nYour **{{product}} — {{plan}}** is live.\n\n**Service:** {{service_name}}\n**Address:** {{address}}\n{{credentials}}\n\n[Open your panel]({{panel_url}})\n\nKeep this email safe — it contains your login details."),
 "free_vps_ready": ("Your FREE 8 GB VPS is ready 🖥", "Hi {{name}},\n\nYour free VPS is online.\n\n**IP:** {{address}}\n**SSH:** `ssh root@{{address}}`\n**Root password:** `{{password}}`\n{{sshx}}\n\n[Open VPS panel]({{panel_url}})\n\nRenew every {{renew_days}} days from the panel to keep it active."),
 "free_mc_ready": ("Your FREE 4 GB Minecraft server is ready ⛏", "Hi {{name}},\n\nYour free Minecraft server is online.\n\n**Address:** {{address}}\n\n[Open game panel]({{panel_url}})\n\nRenew every {{renew_days}} days from the panel to keep it active."),
 "renewal_reminder": ("{{service_name}} renews in {{days}} day(s)", "Hi {{name}},\n\nYour **{{product}} — {{plan}}** renews on **{{date}}** for ₹{{total}}.\n\n[Pay / manage]({{site_url}}/invoices.html)\n\nIf unpaid, the service will be suspended after the due date."),
 "free_renewal_reminder": ("⚠ Your free {{product}} expires in {{days}} day(s)", "Hi {{name}},\n\nYour free **{{product}}** will be suspended on **{{date}}** unless you renew.\n\n[Renew now]({{panel_url}}#settings)\n\nRenewing takes one click."),
 "service_suspended": ("{{service_name}} has been suspended", "Hi {{name}},\n\nYour service **{{service_name}}** was suspended ({{reason}}).\n\n[Reactivate]({{site_url}}/dashboard.html)"),
 "ticket_reply": ("Re: {{subject}} [#{{ticket_id}}]", "Hi {{name}},\n\nOur team replied to your ticket:\n\n> {{message}}\n\n[Open ticket]({{site_url}}/tickets.html)"),
 "admin_new_order": ("[New order] {{order_id}} — ₹{{total}}", "New order from **{{name}}** ({{email}}).\n\n{{product}} — {{plan}} ({{cycle}}) · ₹{{total}}\n\n[Review in admin]({{site_url}}/admin-orders.html)"),
}

def get(key):
    d = db.load()["templates"].get(key)
    return (d["subject"], d["body"]) if d else DEFAULTS[key]

def _sub(text, vars, esc=True):
    def r(m):
        v = vars.get(m.group(1).strip(), "")
        return html.escape(str(v)) if esc else str(v)
    return re.sub(r"\{\{\s*([\w.]+)\s*\}\}", r, text)

def _md_html(body, vars):
    # tiny markdown: **bold**, `code`, [text](url), > quote, blank-line paragraphs
    out = []
    for para in body.split("\n\n"):
        para = _sub(html.escape(para, quote=False), vars)
        para = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", para)
        para = re.sub(r"`(.+?)`", r"<code style='background:#eef2f7;padding:2px 6px;border-radius:5px'>\1</code>", para)
        def btn(m):
            url = m.group(2)
            if not re.match(r"^https?://|^mailto:", html.unescape(url)): return m.group(0)
            return f"<a href='{url}' style='display:inline-block;background:#0ea5e9;color:#fff;text-decoration:none;padding:12px 22px;border-radius:10px;font-weight:600'>{m.group(1)}</a>"
        para = re.sub(r"\[(.+?)\]\((.+?)\)", btn, para)
        if para.startswith("&gt; "): para = f"<blockquote style='border-left:3px solid #0ea5e9;margin:0;padding:4px 14px;color:#475569'>{para[5:]}</blockquote>"
        out.append(f"<p style='margin:0 0 16px;line-height:1.6'>{para.replace(chr(10), '<br>')}</p>")
    return "".join(out)

def render(key, vars):
    s = db.load()["settings"]
    vars = {"site": s["site"]["name"], "site_url": s["site"]["url"].rstrip("/"), **vars}
    subj, body = get(key)
    subject = _sub(subj, vars, esc=False)
    text = _sub(body, vars, esc=False)
    h = f"""<div style='background:#f1f5f9;padding:28px 12px;font-family:Inter,Arial,sans-serif;color:#0f172a'><div style='max-width:560px;margin:auto;background:#fff;border-radius:16px;overflow:hidden;border:1px solid #e2e8f0'><div style='background:linear-gradient(135deg,#0ea5e9,#6366f1);padding:22px 28px;color:#fff;font-size:20px;font-weight:800'>{html.escape(vars['site'])}</div><div style='padding:28px'>{_md_html(body, vars)}</div><div style='padding:16px 28px;background:#f8fafc;color:#64748b;font-size:12.5px'>© {html.escape(vars['site'])} · {html.escape(s['site']['support_email'])}</div></div></div>"""
    return subject, text, h
