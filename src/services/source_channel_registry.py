"""DSA canonical source-channel registry.

This module is intentionally dependency-light.  The canonical policy lives in
``src/data/dsa_source_channels.json``; code should query this module rather than
copying provider/source lists into new call sites.

The registry is governance metadata, not an availability oracle: entries marked
``integrated_if_*`` are only usable when their existing adapter/configuration is
actually available at runtime.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence
from urllib.parse import urlsplit

CATALOG_PATH = Path(__file__).resolve().parents[1] / "data" / "dsa_source_channels.json"

_ALLOWED_NEWS_TIERS = {
    "N0_PRIMARY",
    "N1_WIRE",
    "N2_REGIONAL",
    "N3_AGGREGATOR",
    "N3_SEARCH_TRANSPORT",
    "N4_DISCOVERY_ONLY",
}
_ALLOWED_MARKET_TIERS = {
    "M0_ENTITLEMENT_LIVE",
    "M1_API_NEAR_REALTIME",
    "M1_PUBLIC_NEAR_REALTIME",
    "M2_GLOBAL_BACKUP",
    "M3_HISTORICAL_BACKUP",
}


class SourceChannelCatalogError(ValueError):
    """Raised when the canonical source-channel catalog is malformed."""


def _validate_unique_ids(rows: Sequence[Mapping[str, Any]], *, kind: str) -> None:
    seen = set()
    for row in rows:
        channel_id = str(row.get("id") or "").strip()
        if not channel_id:
            raise SourceChannelCatalogError(f"{kind} channel missing id")
        if channel_id in seen:
            raise SourceChannelCatalogError(f"duplicate {kind} channel id: {channel_id}")
        seen.add(channel_id)
        priority = row.get("priority")
        if not isinstance(priority, int) or priority < 0:
            raise SourceChannelCatalogError(
                f"{kind} channel {channel_id} has invalid priority: {priority!r}"
            )


def validate_source_channel_catalog(payload: Mapping[str, Any]) -> None:
    if payload.get("schema_version") != "1.0":
        raise SourceChannelCatalogError("unsupported source-channel schema_version")
    news = payload.get("news_channels")
    market = payload.get("market_channels")
    profiles = payload.get("runtime_profiles")
    governance = payload.get("governance")
    if not isinstance(news, list) or not isinstance(market, list):
        raise SourceChannelCatalogError("news_channels and market_channels must be lists")
    if not isinstance(profiles, dict) or not isinstance(governance, dict):
        raise SourceChannelCatalogError("runtime_profiles and governance must be objects")

    _validate_unique_ids(news, kind="news")
    _validate_unique_ids(market, kind="market")

    for row in news:
        if row.get("tier") not in _ALLOWED_NEWS_TIERS:
            raise SourceChannelCatalogError(
                f"news channel {row.get('id')} has invalid tier: {row.get('tier')!r}"
            )
    for row in market:
        if row.get("tier") not in _ALLOWED_MARKET_TIERS:
            raise SourceChannelCatalogError(
                f"market channel {row.get('id')} has invalid tier: {row.get('tier')!r}"
            )

    news_ids = {row["id"] for row in news}
    market_ids = {row["id"] for row in market}
    for profile_name in ("news_search_transport", "hk_news_evidence_preference"):
        for channel_id in profiles.get(profile_name, []):
            if channel_id not in news_ids:
                raise SourceChannelCatalogError(
                    f"runtime profile {profile_name} references unknown news id {channel_id}"
                )
    for channel_id in profiles.get("hk_realtime_default_existing", []):
        if channel_id not in market_ids:
            raise SourceChannelCatalogError(
                f"hk_realtime_default_existing references unknown market id {channel_id}"
            )


@lru_cache(maxsize=1)
def load_source_channel_catalog() -> Dict[str, Any]:
    with CATALOG_PATH.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    validate_source_channel_catalog(payload)
    return payload


def _by_id(kind: str) -> Dict[str, Dict[str, Any]]:
    key = "news_channels" if kind == "news" else "market_channels"
    return {row["id"]: dict(row) for row in load_source_channel_catalog()[key]}


def get_news_channel(channel_id: str) -> Optional[Dict[str, Any]]:
    return _by_id("news").get(str(channel_id).strip().lower())


def get_market_channel(channel_id: str) -> Optional[Dict[str, Any]]:
    return _by_id("market").get(str(channel_id).strip().lower())


def ordered_news_transport_ids(available_ids: Optional[Iterable[str]] = None) -> List[str]:
    """Return canonical search-transport order, optionally filtered by availability."""
    configured = list(load_source_channel_catalog()["runtime_profiles"]["news_search_transport"])
    if available_ids is None:
        return configured
    available = {str(value).strip().lower() for value in available_ids}
    return [channel_id for channel_id in configured if channel_id in available]


def news_channel_for_url(url: str) -> Optional[Dict[str, Any]]:
    """Classify a publisher URL by canonical domain; never treats aggregators as publishers."""
    try:
        host = (urlsplit(str(url)).hostname or "").lower().removeprefix("www.")
    except ValueError:
        return None
    if not host:
        return None
    candidates: List[tuple[int, Dict[str, Any]]] = []
    for row in load_source_channel_catalog()["news_channels"]:
        for domain in row.get("domains", []):
            normalized = str(domain).lower().removeprefix("www.")
            if host == normalized or host.endswith("." + normalized):
                candidates.append((len(normalized), dict(row)))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (-item[0], item[1]["priority"], item[1]["id"]))
    return candidates[0][1]


def news_evidence_rank(channel_id: str) -> int:
    """Smaller is stronger. Unknown channels sort last without being rejected."""
    channel = get_news_channel(channel_id)
    return int(channel["priority"]) if channel else 10_000


def market_channel_rank(channel_id: str) -> int:
    """Smaller is preferred by the catalog; runtime entitlements still govern usability."""
    channel = get_market_channel(channel_id)
    return int(channel["priority"]) if channel else 10_000


def hk_realtime_catalog_fallback() -> List[str]:
    return list(load_source_channel_catalog()["runtime_profiles"]["hk_realtime_default_existing"])


def resolve_market_priority(
    existing_priority: Sequence[str] | str | None,
    *,
    market: str,
) -> List[str]:
    """Resolve a safe priority chain without silently overriding runtime configuration.

    Existing explicit runtime configuration always wins.  The catalog supplies a
    fallback only when no chain was configured; today that fallback is defined for HK.
    """
    if isinstance(existing_priority, str):
        existing = [part.strip().lower() for part in existing_priority.split(",") if part.strip()]
    else:
        existing = [str(part).strip().lower() for part in (existing_priority or []) if str(part).strip()]
    if existing:
        return existing
    if str(market).strip().lower() == "hk":
        return hk_realtime_catalog_fallback()
    return []


def source_channel_governance() -> Dict[str, Any]:
    """Return a defensive copy of the shared evidence/news/market rules."""
    return json.loads(json.dumps(load_source_channel_catalog()["governance"]))


def source_channel_summary() -> Dict[str, Any]:
    payload = load_source_channel_catalog()
    news = payload["news_channels"]
    market = payload["market_channels"]
    return {
        "catalog_id": payload["catalog_id"],
        "schema_version": payload["schema_version"],
        "updated_at": payload["updated_at"],
        "news_channels": len(news),
        "market_channels": len(market),
        "news_integrated_or_conditional": sum(
            1 for row in news if str(row.get("status", "")).startswith("integrated")
        ),
        "market_integrated_or_conditional": sum(
            1 for row in market if str(row.get("status", "")).startswith("integrated")
        ),
    }


__all__ = [
    "CATALOG_PATH",
    "SourceChannelCatalogError",
    "get_market_channel",
    "get_news_channel",
    "hk_realtime_catalog_fallback",
    "load_source_channel_catalog",
    "market_channel_rank",
    "news_channel_for_url",
    "news_evidence_rank",
    "ordered_news_transport_ids",
    "resolve_market_priority",
    "source_channel_governance",
    "source_channel_summary",
    "validate_source_channel_catalog",
]
