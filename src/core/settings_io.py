"""Persist selected live/sim settings back to config/settings.yaml."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

from src.core.config import CONFIG_DIR, load_settings


SETTINGS_PATH = CONFIG_DIR / "settings.yaml"


def read_settings(path: Path | None = None) -> dict[str, Any]:
    """Load current settings.yaml."""
    return load_settings(path or SETTINGS_PATH)


def write_live_control_settings(
    *,
    simulation_mode: bool,
    port_name: Optional[str] = None,
    path: Path | None = None,
) -> Path:
    """
    Update simulation_mode / drone.port_name in settings.yaml.

    Uses surgical text replacement so comments and other keys are preserved.
    """
    target = path or SETTINGS_PATH
    if not target.exists():
        raise FileNotFoundError(f"Settings file not found: {target}")

    text = target.read_text(encoding="utf-8")
    sim_value = "true" if simulation_mode else "false"
    if re.search(r"(?m)^simulation_mode:\s*.*$", text):
        text = re.sub(
            r"(?m)^simulation_mode:\s*.*$",
            f"simulation_mode: {sim_value}",
            text,
            count=1,
        )
    else:
        text = f"simulation_mode: {sim_value}\n" + text

    if port_name is not None:
        port_yaml = "null" if not str(port_name).strip() else str(port_name).strip()
        if re.search(r"(?m)^(\s*)port_name:\s*.*$", text):
            text = re.sub(
                r"(?m)^(\s*)port_name:\s*.*$",
                rf"\1port_name: {port_yaml}",
                text,
                count=1,
            )
        else:
            # Insert under drone: block if present.
            if re.search(r"(?m)^drone:\s*$", text):
                text = re.sub(
                    r"(?m)^drone:\s*$",
                    f"drone:\n  port_name: {port_yaml}",
                    text,
                    count=1,
                )
            else:
                text += f"\ndrone:\n  port_name: {port_yaml}\n"

    target.write_text(text, encoding="utf-8")
    return target


def list_controller_ports() -> list[dict[str, Any]]:
    """
    List serial ports; CoDrone EDU controller typically uses USB VID 1155.
    """
    try:
        from serial.tools import list_ports
    except ImportError as exc:
        raise RuntimeError("pyserial is required to list ports") from exc

    results: list[dict[str, Any]] = []
    for port in list_ports.comports():
        results.append(
            {
                "device": port.device,
                "vid": port.vid,
                "pid": port.pid,
                "manufacturer": port.manufacturer,
                "product": port.product,
                "description": port.description,
                "likely_codrone": port.vid == 1155,
            }
        )
    return results
