"""
Petit client Notion minimal pour le pipeline Ichimoku Hub.

Utilise le modèle "data source" de l'API Notion (Notion-Version 2026-03-11) :
- interroger une base       -> PATCH /v1/data_sources/{data_source_id}/query
- créer une page            -> POST  /v1/pages   (parent = {"type": "data_source_id", ...})
- mettre à jour une page    -> PATCH /v1/pages/{page_id}
"""
from __future__ import annotations

import os
import time
from typing import Any, Iterator

import requests

NOTION_VERSION = "2026-03-11"
API_BASE = "https://api.notion.com/v1"


class NotionClient:
    def __init__(self, token: str | None = None):
        self.token = token or os.environ["NOTION_TOKEN"]
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {self.token}",
                "Notion-Version": NOTION_VERSION,
                "Content-Type": "application/json",
            }
        )

    def _request(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        url = f"{API_BASE}{path}"
        for attempt in range(5):
            resp = self.session.request(method, url, timeout=30, **kwargs)
            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", "2"))
                time.sleep(wait + 1)
                continue
            if resp.status_code >= 400:
                raise RuntimeError(
                    f"Notion API {method} {path} -> {resp.status_code}: {resp.text[:800]}"
                )
            return resp.json()
        raise RuntimeError(f"Notion API {method} {path}: trop de 429, abandon")

    def query_data_source(
        self,
        data_source_id: str,
        filter: dict | None = None,
        sorts: list[dict] | None = None,
        page_size: int = 100,
    ) -> Iterator[dict[str, Any]]:
        """Itère sur TOUTES les pages résultat (pagination automatique)."""
        body: dict[str, Any] = {"page_size": page_size}
        if filter:
            body["filter"] = filter
        if sorts:
            body["sorts"] = sorts
        cursor = None
        while True:
            if cursor:
                body["start_cursor"] = cursor
            data = self._request(
                "PATCH", f"/data_sources/{data_source_id}/query", json=body
            )
            for row in data.get("results", []):
                yield row
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")

    def create_page(self, data_source_id: str, properties: dict) -> dict:
        body = {
            "parent": {"type": "data_source_id", "data_source_id": data_source_id},
            "properties": properties,
        }
        return self._request("POST", "/pages", json=body)

    def update_page(self, page_id: str, properties: dict) -> dict:
        return self._request("PATCH", f"/pages/{page_id}", json={"properties": properties})


# ---- Helpers de (dé)sérialisation de propriétés -----------------------------


def prop_title(text: str) -> dict:
    return {"title": [{"text": {"content": text[:2000]}}]}


def prop_rich_text(text: str) -> dict:
    return {"rich_text": [{"text": {"content": text[:2000]}}]}


def prop_url(url: str) -> dict:
    return {"url": url}


def prop_number(value: float | int | None) -> dict:
    return {"number": value}


def prop_select(name: str) -> dict:
    return {"select": {"name": name}}


def prop_date(iso_date: str) -> dict:
    return {"date": {"start": iso_date}}


def get_plain_text(prop: dict | None) -> str:
    """Extrait le texte brut d'une propriété title/rich_text Notion."""
    if not prop:
        return ""
    for key in ("title", "rich_text"):
        if key in prop:
            return "".join(part.get("plain_text", "") for part in prop[key])
    return ""


def get_select_name(prop: dict | None) -> str | None:
    if not prop or not prop.get("select"):
        return None
    return prop["select"].get("name")


def get_url(prop: dict | None) -> str | None:
    if not prop:
        return None
    return prop.get("url")
