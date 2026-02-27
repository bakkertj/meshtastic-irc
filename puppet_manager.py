"""
Puppet manager for the Meshtastic-IRC bridge.

In puppet mode, each mesh node appears as a separate IRC user,
making mesh users first-class participants in IRC conversations.
"""

import logging
import socket
import ssl
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

logger = logging.getLogger(__name__)


@dataclass
class Puppet:
    """Represents a puppet IRC connection for a mesh node."""
    node_id: str
    nickname: str
    sock: Optional[socket.socket] = None
    connected: bool = False
    channels: set = field(default_factory=set)
    last_activity: float = field(default_factory=time.time)


class PuppetManager:
    """
    Manages multiple IRC connections, one per mesh node.

    Each mesh node gets its own IRC "puppet" that joins channels
    and speaks on behalf of the mesh user.
    """

    def __init__(
        self,
        server: str,
        port: int = 6667,
        use_ssl: bool = False,
        nick_prefix: str = "mesh_",
        channels: list[str] = None,
        puppet_timeout: int = 3600,  # Disconnect idle puppets after 1 hour
    ):
        self.server = server
        self.port = port
        self.use_ssl = use_ssl
        self.nick_prefix = nick_prefix
        self.default_channels = channels or []
        self.puppet_timeout = puppet_timeout

        self.puppets: dict[str, Puppet] = {}  # node_id -> Puppet
        self.nick_to_node: dict[str, str] = {}  # nickname -> node_id
        self._lock = threading.Lock()
        self._running = False
        self._cleanup_thread: Optional[threading.Thread] = None

    def start(self):
        """Start the puppet manager."""
        self._running = True
        self._cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        self._cleanup_thread.start()
        logger.info("Puppet manager started")

    def stop(self):
        """Stop all puppets and cleanup."""
        self._running = False
        with self._lock:
            for puppet in list(self.puppets.values()):
                self._disconnect_puppet(puppet)
            self.puppets.clear()
            self.nick_to_node.clear()
        logger.info("Puppet manager stopped")

    def _make_nickname(self, node_name: str) -> str:
        """Generate IRC-safe nickname from node name."""
        # IRC nicknames: letters, digits, special chars, max ~16 chars
        safe = "".join(c for c in node_name if c.isalnum() or c in "_-")
        safe = safe[:12]  # Leave room for prefix
        if not safe:
            safe = "node"
        return f"{self.nick_prefix}{safe}"

    def _connect_puppet(self, puppet: Puppet) -> bool:
        """Establish IRC connection for a puppet."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(30)

            if self.use_ssl:
                context = ssl.create_default_context()
                sock = context.wrap_socket(sock, server_hostname=self.server)

            sock.connect((self.server, self.port))
            puppet.sock = sock

            # Register
            self._send(puppet, f"NICK {puppet.nickname}")
            self._send(puppet, f"USER {puppet.nickname} 0 * :Mesh Node {puppet.node_id}")

            # Wait for registration (simple approach)
            time.sleep(2)

            # Join channels
            for channel in self.default_channels:
                self._send(puppet, f"JOIN {channel}")
                puppet.channels.add(channel)

            puppet.connected = True

            # Start read loop to handle PING/PONG
            read_thread = threading.Thread(
                target=self._read_loop, args=(puppet,), daemon=True
            )
            read_thread.start()

            logger.info(f"Puppet {puppet.nickname} connected for node {puppet.node_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to connect puppet {puppet.nickname}: {e}")
            return False

    def _read_loop(self, puppet: Puppet):
        """Read from puppet socket and respond to PINGs."""
        buf = ""
        while self._running and puppet.connected and puppet.sock:
            try:
                puppet.sock.settimeout(60)
                data = puppet.sock.recv(4096)
                if not data:
                    logger.warning(f"Puppet {puppet.nickname} connection closed")
                    puppet.connected = False
                    break
                buf += data.decode("utf-8", errors="replace")
                while "\r\n" in buf:
                    line, buf = buf.split("\r\n", 1)
                    if line.startswith("PING"):
                        token = line.split(" ", 1)[1] if " " in line else ""
                        self._send(puppet, f"PONG {token}")
            except socket.timeout:
                continue
            except Exception as e:
                logger.warning(f"Puppet {puppet.nickname} read error: {e}")
                puppet.connected = False
                break

    def _disconnect_puppet(self, puppet: Puppet):
        """Disconnect a puppet from IRC."""
        if puppet.sock:
            try:
                self._send(puppet, "QUIT :Mesh node offline")
                puppet.sock.close()
            except Exception:
                pass
            puppet.sock = None
        puppet.connected = False
        self.nick_to_node.pop(puppet.nickname, None)
        logger.info(f"Puppet {puppet.nickname} disconnected")

    def _send(self, puppet: Puppet, message: str):
        """Send raw IRC message via puppet."""
        if puppet.sock:
            try:
                puppet.sock.send(f"{message}\r\n".encode("utf-8"))
            except Exception as e:
                logger.error(f"Puppet send error: {e}")
                puppet.connected = False

    def _cleanup_loop(self):
        """Periodically clean up idle puppets."""
        while self._running:
            time.sleep(60)
            now = time.time()
            with self._lock:
                for node_id, puppet in list(self.puppets.items()):
                    if now - puppet.last_activity > self.puppet_timeout:
                        logger.info(f"Cleaning up idle puppet {puppet.nickname}")
                        self._disconnect_puppet(puppet)
                        del self.puppets[node_id]

    def get_or_create_puppet(self, node_id: str, node_name: str) -> Optional[Puppet]:
        """Get existing puppet or create new one for a mesh node."""
        with self._lock:
            if node_id in self.puppets:
                puppet = self.puppets[node_id]
                puppet.last_activity = time.time()
                if not puppet.connected:
                    self._connect_puppet(puppet)
                return puppet

            # Create new puppet
            nickname = self._make_nickname(node_name)

            # Handle nickname collisions
            base_nick = nickname
            counter = 1
            while nickname in self.nick_to_node:
                nickname = f"{base_nick}{counter}"
                counter += 1

            puppet = Puppet(
                node_id=node_id,
                nickname=nickname,
            )

            if self._connect_puppet(puppet):
                self.puppets[node_id] = puppet
                self.nick_to_node[nickname] = node_id
                return puppet

            return None

    def send_message(
        self,
        node_id: str,
        node_name: str,
        channel: str,
        message: str,
    ) -> bool:
        """Send a message to IRC on behalf of a mesh node."""
        puppet = self.get_or_create_puppet(node_id, node_name)
        if not puppet or not puppet.connected:
            return False

        # Ensure puppet is in channel
        if channel not in puppet.channels:
            self._send(puppet, f"JOIN {channel}")
            puppet.channels.add(channel)
            time.sleep(0.5)  # Brief delay for join

        # Send message (split if too long)
        max_len = 400
        for i in range(0, len(message), max_len):
            chunk = message[i:i + max_len]
            self._send(puppet, f"PRIVMSG {channel} :{chunk}")

        puppet.last_activity = time.time()
        return True

    def send_action(
        self,
        node_id: str,
        node_name: str,
        channel: str,
        action: str,
    ) -> bool:
        """Send an action (/me) to IRC on behalf of a mesh node."""
        puppet = self.get_or_create_puppet(node_id, node_name)
        if not puppet or not puppet.connected:
            return False

        if channel not in puppet.channels:
            self._send(puppet, f"JOIN {channel}")
            puppet.channels.add(channel)
            time.sleep(0.5)

        self._send(puppet, f"PRIVMSG {channel} :\x01ACTION {action}\x01")
        puppet.last_activity = time.time()
        return True

    def is_puppet_nick(self, nickname: str) -> bool:
        """Check if a nickname belongs to one of our puppets."""
        return nickname in self.nick_to_node

    def get_node_for_nick(self, nickname: str) -> Optional[str]:
        """Get mesh node ID for an IRC nickname."""
        return self.nick_to_node.get(nickname)
