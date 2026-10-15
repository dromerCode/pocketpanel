import subprocess

from app.rootconf import render

OPTS = {"source": "/srv/appdata", "dest": "bk@nas:/backups/pp", "ssh_key": "/home/r/.ssh/id_bk",
        "ssh_options": "-p 2222", "keep_days": 5, "excludes": ["cache/", "*.log"]}


def test_render_conf_uses_root_copies_of_key_and_known_hosts():
    conf = render(OPTS)
    out = subprocess.run(["bash", "-c", conf + '\nprintf "%s|" "$SRC" "$DEST_HOST" "$DEST_PATH" "$KEEP_DAYS" '
                          '"$EXCLUDES_FILE" "$SSH_OPTS"'], capture_output=True, text=True, check=True).stdout
    src, host, path, keep, excl, ssh, _ = out.split("|")
    assert (src, host, path, keep, excl) == ("/srv/appdata/", "bk@nas", "/backups/pp", "5",
                                             "/etc/pocketpanel/excludes.txt")
    assert "-i /etc/pocketpanel/id_backup" in ssh and "/home/r" not in ssh
    assert "UserKnownHostsFile=/etc/pocketpanel/known_hosts" in ssh and "-p 2222" in ssh


def test_render_without_key():
    assert "id_backup" not in render({**OPTS, "ssh_key": ""})


def test_user_ssh_options_win_over_defaults():
    # ssh se queda con el primer valor de cada opción: las del usuario van delante
    conf = render({**OPTS, "ssh_options": "-o UserKnownHostsFile=/srv/kh"})
    out = subprocess.run(["bash", "-c", conf + '\nprintf "%s" "$SSH_OPTS"'], capture_output=True, text=True,
                         check=True).stdout
    assert out.index("UserKnownHostsFile=/srv/kh") < out.index("UserKnownHostsFile=/etc/pocketpanel/known_hosts")
