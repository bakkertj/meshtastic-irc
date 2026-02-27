# Meshtastic-IRC Bridge

A bidirectional bridge between Meshtastic mesh networks and IRC channels.

See [USERGUIDE.md](USERGUIDE.md) for complete documentation.

## Features

- Bidirectional message relay between Meshtastic and IRC
- Multiple channel mappings (mesh channel index -> IRC channel)
- Rate limiting to prevent flooding the mesh network
- Node name resolution (shows human-readable names instead of IDs)
- Signal quality display (SNR/RSSI)
- Configurable message formatting

## Requirements

- Python 3.10+
- A Meshtastic node connected via USB, TCP, or BLE
- Access to an IRC server

## Installation

```bash
# Clone or copy this directory
cd meshtastic-irc

# Create virtual environment (recommended)
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

## Configuration

Copy and edit the config file:

```bash
cp config.yaml my-config.yaml
# Edit my-config.yaml with your settings
```

Key configuration options:

```yaml
irc:
  server: "irc.libera.chat"
  port: 6667
  nickname: "meshbridge"

meshtastic:
  connection: "serial"      # or "tcp"
  device: "/dev/ttyUSB0"    # for serial
  # host: "192.168.1.100"   # for tcp
  # port: 4403              # for tcp

channels:
  0: "#meshtastic-primary"  # mesh channel 0 -> IRC #meshtastic-primary
  1: "#meshtastic-aux"      # mesh channel 1 -> IRC #meshtastic-aux
```

## Usage

```bash
# Run with default config.yaml
python bridge.py

# Run with custom config
python bridge.py -c my-config.yaml
```

## How It Works

```
Meshtastic Network          Bridge                    IRC Network
     ┌─────┐                  │                         ┌─────┐
     │Node1│ ──── LoRa ────►  │  ──── TCP ────────────► │ IRC │
     └─────┘                  │                         │ Srv │
     ┌─────┐                  │                         └─────┘
     │Node2│ ◄─── LoRa ─────  │  ◄─── TCP ─────────────    │
     └─────┘                  │                            │
        │                     │                         ┌─────┐
     ┌─────┐               ┌─────┐                      │Users│
     │T-Deck│◄────────────►│Pi/PC│                      └─────┘
     └─────┘  USB/TCP/BLE  └─────┘
```

1. **Mesh → IRC**: Messages received from the mesh are forwarded to the mapped IRC channel
2. **IRC → Mesh**: Messages from IRC are rate-limited and sent to the appropriate mesh channel

## Rate Limiting

The mesh network is bandwidth-constrained (~1 message per second recommended). The bridge implements:

- Token bucket rate limiting (configurable messages per minute)
- Optional message queue for overflow
- Automatic message truncation to fit mesh packet size

## Running as a Service

Create a systemd service file `/etc/systemd/system/mesh-irc.service`:

```ini
[Unit]
Description=Meshtastic IRC Bridge
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/meshtastic-irc
ExecStart=/home/pi/meshtastic-irc/venv/bin/python bridge.py -c config.yaml
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Then:

```bash
sudo systemctl enable mesh-irc
sudo systemctl start mesh-irc
```

## Troubleshooting

### Can't connect to Meshtastic device

- Check device path: `ls /dev/ttyUSB*` or `ls /dev/ttyACM*`
- Ensure user has permission: `sudo usermod -a -G dialout $USER`
- For TCP: ensure device has WiFi enabled and is on the same network

### IRC connection issues

- Check firewall allows outgoing connections on port 6667 (or 6697 for SSL)
- Some networks block IRC; try a different server

### Messages not appearing

- Check channel mappings in config
- Enable DEBUG logging to see all traffic
- Ensure both connections show as established in logs

## License

MIT License - feel free to modify and redistribute.
