# Meshtastic-IRC Bridge User Guide

## Overview

This software bridges Meshtastic mesh networks to IRC channels. Messages sent on mesh appear in IRC, and messages sent in IRC appear on mesh devices.

The bridge supports two modes:
- **Relay mode**: A single IRC bot relays all mesh messages
- **Puppet mode**: Each mesh node appears as a separate IRC user

## Requirements

- Python 3.10 or later
- A Meshtastic-compatible device (T-Deck, T-Beam, etc.)
- Connection to the device via USB serial, TCP, or BLE
- Access to an IRC server

## Installation

```bash
cd meshtastic-irc
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Configuration

Copy `config.yaml` and edit as needed:

```bash
cp config.yaml my-config.yaml
```

### Required Settings

**IRC Connection**

```yaml
irc:
  server: "irc.libera.chat"
  port: 6667
  ssl: false
  nickname: "meshbridge"
```

**Meshtastic Connection**

For USB serial:
```yaml
meshtastic:
  connection: "serial"
  device: "/dev/ttyUSB0"
```

For TCP (device with WiFi):
```yaml
meshtastic:
  connection: "tcp"
  host: "192.168.1.100"
  port: 4403
```

**Channel Mapping**

Map mesh channel indices to IRC channels:
```yaml
channels:
  0: "#meshtastic-primary"
  1: "#meshtastic-secondary"
```

### Optional Settings

**Bridge Mode**

```yaml
mode: "puppet"  # or "relay"
```

In puppet mode, set the nickname prefix:
```yaml
irc:
  puppet_prefix: "mesh_"
```

**Direct Message Channel**

Messages sent directly to the gateway node appear in this channel:
```yaml
dm_channel: "#meshtastic-dm"
```

**Rate Limiting**

Mesh networks have limited bandwidth. Configure rate limiting:
```yaml
rate_limit:
  mesh_max_per_minute: 10
  queue_overflow: true
```

**Message Formatting**

Used in relay mode only:
```yaml
formatting:
  mesh_to_irc: "[{node_name}] {message}"
  irc_to_mesh: "<{nick}> {message}"
  show_signal: true
```

## Running the Bridge

```bash
python bridge.py -c my-config.yaml
```

To run in background:
```bash
nohup python bridge.py -c my-config.yaml &
```

## Modes of Operation

### Relay Mode

All mesh messages come from a single IRC bot:

```
IRC channel:
<meshbridge> [Alice] Hello from the trail
<meshbridge> [Bob] Weather is clear here
<dave> Received, thanks
```

### Puppet Mode

Each mesh node gets its own IRC identity:

```
IRC channel:
<mesh_Alice> Hello from the trail
<mesh_Bob> Weather is clear here
<dave> Received, thanks
```

Puppet connections are created on demand and disconnected after one hour of inactivity.

## Commands for Mesh Users

Mesh users can send commands by starting a message with `/`. Commands are processed by the bridge and not forwarded to IRC (except where noted).

### IRC Commands

| Command | Usage | Description |
|---------|-------|-------------|
| /me | `/me <action>` | Send action to IRC. Appears as `* mesh_Alice <action>` |
| /msg | `/msg <nick> <message>` | Send private message to IRC user |
| /names | `/names` | List mesh users in the bridged channel |
| /topic | `/topic` | Display channel topic |
| /ping | `/ping` | Display bridge status and uptime |

### Mesh Commands

| Command | Usage | Description |
|---------|-------|-------------|
| /nodes | `/nodes` | List known mesh nodes with last-heard times |
| /signal | `/signal` | Show signal strength for nearby nodes |
| /signal | `/signal <name>` | Show signal strength for specific node |
| /pos | `/pos` | Share GPS coordinates to IRC channel |
| /help | `/help` | List available commands |

### Command Examples

```
Mesh user sends:     Bridge response or IRC action:
----------------     -----------------------------
/ping                "Pong! Up 2h15m | IRC: connected | Nodes: 8"
/nodes               "Nodes: Alice(5m), Bob(20m), Carol(2h)"
/signal              "Signal: Alice:12dB, Bob:8dB"
/signal alice        "Alice: SNR:12.3dB RSSI:-89dBm"
/me waves            IRC: * mesh_User waves
/msg dave hello      IRC DM to dave: "hello"
/pos                 IRC: "[User shared location: 52.3701N, 4.8952E] https://..."
```

## Message Flow

### Mesh to IRC

1. Mesh node transmits message
2. Gateway node receives message via LoRa
3. Bridge reads message from gateway via serial/TCP
4. Bridge checks for commands (messages starting with `/`)
5. If command: process and send reply to mesh user
6. If regular message: forward to mapped IRC channel

### IRC to Mesh

1. IRC user sends message to bridged channel
2. Bridge receives message via IRC connection
3. Bridge formats message with sender's nick
4. Bridge sends to mesh network (rate limited)
5. All mesh nodes on that channel receive the message

## Direct Messages

### Mesh User to IRC User

Use `/msg`:
```
/msg dave Are you receiving this?
```

In puppet mode, this sends a PM from `mesh_YourName` to `dave`.
In relay mode, this sends a PM from `meshbridge` with attribution.

### IRC User to Mesh Network

IRC users send to the channel. All mesh users on that channel receive the message.

Direct messaging from IRC to a specific mesh node is not supported due to mesh network constraints.

### Mesh User to Gateway

Messages sent directly to the gateway node (not broadcast) appear in the configured `dm_channel` or the primary channel if not configured.

## Rate Limiting

The mesh network supports approximately one message per second under optimal conditions. The bridge implements rate limiting to prevent congestion:

- Messages exceeding the rate limit are queued (if `queue_overflow: true`)
- Queued messages are sent as bandwidth becomes available
- Queue size is limited to 50 messages
- Messages exceeding queue size are dropped

Configure limits in `config.yaml`:
```yaml
rate_limit:
  mesh_max_per_minute: 10
  queue_overflow: true
```

## Message Size Limits

Meshtastic messages are limited to approximately 230 bytes. Messages exceeding 200 bytes are truncated with `...` appended.

IRC messages have no practical limit, but very long messages may be split across multiple lines.

## Running as a System Service

Create `/etc/systemd/system/mesh-irc.service`:

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

Enable and start:
```bash
sudo systemctl enable mesh-irc
sudo systemctl start mesh-irc
sudo systemctl status mesh-irc
```

View logs:
```bash
journalctl -u mesh-irc -f
```

## Logging

Configure logging level in `config.yaml`:

```yaml
logging:
  level: "INFO"
  file: "bridge.log"
```

Levels: DEBUG, INFO, WARNING, ERROR

DEBUG level logs all IRC and mesh traffic.

## Troubleshooting

### Bridge cannot connect to Meshtastic device

Serial connection:
- Verify device path: `ls /dev/ttyUSB* /dev/ttyACM*`
- Check permissions: `sudo usermod -a -G dialout $USER` (logout required)
- Verify device is not in use by another application

TCP connection:
- Verify device IP and port
- Ensure WiFi is enabled on the Meshtastic device
- Check firewall rules

### Bridge cannot connect to IRC

- Verify server address and port
- Check if SSL is required (port 6697 typically requires SSL)
- Some networks block IRC; try a different server
- Check if nickname is registered and requires password

### Messages not appearing in IRC

- Verify channel mappings in configuration
- Check that the bridge bot has joined the channel
- Enable DEBUG logging to trace message flow

### Messages not appearing on mesh

- Check rate limiting settings
- Verify mesh channel index in configuration
- Ensure gateway device is not in "router" mode (may not relay to serial)

### Puppet connections failing

- Some IRC servers limit connections per IP
- Increase connection delay between puppets
- Use relay mode if puppet mode is problematic

## File Reference

| File | Purpose |
|------|---------|
| bridge.py | Main daemon |
| config.yaml | Configuration file |
| mesh_client.py | Meshtastic connection handler |
| irc_client.py | IRC connection handler |
| puppet_manager.py | Per-node IRC connections (puppet mode) |
| commands.py | Slash command processor |
| formatters.py | Message formatting utilities |

## Limitations

- IRC users cannot send direct messages to specific mesh nodes
- Topic tracking from IRC is not implemented
- BLE connections are not tested
- Mesh channel names are not synchronized with IRC (only indices are mapped)
- Node position updates require the node to have transmitted recently
