from ...module import Module, field

MODULE = Module(
    icon="↓", title="Descargas",
    desc="qBittorrent, Sonarr y Radarr: descargas activas, pausar, cola y próximos estrenos, con avisos.",
    order=80,
    fields=[
        field("qbittorrent_url", "URL de qBittorrent", help="p. ej. http://127.0.0.1:8080. Vacío = sin qBittorrent"),
        field("qbittorrent_user", "Usuario de qBittorrent", "secret"),
        field("qbittorrent_pass", "Contraseña de qBittorrent", "secret"),
        field("sonarr_url", "URL de Sonarr", help="Vacío = sin Sonarr"),
        field("sonarr_key", "API key de Sonarr", "secret", "Sonarr → Settings → General"),
        field("radarr_url", "URL de Radarr", help="Vacío = sin Radarr"),
        field("radarr_key", "API key de Radarr", "secret", "Radarr → Settings → General"),
        field("notify_finished", "Avisar cuando termine una descarga", "bool", default=True),
    ],
)
