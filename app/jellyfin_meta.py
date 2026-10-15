import shlex
from datetime import datetime, timezone

# Por usuario: fecha de alta (evento UserCreated), primera actividad registrada y fecha de su foto de perfil.
SQL = """select upper(u.Id),
 (select min(DateCreated) from ActivityLogs a where a.Type='UserCreated' and upper(a.UserId)=upper(u.Id)),
 (select min(DateCreated) from ActivityLogs a where upper(a.UserId)=upper(u.Id)),
 (select min(LastModified) from ImageInfos i where upper(i.UserId)=upper(u.Id))
from Users u;"""


def meta_command(db: str) -> str:
    return f"sqlite3 -separator '|' {shlex.quote(f'file:{db}?mode=ro')} \"{SQL}\""


def _ts(s: str) -> int | None:
    s = (s or "").strip()
    if not s:
        return None
    try:
        return int(datetime.fromisoformat(s[:19]).replace(tzinfo=timezone.utc).timestamp())
    except ValueError:
        return None


def jfa_id(jellyfin_id: str) -> str:
    return jellyfin_id.replace("-", "").lower()


def parse_meta(out: str) -> dict:
    """{id_de_jfa: {"since": ts|None, "approx": bool, "image": bool}}"""
    res = {}
    for line in out.splitlines():
        p = line.split("|")
        if len(p) != 4 or not p[0].strip():
            continue
        created, first_act, image = _ts(p[1]), _ts(p[2]), _ts(p[3])
        if created:
            since, approx = created, False
        else:
            # sin evento de alta (anterior al registro de actividad): lo más antiguo que sepamos
            known = [t for t in (first_act, image) if t]
            since, approx = (min(known), True) if known else (None, True)
        res[jfa_id(p[0])] = {"since": since, "approx": approx, "image": image is not None}
    return res
