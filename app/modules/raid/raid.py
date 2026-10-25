import re

import shlex

# Solo lee. Sin root, `mdadm --detail` y `smartctl` no dan nada y el estado sale de /proc/mdstat.
SCRIPT = r"""
echo @mdstat; cat /proc/mdstat
echo @detail; {sudo}mdadm --detail {dev} 2>/dev/null
for d in $({sudo}mdadm --detail {dev} 2>/dev/null | awk '$NF ~ /^\/dev\// {{print $NF}}'); do
  echo "@smart $d"; {sudo}smartctl -H -A -i "$d" 2>/dev/null
done
echo @df; df -P -B1 | grep '^{dev} '
true
"""


def raid_command(opts: dict) -> str:
    dev = shlex.quote(opts["device"])
    script = SCRIPT.format(dev=dev, sudo="sudo -n " if opts.get("sudo") else "")
    if not opts.get("ssh"):
        return script
    ssh = " ".join(["ssh -o ConnectTimeout=5 -o BatchMode=yes", opts.get("ssh_options") or "",
                    shlex.quote(opts["ssh"]), "sh -s"]).replace("  ", " ")
    return f"{ssh} <<'PP_EOF'\n{script}\nPP_EOF"


def _sections(out: str) -> list[tuple[str, list[str]]]:
    secs, cur = [], None
    for line in out.splitlines():
        if line.startswith("@"):
            cur = (line[1:].strip(), [])
            secs.append(cur)
        elif cur:
            cur[1].append(line)
    return secs


def _attr(lines: list[str], attr_id: int) -> int | None:
    for l in lines:
        p = l.split()
        if len(p) >= 10 and p[0] == str(attr_id):
            m = re.match(r"\d+", p[9])
            return int(m.group()) if m else None
    return None


def _smart(lines: list[str]) -> dict:
    info = {}
    for l in lines:
        if ":" in l:
            k, _, v = l.partition(":")
            info[k.strip()] = v.strip()
    health = None
    for l in lines:
        if "overall-health" in l:
            health = "PASSED" if "PASSED" in l else "FAILED"
    return {
        "model": info.get("Device Model") or info.get("Model Number"),
        "serial": info.get("Serial Number"),
        "health": health,
        "temp": _attr(lines, 194) or _attr(lines, 190),
        "hours": _attr(lines, 9),
        "realloc": _attr(lines, 5),
        "pending": _attr(lines, 197),
        "crc": _attr(lines, 199),
    }


def _mdstat_block(lines: list[str], device: str) -> list[str]:
    name = device.rsplit("/", 1)[-1]
    block, inside = [], False
    for l in lines:
        if re.match(r"^md\S+ :", l):
            inside = l.startswith(name + " ")
        elif not l.strip():
            inside = False
        if inside:
            block.append(l)
    return block


def _from_mdstat(r: dict, block: list[str]) -> None:
    """Rellena nivel, discos y estado con /proc/mdstat (cuando no hay `mdadm --detail`)."""
    m = re.match(r"^\S+ : (\S+)(?: \(\S+\))? (raid\d+|linear)? ?(.*)$", block[0])
    if not m:
        return
    active, level, rest = m.groups()
    r["level"] = level
    devs = []
    for d in re.finditer(r"(\S+)\[(\d+)\](\([A-Z]\))?", rest):
        state = {"(F)": "faulty", "(S)": "spare"}.get(d.group(3) or "", "active sync")
        devs.append((int(d.group(2)), {"dev": "/dev/" + d.group(1), "state": state}))
    r["devices"] = [d for _, d in sorted(devs, key=lambda x: x[0])]
    text = "\n".join(block)
    bad = re.search(r"\[\d+/\d+\] \[[U_]*_[U_]*\]", text) or any(d["state"] == "faulty" for d in r["devices"])
    if active != "active":
        r["state"] = "inactive"
    elif re.search(r"(recovery|resync|reshape)\s*=", text):
        r["state"] = "degraded, recovering" if bad else "resyncing"
    else:
        r["state"] = "degraded" if bad else "clean"


def parse_raid(out: str, device: str = "/dev/md0") -> dict:
    r = {"status": "unknown", "level": None, "state": None, "progress": None,
         "size": None, "used": None, "avail": None, "pct": None, "devices": [], "problems": []}
    smart = {}
    block = []
    for name, lines in _sections(out):
        if name == "mdstat":
            block = _mdstat_block(lines, device)
            for l in block:
                m = re.search(r"(recovery|resync|reshape|check)\s*=\s*([\d.]+)%", l)
                if m:
                    r["progress"] = float(m.group(2))
        elif name == "detail":
            for l in lines:
                k, _, v = l.partition(" : ")
                k = k.strip()
                if k == "Raid Level":
                    r["level"] = v.strip()
                elif k == "State":
                    r["state"] = v.strip()
                m = re.match(r"\s*(\d+|-)\s+\d+\s+\d+\s+(\d+|-)\s+(.+?)\s+(/dev/\S+)\s*$", l)
                if m:
                    r["devices"].append({"dev": m.group(4), "state": m.group(3).strip()})
        elif name.startswith("smart "):
            smart[name.split(" ", 1)[1]] = _smart(lines)
        elif name == "df":
            for l in lines:
                p = l.split()
                if len(p) >= 5:
                    r["size"], r["used"], r["avail"] = int(p[1]), int(p[2]), int(p[3])
                    r["pct"] = round(r["used"] * 100 / r["size"]) if r["size"] else 0
    if not r["state"] and block:
        _from_mdstat(r, block)
    empty = {"model": None, "serial": None, "health": None, "temp": None, "hours": None,
             "realloc": None, "pending": None, "crc": None}
    for d in r["devices"]:
        d.update(smart.get(d["dev"], empty))

    st = (r["state"] or "").lower()
    if not st:
        r["status"] = "unknown"
    elif any(w in st for w in ("recovering", "resyncing", "reshaping")):
        r["status"] = "rebuilding"
    elif "degraded" in st or "fail" in st or "inactive" in st:
        r["status"] = "degraded"
    else:
        r["status"] = "ok"

    if r["status"] in ("degraded", "rebuilding"):
        r["problems"].append(f"RAID {r['state']}")
    for d in r["devices"]:
        if "faulty" in d["state"]:
            r["problems"].append(f"{d['dev']} marcado como faulty")
        if d["health"] == "FAILED":
            r["problems"].append(f"{d['dev']}: SMART FAILED")
        if (d["realloc"] or 0) > 0 or (d["pending"] or 0) > 0:
            r["problems"].append(f"{d['dev']}: sectores reasignados/pendientes")
    return r
