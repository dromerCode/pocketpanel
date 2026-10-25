"""Qué es un módulo. Cada uno es una carpeta en app/modules/<nombre>/ con:

  __init__.py   MODULE = Module(...): lo que enseña la tienda y sus opciones. Se importa siempre: que sea ligero.
  api.py        setup(ctx) -> APIRouter. Solo se importa si el módulo está activo.
  checks.py     opcional, para «Comprobar requisitos»: script(values) -> (script, etiquetas) que se ejecuta en el
                host y/o async http_checks(values, http) -> [comprobación].
  web/index.js  opcional: su parte de la interfaz (pestaña, tarjetas en Estado…). El navegador solo la descarga
                si el módulo está activo. Ver web/js/registry.js.

El nombre del módulo es el de la carpeta. Para añadir uno basta con crear la carpeta: no hay listas que tocar.
"""
import copy
from dataclasses import dataclass, field as dc_field

TYPES = ("bool", "str", "int", "time", "list", "choice", "secret")


def field(key, label, type="str", help="", default=None, **kw) -> dict:
    """Una opción del módulo: sale en su formulario y, salvo las `secret` (van a data/secrets.json), en config.yml.

    `default` es el valor por defecto (y su tipo, el que se exige en config.yml). Extras: `choices` (choice),
    `nullable` (time: admite null) y `required` (no puede quedar vacía si el módulo está activo)."""
    if type not in TYPES:
        raise ValueError(f"{key}: tipo desconocido {type!r}")
    if type == "secret":
        default = None
    elif default is None:
        default = {"bool": False, "int": 0, "list": []}.get(type, "")
    return {"key": key, "label": label, "type": type, "help": help, "default": default, **kw}


@dataclass(frozen=True)
class Module:
    icon: str
    title: str
    desc: str
    fields: list = dc_field(default_factory=list)
    enabled: bool = False     # activado en una instalación nueva
    order: int = 100          # posición en la tienda y en las pestañas
    after: tuple = ()         # módulos que deben cargarse antes (dejan en ctx algo que este usa al arrancar)
    name: str = ""            # lo pone el registro: el nombre de la carpeta

    def defaults(self) -> dict:
        return {"enabled": self.enabled,
                **{f["key"]: copy.deepcopy(f["default"]) for f in self.fields if f["type"] != "secret"}}

    def secret_keys(self) -> set:
        return {f["key"] for f in self.fields if f["type"] == "secret"}

    def field(self, key: str) -> dict | None:
        return next((f for f in self.fields if f["key"] == key), None)

    def catalog(self) -> dict:
        """Lo que necesita la tienda de módulos para pintarlo."""
        return {"icon": self.icon, "title": self.title, "desc": self.desc, "fields": self.fields}
