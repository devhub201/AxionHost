#!/usr/bin/env bash
# Deploys the AxionHost website + backend on a small server (works without systemd, ~60 MB RAM). Usage: bash deploy-site.sh
set -u
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
pkill -f axion-watch-site 2>/dev/null; pkill -f "backend/app.py" 2>/dev/null; sleep 1
setsid nohup bash -c "set -a; . $DIR/.env; set +a; cd $DIR/backend; exec -a axion-watch-site bash -c 'while true; do $DIR/venv/bin/python app.py >> $LOGD/site.log 2>&1; echo \"[\$(date)] site exited, restarting\" >> $LOGD/site.log; sleep 3; done'" >/dev/null 2>&1 &
for i in $(seq 1 15); do c=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:$PORT/ 2>/dev/null); [ "$c" != 000 ] && break; sleep 1; done
[ "$c" = 200 ] && ok "website chal rahi hai: http://127.0.0.1:$PORT (HTTP 200)" || { bad "HTTP $c"; tail -12 $LOGD/site.log; }
P=$(pgrep -f "backend/app.py|python app.py" | head -1); [ -n "$P" ] && echo " RAM use: $(ps -o rss= -p $P | awk '{printf "%d MB",$1/1024}')"
grep -q "deploy-site.sh" /root/.bashrc 2>/dev/null || echo "pgrep -f axion-watch-site >/dev/null || bash $DIR/deploy-site.sh </dev/null >/dev/null 2>&1 &" >> /root/.bashrc
echo " Cloudflare tunnel mein Public Hostname banao: tumhara-domain -> HTTP -> 127.0.0.1:$PORT"
