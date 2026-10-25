#!/bin/bash
# Parte de root OPCIONAL de los backups: copiar también lo que solo puede leer root y poder restaurar como root.
# Instala backup.sh/restore.sh en /etc/pocketpanel (root:root) y una regla de sudo que deja a tu usuario ejecutar
# SOLO esos dos scripts. Origen y destino salen de config.yml y quedan fijos en /etc/pocketpanel/backup.conf.
#
#   sudo ./install-root.sh            instalar o actualizar (repítelo si cambias modules.backups)
#   sudo ./install-root.sh --remove   quitarlo
set -eu
cd "$(dirname "$0")"
DIR=/etc/pocketpanel
[ "$(id -u)" = 0 ] || { echo "Ejecútalo con sudo: sudo ./install-root.sh"; exit 1; }
USER_NAME="${SUDO_USER:-}"
[ -n "$USER_NAME" ] && [ "$USER_NAME" != root ] || { echo "Ejecútalo con sudo desde tu usuario, no como root"; exit 1; }
USER_HOME=$(getent passwd "$USER_NAME" | cut -d: -f6)

if [ "${1:-}" = --remove ]; then
  rm -f /etc/sudoers.d/pocketpanel
  rm -rf "$DIR"
  echo "pocketpanel: parte de root quitada"
  exit 0
fi

pp() { docker compose run --rm --no-deps -T --entrypoint python pocketpanel -m app.modules.backups.rootconf "$1"; }
conf=$(pp conf)
excludes=$(pp excludes)
key=$(pp key)
key="${key/#\~/$USER_HOME}"

install -d -m 755 -o root -g root "$DIR"
install -m 755 -o root -g root app/modules/backups/scripts/backup.sh app/modules/backups/scripts/restore.sh "$DIR/"
printf '%s\n' "$conf" > "$DIR/backup.conf"
printf '%s\n' "$excludes" > "$DIR/excludes.txt"
chmod 644 "$DIR/backup.conf" "$DIR/excludes.txt"
if [ -n "$key" ]; then install -m 600 -o root -g root "$key" "$DIR/id_backup"; fi
if [ -f "$USER_HOME/.ssh/known_hosts" ]; then
  install -m 644 -o root -g root "$USER_HOME/.ssh/known_hosts" "$DIR/known_hosts"
else
  touch "$DIR/known_hosts"
fi

tmp=$(mktemp)
echo "$USER_NAME ALL=(root) NOPASSWD: $DIR/backup.sh, $DIR/restore.sh" > "$tmp"
visudo -cf "$tmp" >/dev/null
install -m 440 -o root -g root "$tmp" /etc/sudoers.d/pocketpanel
rm -f "$tmp"
echo "pocketpanel: parte de root instalada ($USER_NAME puede ejecutar solo $DIR/backup.sh y restore.sh con sudo)"
