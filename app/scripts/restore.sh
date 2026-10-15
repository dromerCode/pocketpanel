#!/bin/bash
# pocketpanel: restaura SRC/<app> desde una copia. Uso: restore.sh <copia> <app> [dry|run]
# (dry = solo cuenta lo que cambiaría). Respeta las exclusiones: no borra cachés y demás que no están en la copia.
set -u
SNAP="${1:-}"; APP="${2:-}"; RUN="${3:-dry}"
[[ "$SNAP" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}(-[a-z0-9-]{1,40})?$ ]] || { echo "PP_FAIL copia no válida"; exit 2; }
[[ "$APP" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$ ]] || { echo "PP_FAIL carpeta no válida"; exit 2; }
[[ "$RUN" == dry || "$RUN" == run ]] || { echo "PP_FAIL modo no válido"; exit 2; }
if [ "$(id -u)" = 0 ] && [ -f /etc/pocketpanel/backup.conf ]; then . /etc/pocketpanel/backup.conf; fi
: "${SRC:?}" "${DEST_HOST:?}" "${DEST_PATH:?}" "${SSH_OPTS:=}"
[ -d "$SRC$APP" ] || { echo "PP_FAIL $SRC$APP no existe"; exit 2; }
export LANG=C.UTF-8
SSH="ssh $SSH_OPTS"

$SSH "$DEST_HOST" "test -d '$DEST_PATH/$SNAP/$APP'" </dev/null || { echo "PP_FAIL la copia $SNAP no tiene $APP"; exit 3; }
# Las copias incompletas (archivos que no se pudieron leer) borrarían esos archivos al restaurar
$SSH "$DEST_HOST" "test -f '$DEST_PATH/$SNAP/.pocketpanel-complete'" </dev/null || { echo "PP_FAIL la copia $SNAP está incompleta, no se puede restaurar"; exit 3; }
all=$(mktemp); excl=$(mktemp)
if [ -n "${EXCLUDES_FILE:-}" ]; then cp "$EXCLUDES_FILE" "$all"; else printf '%s\n' "${EXCLUDES:-}" > "$all"; fi
# Las exclusiones ancladas (/app/ruta) pasan a ser relativas a la carpeta de la app
while IFS= read -r p; do
  case "$p" in "/$APP/"*) echo "/${p#/$APP/}";; /*) ;; ?*) echo "$p";; esac
done < "$all" > "$excl"
flags=(-a --delete --numeric-ids --exclude-from="$excl")
[ "$RUN" = dry ] && flags+=(-n --itemize-changes)
out=$(mktemp)
rsync "${flags[@]}" -e "$SSH" "$DEST_HOST:$DEST_PATH/$SNAP/$APP/" "$SRC$APP/" >"$out" 2>&1
rc=$?
rm -f "$all" "$excl"
if [ $rc -ne 0 ] && [ $rc -ne 24 ]; then echo "PP_FAIL rsync salió con $rc: $(tail -2 "$out" | tr '\n' ' ')"; rm -f "$out"; exit $rc; fi
if [ "$RUN" = dry ]; then
  echo "PP_CHANGES $(grep -cE '^(>f|cd|\*deleting|>f\+)' "$out")"
  grep -E '^(>f|\*deleting)' "$out" | head -15 | sed 's/^/PP_FILE /'
else
  echo "PP_RESTORED"
fi
rm -f "$out"
