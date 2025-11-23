from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .api import _normalize_mac
from .const import DOMAIN

STORAGE_VERSION = 1
STORAGE_KEY_TEMPLATE = f"{DOMAIN}_known_devices_{{entry_id}}"


async def _load_known_devices(hass: HomeAssistant, entry_id: str) -> dict[str, Any]:
    """Load persisted known device mappings."""

    store = Store(hass, STORAGE_VERSION, STORAGE_KEY_TEMPLATE.format(entry_id=entry_id))
    stored = await store.async_load() or {}

    normalized_devices: dict[str, dict[str, list[str]]] = {}
    for primary_mac, info in (stored.get("devices") or {}).items():
        normalized_primary = _normalize_mac(primary_mac)
        if not normalized_primary:
            continue

        macs: list[str] = []
        for mac in info.get("macs", []):
            normalized_mac = _normalize_mac(mac)
            if normalized_mac and normalized_mac not in macs:
                macs.append(normalized_mac)

        if normalized_primary not in macs:
            macs.insert(0, normalized_primary)

        normalized_devices[normalized_primary] = {"macs": macs}

    pending: list[str] = []
    for mac in stored.get("pending") or []:
        normalized_mac = _normalize_mac(mac)
        if not normalized_mac:
            continue
        if normalized_mac in normalized_devices:
            continue
        if normalized_mac not in pending:
            pending.append(normalized_mac)

    return {"devices": normalized_devices, "pending": pending}


async def _save_known_devices(
    hass: HomeAssistant, entry_id: str, known_devices: dict[str, Any]
) -> None:
    """Persist known devices mapping."""

    store = Store(hass, STORAGE_VERSION, STORAGE_KEY_TEMPLATE.format(entry_id=entry_id))
    await store.async_save(
        {
            "devices": known_devices.get("devices", {}),
            "pending": known_devices.get("pending", []),
        }
    )


def _find_primary_mac(mac: str | None, known_devices: dict[str, Any]) -> str | None:
    """Return the primary MAC for a known device mapping."""

    normalized_mac = _normalize_mac(mac)
    if not normalized_mac:
        return None

    devices = known_devices.get("devices", {})
    if normalized_mac in devices:
        return normalized_mac

    for primary_mac, info in devices.items():
        if normalized_mac in info.get("macs", []):
            return primary_mac

    return None


def _register_secondary_mac(
    primary_mac: str, new_mac: str, known_devices: dict[str, Any]
) -> bool:
    """Associate a new MAC with an existing primary device."""

    normalized_primary = _normalize_mac(primary_mac)
    normalized_new = _normalize_mac(new_mac)

    if not normalized_primary or not normalized_new:
        return False

    devices = known_devices.setdefault("devices", {})
    pending = known_devices.setdefault("pending", [])

    device_entry = devices.setdefault(normalized_primary, {"macs": [normalized_primary]})
    changed = False

    if normalized_primary not in device_entry["macs"]:
        device_entry["macs"].insert(0, normalized_primary)
        changed = True

    if normalized_new not in device_entry["macs"]:
        device_entry["macs"].append(normalized_new)
        changed = True

    if normalized_new in pending:
        pending.remove(normalized_new)
        changed = True

    if normalized_primary in pending:
        pending.remove(normalized_primary)
        changed = True

    for primary, info in list(devices.items()):
        if primary == normalized_primary:
            continue
        if normalized_new in info.get("macs", []):
            info["macs"] = [mac for mac in info["macs"] if mac != normalized_new]
            changed = True
            if not info["macs"]:
                devices.pop(primary)

    return changed


def _merge_device_entries(target: dict[str, Any], source: dict[str, Any]) -> None:
    """Merge device payloads onto the same primary mapping."""

    for key in ("interfaces", "radios", "ipv4_addresses", "ipv6_addresses"):
        existing = set(target.get(key) or [])
        incoming = set(source.get(key) or [])
        if incoming - existing:
            target[key] = sorted(existing | incoming)

    if source.get("state") and not target.get("state"):
        target["state"] = source["state"]

    if source.get("host") and not target.get("host"):
        target["host"] = source["host"]

    if source.get("name") and not target.get("name"):
        target["name"] = source["name"]

    existing_macs = set(target.get("mac_addresses") or [])
    incoming_macs = set(source.get("mac_addresses") or [])
    macs_combined = existing_macs | incoming_macs
    if macs_combined != existing_macs:
        target["mac_addresses"] = sorted(macs_combined)

    existing_connections = target.get("connections") or []
    incoming_connections = source.get("connections") or []
    seen = {tuple(sorted(conn.items())) for conn in existing_connections}
    for conn in incoming_connections:
        normalized = tuple(sorted(conn.items()))
        if normalized in seen:
            continue
        seen.add(normalized)
        existing_connections.append(conn)
    target["connections"] = existing_connections


def consolidate_devices(
    devices: dict[str, Any], known_devices: dict[str, Any]
) -> tuple[dict[str, Any], bool]:
    """Consolidate devices using the known devices mapping.

    Returns the consolidated devices payload and a flag indicating whether
    the known devices mapping changed (e.g., new pending MACs were recorded).
    """

    consolidated: dict[str, Any] = {}
    pending = known_devices.setdefault("pending", [])
    devices_map = known_devices.setdefault("devices", {})
    dirty = False
    bootstrap = not devices_map and not pending

    for mac, device in devices.items():
        normalized_mac = _normalize_mac(mac)
        if not normalized_mac:
            continue

        primary_mac = _find_primary_mac(normalized_mac, known_devices)
        if not primary_mac:
            if bootstrap:
                _register_secondary_mac(normalized_mac, normalized_mac, known_devices)
                primary_mac = normalized_mac
                dirty = True
            else:
                if normalized_mac not in pending:
                    pending.append(normalized_mac)
                    dirty = True
                continue

        primary_key = primary_mac.lower()
        known_macs = devices_map.get(primary_mac, {}).get("macs", [])
        mac_candidates = {primary_key}
        mac_candidates.update({m.lower() for m in known_macs})
        mac_candidates.update({m.lower() for m in device.get("mac_addresses", [])})

        device_payload = {**device}
        device_payload["primary_mac"] = primary_key
        device_payload["mac_addresses"] = sorted(mac_candidates)

        existing = consolidated.get(primary_key)
        if existing:
            _merge_device_entries(existing, device_payload)
        else:
            consolidated[primary_key] = device_payload

    return consolidated, dirty
