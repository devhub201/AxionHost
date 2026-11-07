"""Tiny JSON-file store with a lock. Swap for SQLite/Postgres later — every access goes through these helpers."""
import json, os, threading, time, secrets, tempfile
LOCK = threading.RLock()
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(__file__), "data"))
PATH = lambda: os.path.join(DATA_DIR, "db.json")

DEFAULT_SETTINGS = {
  "site": {"name": "AxionHost", "url": "http://localhost:8080", "support_email": "support@axionhost.net", "discord": ""},
  "smtp": {"host": "", "port": 587, "security": "starttls", "user": "", "password": "", "from_name": "AxionHost", "from_email": "", "enabled": False},
  "paid_panel": {"url": "", "api_key": "", "client_key": "", "node_id": 1, "egg_id": 1, "docker_image": "ghcr.io/pterodactyl/yolks:java_21", "startup": "java -Xms128M -Xmx{{SERVER_MEMORY}}M -jar server.jar", "enabled": False},
  "free_panel": {"url": "", "api_key": "", "client_key": "", "node_id": 1, "egg_id": 1, "docker_image": "ghcr.io/pterodactyl/yolks:java_21", "startup": "java -Xms128M -Xmx{{SERVER_MEMORY}}M -jar server.jar", "ram_mb": 4096, "disk_mb": 20480, "cpu_percent": 200, "enabled": False},
  "vps": {"mode": "ssh", "host": "", "port": 22, "user": "root", "private_key": "", "ssh_bin": "ssh",
          "provision_cmd": "axion-vps create --name {name} --ram {ram} --cpu {cpu} --disk {disk} --password {password}",
          "sshx_cmd": "sshx -q --name {name}", "free_ram_gb": 8, "free_cpu": 2, "free_disk_gb": 50, "enabled": False},
  "free": {"vps_enabled": True, "mc_enabled": True, "renew_days": 7, "max_per_ip_per_day": 2, "require_verified_email": True},
  "payments": {"mode": "manual", "upi_id": "", "note": "Pay via UPI and your order is approved after verification."},
  "notify": {"renewal_days": [3, 1], "order_admin_copy": True}
}
SECRET_FIELDS = {"smtp": ["password"], "paid_panel": ["api_key", "client_key"], "free_panel": ["api_key", "client_key"], "vps": ["private_key"]}

def _fresh():
    return {"users": [], "orders": [], "services": [], "notifications": [], "emaillog": [], "tokens": [], "templates": {}, "settings": json.loads(json.dumps(DEFAULT_SETTINGS)), "seq": 1000, "ipclaims": []}

_cache = None
def load():
    global _cache
    with LOCK:
        if _cache is None:
            os.makedirs(DATA_DIR, exist_ok=True)
            try:
                _cache = json.load(open(PATH()))
            except Exception:
                _cache = _fresh()
            for k, v in _fresh().items():
                _cache.setdefault(k, v)
            for sec, d in DEFAULT_SETTINGS.items():
                _cache["settings"].setdefault(sec, {})
                for k, v in d.items():
                    _cache["settings"][sec].setdefault(k, v)
        return _cache

def save():
    with LOCK:
        os.makedirs(DATA_DIR, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=DATA_DIR)
        with os.fdopen(fd, "w") as f:
            json.dump(_cache, f, indent=1)
        os.chmod(tmp, 0o600)
        os.replace(tmp, PATH())

def reset():
    global _cache
    with LOCK:
        _cache = None

def nid(prefix):
    d = load(); d["seq"] += 1
    return f"{prefix}-{d['seq']}"

def now():
    return int(time.time())

def token(n=24):
    return secrets.token_urlsafe(n)
