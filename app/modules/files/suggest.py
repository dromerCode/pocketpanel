SKIP = ("/boot", "/snap", "/var/lib/docker", "/run", "/proc", "/sys", "/dev")


async def suggest(env) -> dict:
    """Tu carpeta personal y los discos montados (los que cuelgan de la misma carpeta, juntos: /mnt)."""
    out = await env.sh("findmnt -rn -o TARGET -t ext4,ext3,xfs,btrfs,zfs,f2fs,ntfs,ntfs3,exfat,vfat,fuse.mergerfs,"
                       "fuse.sshfs,nfs,nfs4,cifs 2>/dev/null; true")
    mounts = [m for m in out.split() if m != "/" and not m.startswith(SKIP)]
    if not mounts:
        return {}
    tops = {}
    for m in mounts:
        top = "/" + m.strip("/").split("/", 1)[0]
        tops.setdefault(top, []).append(m)
    roots = ["~"] + sorted(top if len(ms) > 1 or ms[0] == top else ms[0] for top, ms in tops.items())
    return {"roots": {"value": roots, "why": f"tu carpeta personal y los discos montados: {', '.join(sorted(mounts))}"}}
