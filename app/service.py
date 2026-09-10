"""Wires the portal client, the TTL caches, and the in-memory index together.

This is the one object routers depend on. It owns *when* to refetch from
the portal; routers just ask for "the current meter index" and get either
a cached copy or a freshly refreshed one.
"""
from __future__ import annotations

from app.cache import KeyedTTLCache, TTLCache
from app.config import Settings
from app.consumption import build_consumption
from app.index import MeterIndex, build_hierarchy_tree, build_transformers
from app.models import HealthStatus, HierarchyTree, MeterConsumption, Transformer
from app.portal_client import PortalClient


class UrjaService:
    def __init__(self, settings: Settings, portal: PortalClient | None = None):
        self._settings = settings
        self.portal = portal or PortalClient(settings)
        self._meters_cache: TTLCache[MeterIndex] = TTLCache(settings.meters_cache_ttl_seconds)
        self._transformers_cache: TTLCache[list[dict]] = TTLCache(settings.transformers_cache_ttl_seconds)
        self._energy_cache: KeyedTTLCache[list[dict]] = KeyedTTLCache(settings.energy_cache_ttl_seconds)

    async def aclose(self) -> None:
        await self.portal.aclose()

    async def meter_index(self) -> MeterIndex:
        return await self._meters_cache.get(self._load_meter_index)

    async def _load_meter_index(self) -> MeterIndex:
        raw = await self.portal.fetch_all_meters()
        return MeterIndex(raw)

    async def transformers(self) -> list[Transformer]:
        raw_dts = await self._transformers_cache.get(self.portal.fetch_all_transformers)
        index = await self.meter_index()
        return build_transformers(raw_dts, index)

    async def transformer(self, code: str) -> Transformer | None:
        for t in await self.transformers():
            if t.code == code:
                return t
        return None

    async def hierarchy(self) -> HierarchyTree:
        index = await self.meter_index()
        return build_hierarchy_tree(index)

    async def consumption(self, meter_id: str) -> MeterConsumption:
        raw = await self._energy_cache.get(meter_id, lambda: self.portal.fetch_meter_energy(meter_id))
        return build_consumption(meter_id, raw)

    async def health(self) -> HealthStatus:
        portal_reachable = True
        try:
            await self.meter_index()
        except Exception:
            portal_reachable = False
        return HealthStatus(
            status="ok" if portal_reachable else "degraded",
            portal_reachable=portal_reachable,
            session_active=self.portal.session_active(),
            meters_cache_age_seconds=self._meters_cache.age_seconds(),
            transformers_cache_age_seconds=self._transformers_cache.age_seconds(),
        )
