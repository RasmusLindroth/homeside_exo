# HomeSide EXO for Home Assistant

A Home Assistant integration that reads data from **Regin ControllerWeb / HomeSide**
district heating substations (*fjärrvärmecentraler*) over the controller's local
EXOsocket WebSocket, and exposes the values as sensors.

- **Read-only.** The integration never writes anything to the controller.
- **Local polling.** No cloud, no MQTT broker, no extra server. Everything runs
  inside Home Assistant.
- **No extra dependencies.** Uses only libraries that ship with Home Assistant.

> This project is not affiliated with, endorsed by, or supported by Regin or
> HomeSide. Product names are used only to describe compatibility.

> **På svenska:** Integration som läser värden (temperaturer, tryck, börvärde,
> ventillägen m.m.) från en HomeSide-fjärrvärmecentral via regulatorns lokala
> webbgränssnitt. Endast läsning. Installeras via Home Assistant Marketplace
> → *Lägg till från länk* med `RasmusLindroth/homeside_exo`.

## Sensors

| Sensor | Unit |
|---|---|
| Heating system supply / return temperature (*Värmesystem framledning / retur*) | °C |
| Outdoor temperature (*Utegivare temperatur*) and sensor status | °C |
| Room temperature and desired room temperature / setpoint (*Önskad rumstemperatur*) | °C |
| Domestic hot water temperatures (*Varmvatten*) | °C |
| Heat meter temperature (*Värmemängdsmätare temp*) | °C |
| System pressure (*Systemtryck*) | bar |
| Valve and pump modes (Auto / Manual) | – |
| Wireless room sensor status and reception (diagnostic) | dB |
| Controller software version (diagnostic) | – |

Room sensors 2–5 and the district heating supply sensor are created as
**disabled entities**, since many installations don't have them. Enable them in
Home Assistant if you do.

The heat meter's instantaneous power (kW), flow and energy are **not** available:
the controller does not expose them as readable values.

## Supported controllers

Data point numbers are specific to the controller's application template. This
integration has been verified against:

- `MALL_FJV_Villa_2_244`

You can see your controller's template at `http://<controller-ip>/Controllers.json`.
During setup the integration checks the template and warns you if it's
different, because the sensors could then show the wrong values. If you have
another template and want to help add support, please open an issue.

## Requirements

- Home Assistant **2026.11** or newer to install via the Marketplace.
- Network access from Home Assistant to the controller.
- A local controller account. A **read-only account is recommended**: Home
  Assistant stores integration passwords in plain text in
  `config/.storage/core.config_entries`, like it does for every integration.

## Installation

### Home Assistant Marketplace

1. Go to **Settings → Marketplace**.
2. Select **Add from link** (upper right) and enter
   `RasmusLindroth/homeside_exo`. Adding a repository by link requires
   connecting Home Assistant to GitHub.
3. Open the repository and select **Install**.
4. Restart Home Assistant.

### Manual

Copy `custom_components/homeside_exo/` into your Home Assistant
`config/custom_components/` folder and restart Home Assistant.

## Configuration

**Settings → Devices & services → Add integration → HomeSide EXO**, then enter:

- the controller's IP address or hostname,
- user and password,
- update interval in seconds (default 60, minimum 15).

All sensors are grouped under a device called *Fjärrvärmecentral*.

- **Change the update interval:** select **Configure** on the integration.
- **New password:** when login stops working, Home Assistant asks you to log in
  again. You don't need to remove the integration.

## How it works

The controller's web interface talks to the controller over a WebSocket
(`ws://<host>/_EXOsocket/`). This integration uses the same protocol: a version
handshake, the same challenge/response login the web interface uses, and a
read of "indexed points". The point definitions are in
[`points.json`](custom_components/homeside_exo/points.json).

## Development

```bash
python3.13 -m venv .venv
.venv/bin/pip install -r requirements_test.txt
.venv/bin/pytest
```

The tests run the integration in a real Home Assistant test instance with the
controller replaced by a fake.

## License

[MIT](LICENSE)
