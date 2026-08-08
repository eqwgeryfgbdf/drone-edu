"""
CoDrone EDU Gesture Control Demo — Streamlit entrypoint.

Launch:
    streamlit run app.py
"""

from __future__ import annotations

import atexit
import sys
from pathlib import Path

import streamlit as st

# Ensure project root is importable when launched via `streamlit run app.py`.
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.core.command_bus import CommandBus
from src.core.config import load_gestures, load_settings, resolve_project_path
from src.core.logging_utils import setup_logging
from src.core.settings_io import list_controller_ports, write_live_control_settings
from src.core.state import AppState, ConnectionStatus
from src.dashboard.ui import render_dashboard
from src.drone.controller import DroneController
from src.vision.worker import VisionWorker


def _bootstrap() -> tuple[AppState, CommandBus, dict]:
    """Create or reuse session-scoped runtime objects."""
    settings = load_settings()
    gestures = load_gestures()
    log_cfg = settings.get("logging", {})
    setup_logging(
        level=str(log_cfg.get("level", "INFO")),
        log_dir=PROJECT_ROOT / "logs",
    )

    if "app_runtime" not in st.session_state:
        state = AppState(simulation_mode=bool(settings.get("simulation_mode", True)))
        if state.simulation_mode:
            state.set_connection(ConnectionStatus.SIMULATION)
        command_bus = CommandBus()
        csv_path = resolve_project_path(str(log_cfg.get("csv_path", "logs/flight_log.csv")))

        controller = DroneController(
            state,
            command_bus,
            simulation_mode=bool(settings.get("simulation_mode", True)),
            drone_settings=settings.get("drone", {}),
            sensor_settings=settings.get("sensors", {}),
            csv_path=csv_path,
        )
        vision = VisionWorker(
            state,
            command_bus,
            camera_settings=settings.get("camera", {}),
            gesture_settings=settings.get("gesture", {}),
            model_path=resolve_project_path(
                str(settings.get("gesture", {}).get("model_path", "models/gesture_recognizer.task"))
            ),
            gesture_mappings=dict(gestures.get("mappings", {})),
            enabled_intents=set(gestures.get("enabled_intents", [])),
            display_names=dict(gestures.get("display_names", {})),
        )

        controller.start()
        # Auto-connect in simulation so telemetry starts immediately.
        if state.simulation_mode:
            from src.core.command_bus import CommandType

            command_bus.publish_type(CommandType.CONNECT, source="bootstrap")

        st.session_state["app_runtime"] = {
            "state": state,
            "command_bus": command_bus,
            "controller": controller,
            "vision": vision,
            "settings": settings,
            "vision_started": False,
        }

        def _shutdown() -> None:
            runtime = st.session_state.get("app_runtime")
            if not runtime:
                return
            runtime["vision"].stop()
            runtime["controller"].stop()

        atexit.register(_shutdown)

    runtime = st.session_state["app_runtime"]
    return runtime["state"], runtime["command_bus"], runtime


def _render_live_setup_sidebar(state: AppState, settings: dict) -> None:
    """Sidebar section: how to enable physical CoDrone control."""
    st.subheader("實體控制設定")
    drone_cfg = settings.get("drone") or {}
    current_port = drone_cfg.get("port_name") or ""
    mode_label = "模擬 SIM" if state.simulation_mode else "實體 LIVE"
    st.caption(f"目前執行中：{mode_label}　設定檔 port：`{current_port or 'auto'}`")

    with st.expander("如何切換到實體控制", expanded=not state.simulation_mode):
        st.markdown(
            """
**連線路徑（必經遙控器）**

```text
電腦 --USB 資料線--> 遙控器（LINK）--無線--> 無人機
```

**步驟**

1. 取下螺旋槳（第一次務必無槳）
2. 無人機與遙控器開機並已配對（燈號常亮）
3. 遙控器用原廠資料線接電腦，切到 **LINK**
4. 下方選「實體 LIVE」並儲存設定
5. **重啟** Streamlit（`Ctrl+C` 後再 `streamlit run app.py`）
6. 儀表板按「連線」，確認電量／距離有數值
7. 先用按鈕測起飛／懸停／降落，再開攝影機手勢

也可在終端機執行：

```bash
./scripts/set-live-mode.sh on
./scripts/set-live-mode.sh status
```
            """
        )

    try:
        ports = list_controller_ports()
    except Exception as exc:  # noqa: BLE001 — surface port scan failures in UI
        ports = []
        st.warning(f"無法列出序列埠：{exc}")

    port_options = ["（自動偵測）"]
    port_options.extend(p["device"] for p in ports)
    if current_port and current_port not in port_options:
        port_options.append(current_port)

    default_index = 0
    if current_port and current_port in port_options:
        default_index = port_options.index(current_port)
    else:
        for idx, port in enumerate(ports):
            if port.get("likely_codrone"):
                default_index = idx + 1
                break

    desired_live = st.radio(
        "目標模式（寫入 settings.yaml）",
        options=["模擬 SIM", "實體 LIVE"],
        index=0 if state.simulation_mode else 1,
        horizontal=True,
    )
    selected_port_label = st.selectbox("遙控器序列埠", options=port_options, index=default_index)
    selected_port = (
        None if selected_port_label == "（自動偵測）" else selected_port_label
    )

    if ports:
        likely = [p["device"] for p in ports if p.get("likely_codrone")]
        if likely:
            st.success("偵測到可能的 CoDrone 遙控器：" + ", ".join(likely))
        else:
            st.info("未看到 VID=1155 的 CoDrone 埠；請確認 LINK／USB 資料線。")

    if st.button("儲存實體控制設定", use_container_width=True):
        try:
            path = write_live_control_settings(
                simulation_mode=(desired_live == "模擬 SIM"),
                port_name=selected_port or "",
            )
            st.success(f"已寫入 `{path.name}`。請重啟 Streamlit 後生效。")
            st.session_state["restart_required"] = True
        except Exception as exc:
            st.error(f"寫入設定失敗：{exc}")

    if st.session_state.get("restart_required"):
        st.warning("設定已變更：請在終端機 `Ctrl+C`，再執行 `streamlit run app.py`。")


def main() -> None:
    """Streamlit page configuration and dashboard loop."""
    st.set_page_config(
        page_title="CoDrone EDU Gesture Control",
        page_icon="🛫",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    state, command_bus, runtime = _bootstrap()
    settings = runtime["settings"]

    with st.sidebar:
        st.header("DEMO 控制台")
        st.write(
            "執行中模式以**啟動當下**的 `settings.yaml` 為準。"
            "切換模擬／實體後必須重啟 Streamlit。"
        )
        st.metric("執行中", "模擬 SIM" if state.simulation_mode else "實體 LIVE")

        start_cam = st.toggle("啟用攝影機／手勢", value=bool(runtime.get("vision_started")))
        if start_cam and not runtime["vision_started"]:
            runtime["vision"].start()
            runtime["vision_started"] = True
            state.workers_running = True
            state.add_event("Camera / gesture enabled", source="ui")
        if not start_cam and runtime["vision_started"]:
            runtime["vision"].stop()
            runtime["vision_started"] = False
            state.workers_running = False
            state.add_event("Camera / gesture disabled", source="ui")

        st.divider()
        _render_live_setup_sidebar(state, settings)
        st.divider()
        st.markdown(
            """
**手勢（MVP）**
- 👍 `Thumb_Up` → 起飛
- ✋ `Open_Palm` → 懸停
- ✊ `Closed_Fist` → 降落
- 雙手張開 → 緊急停止

方向控制預設關閉，可在 `config/gestures.yaml` 啟用。
            """
        )

    refresh_ms = int(settings.get("ui", {}).get("refresh_ms", 200))
    render_dashboard(state, command_bus, refresh_ms=refresh_ms)


if __name__ == "__main__":
    main()
