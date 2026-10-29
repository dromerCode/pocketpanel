import gzip
import re

from tests.test_modules import ALL, client


def version(c):
    r = c.get("/")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-cache"
    v = re.search(r'data-v="([0-9a-f]{12})"', r.text)[1]
    assert f'src="/v/{v}/js/main.js"' in r.text and f'"/js/": "/v/{v}/js/"' in r.text
    assert f'<link rel="modulepreload" href="/v/{v}/js/api.js">' in r.text and "{{V}}" not in r.text
    assert c.get("/", headers={"if-none-match": r.headers["etag"]}).status_code == 304
    return v


def test_versioned_assets_are_immutable_and_gzipped(tmp_path):
    c = client(tmp_path, ALL)
    v = version(c)
    r = c.get(f"/v/{v}/modules/terminal/vendor/xterm.js", headers={"accept-encoding": "gzip"})
    assert r.status_code == 200 and "immutable" in r.headers["cache-control"]
    assert r.headers["content-encoding"] == "gzip" and r.headers["content-type"].startswith("text/javascript")
    assert int(r.headers["content-length"]) < 100_000 and "Terminal" in r.text  # 289 KB sin comprimir
    plain = c.get(f"/v/{v}/js/main.js", headers={"accept-encoding": "identity"})
    assert "content-encoding" not in plain.headers and "import" in plain.text


def test_old_version_is_served_but_not_cached(tmp_path):
    c = client(tmp_path, ALL)
    r = c.get("/v/000000000000/js/main.js")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-cache"


def test_versioned_paths_stay_inside(tmp_path):
    c = client(tmp_path, "modules: {}\n")
    v = version(c)
    for bad in ("../app/main.py", "js/../../app/main.py", "modules/stocks/index.js", "modules/../config.yml",
                "js/nope.js", "modules//x.js"):
        assert c.get(f"/v/{v}/{bad}").status_code == 404, bad


def test_api_json_is_gzipped(tmp_path):
    c = client(tmp_path, ALL)
    r = c.get("/api/me", headers={"accept-encoding": "gzip"})
    assert r.status_code == 200 and r.json()["modules"]
    big = c.get("/api/modules", headers={"accept-encoding": "gzip"})
    if len(big.content) >= 1024:
        assert big.headers.get("content-encoding") == "gzip"
