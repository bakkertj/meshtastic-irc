#!/usr/bin/env python3
"""
Meshtastic-IRC Bridge

Bridges messages between a Meshtastic mesh network and IRC channels.
Supports "puppet mode" where each mesh node appears as a separate IRC user.
"""

import argparse
import logging
import signal
import sys
import threading
import time
from collections import deque
from pathlib import Path
from typing import Optional

import yaml

from commands import CommandHandler
from irc_client import IRCClient, IRCMessage
from mesh_client import MeshClient, MeshMessage
from puppet_manager import PuppetManager

logger = logging.getLogger(__name__)


class RateLimiter:
    """Simple token bucket rate limiter."""

    def __init__(self, max_per_minute: int):
        self.max_per_minute = max_per_minute
        self.tokens = max_per_minute
        self.last_update = time.time()
        self.lock = threading.Lock()

    def acquire(self) -> bool:
        """Try to acquire a token. Returns True if allowed."""
        with self.lock:
            now = time.time()
            elapsed = now - self.last_update
            self.tokens = min(
                self.max_per_minute,
                self.tokens + (elapsed * self.max_per_minute / 60),
            )
            self.last_update = now

            if self.tokens >= 1:
                self.tokens -= 1
                return True
            return False


class MeshIRCBridge:
    """Main bridge class connecting Meshtastic and IRC."""

    def __init__(self, config_path: str):
        self.config = self._load_config(config_path)
        self.mesh: Optional[MeshClient] = None
        self.irc: Optional[IRCClient] = None
        self.puppets: Optional[PuppetManager] = None
        self.running = False

        # Mode: "relay" (single bot) or "puppet" (per-node users)
        self.mode = self.config.get("mode", "relay")

        # Channel mappings
        self.mesh_to_irc: dict[int, str] = {}
        self.irc_to_mesh: dict[str, int] = {}

        # Track our own node ID to avoid echo
        self.my_node_id: Optional[str] = None

        # Direct message channel (for DMs sent to gateway)
        self.dm_channel = self.config.get("dm_channel")

        # Rate limiting for mesh (it's slow)
        rate_config = self.config.get("rate_limit", {})
        self.rate_limiter = RateLimiter(rate_config.get("mesh_max_per_minute", 10))
        self.queue_overflow = rate_config.get("queue_overflow", True)
        self.message_queue: deque[tuple[str, int, Optional[str]]] = deque(maxlen=50)
        self.queue_thread: Optional[threading.Thread] = None

        # Formatting config
        self.format_config = self.config.get("formatting", {})

        # Command handler for mesh-side slash commands
        self.commands: Optional[CommandHandler] = None

        self._setup_channel_mappings()

    def _load_config(self, config_path: str) -> dict:
        """Load configuration from YAML file."""
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")

        with open(path) as f:
            return yaml.safe_load(f)

    def _setup_channel_mappings(self):
        """Set up bidirectional channel mappings."""
        channels = self.config.get("channels", {0: "#meshtastic"})
        for mesh_ch, irc_ch in channels.items():
            mesh_ch = int(mesh_ch)
            if not irc_ch.startswith("#"):
                irc_ch = f"#{irc_ch}"
            self.mesh_to_irc[mesh_ch] = irc_ch
            self.irc_to_mesh[irc_ch] = mesh_ch

        logger.info(f"Channel mappings: {self.mesh_to_irc}")

    def start(self):
        """Start the bridge."""
        logger.info(f"Starting Meshtastic-IRC Bridge (mode: {self.mode})")

        # Connect to Meshtastic
        mesh_config = self.config.get("meshtastic", {})
        self.mesh = MeshClient(
            connection_type=mesh_config.get("connection", "serial"),
            device=mesh_config.get("device"),
            host=mesh_config.get("host"),
            port=mesh_config.get("port", 4403),
        )
        self.mesh.on_message = self._on_mesh_message

        if not self.mesh.connect():
            logger.error("Failed to connect to Meshtastic")
            return False

        # Get our node ID
        my_info = self.mesh.get_my_info()
        if my_info:
            self.my_node_id = f"!{my_info.get('my_node_num', 0):08x}"
            logger.info(f"Gateway node ID: {self.my_node_id}")

        # Connect to IRC
        irc_config = self.config.get("irc", {})

        if self.mode == "puppet":
            # Puppet mode: each mesh node gets its own IRC connection
            self.puppets = PuppetManager(
                server=irc_config.get("server", "irc.libera.chat"),
                port=irc_config.get("port", 6667),
                use_ssl=irc_config.get("ssl", False),
                nick_prefix=irc_config.get("puppet_prefix", "mesh_"),
                channels=list(self.mesh_to_irc.values()),
            )
            self.puppets.start()

            # Still need main IRC client to receive messages from IRC users
            self.irc = IRCClient(
                server=irc_config.get("server", "irc.libera.chat"),
                port=irc_config.get("port", 6667),
                nickname=irc_config.get("nickname", "meshbridge"),
                realname=irc_config.get("realname", "Meshtastic IRC Bridge"),
                use_ssl=irc_config.get("ssl", False),
                password=irc_config.get("password"),
            )
        else:
            # Relay mode: single bot relays all messages
            self.irc = IRCClient(
                server=irc_config.get("server", "irc.libera.chat"),
                port=irc_config.get("port", 6667),
                nickname=irc_config.get("nickname", "meshbridge"),
                realname=irc_config.get("realname", "Meshtastic IRC Bridge"),
                use_ssl=irc_config.get("ssl", False),
                password=irc_config.get("password"),
            )

        self.irc.on_message = self._on_irc_message

        # Pre-register channels to join
        for irc_ch in self.mesh_to_irc.values():
            self.irc.join(irc_ch)

        # Join DM channel if configured
        if self.dm_channel:
            if not self.dm_channel.startswith("#"):
                self.dm_channel = f"#{self.dm_channel}"
            self.irc.join(self.dm_channel)

        if not self.irc.connect():
            logger.error("Failed to connect to IRC")
            self.mesh.disconnect()
            if self.puppets:
                self.puppets.stop()
            return False

        self.running = True

        # Initialize command handler
        self.commands = CommandHandler(self)

        # Start queue processor thread
        self.queue_thread = threading.Thread(target=self._process_queue, daemon=True)
        self.queue_thread.start()

        logger.info("Bridge started successfully")
        return True

    def stop(self):
        """Stop the bridge."""
        logger.info("Stopping bridge")
        self.running = False

        if self.puppets:
            self.puppets.stop()
        if self.irc:
            self.irc.disconnect()
        if self.mesh:
            self.mesh.disconnect()

    def _get_node_name(self, msg: MeshMessage) -> str:
        """Get human-readable name for a mesh message sender."""
        if msg.from_node:
            return msg.from_node.long_name or msg.from_node.short_name
        elif self.mesh:
            return self.mesh.get_node_name(msg.from_id)
        return "unknown"

    def _format_mesh_to_irc(self, msg: MeshMessage) -> str:
        """Format a mesh message for IRC (relay mode only)."""
        template = self.format_config.get("mesh_to_irc", "[{node_name}] {message}")
        node_name = self._get_node_name(msg)

        result = template.format(
            node_name=node_name,
            node_id=msg.from_id,
            message=msg.text,
        )

        # Optionally add signal info
        if self.format_config.get("show_signal") and msg.snr is not None:
            result += f" [SNR:{msg.snr:.1f}dB]"

        return result

    def _format_irc_to_mesh(self, msg: IRCMessage) -> str:
        """Format an IRC message for mesh."""
        template = self.format_config.get("irc_to_mesh", "<{nick}> {message}")
        return template.format(
            nick=msg.nick,
            channel=msg.channel,
            message=msg.text,
        )

    def _is_direct_message(self, msg: MeshMessage) -> bool:
        """Check if message is a DM to our gateway node."""
        if not self.my_node_id:
            return False
        return msg.to_id == self.my_node_id

    def _on_mesh_message(self, msg: MeshMessage):
        """Handle incoming mesh message."""
        # Ignore our own messages
        if msg.from_id == self.my_node_id:
            return

        # Handle direct messages to gateway
        if self._is_direct_message(msg):
            self._handle_mesh_dm(msg)
            return

        # Process commands first
        if self.commands and msg.text.startswith("/"):
            result = self.commands.process(msg)

            # Send reply back to mesh user if any
            if result.reply:
                self._send_reply_to_mesh(msg, result.reply)

            # Handle IRC action (/me)
            if result.irc_action:
                self._send_action_to_irc(msg, result.irc_action)

            # Handle IRC DM (/msg)
            if result.irc_target and result.irc_message:
                self._send_dm_to_irc(msg, result.irc_target, result.irc_message)

            # If command was handled, don't relay as normal message
            if result.handled:
                return

        # Find IRC channel for this mesh channel
        irc_channel = self.mesh_to_irc.get(msg.channel)
        if not irc_channel:
            logger.debug(f"No IRC mapping for mesh channel {msg.channel}")
            return

        node_name = self._get_node_name(msg)

        if self.mode == "puppet" and self.puppets:
            # Puppet mode: message comes from node's own IRC user
            logger.info(f"Mesh->IRC puppet ({irc_channel}): <{node_name}> {msg.text}")
            self.puppets.send_message(
                node_id=msg.from_id,
                node_name=node_name,
                channel=irc_channel,
                message=msg.text,
            )
        else:
            # Relay mode: message comes from bridge bot
            formatted = self._format_mesh_to_irc(msg)
            logger.info(f"Mesh->IRC ({irc_channel}): {formatted}")
            if self.irc:
                self.irc.send_message(irc_channel, formatted)

    def _handle_mesh_dm(self, msg: MeshMessage):
        """Handle a direct message sent to the gateway node."""
        node_name = self._get_node_name(msg)

        if self.dm_channel:
            # Send DMs to dedicated channel
            dm_text = f"[DM from {node_name}] {msg.text}"
            logger.info(f"Mesh DM->IRC ({self.dm_channel}): {dm_text}")
            if self.irc:
                self.irc.send_message(self.dm_channel, dm_text)
        else:
            # No DM channel configured, send to primary channel
            primary_channel = self.mesh_to_irc.get(0)
            if primary_channel and self.irc:
                dm_text = f"[DM from {node_name}] {msg.text}"
                self.irc.send_message(primary_channel, dm_text)

    def _send_reply_to_mesh(self, original_msg: MeshMessage, reply: str):
        """Send a reply back to the mesh user who sent a command."""
        logger.info(f"Command reply to {original_msg.from_id}: {reply}")
        if self.mesh:
            # Send as DM to the user
            self.mesh.send_message(
                text=reply,
                channel=original_msg.channel,
                destination=original_msg.from_id,
            )

    def _send_action_to_irc(self, msg: MeshMessage, action: str):
        """Send an action (/me) to IRC on behalf of a mesh user."""
        irc_channel = self.mesh_to_irc.get(msg.channel)
        if not irc_channel:
            return

        node_name = self._get_node_name(msg)

        if self.mode == "puppet" and self.puppets:
            # Use puppet to send action
            logger.info(f"Mesh->IRC action ({irc_channel}): * {node_name} {action}")
            self.puppets.send_action(
                node_id=msg.from_id,
                node_name=node_name,
                channel=irc_channel,
                action=action,
            )
        elif self.irc:
            # Relay mode: send as formatted action from bot
            logger.info(f"Mesh->IRC action ({irc_channel}): * {node_name} {action}")
            self.irc.send_action(irc_channel, f"{node_name} {action}")

    def _send_dm_to_irc(self, msg: MeshMessage, target: str, message: str):
        """Send a DM to an IRC user on behalf of a mesh user."""
        node_name = self._get_node_name(msg)

        if self.mode == "puppet" and self.puppets:
            # Use puppet to send DM (creates puppet if needed)
            puppet = self.puppets.get_or_create_puppet(msg.from_id, node_name)
            if puppet and puppet.connected:
                logger.info(f"Mesh->IRC DM: {node_name} -> {target}: {message}")
                self.puppets._send(puppet, f"PRIVMSG {target} :{message}")
        elif self.irc:
            # Relay mode: send DM from bridge bot with attribution
            dm_text = f"[From {node_name}] {message}"
            logger.info(f"Mesh->IRC DM (via bridge): -> {target}: {dm_text}")
            self.irc.send_message(target, dm_text)

    def _on_irc_message(self, msg: IRCMessage):
        """Handle incoming IRC message."""
        mesh_channel = self.irc_to_mesh.get(msg.channel)
        if mesh_channel is None:
            # Check if it's from DM channel
            if msg.channel == self.dm_channel:
                # Could implement DM replies here
                logger.debug(f"Message in DM channel from {msg.nick}: {msg.text}")
            return

        # Ignore messages from self
        if self.irc and msg.nick == self.irc.nickname:
            return

        # Ignore messages from our puppets (avoid echo)
        if self.mode == "puppet" and self.puppets:
            if self.puppets.is_puppet_nick(msg.nick):
                return

        formatted = self._format_irc_to_mesh(msg)
        logger.info(f"IRC->Mesh (ch={mesh_channel}): {formatted}")

        # Rate limit mesh sends
        if self.rate_limiter.acquire():
            self._send_to_mesh(formatted, mesh_channel)
        elif self.queue_overflow:
            logger.debug("Rate limited, queueing message")
            self.message_queue.append((formatted, mesh_channel, None))
        else:
            logger.warning("Rate limited, dropping message")

    def _send_to_mesh(self, text: str, channel: int, destination: Optional[str] = None):
        """Send a message to the mesh network."""
        if self.mesh:
            # Truncate if too long for mesh (max ~230 bytes)
            if len(text.encode("utf-8")) > 200:
                text = text[:197] + "..."
            self.mesh.send_message(text, channel=channel, destination=destination)

    def _process_queue(self):
        """Background thread to process queued messages."""
        while self.running:
            if self.message_queue and self.rate_limiter.acquire():
                text, channel, dest = self.message_queue.popleft()
                self._send_to_mesh(text, channel, dest)
            time.sleep(0.5)

    def run_forever(self):
        """Run the bridge until interrupted."""
        if not self.start():
            return 1

        # Set up signal handlers
        def signal_handler(sig, frame):
            logger.info("Received shutdown signal")
            self.stop()

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        # Main loop
        while self.running:
            time.sleep(1)

            # Check connections
            if self.irc and not self.irc.is_connected():
                logger.warning("IRC disconnected, attempting reconnect...")
                time.sleep(5)
                self.irc.connect()

        return 0


def setup_logging(config: dict):
    """Configure logging based on config."""
    log_config = config.get("logging", {})
    level = getattr(logging, log_config.get("level", "INFO").upper())

    handlers = [logging.StreamHandler()]

    log_file = log_config.get("file")
    if log_file:
        handlers.append(logging.FileHandler(log_file))

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )


def main():
    parser = argparse.ArgumentParser(description="Meshtastic-IRC Bridge")
    parser.add_argument(
        "-c", "--config",
        default="config.yaml",
        help="Path to config file (default: config.yaml)",
    )
    args = parser.parse_args()

    # Load config for logging setup
    config_path = Path(args.config)
    if not config_path.exists():
        print(f"Config file not found: {args.config}", file=sys.stderr)
        example = config_path.parent / "config.yaml.example"
        if example.exists():
            print(f"Copy the example config and edit it:", file=sys.stderr)
            print(f"  cp {example} {args.config}", file=sys.stderr)
        else:
            print("See config.yaml.example for a template.", file=sys.stderr)
        return 1

    try:
        with open(args.config) as f:
            config = yaml.safe_load(f)
        setup_logging(config)
    except Exception as e:
        print(f"Failed to load config: {e}", file=sys.stderr)
        return 1

    # Run bridge
    bridge = MeshIRCBridge(args.config)
    return bridge.run_forever()


if __name__ == "__main__":
    sys.exit(main())
