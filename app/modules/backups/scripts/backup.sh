#!/bin/bash
# pocketpanel: copia incremental (rsync + hardlinks) de SRC a DEST_HOST:DEST_PATH/<copia>.
# Modo usuario: el panel lo ejecuta por SSH con las variables en el entorno.
# Modo root: instalado en /etc/pocketpanel (ver install-root.sh); lee backup.conf y solo se puede llamar por sudo.
set -u
SNAP="${1:-}"
[[ "$SNAP" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}(-[a-z0-9-]{1,40})?$ ]] || { echo "PP_FAIL nombre de copia no válido"; exit 2; }
if [ "$(id -u)" = 0 ] && [ -f /etc/pocketpanel/backup.conf ]; then
  . /etc/pocketpanel/backup.conf
  MODE=root
else
  MODE=user
fi
: "${SRC:?}" "${DEST_HOST:?}" "${DEST_PATH:?}" "${KEEP_DAYS:=7}" "${SSH_OPTS:=}"
export LANG=C.UTF-8
SSH="ssh $SSH_OPTS"
excl=$(mktemp)
if [ -n "${EXCLUDES_FILE:-}" ]; then cp "$EXCLUDES_FILE" "$excl"; else printf '%s\n' "${EXCLUDES:-}" > "$excl"; fi

$SSH "$DEST_HOST" "mkdir -p '$DEST_PATH'" </dev/null || { echo "PP_FAIL no se puede entrar en $DEST_HOST"; rm -f "$excl"; exit 90; }
err=$(mktemp)
# --whole-file: sin delta. "failed verification -- update discarded" deja el archivo FUERA de la copia, así que si
# aparece se repite la pasada (los que cambian sin parar, como los -wal de SQLite, pueden seguir fallando).
for _ in 1 2 3; do
  rsync -a --whole-file --delete --numeric-ids -e "$SSH" --link-dest=../latest --exclude-from="$excl" \
    "$SRC" "$DEST_HOST:$DEST_PATH/$SNAP.partial/" 2>"$err"
  rc=$?
  grep -q "failed verification" "$err" || break
done
rm -f "$excl"
discarded=$(grep "failed verification" "$err" | sed -E 's/^ERROR: (.*) failed verification.*/\1/' | grep -v -E -- '-(wal|shm)$')
denied=$(grep -c "Permission denied" "$err")
others=$(grep -v -e "Permission denied" -e "some files/attrs were not transferred" -e "link-dest arg does not exist" \
  -e "IO error encountered" -e "failed verification" -e "vanished" "$err" | grep -c .)
# 24: ficheros que desaparecen durante la copia. 23 solo por permisos: copia parcial (se informa)
if [ $rc -ne 0 ] && [ $rc -ne 24 ] && ! { [ $rc -eq 23 ] && [ "$others" -eq 0 ]; }; then
  echo "PP_FAIL rsync salió con $rc: $(grep -v 'Permission denied' "$err" | tail -2 | tr '\n' ' ')"; rm -f "$err"; exit $rc
fi
echo "PP_MODE $MODE"
echo "PP_DENIED $denied"
[ -n "$discarded" ] && echo "$discarded" | head -8 | sed 's/^/PP_CHANGED /'
grep "Permission denied" "$err" | sed -E "s#.*\"${SRC}([^/\"]+(/[^/\"]+)?).*#\\1#" | sort | uniq -c | sort -rn | head -8 | sed 's/^/PP_DIR /'
rm -f "$err"
# Restaurable solo si está completa: hecha como root o sin archivos que no se pudieran leer
complete=""
{ [ "$MODE" = root ] || [ "$denied" -eq 0 ]; } && complete="touch $SNAP/.pocketpanel-complete"

$SSH "$DEST_HOST" bash -s <<PP_EOF
set -e
cd '$DEST_PATH'
rm -rf $SNAP
mv $SNAP.partial $SNAP
$complete
ln -sfn $SNAP latest
ls -1d *.partial 2>/dev/null | xargs -r rm -rf
ls -1d 20??-??-?? 2>/dev/null | sort | head -n -$KEEP_DAYS | xargs -r rm -rf
cutoff=\$(date -d '-$KEEP_DAYS days' +%F)
for d in 20??-??-??-*; do [ -d "\$d" ] || continue
  [[ "\${d:0:10}" < "\$cutoff" ]] && rm -rf "\$d"; done
echo "PP_OK \$(du -sb . | cut -f1) \$(du -sb $SNAP | cut -f1) \$(ls -1d 20??-??-??* | wc -l)"
PP_EOF
