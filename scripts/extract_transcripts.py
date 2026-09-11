#!/usr/bin/env python3
"""
Étape 2 (partie mécanique) du pipeline Ichimoku Hub : pour les vidéos en
backlog (Statut = "À traiter" + Pertinence = "Ichimoku"), télécharge les
sous-titres, les nettoie en texte brut, et les commit dans transcripts/.

Marque la ligne Notion "🔎 En cours" une fois la transcription prête —
c'est le signal pour la tâche planifiée Claude (qui a accès à Notion et au
repo GitHub) de faire l'extraction de concepts et la rédaction dans la base
"Concepts Ichimoku".

Si les sous-titres restent indisponibles après plusieurs essais, la ligne
est remise à "⏳ À traiter" pour être retentée au prochain run.
"""
from __future__ import annotations

import glob
import os
import random
import re
import subprocess
import sys
import tempfile
import time

from notion_client import NotionClient, get_plain_text, get_url, prop_select
from ytdlp_common import EXTRACTOR_ARGS, cookie_args

STATUT_A_TRAITER = "⏳ À traiter"
STATUT_EN_COURS = "🔎 En cours"
PERTINENCE_ICHIMOKU = "🎯 Ichimoku"

TRANSCRIPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "transcripts")


def clean_vtt(text: str) -> str:
    lines = text.splitlines()
    out: list[str] = []
    last = None
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if line.upper().startswith("WEBVTT"):
            continue
        if line.startswith(("Kind:", "Language:", "NOTE")):
            continue
        if "-->" in line:
            continue
        if re.fullmatch(r"\d+", line):
            continue
        line = re.sub(r"<[^>]+>", "", line).strip()
        if not line or line == last:
            continue
        out.append(line)
        last = line
    return "\n".join(out)


BACKOFF_SECONDS = [15, 30, 60, 90, 120]
INTER_VIDEO_DELAY = (10, 20)  # secondes, aléatoire, entre deux vidéos


def download_subtitles(video_id: str, url: str, attempts: int | None = None) -> str | None:
    """Télécharge les sous-titres (VTT) et renvoie le texte nettoyé, ou None."""
    attempts = attempts or len(BACKOFF_SECONDS)
    for attempt in range(1, attempts + 1):
        with tempfile.TemporaryDirectory() as tmp:
            out_template = os.path.join(tmp, f"{video_id}.%(ext)s")
            cmd = [
                "yt-dlp", "--skip-download", "--write-auto-sub", "--write-sub",
                "--sub-lang", "en", "--sub-format", "vtt",
                *EXTRACTOR_ARGS, *cookie_args(), "-o", out_template, url,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            vtt_files = glob.glob(os.path.join(tmp, "*.vtt"))
            if vtt_files:
                with open(vtt_files[0], encoding="utf-8", errors="ignore") as f:
                    return clean_vtt(f.read())
            stderr = result.stderr or ""
            if "429" in stderr or "Sign in to confirm" in stderr:
                if attempt >= attempts:
                    break
                wait = BACKOFF_SECONDS[attempt - 1]
                print(f"    [.] rate-limited, retry dans {wait}s ({attempt}/{attempts})")
                time.sleep(wait)
                continue
            # pas de sous-titres du tout (vidéo sans caption) -> inutile de retenter
            print(f"    [!] pas de sous-titres trouvés pour {video_id}: {stderr[:300]}")
            return None
    print(f"    [!] abandon après {attempts} tentative(s) rate-limitées pour {video_id}")
    return None


def main() -> None:
    token = os.environ["NOTION_TOKEN"]
    data_source_id = os.environ["NOTION_VIDEOS_DATA_SOURCE_ID"]
    limit = int(os.environ.get("TRANSCRIPT_LIMIT", "8"))
    client = NotionClient(token)

    os.makedirs(TRANSCRIPTS_DIR, exist_ok=True)

    filter_ = {
        "and": [
            {"property": "Statut", "select": {"equals": STATUT_A_TRAITER}},
            {"property": "Pertinence", "select": {"equals": PERTINENCE_ICHIMOKU}},
        ]
    }
    sorts = [{"property": "Date de publication", "direction": "descending"}]

    backlog = []
    for row in client.query_data_source(data_source_id, filter=filter_, sorts=sorts):
        backlog.append(row)
        if len(backlog) >= limit:
            break

    print(f"[*] {len(backlog)} vidéo(s) sélectionnée(s) pour extraction (limite={limit}).")

    done, failed = 0, 0
    for i, row in enumerate(backlog):
        if i > 0:
            pause = random.uniform(*INTER_VIDEO_DELAY)
            print(f"[.] pause {pause:.0f}s avant la prochaine vidéo ...")
            time.sleep(pause)
        props = row["properties"]
        page_id = row["id"]
        video_id = get_plain_text(props.get("Vidéo ID"))
        title = get_plain_text(props.get("Titre"))
        url = get_url(props.get("URL")) or f"https://www.youtube.com/watch?v={video_id}"

        if not video_id:
            print(f"  [!] ligne {page_id} sans Vidéo ID, ignorée")
            continue

        print(f"[*] {video_id} — {title[:70]}")
        client.update_page(page_id, {"Statut": prop_select(STATUT_EN_COURS)})

        text = download_subtitles(video_id, url)
        if not text or not text.strip():
            client.update_page(page_id, {"Statut": prop_select(STATUT_A_TRAITER)})
            failed += 1
            continue

        out_path = os.path.join(TRANSCRIPTS_DIR, f"{video_id}.txt")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(text)
        done += 1
        print(f"    [+] transcript.écrit ({len(text)} caractères) -> transcripts/{video_id}.txt")

    print(f"SUMMARY: {done} transcription(s) prête(s), {failed} échec(s) (remises en file).")


if __name__ == "__main__":
    main()
