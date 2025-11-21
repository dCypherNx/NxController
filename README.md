# Nx Controller

Custom Home Assistant integration that aggregates device presence and metadata from OpenWrt (ubus) routers and SSH-accessible access points.

## Features
- Polls one or more sources and merges device details by MAC address so attributes enrich each other.
- Supports native OpenWrt ubus endpoints and generic APs reachable via SSH.
- Provides device tracker entities with MAC-based unique IDs and attributes such as interface, signal, RX/TX metrics, and contributing sources.

## Installation
1. Ensure [HACS](https://hacs.xyz/) is installed.
2. Add this repository as a custom integration in HACS.
3. Install **Nx Controller** and restart Home Assistant.

## Release flow
1. Update `custom_components/nx_controller/manifest.json` with the new semantic version.
2. Commit the change and push it to the default branch.
3. Tag the commit with the same version prefixed by `v` (for example, `v0.2.5`) and push the tag.
4. GitHub Actions will build a ZIP archive containing `custom_components`, `README.md`, and `hacs.json`, then publish a release that HACS can consume.

## Configuration
1. In Home Assistant, go to **Settings → Devices & Services → Add Integration** and search for **Nx Controller**.
2. Add at least one source:
   - **ubus/OpenWrt**: Provide host, username, password, and SSL preferences.
   - **SSH AP**: Provide host, username, password, and (optionally) port.
3. SSH sources default to discovery commands that start with `iw dev` to list interfaces and then probe each one (e.g., `iwinfo {iface} assoclist`, `iw dev {iface} station dump`).
   - You can set a preferred command and/or supply a custom list (one per line). The integration will try each command in order until it collects data.
4. Optionally add multiple sources; device attributes merge when the same MAC is found.
5. Adjust the update interval in the options flow if needed.

## Entity Behavior
- Each discovered MAC address yields one device tracker entity.
- Entity attributes include merged details from every source plus a `sources` list indicating contributors.
- Entities are identified by the first MAC discovered and persist across updates.
