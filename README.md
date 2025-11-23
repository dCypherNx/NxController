# NxController

Custom component for Home Assistant that connects to OpenWrt-based routers and access points over SSH. Each configured router/AP exposes one sensor per detected client (wired or wireless) using DHCP leases, ARP/neighbour tables, and Wi-Fi association lists. The integration supports mapping randomized MAC addresses to stable device identifiers via the `nx_controller.map_mac` service and raises `nx_controller.new_mac_detected` events for new clients.

## Installation

Install via [HACS](https://hacs.xyz/) by adding this repository as a custom integration or by copying the `custom_components/nx_controller` folder into your Home Assistant configuration directory.

## Configuration

Add NxController through the Home Assistant UI. Required fields:

- **Alias**: Friendly name for the router/AP (must be unique per integration instance).
- **Host/Port**: SSH endpoint (default port 22).
- **Username/Password**: SSH credentials.
- **Is DHCP server**: If enabled, DHCPv4/v6 leases will be merged with connected clients so offline devices still appear.

During setup the integration validates SSH connectivity using a simple command.

## Entities

For each known client, the integration creates a sensor whose state is `online` or `offline`. Attributes include MAC address, IP information, hostname, interface, connection type, signal strength when available, traffic counters (if provided by the device), the router alias, DHCP source, and the last seen timestamp.

## Handling randomized MAC addresses

When a new MAC address is seen, the integration emits an `nx_controller.new_mac_detected` event. Use the `nx_controller.map_mac` service to associate the new MAC with an existing primary MAC so that the sensor unique ID remains stable.

## Services

- `nx_controller.map_mac`: Map an alternate MAC address to an existing primary MAC for a specific router alias, persisting the association.
