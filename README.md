# Nx Controller

Custom Home Assistant integration that aggregates device presence and metadata from OpenWrt routers and SSH-accessible access points.

## Setup
1. In Home Assistant, go to **Settings → Devices & Services → Add Integration** and choose **Nx Controller**.
2. Provide the connection details requested by the wizard:
   - **Host or IP**, **Username**, and **Password** of your OpenWrt controller or SSH-capable access point.
   - Optional TLS verification (for ubus) or SSH parameters (port and commands) depending on the chosen source type.
   - An optional custom name for each source and the desired update interval.
3. After the first source is validated you can add additional sources before finishing the flow.

If the dialog does not prompt for host/username/password, ensure the integration is up to date and re-open the setup from the Integrations page.
