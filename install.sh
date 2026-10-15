#!/bin/bash
# Instala o actualiza pocketpanel. Ejecútalo como tu usuario (no root) desde esta carpeta:
#   ./install.sh            instalar / actualizar (se puede repetir: conserva PIN y ajustes)
#   ./install.sh 4821       cambiar el PIN
set -eu
cd "$(dirname "$0")"

die() { echo "✗ $*" >&2; exit 1; }
warn() { echo "⚠ $*" >&2; }
# Pregunta con valor por defecto; sin terminal (p. ej. por un script) se queda con el de por defecto
ask() { local a=""; read -rp "$1 " a </dev/tty 2>/dev/null || true; echo "${a:-$2}"; }
# Lee una variable del .env (vacío si no está)
getv() { grep -s "^$1=" .env | head -1 | cut -d= -f2- || true; }
# Escribe una variable en el .env conservando el resto
setv() {
  touch .env
  { grep -v "^$1=" .env || true; printf '%s=%s\n' "$1" "$2"; } > .env.new && mv .env.new .env
}

[ "$(id -u)" != 0 ] || die "ejecútalo como tu usuario normal, no como root ni con sudo"
command -v docker >/dev/null || die "falta Docker: https://docs.docker.com/engine/install/ubuntu/"
docker compose version >/dev/null 2>&1 || die "falta el plugin de Docker Compose (paquete docker-compose-plugin)"
docker info >/dev/null 2>&1 || die "tu usuario no puede usar Docker: sudo usermod -aG docker $USER (y vuelve a entrar)"
command -v python3 >/dev/null || die "falta python3"
HOSTKEY=/etc/ssh/ssh_host_ed25519_key.pub
[ -r "$HOSTKEY" ] || die "falta el servidor SSH: sudo apt install openssh-server"
for t in tmux rsync sqlite3; do command -v "$t" >/dev/null || warn "no está '$t' (lo usan algunos módulos: sudo apt install $t)"; done

umask 077
mkdir -p ssh data uploads

# --- clave SSH del panel para entrar en este host (solo desde 127.0.0.1) ---
[ -f ssh/id_ed25519 ] || ssh-keygen -q -t ed25519 -N "" -C pocketpanel -f ssh/id_ed25519
pub=$(cut -d' ' -f1,2 ssh/id_ed25519.pub)
mkdir -p ~/.ssh
[ -O ~/.ssh ] && chmod 700 ~/.ssh   # en algunos sistemas ~/.ssh es de root: entonces no se toca
[ -e ~/.ssh/authorized_keys ] || { touch ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys; }
if ! grep -qF "$pub" ~/.ssh/authorized_keys; then
  echo "from=\"127.0.0.1\" $pub pocketpanel" >> ~/.ssh/authorized_keys
  echo "✓ clave del panel añadida a ~/.ssh/authorized_keys (solo desde 127.0.0.1)"
fi
# known_hosts a partir de la clave del propio host (sin ssh-keyscan: no hace falta ni deja intentos fallidos)
port=$(grep -s '^PANEL_SSH_PORT=' .env | cut -d= -f2- || true)
host="127.0.0.1"; [ -z "$port" ] || [ "$port" = 22 ] || host="[127.0.0.1]:$port"
echo "$host $(cut -d' ' -f1,2 "$HOSTKEY")" > ssh/known_hosts

# --- .env ---
setv PANEL_HOST_USER "$(id -un)"
setv PANEL_UID "$(id -u)"
setv PANEL_GID "$(id -g)"
setv DOCKER_GID "$(stat -c %g /var/run/docker.sock)"
setv PANEL_HOST_DIR "$(pwd)"
[ -n "$(getv PANEL_PORT)" ] || setv PANEL_PORT 9300
[ -n "$(getv TZ)" ] || setv TZ "$(timedatectl show -p Timezone --value 2>/dev/null || echo Europe/Madrid)"

[ -n "$(getv PANEL_SECRET)" ] || setv PANEL_SECRET "$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')"

# PIN: lo normal es crearlo en el asistente de la app. ./install.sh NUEVOPIN lo cambia desde aquí.
pin="${1:-}"
if [ -n "$pin" ]; then
  echo "$pin" | grep -Eq '^[0-9]{4,12}$' || die "el PIN tiene que tener de 4 a 12 números"
  PIN="$pin" python3 - <<'PY'
import base64, hashlib, json, os
s = os.urandom(16)
dk = hashlib.scrypt(os.environ["PIN"].encode(), salt=s, n=2**14, r=8, p=1, dklen=32)
f = "data/auth.json"
try:
    a = json.load(open(f))
except (OSError, ValueError):
    a = {}
a["pin_hash"] = "scrypt:" + base64.b64encode(s).decode() + ":" + base64.b64encode(dk).decode()
fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w") as fh:
    json.dump(a, fh)
PY
  echo "✓ PIN cambiado"
fi
has_pin() { [ -n "$(getv PANEL_PIN_HASH)" ] || grep -qs '"pin_hash"' data/auth.json; }
if ! has_pin && [ -z "$(getv PANEL_SETUP_CODE)" ]; then
  # código de un solo uso para que solo quien instala pueda hacer el asistente (sin 0/O ni 1/I/L)
  setv PANEL_SETUP_CODE "$(python3 -c 'import secrets;a="ABCDEFGHJKMNPQRSTUVWXYZ23456789";c="".join(secrets.choice(a) for _ in range(6));print(c[:3]+"-"+c[3:])')"
fi

umask 022
[ -f config.yml ] || cp config.example.yml config.yml
[ -f actions.yml ] || cp actions.example.yml actions.yml

docker compose up -d --build --force-recreate
port=$(getv PANEL_PORT)
url="http://127.0.0.1:$port"

# --- Tailscale: publicarlo en tu tailnet con HTTPS (lo necesitan la app instalable y los avisos) ---
if command -v tailscale >/dev/null; then
  ts_url=$(tailscale status --json 2>/dev/null | python3 -c 'import json,sys
try: print("https://"+json.load(sys.stdin)["Self"]["DNSName"].rstrip(".")+":8443")
except Exception: pass')
  if [ -n "$ts_url" ]; then
    if tailscale serve status 2>/dev/null | grep -q "127.0.0.1:$port"; then
      url="$ts_url"
    elif [ "$(ask "¿Lo publico en tu Tailscale como $ts_url? (S/n)" s)" != n ]; then
      sudo tailscale serve --bg --https=8443 "http://127.0.0.1:$port" >/dev/null && url="$ts_url" \
        || warn "no se pudo publicar; hazlo a mano: sudo tailscale serve --bg --https=8443 http://127.0.0.1:$port"
    fi
  fi
else
  warn "Tailscale no está instalado: https://tailscale.com/download/linux (luego vuelve a ejecutar ./install.sh)"
fi

echo
echo "✓ pocketpanel en marcha"
if has_pin; then
  echo "  Ábrelo en $url"
else
  code=$(getv PANEL_SETUP_CODE)
  echo "  Escanea este código con el móvil para empezar (o abre $url/#setup/$code):"
  echo
  docker compose exec -T pocketpanel python -m app.qr "$url/#setup/$code" 2>/dev/null | sed 's/^/    /'
  echo
  echo "  Código de instalación: $code"
fi
