#!/usr/bin/env bash
# AxionHost installer: website + backend + Cloudflare Tunnel (no public IPv4 needed, no systemd needed, ~100 MB RAM).
# Usage: bash install.sh [CLOUDFLARE_TUNNEL_TOKEN]
set -u
CFTOKEN="${1:-}"
REPO="https://github.com/devhub201/axionhost.git"; DIR="${SITE_DIR:-/opt/axionhost-site}"; PORT="${SITE_PORT:-8081}"; LOGD=/var/log/axionhost; mkdir -p $LOGD
ok(){ printf ' \033[32m✔\033[0m %s\n' "$*"; }; bad(){ printf ' \033[31m✘\033[0m %s\n' "$*"; }
[ "$(id -u)" = 0 ] || { bad "root se chalao"; exit 1; }
apt-get install -y -qq git python3 python3-venv curl >/dev/null 2>&1
if [ -d "$DIR/.git" ]; then git -C "$DIR" fetch -q origin && git -C "$DIR" reset -q --hard origin/main && ok "site updated"; else git clone -q "$REPO" "$DIR" && ok "site cloned" || { bad "clone fail"; exit 1; }; fi
cd "$DIR" || exit 1
[ -x venv/bin/python ] || python3 -m venv venv
venv/bin/pip install -q -r backend/requirements.txt && ok "python deps" || { bad "pip fail"; exit 1; }
if [ ! -f .env ]; then
  read -rp " Admin email (login ke liye): " AE; read -rsp " Admin password (min 8): " AP; echo
  [ ${#AP} -ge 8 ] || { bad "password chhota hai"; exit 1; }
  printf 'ADMIN_EMAIL=%s\nADMIN_PASSWORD=%s\nSECRET_KEY=%s\nHOST=127.0.0.1\nPORT=%s\n' "$AE" "$AP" "$(python3 -c 'import secrets;print(secrets.token_hex(32))')" "$PORT" > .env; chmod 600 .env; ok ".env bani"
fi

# ---- Cloudflare Tunnel ----
[ -z "$CFTOKEN" ] && [ -f .cf-token ] && CFTOKEN=$(cat .cf-token)
if [ -z "$CFTOKEN" ]; then read -rp " Cloudflare tunnel token (Enter = skip): " CFTOKEN; fi
if [ -n "$CFTOKEN" ]; then
  if ! command -v cloudflared >/dev/null; then
    A=$(dpkg --print-architecture 2>/dev/null || echo amd64); curl -fsSL -o /tmp/cf.deb "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-$A.deb" && dpkg -i /tmp/cf.deb >/dev/null 2>&1 && ok "cloudflared installed" || bad "cloudflared install fail"
  fi
  if command -v cloudflared >/dev/null; then
    printf '%s' "$CFTOKEN" > .cf-token; chmod 600 .cf-token
    pkill -f axion-watch-tunnel 2>/dev/null; service cloudflared stop >/dev/null 2>&1; pkill -f "cloudflared.*tunnel" 2>/dev/null; sleep 1
    setsid nohup bash -c "exec -a axion-watch-tunnel bash -c 'while true; do cloudflared tunnel --no-autoupdate run --token $(cat $DIR/.cf-token) >> $LOGD/tunnel.log 2>&1; sleep 5; done'" >/dev/null 2>&1 &
    for i in $(seq 1 15); do grep -qiE "registered tunnel connection" $LOGD/tunnel.log 2>/dev/null && break; sleep 1; done
    grep -qiE "registered tunnel connection" $LOGD/tunnel.log && ok "Cloudflare tunnel connected" || { bad "tunnel connect nahi hua:"; tail -6 $LOGD/tunnel.log; }
  fi
fi
pkill -f axion-watch-site 2>/dev/null; pkill -f "backend/app.py" 2>/dev/null; sleep 1
setsid nohup bash -c "set -a; . $DIR/.env; set +a; cd $DIR/backend; exec -a axion-watch-site bash -c 'while true; do $DIR/venv/bin/python app.py >> $LOGD/site.log 2>&1; echo \"[\$(date)] site exited, restarting\" >> $LOGD/site.log; sleep 3; done'" >/dev/null 2>&1 &
for i in $(seq 1 15); do c=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:$PORT/ 2>/dev/null); [ "$c" != 000 ] && break; sleep 1; done
[ "$c" = 200 ] && ok "website chal rahi hai: http://127.0.0.1:$PORT (HTTP 200)" || { bad "HTTP $c"; tail -12 $LOGD/site.log; }
P=$(pgrep -f "backend/app.py|python app.py" | head -1); [ -n "$P" ] && echo " RAM use: $(ps -o rss= -p $P | awk '{printf "%d MB",$1/1024}')"
grep -q "install.sh" /root/.bashrc 2>/dev/null || echo "pgrep -f axion-watch-site >/dev/null || bash $DIR/install.sh </dev/null >/dev/null 2>&1 &" >> /root/.bashrc
echo " Cloudflare Zero Trust -> Tunnels -> tumhara tunnel -> Public Hostname: tumhara-domain -> HTTP -> 127.0.0.1:$PORT"
