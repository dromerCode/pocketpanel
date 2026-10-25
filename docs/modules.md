# Writing a module

Every optional feature of pocketpanel is a folder in `app/modules/`. The panel discovers the folders at startup:
adding a module means adding a folder, with no lists to edit anywhere else. A module that is switched off costs
nothing: its backend code is not imported and the browser never downloads its interface.

```
app/modules/weather/
├── __init__.py      manifest: what the module store shows and its options (always imported: keep it light)
├── api.py           setup(ctx) -> APIRouter (imported only when the module is on)
├── checks.py        optional: requirement checks for the "Comprobar requisitos" button
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

- **Cards** go into a slot of the status screen (`left`, `right` or `bottom`). `init` runs once, `show` when
  the status screen opens, `fast` every 5 s and `slow` every 30 s while it is visible.
- **A view** is an HTML fragment with a `<section class="view" data-view="<name>" hidden>`; with `tab` it also gets
  a button in the tab bar. It is reachable at `#<name>` (the module name, or `view.name`).
- **Hooking into other screens**: `/js/services.js` exports `addFilter`, `addHeader`, `addInfo`,
  `addSheetButton`, `onShow`, `current` and `reload` (the updates and backups modules use them), and `/js/ui.js`
  has the shared sheet (`openSheet`) and the output window (`openRunner`, `watchJob`).
- Import core helpers with absolute paths (`/js/api.js`) and your own files with relative ones (`./weather.js`).

The tests check that every module folder is complete (`tests/test_registry_modules.py`).
