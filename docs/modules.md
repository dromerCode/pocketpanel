# Writing a module

Every optional feature of pocketpanel is a folder in `app/modules/`. The panel discovers the folders at startup:
adding a module means adding a folder, with no lists to edit anywhere else. A module that is switched off costs
nothing: its backend code is not imported and the browser never downloads its interface.

```
app/modules/weather/
├── __init__.py      manifest: what the module store shows and its options (always imported: keep it light)
├── api.py           setup(ctx) -> APIRouter (imported only when the module is on)
├── checks.py        optional: requirement checks for the "Comprobar requisitos" button
├── suggest.py       optional: fills its form with what it finds on the server
├── requirements.txt optional: Python packages only this module needs (see below)
├── weather.py       your own logic, as many files as you like
└── web/             optional: its part of the interface, served at /modules/weather/
    ├── index.js     what it adds to the app (see below)
    ├── card.html    / view.html: HTML fragments it mounts
    └── style.css
```

## Manifest (`__init__.py`)

```python
from ...module import Module, field

MODULE = Module(
    icon="☀", title="Weather", desc="Today's forecast on the status screen.",
    order=95,                 # position in the store
    enabled=False,            # on in a fresh install?
    after=(),                 # modules that must be set up first (they leave something in ctx this one uses)
    fields=[
        field("city", "City", default="Madrid", required=True),
        field("every", "Refresh every (minutes)", "int", default=30),
        field("api_key", "API key", "secret"),   # stored in data/secrets.json, never in config.yml
    ],
)
```

Field types: `str`, `int`, `bool`, `time` (`HH:MM`, `nullable=True` allows null), `list`, `choice` (`choices=[…]`)
and `secret`. The defaults, the validation of `config.yml` and the form in the store all come from this list.

## Backend (`api.py`)

```python
from fastapi import APIRouter, Depends

from ... import auth


def setup(ctx) -> APIRouter:
    opts = ctx.cfg.mod("weather")                 # this module's options from config.yml
    r = APIRouter(dependencies=[Depends(auth.require_auth)])

    @r.get("/api/weather")
    async def weather():
        return {"city": opts["city"]}

    return r
```

What the core offers in `ctx`: `cfg`, `ssh` (run commands on the host), `docker`, `push` (send a notification),
`history`, `tz`. A module can also:

- append to `ctx.hooks` an object with `async tick(n, now) -> [(text, url)]`: it runs every 30 s and each pair it
  returns is sent as a push notification;
- append to `ctx.busy_checks` a function returning why the panel must not restart now (or `None`);
- put data for the interface in `ctx.info["weather"]` (it arrives in `/api/me`, readable as `panel.weather`);
- leave an object for other modules (`ctx.backup = …`). Reading something no module left gives `None`, so
  `if ctx.backup:` is how a module checks whether another one is on.

## Its own Python packages (`requirements.txt`)

What only one module needs doesn't go in the image. List it, pinned, in the module's `requirements.txt`:

```
curl_cffi==0.16.3
```

When the module is switched on, the panel starts without it, downloads the packages in the background into
`data/deps/<module>-<fingerprint>/` (with `pip --prefix`, so whatever the image already has is not downloaded
again), and restarts itself to load the module; the module store shows the progress and lets you retry if it
fails. It happens once: the folder survives restarts and image updates. Switching the module off, or changing the
versions, removes the old folder on the next start. Import the packages inside the module's code as usual, but not
in its `__init__.py` (the manifest is read even when the module is off).

## Requirement checks (`checks.py`)

Both functions are optional:

```python
from ...requirements import PRELUDE, chk

def script(values):          # a shell script that runs on the host, and a label per check
    return PRELUDE + chk("curl", "error", "command -v curl"), {"curl": "curl installed"}

async def http_checks(values, http):   # checks made from the panel itself
    r = await http.get("https://api.example.com/ping")
    return [{"label": "The API answers", "ok": r.status_code == 200, "level": "error", "detail": ""}]
```

## Filling the form for the user (`suggest.py`)

When the module's form opens (in the module store or in the first-run setup), the panel calls `suggest(env)`
and fills the form with the result, showing under each field where the value came from. In a module that is
off, it fills everything. In one already set up, it fills only empty fields; for anything else it offers the
value behind a "Usar" button, and for lists it only offers to add what is missing.

```python
async def suggest(env):
    c = await env.find("weatherd")              # a container by name or image (prefers a running one)
    if c and (url := c.url(8000)):              # how the panel reaches that container port (published or host network)
        return {"api_url": {"value": url, "why": c.where(8000)}}
    return {}
```

`env` (`app/suggest.py`) also has `containers()` (with `.ports`, `.mounts`, `.labels`), `sh(script)` to run
something on the host, and `read(path)`. Return only what you found. It must only look, never change anything.
It has 20 s, and if it fails, the form just opens as usual.

## Interface (`web/index.js`)

It exports an object describing what the module adds. Every key is optional:

```js
import { api } from "/js/api.js";

const $ = (id) => document.getElementById(id);

async function load() {
  $("weather").textContent = (await api("/api/weather")).city;
}

export default {
  styles: ["style.css"],                          // relative to web/; full URLs work too
  scripts: [],                                    // classic <script> libraries it needs (loaded first, once)
  cards: [{ slot: "right", html: "card.html", show: load, slow: load }],   // on the status screen
  // view: { html: "view.html", tab: { icon: "☀", label: "Weather", order: 40 } },  // its own tab (#weather)
  // tour: [{ sel: '.tabbar a[data-tab="weather"]', title: "Weather", text: "…" }],
  // init() {}, show(args) {}, hide() {}, leave() {},   // lifecycle of its view
};
```

- **Cards** are widgets on the status screen. `slot` (`left`: after the history, `right`: after the disks,
  `bottom`: at the end) and `order` only say where a card shows up the first time, and `size` its width in a
  4-column grid (1 to 4; 2 by default, 4 for `bottom`; on a phone 1 is half the screen and the rest full width).
  After that the user moves, resizes and hides them with ✎ (stored in `data/layout.json`, the same on every device).
  The title in the organizer is `title`, or the card's first `.section-title`. `init` runs once, `show` when the status screen opens, `fast` every 5 s and
  `slow` every 30 s while it is visible.
- **A view** is an HTML fragment with a `<section class="view" data-view="<name>" hidden>`; with `tab` it also gets
  a button in the tab bar. It is reachable at `#<name>` (the module name, or `view.name`).
- **Hooking into other screens**: `/js/services.js` exports `addFilter`, `addHeader`, `addInfo`,
  `addSheetButton`, `onShow`, `current` and `reload` (the updates and backups modules use them), and `/js/ui.js`
  has the shared sheet (`openSheet`) and the output window (`openRunner`, `watchJob`).
- Import core helpers with absolute paths (`/js/api.js`) and your own files with relative ones (`./weather.js`).

The tests check that every module folder is complete (`tests/test_registry_modules.py`).
