# MeshCore IRC Bridge Implementation

This document describes the changes required to adapt the Meshtastic-IRC bridge for MeshCore.

## MeshCore Overview

MeshCore is a lightweight mesh networking protocol for LoRa radios. It differs from Meshtastic in several ways:

- Uses hybrid intelligent routing instead of flood-based routing
- Implements KISS TNC protocol with custom extensions
- Defines distinct node types: Clients, Repeaters, Room Servers
- Provides persistent message storage via Room Servers
- Uses Ed25519/X25519/AES-128 for identity and encryption

## Protocol Fundamentals

### KISS Framing

MeshCore uses standard KISS TNC framing over serial (115200 8N1):

```
Frame: FEND | Type Byte | Data (escaped) | FEND

FEND  = 0xC0  (frame delimiter)
FESC  = 0xDB  (escape character)
TFEND = 0xDC  (escaped FEND)
TFESC = 0xDD  (escaped FESC)
```

Type byte format: `(port << 4) | command`

Maximum unescaped frame size: 512 bytes
Maximum data frame payload: 255 bytes

### Standard KISS Commands

Host to TNC:
- 0x00: Data - queue packet for transmission
- 0x01: TXDELAY - transmitter keyup delay (10ms units)
- 0x02: Persistence - CSMA parameter (0-255)
- 0x03: SlotTime - CSMA slot interval (10ms units)
- 0x04: TXtail - post-TX hold time (10ms units)
- 0x05: FullDuplex - half/full duplex mode
- 0x06: SetHardware - MeshCore extensions

TNC to Host:
- 0x00: Data - received packet from radio

### MeshCore SetHardware Extensions (0x06)

Sub-commands for MeshCore-specific functionality:

Cryptographic:
- GetIdentity
- SignData
- VerifySignature
- EncryptData
- DecryptData
- KeyExchange
- Hash

Radio Control:
- SetRadio
- SetTxPower
- GetRadio
- GetTxPower
- GetCurrentRssi
- IsChannelBusy

Telemetry:
- GetAirtime
- GetNoiseFloor
- GetVersion
- GetStats
- GetBattery
- GetMCUTemp
- GetSensors
- GetDeviceName

System:
- Ping
- Reboot
- SetSignalReport
- GetSignalReport

Response convention: `response_code = command | 0x80`

### Cryptographic Algorithms

- Identity/Signing: Ed25519
- Key Exchange: X25519 (ECDH)
- Encryption: AES-128-CBC + HMAC-SHA256 (MAC truncated to 2 bytes)
- Hashing: SHA-256

## Architecture Changes

### New Files

```
meshtastic-irc/
├── meshcore_client.py    # MeshCore KISS protocol client (replaces mesh_client.py)
├── meshcore_crypto.py    # Ed25519/X25519/AES handling
├── kiss.py               # KISS framing utilities
└── meshcore_bridge.py    # MeshCore-specific bridge (or modify bridge.py)
```

### kiss.py

KISS framing implementation:

```python
"""
KISS TNC framing for MeshCore.
"""

FEND = 0xC0
FESC = 0xDB
TFEND = 0xDC
TFESC = 0xDD

def escape(data: bytes) -> bytes:
    """Escape special characters in frame data."""
    result = bytearray()
    for b in data:
        if b == FEND:
            result.extend([FESC, TFEND])
        elif b == FESC:
            result.extend([FESC, TFESC])
        else:
            result.append(b)
    return bytes(result)

def unescape(data: bytes) -> bytes:
    """Unescape special characters in frame data."""
    result = bytearray()
    i = 0
    while i < len(data):
        if data[i] == FESC and i + 1 < len(data):
            if data[i + 1] == TFEND:
                result.append(FEND)
            elif data[i + 1] == TFESC:
                result.append(FESC)
            i += 2
        else:
            result.append(data[i])
            i += 1
    return bytes(result)

def frame(command: int, data: bytes, port: int = 0) -> bytes:
    """Build a KISS frame."""
    type_byte = (port << 4) | (command & 0x0F)
    return bytes([FEND, type_byte]) + escape(data) + bytes([FEND])

def parse(raw: bytes) -> list[tuple[int, int, bytes]]:
    """
    Parse KISS frames from raw bytes.
    Returns list of (port, command, data) tuples.
    """
    frames = []
    current = bytearray()
    in_frame = False

    for b in raw:
        if b == FEND:
            if in_frame and len(current) > 0:
                type_byte = current[0]
                port = (type_byte >> 4) & 0x0F
                command = type_byte & 0x0F
                data = unescape(bytes(current[1:]))
                frames.append((port, command, data))
            current = bytearray()
            in_frame = True
        elif in_frame:
            current.append(b)

    return frames
```

### meshcore_crypto.py

Cryptographic operations:

```python
"""
MeshCore cryptographic operations.

Requires: pip install pynacl cryptography
"""

from nacl.signing import SigningKey, VerifyKey
from nacl.public import PrivateKey, PublicKey, Box
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
import hashlib
import hmac
import os


class MeshCoreIdentity:
    """Ed25519 identity for MeshCore node."""

    def __init__(self, seed: bytes = None):
        if seed:
            self.signing_key = SigningKey(seed)
        else:
            self.signing_key = SigningKey.generate()
        self.verify_key = self.signing_key.verify_key

    @property
    def public_key(self) -> bytes:
        return bytes(self.verify_key)

    @property
    def private_key(self) -> bytes:
        return bytes(self.signing_key)

    def sign(self, data: bytes) -> bytes:
        return self.signing_key.sign(data).signature

    def verify(self, data: bytes, signature: bytes, public_key: bytes) -> bool:
        try:
            vk = VerifyKey(public_key)
            vk.verify(data, signature)
            return True
        except Exception:
            return False


class MeshCoreKeyExchange:
    """X25519 key exchange for MeshCore."""

    def __init__(self):
        self.private_key = PrivateKey.generate()
        self.public_key = self.private_key.public_key

    def derive_shared_key(self, peer_public: bytes) -> bytes:
        peer_key = PublicKey(peer_public)
        box = Box(self.private_key, peer_key)
        # Derive AES key from shared secret
        return hashlib.sha256(bytes(box)).digest()[:16]


class MeshCoreEncryption:
    """AES-128-CBC encryption with HMAC-SHA256."""

    @staticmethod
    def encrypt(key: bytes, plaintext: bytes) -> bytes:
        iv = os.urandom(16)
        # Pad to AES block size
        padding_len = 16 - (len(plaintext) % 16)
        padded = plaintext + bytes([padding_len] * padding_len)

        cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
        encryptor = cipher.encryptor()
        ciphertext = encryptor.update(padded) + encryptor.finalize()

        # HMAC (truncated to 2 bytes per MeshCore spec)
        mac = hmac.new(key, iv + ciphertext, hashlib.sha256).digest()[:2]

        return iv + ciphertext + mac

    @staticmethod
    def decrypt(key: bytes, data: bytes) -> bytes:
        iv = data[:16]
        mac = data[-2:]
        ciphertext = data[16:-2]

        # Verify MAC
        expected_mac = hmac.new(key, iv + ciphertext, hashlib.sha256).digest()[:2]
        if mac != expected_mac:
            raise ValueError("MAC verification failed")

        cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
        decryptor = cipher.decryptor()
        padded = decryptor.update(ciphertext) + decryptor.finalize()

        # Remove padding
        padding_len = padded[-1]
        return padded[:-padding_len]


def sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()
```

### meshcore_client.py

Main client implementation:

```python
"""
MeshCore client for IRC bridge.
"""

import logging
import serial
import socket
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

from kiss import frame, parse, FEND
from meshcore_crypto import MeshCoreIdentity, MeshCoreKeyExchange, MeshCoreEncryption

logger = logging.getLogger(__name__)

# KISS commands
CMD_DATA = 0x00
CMD_SET_HARDWARE = 0x06

# SetHardware sub-commands (partial list)
HW_GET_IDENTITY = 0x01
HW_SIGN_DATA = 0x02
HW_VERIFY_SIGNATURE = 0x03
HW_ENCRYPT_DATA = 0x04
HW_DECRYPT_DATA = 0x05
HW_KEY_EXCHANGE = 0x06
HW_HASH = 0x07
HW_SET_RADIO = 0x10
HW_GET_RADIO = 0x11
HW_GET_VERSION = 0x20
HW_GET_STATS = 0x21
HW_GET_BATTERY = 0x22
HW_GET_DEVICE_NAME = 0x25
HW_PING = 0x30


@dataclass
class MeshCoreNode:
    """Represents a MeshCore node."""
    node_id: bytes  # Ed25519 public key
    name: str
    last_heard: float
    rssi: Optional[int] = None


@dataclass
class MeshCoreMessage:
    """Represents a received message."""
    from_id: bytes
    from_name: str
    to_id: Optional[bytes]  # None for broadcast/room
    room: Optional[str]
    text: str
    timestamp: float


class MeshCoreClient:
    """
    MeshCore KISS protocol client.

    Connects to a MeshCore companion device via serial, TCP, or BLE.
    """

    def __init__(
        self,
        connection_type: str = "serial",
        device: Optional[str] = None,
        host: Optional[str] = None,
        port: int = 5000,
    ):
        self.connection_type = connection_type
        self.device = device
        self.host = host
        self.port = port

        self.conn = None
        self.identity: Optional[MeshCoreIdentity] = None
        self.nodes: dict[bytes, MeshCoreNode] = {}
        self.contacts: dict[str, bytes] = {}  # name -> public key
        self.rooms: list[str] = []

        self.on_message: Optional[Callable[[MeshCoreMessage], None]] = None

        self._running = False
        self._recv_thread: Optional[threading.Thread] = None
        self._buffer = bytearray()

    def connect(self) -> bool:
        """Establish connection to MeshCore device."""
        try:
            if self.connection_type == "serial":
                self.conn = serial.Serial(self.device, 115200, timeout=1)
            elif self.connection_type == "tcp":
                self.conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.conn.connect((self.host, self.port))
                self.conn.settimeout(1)
            else:
                raise ValueError(f"Unsupported connection type: {self.connection_type}")

            self._running = True
            self._recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
            self._recv_thread.start()

            # Get device identity
            self._request_identity()

            logger.info(f"Connected to MeshCore via {self.connection_type}")
            return True

        except Exception as e:
            logger.error(f"Failed to connect: {e}")
            return False

    def disconnect(self):
        """Close connection."""
        self._running = False
        if self.conn:
            try:
                self.conn.close()
            except Exception:
                pass
            self.conn = None

    def _send(self, data: bytes):
        """Send raw bytes."""
        if self.conn:
            if self.connection_type == "serial":
                self.conn.write(data)
            else:
                self.conn.send(data)

    def _send_command(self, command: int, data: bytes = b""):
        """Send a KISS command."""
        self._send(frame(command, data))

    def _send_hardware_command(self, sub_cmd: int, data: bytes = b""):
        """Send a SetHardware sub-command."""
        self._send_command(CMD_SET_HARDWARE, bytes([sub_cmd]) + data)

    def _recv_loop(self):
        """Background receive loop."""
        while self._running:
            try:
                if self.connection_type == "serial":
                    data = self.conn.read(256)
                else:
                    data = self.conn.recv(256)

                if data:
                    self._buffer.extend(data)
                    self._process_buffer()

            except (socket.timeout, serial.SerialTimeoutException):
                continue
            except Exception as e:
                logger.error(f"Receive error: {e}")
                break

    def _process_buffer(self):
        """Process received data buffer."""
        frames = parse(bytes(self._buffer))

        # Keep unprocessed data
        last_fend = self._buffer.rfind(FEND)
        if last_fend >= 0:
            self._buffer = self._buffer[last_fend + 1:]

        for port, command, data in frames:
            self._handle_frame(port, command, data)

    def _handle_frame(self, port: int, command: int, data: bytes):
        """Handle a received KISS frame."""
        if command == CMD_DATA:
            self._handle_data(data)
        elif command == CMD_SET_HARDWARE:
            self._handle_hardware_response(data)

    def _handle_data(self, data: bytes):
        """Handle incoming data packet."""
        # TODO: Parse MeshCore packet format
        # This requires understanding the MeshCore packet structure
        # which may include: sender ID, recipient ID, room ID, flags, payload
        logger.debug(f"Received data: {data.hex()}")

    def _handle_hardware_response(self, data: bytes):
        """Handle SetHardware response."""
        if len(data) < 1:
            return

        sub_cmd = data[0]
        payload = data[1:]

        # Response bit is 0x80
        if sub_cmd & 0x80:
            original_cmd = sub_cmd & 0x7F
            logger.debug(f"Hardware response for {original_cmd:02x}: {payload.hex()}")

    def _request_identity(self):
        """Request device identity."""
        self._send_hardware_command(HW_GET_IDENTITY)

    def ping(self) -> bool:
        """Ping the device."""
        self._send_hardware_command(HW_PING)
        return True

    def get_version(self):
        """Request firmware version."""
        self._send_hardware_command(HW_GET_VERSION)

    def get_battery(self):
        """Request battery status."""
        self._send_hardware_command(HW_GET_BATTERY)

    def get_device_name(self):
        """Request device name."""
        self._send_hardware_command(HW_GET_DEVICE_NAME)

    def send_message(
        self,
        text: str,
        contact: Optional[str] = None,
        room: Optional[str] = None,
    ) -> bool:
        """
        Send a text message.

        Args:
            text: Message text
            contact: Contact name for direct message
            room: Room name for room message

        Returns:
            True if message was queued
        """
        # TODO: Implement message encoding
        # This requires understanding the MeshCore message format
        # and potentially encrypting for the recipient
        logger.warning("send_message not yet implemented")
        return False

    def sync_messages(self):
        """Request message sync from device."""
        # TODO: Implement message sync request
        pass

    def get_contacts(self) -> dict[str, bytes]:
        """Get known contacts."""
        return self.contacts.copy()

    def get_rooms(self) -> list[str]:
        """Get joined rooms."""
        return self.rooms.copy()
```

## Bridge Integration

### Configuration Changes

```yaml
# config.yaml additions for MeshCore

protocol: "meshcore"  # or "meshtastic"

meshcore:
  connection: "serial"
  device: "/dev/ttyUSB0"
  # For TCP:
  # host: "192.168.1.100"
  # port: 5000

# MeshCore uses rooms instead of channels
rooms:
  "General": "#meshtastic-general"
  "Emergency": "#meshtastic-emergency"

# Or map contacts to IRC
contacts:
  "Alice": "#alice-dm"
  "Bob": "#bob-dm"
```

### Bridge Modifications

The bridge needs to handle MeshCore's concepts:

1. **Rooms vs Channels**: MeshCore has named rooms hosted on Room Servers, not numbered channels
2. **Contacts**: Direct messages require knowing the recipient's public key
3. **Encryption**: Messages may need encryption/decryption
4. **Store-and-Forward**: Room Servers store messages; bridge should sync on reconnect

```python
# In bridge.py, add protocol selection:

if self.config.get("protocol") == "meshcore":
    from meshcore_client import MeshCoreClient
    self.mesh = MeshCoreClient(
        connection_type=mesh_config.get("connection", "serial"),
        device=mesh_config.get("device"),
        host=mesh_config.get("host"),
        port=mesh_config.get("port", 5000),
    )
else:
    from mesh_client import MeshClient
    self.mesh = MeshClient(...)
```

## Implementation Phases

### Phase 1: Basic Connectivity

1. Implement KISS framing (kiss.py)
2. Implement serial/TCP connection
3. Test with HW_PING, HW_GET_VERSION, HW_GET_DEVICE_NAME
4. Verify two-way communication

### Phase 2: Message Handling

1. Reverse-engineer or document MeshCore packet format
2. Implement message parsing
3. Implement message sending
4. Test with meshcore-cli as reference

### Phase 3: Cryptography

1. Implement identity handling
2. Implement key exchange with contacts
3. Implement message encryption/decryption
4. Test encrypted messaging

### Phase 4: Bridge Integration

1. Adapt bridge.py for MeshCore client
2. Map rooms to IRC channels
3. Handle contact-based messaging
4. Test full bridge functionality

### Phase 5: Commands

1. Adapt /nodes for MeshCore node list
2. Adapt /signal for MeshCore signal data
3. Add /rooms command
4. Add /contacts command

## Dependencies

Additional Python packages required:

```
pynacl>=1.5.0       # Ed25519, X25519
cryptography>=41.0  # AES-128-CBC
pyserial>=3.5       # Serial communication
```

Add to requirements.txt:

```
meshtastic>=2.3.0
PyYAML>=6.0
pypubsub>=4.0.3
pynacl>=1.5.0
cryptography>=41.0
pyserial>=3.5
```

## Open Questions

1. **Packet Format**: The exact MeshCore packet structure is not fully documented. May need to examine meshcore-cli source or meshcore.js.

2. **Room Server Protocol**: How does a client interact with Room Servers? Is there a specific message type for room messages?

3. **Contact Discovery**: How are contacts discovered and added? Is there a broadcast/announce mechanism?

4. **BLE Support**: The KISS protocol docs focus on serial. BLE may use a different framing or characteristic layout.

5. **Message Sync**: What is the protocol for syncing missed messages from a Room Server?

## Resources

- MeshCore GitHub: https://github.com/meshcore-dev/MeshCore
- KISS Protocol Docs: https://github.com/meshcore-dev/MeshCore/blob/main/docs/kiss_modem_protocol.md
- meshcore-cli: https://github.com/fdlamotte/meshcore-cli
- meshcore.js: https://github.com/liamcottle/meshcore.js
- MeshCore FAQ: https://github.com/meshcore-dev/MeshCore/blob/main/docs/faq.md

## Testing

Once hardware is available:

```bash
# Test basic connectivity
python -c "
from meshcore_client import MeshCoreClient
client = MeshCoreClient(connection_type='serial', device='/dev/ttyUSB0')
client.connect()
client.ping()
client.get_version()
"

# Compare with meshcore-cli
pip install meshcore-cli
meshcore-cli -s /dev/ttyUSB0 infos
meshcore-cli -s /dev/ttyUSB0 ping
```
