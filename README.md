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
1. Update `custom_components/nx_controller/manifest.json` with the new semantic version in the PR that introduces the change.
2. Merge the PR into `main`.
3. The **Tag latest main** workflow will read the manifest version and automatically create a tag (for example, `v0.2.5`) on the merge commit when that tag does not already exist.
4. The tag triggers the **Release** workflow, which builds a ZIP archive containing `custom_components`, `README.md`, and `hacs.json`, then publishes the release that HACS can consume.

## Configuration
1. In Home Assistant, go to **Settings → Devices & Services → Add Integration** and search for **Nx Controller**.
2. Add a source and set the update interval for the integration:
   - **ubus/OpenWrt**: Provide host, username, password, and SSL preferences.
   - **SSH AP**: Provide host, username, password, and (optionally) port.
3. After the first source is validated you can add as many additional sources as needed before finishing the flow; attributes are merged when the same MAC is observed from multiple inputs.
4. SSH sources default to discovery commands that start with `iw dev` to list interfaces and then probe each one (e.g., `iwinfo {iface} assoclist`, `iw dev {iface} station dump`).
   - You can set a preferred command and/or supply a custom list (one per line). The integration will try each command in order until it collects data.
5. You can revisit the integration options later to adjust the update interval without recreating the sources.

## Entity Behavior
- Each discovered MAC address yields one device tracker entity.
- Entity attributes include merged details from every source plus a `sources` list indicating contributors.
- Entities are identified by the first MAC discovered and persist across updates.
