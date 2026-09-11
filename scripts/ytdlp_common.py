"""Args yt-dlp partagés entre detect_new_videos.py et extract_transcripts.py."""
from __future__ import annotations

import os

EXTRACTOR_ARGS = ["--extractor-args", "youtube:player_client=android"]


def cookie_args() -> list[str]:
    """Renvoie ["--cookies", <chemin>] si un fichier de cookies YouTube est
    disponible (variable d'env YT_COOKIES_FILE), sinon [].

    Sans cookies, YouTube bloque/rate-limit très vite les IPs des runners
    GitHub Actions (erreurs 429 / "Sign in to confirm you're not a bot") dès
    qu'on dépasse le simple listing flat-playlist — c'est ce qui provoque des
    runs "verts" qui ne produisent rien. Voir README.md.
    """
    path = os.environ.get("YT_COOKIES_FILE")
    if path and os.path.isfile(path) and os.path.getsize(path) > 0:
        return ["--cookies", path]
    return []
