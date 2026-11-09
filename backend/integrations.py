"""Game-panel (Application API) and VPS-over-SSH/SSHX integrations. The game panel is never exposed to customers —
they only ever see our own in-site panel; the backend talks to it with the admin API key."""
import json, os, re, shlex, subprocess, tempfile, urllib.request, urllib.error, secrets, string, db

class IntegrationError(Exception): pass

def _alnum(n=16):
    a = string.ascii_letters + string.digits
    return "".join(secrets.choice(a) for _ in range(n))

# ---------------- game panel ----------------
def _req(cfg, method, path, body=None, key="api_key"):
    base = (cfg.get("url") or "").rstrip("/")
    if not base.startswith("http"): raise IntegrationError("Panel URL is not set")
    if not cfg.get(key): raise IntegrationError("Panel API key is not set")
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(base + path, data=data, method=method, headers={"Authorization": "Bearer " + cfg[key], "Accept": "application/json", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=20) as f:
            raw = f.read(); return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        msg = e.read().decode(errors="ignore")[:200]
        raise IntegrationError(f"Panel API {e.code}: {msg}")
    except (urllib.error.URLError, OSError) as e:
        raise IntegrationError(f"Cannot reach panel: {getattr(e, 'reason', e)}")

def panel_test(cfg):
    n = _req(cfg, "GET", "/api/application/nodes")
    nodes = [x["attributes"] for x in n.get("data", [])]
    return {"nodes": [{"id": x["id"], "name": x["name"]} for x in nodes], "message": f"Connected — {len(nodes)} node(s) found"}

def panel_user(cfg, email, name):
    q = _req(cfg, "GET", "/api/application/users?filter[email]=" + urllib.request.quote(email))
    if q.get("data"): return q["data"][0]["attributes"]["id"]
    uname = re.sub(r"[^a-z0-9]", "", email.split("@")[0].lower())[:12] or "user"
    parts = (name or "Customer").split(" ", 1)
    r = _req(cfg, "POST", "/api/application/users", {"email": email, "username": uname + _alnum(4).lower(), "first_name": parts[0][:30], "last_name": (parts[1] if len(parts) > 1 else "-")[:30], "password": _alnum(24)})
    return r["attributes"]["id"]

def panel_allocation(cfg):
    r = _req(cfg, "GET", f"/api/application/nodes/{int(cfg['node_id'])}/allocations?per_page=100")
    for a in r.get("data", []):
        if not a["attributes"].get("assigned"): return a["attributes"]
    raise IntegrationError("No free port allocations on the node — add more in the panel")

def panel_create_server(cfg, owner_email, owner_name, name, ram_mb, disk_mb, cpu_percent, extra_env=None):
    uid = panel_user(cfg, owner_email, owner_name); al = panel_allocation(cfg)
    body = {"name": name[:60], "user": uid, "egg": int(cfg["egg_id"]), "docker_image": cfg["docker_image"], "startup": cfg["startup"],
            "environment": {"SERVER_JARFILE": "server.jar", "BUILD_NUMBER": "latest", "MINECRAFT_VERSION": "latest", **(extra_env or {})},
            "limits": {"memory": ram_mb, "swap": 0, "disk": disk_mb, "io": 500, "cpu": cpu_percent},
            "feature_limits": {"databases": 2, "backups": 5, "allocations": 1}, "allocation": {"default": al["id"]}, "start_on_completion": True}
    r = _req(cfg, "POST", "/api/application/servers", body)
    a = r["attributes"]
    return {"remote_id": a["id"], "uuid": a["uuid"], "identifier": a.get("identifier"), "ip": al.get("ip_alias") or al.get("ip"), "port": al.get("port")}

def panel_power(cfg, identifier, action):
    if action not in ("start", "stop", "restart", "kill"): raise IntegrationError("bad action")
    _req(cfg, "POST", f"/api/client/servers/{identifier}/power", {"signal": action}, key="client_key")
    return True

def panel_suspend(cfg, remote_id, on=True):
    _req(cfg, "POST", f"/api/application/servers/{int(remote_id)}/{'suspend' if on else 'unsuspend'}"); return True

# ---------------- VPS over SSH / SSHX ----------------
def _ssh(cfg, command, timeout=60):
    if not cfg.get("host"): raise IntegrationError("VPS node host is not set")
    if not cfg.get("private_key"): raise IntegrationError("SSH private key is not set")
    fd, kp = tempfile.mkstemp(); os.write(fd, (cfg["private_key"].strip() + "\n").encode()); os.close(fd); os.chmod(kp, 0o600)
    try:
        cmd = [cfg.get("ssh_bin") or "ssh", "-i", kp, "-p", str(int(cfg.get("port") or 22)), "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=10", f"{cfg.get('user') or 'root'}@{cfg['host']}", command]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError: raise IntegrationError("`ssh` client is not installed on the server running the backend")
    except subprocess.TimeoutExpired: raise IntegrationError("SSH command timed out")
    finally: os.unlink(kp)
    if p.returncode != 0: raise IntegrationError("SSH failed: " + (p.stderr or p.stdout).strip()[:200])
    return p.stdout

def vps_test(cfg):
    out = _ssh(cfg, "echo axion-ok && uname -sr", 20)
    if "axion-ok" not in out: raise IntegrationError("Unexpected reply from node")
    msg = "SSH connected — " + out.strip().splitlines()[-1]
    if cfg.get("mode") == "sshx":
        try: _ssh(cfg, "command -v sshx >/dev/null && echo yes", 20); msg += " · sshx found"
        except IntegrationError: msg += " · ⚠ sshx not found on node"
    return {"message": msg}

def vps_provision(cfg, name, ram_gb, cpu, disk_gb, port=0):
    name = re.sub(r"[^a-z0-9-]", "", name.lower())[:30] or "vps"
    pw = _alnum(18)
    cmd = cfg["provision_cmd"].format(name=shlex.quote(name), ram=int(ram_gb), cpu=int(cpu), disk=int(disk_gb), password=shlex.quote(pw), port=int(port or 0))
    out = _ssh(cfg, cmd, 180)
    info = {}
    for line in out.splitlines()[::-1]:
        line = line.strip()
        if line.startswith("{"):
            try: info = json.loads(line); break
            except ValueError: pass
    res = {"ip": info.get("ip") or cfg["host"], "port": info.get("port") or port or 22, "password": info.get("password") or pw, "name": name, "sshx_url": ""}
    if cfg.get("mode") == "sshx":
        try:
            o = _ssh(cfg, cfg["sshx_cmd"].format(name=shlex.quote(name)), 40)
            m = re.search(r"https://sshx\.io/\S+", o)
            res["sshx_url"] = m.group(0) if m else ""
        except IntegrationError: pass
    return res

def vps_power(cfg, name, action):
    if action not in ("start", "stop", "restart"): raise IntegrationError("bad action")
    _ssh(cfg, f"axion-vps {action} --name {shlex.quote(name)}", 60); return True


# ---------------- Node IPs & ports ----------------
import socket, ipaddress, time as _t
def valid_ip(v):
    try: ipaddress.ip_address(v.strip()); return True
    except ValueError: return False

def node_check(node):
    """TCP-probe the node's public IP on its SSH port. Returns dict(ok, ms, error)."""
    t = _t.time()
    try:
        with socket.create_connection((node["public_ip"], int(node["ssh_port"])), timeout=4): pass
        return {"ok": True, "ms": int((_t.time() - t) * 1000), "error": ""}
    except OSError as e:
        return {"ok": False, "ms": 0, "error": (str(e) or e.__class__.__name__)[:120]}
