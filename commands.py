"""
Command handler for mesh-side slash commands.

Mesh users can send IRC-style commands that the bridge interprets
and executes on their behalf.
"""

import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Optional

if TYPE_CHECKING:
    from bridge import MeshIRCBridge
    from mesh_client import MeshMessage

logger = logging.getLogger(__name__)


@dataclass
class CommandResult:
    """Result of a command execution."""
    # If True, don't relay the message to IRC
    handled: bool = False
    # Optional reply to send back to the mesh user
    reply: Optional[str] = None
    # Optional IRC action to perform instead of normal message
    irc_action: Optional[str] = None
    # Optional IRC target for /msg
    irc_target: Optional[str] = None
    irc_message: Optional[str] = None


class CommandHandler:
    """
    Handles slash commands from mesh users.

    Commands are processed before messages are relayed to IRC,
    allowing mesh users to interact with IRC features.
    """

    def __init__(self, bridge: "MeshIRCBridge"):
        self.bridge = bridge
        self.start_time = time.time()

        # Command registry: name -> (handler, description)
        self.commands: dict[str, tuple[Callable, str]] = {
            "me": (self._cmd_me, "Send an action (/me waves)"),
            "msg": (self._cmd_msg, "DM an IRC user (/msg nick message)"),
            "names": (self._cmd_names, "List users in channel"),
            "topic": (self._cmd_topic, "Show channel topic"),
            "ping": (self._cmd_ping, "Check bridge status"),
            "nodes": (self._cmd_nodes, "List mesh nodes"),
            "signal": (self._cmd_signal, "Show signal stats for nodes"),
            "pos": (self._cmd_pos, "Share your GPS position"),
            "help": (self._cmd_help, "Show available commands"),
        }

    def process(self, msg: "MeshMessage") -> CommandResult:
        """
        Process a mesh message, handling any commands.

        Returns CommandResult indicating what to do with the message.
        """
        text = msg.text.strip()

        # Not a command
        if not text.startswith("/"):
            return CommandResult(handled=False)

        # Parse command and args
        parts = text[1:].split(None, 1)
        if not parts:
            return CommandResult(handled=False)

        cmd_name = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        # Look up handler
        if cmd_name not in self.commands:
            return CommandResult(
                handled=True,
                reply=f"Unknown command: /{cmd_name}. Try /help",
            )

        handler, _ = self.commands[cmd_name]

        try:
            return handler(msg, args)
        except Exception as e:
            logger.error(f"Command error: {e}")
            return CommandResult(
                handled=True,
                reply=f"Error: {e}",
            )

    def _cmd_me(self, msg: "MeshMessage", args: str) -> CommandResult:
        """/me <action> - Send an action message."""
        if not args:
            return CommandResult(handled=True, reply="Usage: /me <action>")

        return CommandResult(
            handled=True,
            irc_action=args,
        )

    def _cmd_msg(self, msg: "MeshMessage", args: str) -> CommandResult:
        """/msg <nick> <message> - Send a private message."""
        parts = args.split(None, 1)
        if len(parts) < 2:
            return CommandResult(handled=True, reply="Usage: /msg <nick> <message>")

        target, message = parts
        return CommandResult(
            handled=True,
            irc_target=target,
            irc_message=message,
        )

    def _cmd_names(self, msg: "MeshMessage", args: str) -> CommandResult:
        """/names - List users in the IRC channel."""
        if not self.bridge.irc:
            return CommandResult(handled=True, reply="IRC not connected")

        # Get channel for this mesh channel
        irc_channel = self.bridge.mesh_to_irc.get(msg.channel)
        if not irc_channel:
            return CommandResult(handled=True, reply="No IRC channel mapped")

        # In puppet mode, list puppets + regular IRC users
        users = []

        # Add puppet users (mesh nodes)
        if self.bridge.puppets:
            for node_id, puppet in self.bridge.puppets.puppets.items():
                if puppet.connected and irc_channel in puppet.channels:
                    users.append(f"[M]{puppet.nickname}")

        # Note: Getting actual IRC user list requires NAMES query
        # For now, we note that IRC users are also present
        reply = f"Mesh users in {irc_channel}: {', '.join(users) if users else 'none'}"
        reply += " (IRC users also present)"

        return CommandResult(handled=True, reply=reply)

    def _cmd_topic(self, msg: "MeshMessage", args: str) -> CommandResult:
        """/topic - Show channel topic."""
        irc_channel = self.bridge.mesh_to_irc.get(msg.channel)
        if not irc_channel:
            return CommandResult(handled=True, reply="No IRC channel mapped")

        # We'd need to track topics from IRC 332 responses
        # For now, return a placeholder
        return CommandResult(
            handled=True,
            reply=f"Topic for {irc_channel}: (topic tracking not yet implemented)",
        )

    def _cmd_ping(self, msg: "MeshMessage", args: str) -> CommandResult:
        """/ping - Check bridge status."""
        uptime = int(time.time() - self.start_time)
        hours, remainder = divmod(uptime, 3600)
        minutes, seconds = divmod(remainder, 60)

        irc_status = "connected" if self.bridge.irc and self.bridge.irc.is_connected() else "disconnected"
        mesh_status = "connected" if self.bridge.mesh else "disconnected"

        node_count = len(self.bridge.mesh.nodes) if self.bridge.mesh else 0

        reply = f"Pong! Up {hours}h{minutes}m{seconds}s | IRC: {irc_status} | Mesh: {mesh_status} | Nodes: {node_count}"

        return CommandResult(handled=True, reply=reply)

    def _cmd_nodes(self, msg: "MeshMessage", args: str) -> CommandResult:
        """/nodes - List known mesh nodes."""
        if not self.bridge.mesh:
            return CommandResult(handled=True, reply="Mesh not connected")

        nodes = self.bridge.mesh.nodes
        if not nodes:
            return CommandResult(handled=True, reply="No nodes discovered yet")

        # Format node list (keep it short for mesh)
        node_list = []
        for node_id, node in list(nodes.items())[:10]:  # Limit to 10
            name = node.short_name or node.long_name or node_id[-4:]
            # Show last heard time if available
            if node.last_heard:
                ago = int(time.time() - node.last_heard)
                if ago < 60:
                    time_str = f"{ago}s"
                elif ago < 3600:
                    time_str = f"{ago // 60}m"
                else:
                    time_str = f"{ago // 3600}h"
                node_list.append(f"{name}({time_str})")
            else:
                node_list.append(name)

        reply = f"Nodes: {', '.join(node_list)}"
        if len(nodes) > 10:
            reply += f" (+{len(nodes) - 10} more)"

        return CommandResult(handled=True, reply=reply)

    def _cmd_signal(self, msg: "MeshMessage", args: str) -> CommandResult:
        """/signal [node] - Show signal stats."""
        if not self.bridge.mesh:
            return CommandResult(handled=True, reply="Mesh not connected")

        nodes = self.bridge.mesh.nodes

        if args:
            # Find specific node
            search = args.lower()
            found = None
            for node_id, node in nodes.items():
                if (search in (node.short_name or "").lower() or
                    search in (node.long_name or "").lower() or
                    search in node_id.lower()):
                    found = node
                    break

            if not found:
                return CommandResult(handled=True, reply=f"Node '{args}' not found")

            snr = f"SNR:{found.snr:.1f}dB" if found.snr else "SNR:?"
            rssi = f"RSSI:{found.rssi}dBm" if found.rssi else "RSSI:?"
            return CommandResult(
                handled=True,
                reply=f"{found.short_name or found.long_name}: {snr} {rssi}",
            )
        else:
            # Show stats for recent nodes
            recent = sorted(
                [(n.short_name or n.long_name or nid[-4:], n.snr)
                 for nid, n in nodes.items() if n.snr is not None],
                key=lambda x: x[1],
                reverse=True,
            )[:5]

            if not recent:
                return CommandResult(handled=True, reply="No signal data available")

            stats = ", ".join(f"{name}:{snr:.0f}dB" for name, snr in recent)
            return CommandResult(handled=True, reply=f"Signal: {stats}")

    def _cmd_pos(self, msg: "MeshMessage", args: str) -> CommandResult:
        """/pos - Share your GPS position to IRC."""
        if not self.bridge.mesh:
            return CommandResult(handled=True, reply="Mesh not connected")

        # Get sender's node info
        node = self.bridge.mesh.nodes.get(msg.from_id)
        if not node:
            return CommandResult(handled=True, reply="Node info not found")

        if node.latitude is None or node.longitude is None:
            return CommandResult(handled=True, reply="No GPS position available")

        lat = node.latitude
        lon = node.longitude

        lat_dir = "N" if lat >= 0 else "S"
        lon_dir = "E" if lon >= 0 else "W"

        pos_str = f"{abs(lat):.4f}{lat_dir}, {abs(lon):.4f}{lon_dir}"
        osm_link = f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}&zoom=15"

        # This gets sent to IRC as a regular message
        name = node.short_name or node.long_name or msg.from_id[-4:]
        irc_msg = f"[{name} shared location: {pos_str}] {osm_link}"

        # Send to IRC channel
        irc_channel = self.bridge.mesh_to_irc.get(msg.channel)
        if irc_channel and self.bridge.irc:
            self.bridge.irc.send_message(irc_channel, irc_msg)

        return CommandResult(handled=True, reply=f"Shared: {pos_str}")

    def _cmd_help(self, msg: "MeshMessage", args: str) -> CommandResult:
        """/help - Show available commands."""
        # Keep it short for mesh bandwidth
        cmd_list = ", ".join(f"/{name}" for name in sorted(self.commands.keys()))
        return CommandResult(
            handled=True,
            reply=f"Commands: {cmd_list}",
        )
