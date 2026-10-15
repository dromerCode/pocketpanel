import re

import httpx

HUB = "registry-1.docker.io"
ACCEPT = ", ".join([
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
])


def parse_ref(ref: str) -> tuple[str, str, str] | None:
    """'nginx:alpine' → ('registry-1.docker.io', 'library/nginx', 'alpine'). None si va fijado por digest."""
    if "@" in ref:
        return None
    first, _, rest = ref.partition("/")
    if rest and ("." in first or ":" in first or first == "localhost"):
        registry, path = first, rest
    else:
        registry, path = HUB, ref
    if registry == "docker.io":
        registry = HUB
    name, _, tag = path.rpartition(":") if ":" in path.rsplit("/", 1)[-1] else (path, "", "latest")
    if registry == HUB and "/" not in name:
        name = f"library/{name}"
    return registry, name, tag or "latest"


def parse_www_authenticate(h: str) -> dict | None:
    if not h or not h.lower().startswith("bearer "):
        return None
    return dict(re.findall(r'(\w+)="([^"]*)"', h))


def _norm(registry: str, repo: str) -> str:
    if registry == HUB:
        return repo.removeprefix("library/")
    return f"{registry}/{repo}"


def digest_matches(repo_digests: list, registry: str, repo: str, digest: str) -> bool:
    want = f"{_norm(registry, repo)}@{digest}"
    alt = f"docker.io/{repo}@{digest}" if registry == HUB else None
    return any(rd in (want, alt) for rd in repo_digests or [])


async def remote_digest(client: httpx.AsyncClient, registry: str, repo: str, tag: str) -> str:
    """Digest del tag en el registro con HEAD (no cuenta como pull en Docker Hub). Token anónimo si lo pide."""
    url = f"https://{registry}/v2/{repo}/manifests/{tag}"
    r = await client.head(url, headers={"Accept": ACCEPT})
    if r.status_code == 401:
        auth = parse_www_authenticate(r.headers.get("www-authenticate", ""))
        if not auth or "realm" not in auth:
            raise RuntimeError("el registro pide autenticación")
        params = {k: v for k, v in auth.items() if k in ("service", "scope")}
        params.setdefault("scope", f"repository:{repo}:pull")
        t = await client.get(auth["realm"], params=params)
        t.raise_for_status()
        token = t.json().get("token") or t.json().get("access_token")
        r = await client.head(url, headers={"Accept": ACCEPT, "Authorization": f"Bearer {token}"})
    if r.status_code >= 400:
        raise RuntimeError(f"registro respondió {r.status_code}")
    d = r.headers.get("docker-content-digest")
    if not d:
        raise RuntimeError("el registro no dio digest")
    return d
