from __future__ import annotations
import asyncio
_dirty_assets: set[str] = set()
_update_event = asyncio.Event()
def mark_asset_dirty(asset: str) -> None:
    _dirty_assets.add(asset)
    _update_event.set()
async def wait_for_updates() -> None:
    await _update_event.wait()
def take_dirty_assets() -> set[str]:
    assets = set(_dirty_assets)
    _dirty_assets.clear()
    _update_event.clear()
    return assets
