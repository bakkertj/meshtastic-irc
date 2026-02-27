"""
Meshtastic client wrapper for the IRC bridge.
Handles connection, message sending/receiving, and node management.
"""

import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

import meshtastic
import meshtastic.serial_interface
import meshtastic.tcp_interface
from pubsub import pub

logger = logging.getLogger(__name__)


@dataclass
class MeshNode:
    """Represents a node in the mesh network."""
    node_id: str
    short_name: str
    long_name: str
    hw_model: Optional[str] = None
    last_heard: Optional[float] = None
    snr: Optional[float] = None
    rssi: Optional[int] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None


@dataclass
class MeshMessage:
    """Represents a message received from the mesh."""
    from_id: str
    from_node: Optional[MeshNode]
    to_id: str
    channel: int
    text: str
    snr: Optional[float] = None
    rssi: Optional[int] = None
    hop_limit: Optional[int] = None


class MeshClient:
    """Wrapper around Meshtastic interface for the bridge."""

    def __init__(
        self,
        connection_type: str = "serial",
        device: Optional[str] = None,
        host: Optional[str] = None,
        port: int = 4403,
    ):
        self.connection_type = connection_type
        self.device = device
        self.host = host
        self.port = port
        self.interface: Optional[meshtastic.MeshInterface] = None
        self.nodes: dict[str, MeshNode] = {}
        self.on_message: Optional[Callable[[MeshMessage], None]] = None
        self._running = False

    def connect(self) -> bool:
        """Establish connection to the Meshtastic device."""
        try:
            if self.connection_type == "serial":
                self.interface = meshtastic.serial_interface.SerialInterface(
                    self.device
                )
            elif self.connection_type == "tcp":
                self.interface = meshtastic.tcp_interface.TCPInterface(
                    hostname=self.host, portNumber=self.port
                )
            else:
                raise ValueError(f"Unknown connection type: {self.connection_type}")

            # Subscribe to message events
            pub.subscribe(self._on_receive, "meshtastic.receive")
            pub.subscribe(self._on_connection, "meshtastic.connection.established")
            pub.subscribe(self._on_node_update, "meshtastic.node.updated")

            # Load existing nodes
            self._load_nodes()

            self._running = True
            logger.info(f"Connected to Meshtastic via {self.connection_type}")
            return True

        except Exception as e:
            logger.error(f"Failed to connect to Meshtastic: {e}")
            return False

    def disconnect(self):
        """Close the Meshtastic connection."""
        self._running = False
        if self.interface:
            try:
                pub.unsubscribe(self._on_receive, "meshtastic.receive")
                pub.unsubscribe(self._on_connection, "meshtastic.connection.established")
                pub.unsubscribe(self._on_node_update, "meshtastic.node.updated")
                self.interface.close()
            except Exception as e:
                logger.warning(f"Error during disconnect: {e}")
            self.interface = None
        logger.info("Disconnected from Meshtastic")

    def _load_nodes(self):
        """Load node database from the connected device."""
        if not self.interface:
            return

        node_db = self.interface.nodes
        if node_db:
            for node_id, info in node_db.items():
                user = info.get("user", {})
                position = info.get("position", {})
                self.nodes[node_id] = MeshNode(
                    node_id=node_id,
                    short_name=user.get("shortName", node_id[-4:]),
                    long_name=user.get("longName", node_id),
                    hw_model=user.get("hwModel"),
                    last_heard=info.get("lastHeard"),
                    snr=info.get("snr"),
                    latitude=position.get("latitude"),
                    longitude=position.get("longitude"),
                )
            logger.info(f"Loaded {len(self.nodes)} nodes from device")

    def _on_connection(self, interface, topic=pub.AUTO_TOPIC):
        """Handle connection established event."""
        logger.info("Meshtastic connection established")
        self._load_nodes()

    def _on_node_update(self, node, interface, topic=pub.AUTO_TOPIC):
        """Handle node database updates."""
        node_id = node.get("num")
        if node_id:
            node_id = f"!{node_id:08x}"
            user = node.get("user", {})
            position = node.get("position", {})
            self.nodes[node_id] = MeshNode(
                node_id=node_id,
                short_name=user.get("shortName", node_id[-4:]),
                long_name=user.get("longName", node_id),
                hw_model=user.get("hwModel"),
                last_heard=node.get("lastHeard"),
                snr=node.get("snr"),
                latitude=position.get("latitude"),
                longitude=position.get("longitude"),
            )

    def _on_receive(self, packet, interface, topic=pub.AUTO_TOPIC):
        """Handle incoming mesh packets."""
        if not self.on_message:
            return

        # Only process text messages
        decoded = packet.get("decoded", {})
        if decoded.get("portnum") != "TEXT_MESSAGE_APP":
            return

        try:
            text = decoded.get("payload", b"").decode("utf-8")
        except UnicodeDecodeError:
            logger.warning("Received non-UTF8 message, skipping")
            return

        from_id = packet.get("fromId", "unknown")
        from_node = self.nodes.get(from_id)

        msg = MeshMessage(
            from_id=from_id,
            from_node=from_node,
            to_id=packet.get("toId", "^all"),
            channel=packet.get("channel", 0),
            text=text,
            snr=packet.get("rxSnr"),
            rssi=packet.get("rxRssi"),
            hop_limit=packet.get("hopLimit"),
        )

        logger.debug(f"Received mesh message: {msg}")

        try:
            self.on_message(msg)
        except Exception as e:
            logger.error(f"Error in message callback: {e}")

    def send_message(
        self,
        text: str,
        channel: int = 0,
        destination: Optional[str] = None,
    ) -> bool:
        """
        Send a text message to the mesh.

        Args:
            text: Message text to send
            channel: Channel index (0-7)
            destination: Optional destination node ID, or None for broadcast

        Returns:
            True if message was sent successfully
        """
        if not self.interface:
            logger.error("Cannot send: not connected")
            return False

        try:
            self.interface.sendText(
                text=text,
                channelIndex=channel,
                destinationId=destination or "^all",
            )
            logger.debug(f"Sent to mesh (ch={channel}): {text[:50]}...")
            return True
        except Exception as e:
            logger.error(f"Failed to send mesh message: {e}")
            return False

    def get_node_name(self, node_id: str) -> str:
        """Get human-readable name for a node ID."""
        node = self.nodes.get(node_id)
        if node:
            return node.long_name or node.short_name
        # Return last 4 chars of ID as fallback
        return node_id[-4:] if len(node_id) >= 4 else node_id

    def get_my_info(self) -> Optional[dict]:
        """Get info about the local node."""
        if self.interface and self.interface.myInfo:
            return {"my_node_num": self.interface.myInfo.my_node_num}
        return None
