#!/bin/bash
# Instala o actualiza pocketpanel. Ejecútalo como tu usuario (no root) desde esta carpeta:
#   ./install.sh            instalar / actualizar (se puede repetir: conserva PIN y ajustes)
#   ./install.sh 4821       cambiar el PIN
set -eu
cd "$(dirname "$0")"

die() { echo "✗ $*" >&2; exit 1; }
warn() { echo "⚠ $*" >&2; }
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
mkdir -p ~/.ssh && chmod 700 ~/.ssh
touch ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys
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

pin="${1:-}"
if [ -n "$pin" ] || [ -z "$(getv PANEL_PIN_HASH)" ]; then
  [ -n "$pin" ] || pin=$(python3 -c 'import secrets;print(f"{secrets.randbelow(10**6):06d}")')
  [ -n "$(getv PANEL_SECRET)" ] || setv PANEL_SECRET "$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')"
  # separador ':' y no '$': compose interpreta los '$' del .env
  setv PANEL_PIN_HASH "$(PIN="$pin" python3 -c '
import base64,hashlib,os
s=os.urandom(16);dk=hashlib.scrypt(os.environ["PIN"].encode(),salt=s,n=2**14,r=8,p=1,dklen=32)
print("scrypt:"+base64.b64encode(s).decode()+":"+base64.b64encode(dk).decode())')"
  new_pin=1
fi

umask 022
[ -f config.yml ] || { cp config.example.yml config.yml; echo "✓ config.yml creado (los módulos se activan desde la app: Estado → ⚙)"; }
[ -f actions.yml ] || cp actions.example.yml actions.yml

docker compose up -d --build --force-recreate
port=$(getv PANEL_PORT)
echo
echo "✓ pocketpanel en marcha en http://127.0.0.1:$port"
[ -z "${new_pin:-}" ] || echo "  PIN: $pin   (cámbialo con ./install.sh NUEVO_PIN)"
echo "  Para abrirlo desde el móvil por Tailscale (HTTPS, necesario para instalarla y para los avisos):"
echo "    sudo tailscale serve --bg --https=8443 http://127.0.0.1:$port"
echo "  y entra en https://<nombre-del-servidor>.<tu-tailnet>.ts.net:8443"
