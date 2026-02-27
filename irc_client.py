"""
IRC client wrapper for the Meshtastic bridge.
Handles connection, channel management, and message routing.
"""

import logging
import socket
import ssl
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

logger = logging.getLogger(__name__)


@dataclass
class IRCMessage:
    """Represents a message received from IRC."""
    channel: str
    nick: str
    user: str
    host: str
    text: str


class IRCClient:
    """Simple IRC client for the bridge."""

    def __init__(
        self,
        server: str,
        port: int = 6667,
        nickname: str = "meshbridge",
        realname: str = "Meshtastic IRC Bridge",
        use_ssl: bool = False,
        password: Optional[str] = None,
    ):
        self.server = server
        self.port = port
        self.nickname = nickname
        self.realname = realname
        self.use_ssl = use_ssl
        self.password = password

        self.socket: Optional[socket.socket] = None
        self.channels: set[str] = set()
        self.on_message: Optional[Callable[[IRCMessage], None]] = None
        self._running = False
        self._recv_thread: Optional[threading.Thread] = None
        self._buffer = ""

    def connect(self) -> bool:
        """Connect to the IRC server."""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(300)  # 5 minute timeout

            if self.use_ssl:
                context = ssl.create_default_context()
                self.socket = context.wrap_socket(
                    self.socket, server_hostname=self.server
                )

            self.socket.connect((self.server, self.port))
            logger.info(f"Connected to {self.server}:{self.port}")

            # Send registration
            if self.password:
                self._send(f"PASS {self.password}")
            self._send(f"NICK {self.nickname}")
            self._send(f"USER {self.nickname} 0 * :{self.realname}")

            # Start receive thread
            self._running = True
            self._recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
            self._recv_thread.start()

            return True

        except Exception as e:
            logger.error(f"Failed to connect to IRC: {e}")
            return False

    def disconnect(self):
        """Disconnect from the IRC server."""
        self._running = False
        if self.socket:
            try:
                self._send("QUIT :Bridge shutting down")
                self.socket.close()
            except Exception:
                pass
            self.socket = None
        logger.info("Disconnected from IRC")

    def _send(self, message: str):
        """Send a raw IRC message."""
        if self.socket:
            try:
                self.socket.send(f"{message}\r\n".encode("utf-8"))
                logger.debug(f"IRC >>> {message}")
            except Exception as e:
                logger.error(f"Failed to send IRC message: {e}")

    def _recv_loop(self):
        """Receive loop running in background thread."""
        while self._running and self.socket:
            try:
                data = self.socket.recv(4096)
                if not data:
                    logger.warning("IRC connection closed")
                    self._running = False
                    break

                self._buffer += data.decode("utf-8", errors="replace")
                lines = self._buffer.split("\r\n")
                self._buffer = lines.pop()  # Keep incomplete line in buffer

                for line in lines:
                    if line:
                        self._handle_line(line)

            except socket.timeout:
                continue
            except Exception as e:
                logger.error(f"IRC receive error: {e}")
                self._running = False
                break

    def _handle_line(self, line: str):
        """Process a single IRC line."""
        logger.debug(f"IRC <<< {line}")

        # Handle PING
        if line.startswith("PING"):
            self._send(f"PONG {line[5:]}")
            return

        # Parse IRC message
        prefix = ""
        if line.startswith(":"):
            prefix, line = line[1:].split(" ", 1)

        parts = line.split(" ", 2)
        command = parts[0]

        # Handle specific commands
        if command == "001":  # RPL_WELCOME
            logger.info("IRC registration complete")
            # Join configured channels
            for channel in list(self.channels):
                self._send(f"JOIN {channel}")

        elif command == "433":  # ERR_NICKNAMEINUSE
            self.nickname = self.nickname + "_"
            self._send(f"NICK {self.nickname}")
            logger.warning(f"Nickname in use, trying {self.nickname}")

        elif command == "JOIN":
            channel = parts[1].lstrip(":")
            nick = prefix.split("!")[0]
            if nick == self.nickname:
                logger.info(f"Joined {channel}")

        elif command == "PRIVMSG":
            self._handle_privmsg(prefix, parts)

    def _handle_privmsg(self, prefix: str, parts: list[str]):
        """Handle PRIVMSG command."""
        if len(parts) < 3:
            return

        target = parts[1]
        text = parts[2]
        if text.startswith(":"):
            text = text[1:]

        # Parse prefix (nick!user@host)
        if "!" in prefix:
            nick, rest = prefix.split("!", 1)
            user, host = rest.split("@", 1) if "@" in rest else (rest, "")
        else:
            nick, user, host = prefix, "", ""

        # Only handle channel messages, not PMs
        if not target.startswith("#"):
            return

        msg = IRCMessage(
            channel=target,
            nick=nick,
            user=user,
            host=host,
            text=text,
        )

        if self.on_message:
            try:
                self.on_message(msg)
            except Exception as e:
                logger.error(f"Error in IRC message callback: {e}")

    def join(self, channel: str):
        """Join an IRC channel."""
        if not channel.startswith("#"):
            channel = f"#{channel}"
        self.channels.add(channel)
        if self._running:
            self._send(f"JOIN {channel}")

    def part(self, channel: str, message: str = "Leaving"):
        """Leave an IRC channel."""
        self.channels.discard(channel)
        if self._running:
            self._send(f"PART {channel} :{message}")

    def send_message(self, channel: str, text: str):
        """Send a message to an IRC channel."""
        # IRC messages have a max length, split if needed
        max_len = 400  # Conservative limit
        for i in range(0, len(text), max_len):
            chunk = text[i:i + max_len]
            self._send(f"PRIVMSG {channel} :{chunk}")

    def send_action(self, channel: str, action: str):
        """Send an action (/me) to an IRC channel."""
        self._send(f"PRIVMSG {channel} :\x01ACTION {action}\x01")

    def is_connected(self) -> bool:
        """Check if connected to IRC."""
        return self._running and self.socket is not None
