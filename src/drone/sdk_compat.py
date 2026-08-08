"""
Compatibility shims for codrone-edu under Streamlit / desktop asyncio.

codrone_edu.drone monkey-patches asyncio.sleep with interruptible_sleep that
calls checkInterrupt(). That symbol only exists in the web/emscripten build.
On desktop, Streamlit's event loop then crashes with:

    NameError: name 'checkInterrupt' is not defined

…which makes the whole process exit right after Connect succeeds.
"""

from __future__ import annotations

import asyncio
from typing import Any, Type


def load_drone_class() -> Type[Any]:
    """
    Import CoDrone EDU Drone and restore the real asyncio.sleep.

    Always call this instead of `from codrone_edu.drone import Drone`.
    """
    # Capture the real sleep before (or despite) the library patch.
    try:
        from codrone_edu import drone as drone_module
    except ImportError as exc:
        raise RuntimeError(
            "codrone-edu is not installed. Run: pip install -r requirements.txt"
        ) from exc

    original_sleep = getattr(drone_module, "original_asyncio_sleep", None)
    if original_sleep is None:
        # Fallback if the library renames the attribute in a future release.
        original_sleep = asyncio.sleep

    from codrone_edu.drone import Drone  # noqa: WPS433 — intentional late import

    # Undo the broken global patch so Streamlit / uvicorn keep working.
    asyncio.sleep = original_sleep

    # Also provide a no-op checkInterrupt on the module in case anything else
    # still calls the patched sleep path.
    if not hasattr(drone_module, "checkInterrupt"):
        def checkInterrupt() -> None:
            """No-op desktop stand-in for the web interrupter."""
            return None

        drone_module.checkInterrupt = checkInterrupt  # type: ignore[attr-defined]

    return Drone
