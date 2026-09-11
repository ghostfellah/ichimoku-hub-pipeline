#!/usr/bin/env python3
"""
Étape 1 du pipeline Ichimoku Hub : détecte les nouvelles vidéos publiées dans
les dernières 24h (72h le lundi) sur les chaînes listées dans sources.yml,
et crée une ligne dans la base Notion "Vidéos — Sources" pour chacune,
si elle n'existe pas déjà (dédup sur "Vidéo ID").

Utilise UNIQUEMENT le listing "flat playlist" (avec l'option d'extracteur
youtubetab:approximate_date pour récupérer la date directement) — PAS
d'appel individuel par vidéo. Un appel complet par vidéo (yt-dlp
--print upload_date) se fait quasi systématiquement bloquer par YouTube
("Sign in to confirm you're not a bot") sur les IPs des runners GitHub
Actions, même avec des cookies ; le listing léger, lui, passe.
La date obtenue est approximative (arrondie au jour) mais suffisante pour
une fenêtre de 24h/72h.

Ne fait AUCUNE extraction de concepts : ça reste le travail de Claude, qui
lit ensuite les transcriptions produites par extract_transcripts.py.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys

import yaml

from notion_client import NotionClient, prop_date, prop_number, prop_rich_text, prop_select, prop_title, prop_url
from ytdlp_common import EXTRACTOR_ARGS, cookie_args

KEYWORDS = [
    "ichimoku", "kumo", "tenkan", "kijun", "chiko", "chikou", "sanyaku",
    "senkou", "senko", "kihon suchi", "taito suchi", "kts",
]


def run_ytdlp_json(url: str) -> dict | None:
    cmd = [
        "yt-dlp", "--flat-playlist", "--playlist-items", "1-10",
        *EXTRACTOR_ARGS,
        "--extractor-args", "youtubetab:approximate_date",
        *cookie_args(), "--dump-single-json", url,
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        print(f"  [!] timeout sur {url}", file=sys.stderr)
        return None
    if out.returncode != 0 or not out.stdout.strip():
        print(f"  [!] échec listing {url}: {out.stderr[:500]}", file=sys.stderr)
        return None
    try:
        return json.loads(out.stdout)
    except json.JSONDecodeError:
        return None


def parse_upload_date(entry: dict) -> str | None:
    """YYYYMMDD -> YYYY-MM-DD, ou None si absent/invalide."""
    raw = entry.get("upload_date")
    if not raw or not isinstance(raw, str) or len(raw) != 8:
        return None
    try:
        return f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}"
    except (IndexError, ValueError):
        return None


def parse_duration_min(entry: dict) -> float | None:
    duration = entry.get("duration")
    try:
        return round(float(duration) / 60, 1) if duration is not None else None
    except (ValueError, TypeError):
        return None


def pertinence_for(title: str) -> str:
    low = title.lower()
    return "🎯 Ichimoku" if any(k in low for k in KEYWORDS) else "📈 Trading général"


def load_sources() -> list[dict]:
    with open(os.path.join(os.path.dirname(__file__), "..", "sources.yml"), encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return cfg.get("channels", [])


def collect_candidates(sources: list[dict], cutoff_date: dt.date) -> list[dict]:
    kept: dict[str, dict] = {}
    for channel in sources:
        for tab_key in ("videos_url", "streams_url"):
            tab_url = channel.get(tab_key)
            if not tab_url:
                continue
            print(f"[*] Listing {channel['name']} ({tab_key}) ...")
            data = run_ytdlp_json(tab_url)
            if not data:
                continue
            entries = data.get("entries") or []
            for entry in entries:
                vid = entry.get("id")
                if not vid or vid in kept:
                    continue
                upload_date = parse_upload_date(entry)
                if not upload_date:
                    print(f"  [!] pas de date (approximate_date) pour {vid}, ignoré")
                    continue
                pub_date = dt.date.fromisoformat(upload_date)
                if pub_date < cutoff_date:
                    continue
                kept[vid] = {
                    "id": vid,
                    "title": entry.get("title") or "",
                    "upload_date": upload_date,
                    "duration_min": parse_duration_min(entry),
                    "source": channel["name"],
                }
    return list(kept.values())


def main() -> None:
    token = os.environ["NOTION_TOKEN"]
    data_source_id = os.environ["NOTION_VIDEOS_DATA_SOURCE_ID"]
    client = NotionClient(token)

    now = dt.datetime.now(dt.timezone.utc)
    window_hours = 72 if now.weekday() == 0 else 24  # lundi = 0
    cutoff_date = (now - dt.timedelta(hours=window_hours)).date()
    print(f"[*] Fenêtre : {window_hours}h -> cutoff {cutoff_date.isoformat()}")

    sources = load_sources()
    if not sources:
        print("[!] sources.yml vide ou introuvable.", file=sys.stderr)
        sys.exit(1)

    candidates = collect_candidates(sources, cutoff_date)
    print(f"[*] {len(candidates)} vidéo(s) candidate(s) dans la fenêtre.")

    if not candidates:
        print("SUMMARY: 0 nouvelle vidéo (aucune candidate dans la fenêtre).")
        return

    print("[*] Récupération des IDs déjà présents dans Notion ...")
    existing_ids = set()
    for row in client.query_data_source(data_source_id):
        vid_prop = row.get("properties", {}).get("Vidéo ID", {})
        text = "".join(p.get("plain_text", "") for p in vid_prop.get("rich_text", []))
        if text:
            existing_ids.add(text.strip())
    print(f"[*] {len(existing_ids)} vidéo(s) déjà en base.")

    created = 0
    today_iso = now.date().isoformat()
    for cand in candidates:
        if cand["id"] in existing_ids:
            continue
        props = {
            "Titre": prop_title(cand["title"] or cand["id"]),
            "Vidéo ID": prop_rich_text(cand["id"]),
            "URL": prop_url(f"https://www.youtube.com/watch?v={cand['id']}"),
            "Date de publication": prop_date(cand["upload_date"]),
            "Pertinence": prop_select(pertinence_for(cand["title"])),
            "Statut": prop_select("⏳ À traiter"),
            "Ajouté le": prop_date(today_iso),
        }
        if cand.get("duration_min") is not None:
            props["Durée (min)"] = prop_number(cand["duration_min"])
        client.create_page(data_source_id, props)
        created += 1
        print(f"  [+] {cand['id']} — {cand['title'][:70]}")

    print(f"SUMMARY: {created} nouvelle(s) vidéo(s) ajoutée(s) sur {len(candidates)} candidate(s).")


if __name__ == "__main__":
    main()
