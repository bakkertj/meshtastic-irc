"""
Message formatters and utilities for the Meshtastic-IRC bridge.
"""

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class Position:
    """GPS position."""
    latitude: float
    longitude: float
    altitude: Optional[float] = None

    def to_string(self, precision: int = 4) -> str:
        """Format position as string."""
        lat_dir = "N" if self.latitude >= 0 else "S"
        lon_dir = "E" if self.longitude >= 0 else "W"
        result = f"{abs(self.latitude):.{precision}f}{lat_dir}, {abs(self.longitude):.{precision}f}{lon_dir}"
        if self.altitude is not None:
            result += f" ({self.altitude:.0f}m)"
        return result

    def to_osm_link(self) -> str:
        """Generate OpenStreetMap link."""
        return f"https://www.openstreetmap.org/?mlat={self.latitude}&mlon={self.longitude}&zoom=15"

    def to_google_link(self) -> str:
        """Generate Google Maps link."""
        return f"https://maps.google.com/?q={self.latitude},{self.longitude}"


def sanitize_for_irc(text: str) -> str:
    """
    Sanitize text for safe IRC display.
    Removes control characters and limits length.
    """
    # Remove IRC control codes that could cause issues
    text = re.sub(r"[\x00-\x1f\x7f]", "", text)
    # Replace newlines with spaces
    text = text.replace("\n", " ").replace("\r", " ")
    # Collapse multiple spaces
    text = re.sub(r" +", " ", text)
    return text.strip()


def sanitize_for_mesh(text: str) -> str:
    """
    Sanitize text for mesh network.
    Mesh has limited bandwidth, so we trim aggressively.
    """
    # Remove IRC color codes
    text = re.sub(r"\x03\d{0,2}(,\d{0,2})?", "", text)
    # Remove other IRC formatting
    text = re.sub(r"[\x02\x0f\x16\x1d\x1f]", "", text)
    # Remove URLs to save space (optional)
    # text = re.sub(r'https?://\S+', '[link]', text)
    return text.strip()


def truncate_message(text: str, max_bytes: int = 200) -> str:
    """
    Truncate message to fit within byte limit.
    Handles UTF-8 properly to avoid breaking multi-byte characters.
    """
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text

    # Binary search for the right truncation point
    low, high = 0, len(text)
    while low < high:
        mid = (low + high + 1) // 2
        if len(text[:mid].encode("utf-8")) <= max_bytes - 3:  # Room for "..."
            low = mid
        else:
            high = mid - 1

    return text[:low] + "..."


def format_signal_info(snr: Optional[float], rssi: Optional[int]) -> str:
    """Format signal information for display."""
    parts = []
    if snr is not None:
        parts.append(f"SNR:{snr:.1f}dB")
    if rssi is not None:
        parts.append(f"RSSI:{rssi}dBm")
    return " ".join(parts)


def format_node_info(
    short_name: str,
    long_name: Optional[str] = None,
    hw_model: Optional[str] = None,
) -> str:
    """Format node information for display."""
    result = short_name
    if long_name and long_name != short_name:
        result = f"{short_name} ({long_name})"
    if hw_model:
        result += f" [{hw_model}]"
    return result


def parse_irc_action(text: str) -> Optional[str]:
    """
    Parse IRC ACTION (/me) message.
    Returns the action text, or None if not an action.
    """
    if text.startswith("\x01ACTION ") and text.endswith("\x01"):
        return text[8:-1]
    return None


def format_as_action(nick: str, action: str) -> str:
    """Format text as an action message."""
    return f"* {nick} {action}"


class ColorCodes:
    """IRC color codes for optional colorization."""
    WHITE = "\x0300"
    BLACK = "\x0301"
    BLUE = "\x0302"
    GREEN = "\x0303"
    RED = "\x0304"
    BROWN = "\x0305"
    PURPLE = "\x0306"
    ORANGE = "\x0307"
    YELLOW = "\x0308"
    LIGHT_GREEN = "\x0309"
    CYAN = "\x0310"
    LIGHT_CYAN = "\x0311"
    LIGHT_BLUE = "\x0312"
    PINK = "\x0313"
    GREY = "\x0314"
    LIGHT_GREY = "\x0315"
    RESET = "\x0f"
    BOLD = "\x02"
    ITALIC = "\x1d"
    UNDERLINE = "\x1f"


def colorize_node_name(name: str) -> str:
    """Add consistent color to node name based on hash."""
    colors = [
        ColorCodes.BLUE,
        ColorCodes.GREEN,
        ColorCodes.RED,
        ColorCodes.PURPLE,
        ColorCodes.ORANGE,
        ColorCodes.CYAN,
        ColorCodes.PINK,
    ]
    color = colors[hash(name) % len(colors)]
    return f"{color}{name}{ColorCodes.RESET}"
