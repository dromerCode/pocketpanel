import pytest

from app.modules.updates.registry import digest_matches, parse_ref, parse_www_authenticate


@pytest.mark.parametrize("ref,expected", [
    ("linuxserver/jellyfin", ("registry-1.docker.io", "linuxserver/jellyfin", "latest")),
    ("nginx:alpine", ("registry-1.docker.io", "library/nginx", "alpine")),
    ("alpine:3", ("registry-1.docker.io", "library/alpine", "3")),
    ("docker.io/library/postgres:18-alpine", ("registry-1.docker.io", "library/postgres", "18-alpine")),
    ("ghcr.io/hotio/qbittorrent:latest", ("ghcr.io", "hotio/qbittorrent", "latest")),
    ("lscr.io/linuxserver/obsidian:1.12.7", ("lscr.io", "linuxserver/obsidian", "1.12.7")),
    ("localhost:5000/foo/bar:v1", ("localhost:5000", "foo/bar", "v1")),
    ("localhost:5000/foo", ("localhost:5000", "foo", "latest")),
])
def test_parse_ref(ref, expected):
    assert parse_ref(ref) == expected


def test_parse_ref_pinned_digest():
    assert parse_ref("nginx@sha256:abc") is None


def test_parse_www_authenticate():
    h = 'Bearer realm="https://auth.docker.io/token",service="registry.docker.io",scope="repository:library/nginx:pull"'
    assert parse_www_authenticate(h) == {
        "realm": "https://auth.docker.io/token", "service": "registry.docker.io", "scope": "repository:library/nginx:pull"}
    assert parse_www_authenticate("Basic realm=x") is None


def test_digest_matches():
    rd = ["linuxserver/jellyfin@sha256:aaa", "ghcr.io/x/y@sha256:bbb"]
    assert digest_matches(rd, "registry-1.docker.io", "linuxserver/jellyfin", "sha256:aaa")
    assert not digest_matches(rd, "registry-1.docker.io", "linuxserver/jellyfin", "sha256:zzz")
    assert digest_matches(["nginx@sha256:ccc"], "registry-1.docker.io", "library/nginx", "sha256:ccc")
    assert digest_matches(rd, "ghcr.io", "x/y", "sha256:bbb")
    # mismo digest pero de otro repo no cuenta
    assert not digest_matches(rd, "ghcr.io", "linuxserver/jellyfin", "sha256:aaa")
