"""Streamlit real-time dashboard for CoDrone gesture control."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

import streamlit as st

from src.core.command_bus import CommandBus, CommandType
from src.core.state import AppState, SensorSnapshot


def _fmt(value: Optional[float], suffix: str = "", digits: int = 1) -> str:
    """Format optional sensor numbers for metric tiles."""
    if value is None:
        return "—"
    return f"{value:.{digits}f}{suffix}"


def _status_color(status: str) -> str:
    """Return a CSS color for connection status."""
    return {
        "connected": "#1f7a4c",
        "simulation": "#0b6e99",
        "connecting": "#b7791f",
        "disconnected": "#6b7280",
        "error": "#b42318",
    }.get(status, "#6b7280")


def _sensor_chart_data(history: list[SensorSnapshot]) -> dict[str, list[float]]:
    """
    Build a plain dict for st.line_chart (no Plotly).

    Avoids Plotly's lazy pandas import, which races with Streamlit reruns
    and can raise: partially initialized module 'pandas' has no attribute 'Series'.
    """
    chart: dict[str, list[float]] = {}
    if not history:
        return chart

    def collect(key: str, values: list[Optional[float]]) -> None:
        if any(value is not None for value in values):
            chart[key] = [0.0 if value is None else float(value) for value in values]

    collect("高度 cm", [item.height_cm for item in history])
    collect("前方距離 cm", [item.front_range_cm for item in history])
    collect("Roll °", [item.roll_deg for item in history])
    collect("Pitch °", [item.pitch_deg for item in history])
    collect("Yaw °", [item.yaw_deg for item in history])
    collect("電量 %", [item.battery_pct for item in history])
    collect("溫度 °C", [item.temperature_c for item in history])
    return chart


def inject_styles() -> None:
    """Custom dashboard styling — aviation teal, not generic purple AI look."""
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;600;700&family=JetBrains+Mono:wght@400;600&display=swap');

        .stApp {
            background:
                radial-gradient(1200px 600px at 10% -10%, rgba(14, 116, 144, 0.18), transparent 55%),
                radial-gradient(900px 500px at 100% 0%, rgba(15, 118, 110, 0.14), transparent 50%),
                linear-gradient(180deg, #eef3f6 0%, #dfe8ee 100%);
            font-family: 'IBM Plex Sans', sans-serif;
            color: #0f172a;
        }
        h1, h2, h3 { font-family: 'IBM Plex Sans', sans-serif !important; letter-spacing: -0.02em; }
        .brand-title {
            font-size: 1.85rem; font-weight: 700; margin: 0;
            color: #0b3d4a;
        }
        .brand-sub {
            margin: 0.15rem 0 0.8rem; color: #48617a; font-size: 0.95rem;
        }
        .status-pill {
            display: inline-block; padding: 0.25rem 0.7rem; border-radius: 999px;
            color: white; font-size: 0.8rem; font-weight: 600;
            font-family: 'JetBrains Mono', monospace;
        }
        .panel {
            background: rgba(255,255,255,0.72);
            border: 1px solid rgba(15, 55, 70, 0.08);
            border-radius: 14px;
            padding: 0.9rem 1rem;
            backdrop-filter: blur(6px);
        }
        .progress-track {
            width: 100%; height: 10px; background: #d7e2ea; border-radius: 999px; overflow: hidden;
        }
        .progress-fill {
            height: 100%; background: linear-gradient(90deg, #0e7490, #0f766e);
        }
        div[data-testid="stMetric"] {
            background: rgba(255,255,255,0.65);
            border: 1px solid rgba(15,55,70,0.08);
            border-radius: 12px;
            padding: 0.55rem 0.75rem;
        }
        .estop button {
            background: #b42318 !important; color: white !important; border: none !important;
            font-weight: 700 !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_dashboard(
    state: AppState,
    command_bus: CommandBus,
    *,
    refresh_ms: int = 200,
) -> None:
    """Render the dashboard shell; live panels refresh via fragment."""
    inject_styles()

    st.markdown('<p class="brand-title">CoDrone EDU Gesture Control</p>', unsafe_allow_html=True)
    st.markdown(
        '<p class="brand-sub">MediaPipe 手勢辨識 → 安全過濾 → CoDrone EDU 飛行指令</p>',
        unsafe_allow_html=True,
    )

    interval = timedelta(milliseconds=max(refresh_ms, 150))

    @st.fragment(run_every=interval)
    def live_panels() -> None:
        """Auto-refresh camera, sensors, and logs without full-script reruns."""
        snap = state.snapshot()
        gesture = snap["gesture"]
        sensors = snap["sensors"]
        status = snap["connection_status"]

        st.markdown(
            f'<span class="status-pill" style="background:{_status_color(status)}">'
            f"{status.upper()}</span>"
            f'&nbsp;&nbsp;<span style="font-family:JetBrains Mono,monospace;font-size:0.85rem">'
            f'phase={snap["flight_phase"]} · cam {snap["camera_fps"]:.0f} FPS · '
            f'gesture {snap["gesture_fps"]:.0f} FPS · '
            f'{"SIM" if snap["simulation_mode"] else "LIVE"}</span>',
            unsafe_allow_html=True,
        )
        if snap["last_error"]:
            st.error(snap["last_error"])

        left, right = st.columns([1.35, 1], gap="large")

        with left:
            st.subheader("攝影機與手部骨架")
            if snap["frame_jpeg"]:
                st.image(snap["frame_jpeg"], use_container_width=True)
            else:
                st.info("等待攝影機畫面… 請確認已啟動 Workers，並允許攝影機權限。")

            g1, g2, g3 = st.columns(3)
            g1.metric("當前手勢", gesture.label)
            g2.metric("信心值", f"{gesture.confidence:.0%}")
            g3.metric("預計動作", gesture.pending_action)
            progress_pct = int(max(0.0, min(1.0, gesture.confirm_progress)) * 100)
            st.markdown(
                f'<div class="panel"><div style="margin-bottom:0.35rem;font-size:0.85rem">'
                f"確認進度 {progress_pct}%</div>"
                f'<div class="progress-track"><div class="progress-fill" '
                f'style="width:{progress_pct}%"></div></div></div>',
                unsafe_allow_html=True,
            )

        with right:
            st.subheader("連線與感測器")
            m1, m2 = st.columns(2)
            m1.metric("電量", _fmt(sensors.battery_pct, "%", 0))
            m2.metric("高度", _fmt(sensors.height_cm, " cm", 0))
            m3, m4 = st.columns(2)
            m3.metric("前方距離", _fmt(sensors.front_range_cm, " cm", 0))
            m4.metric("溫度", _fmt(sensors.temperature_c, " °C", 1))
            a1, a2, a3 = st.columns(3)
            a1.metric("Roll", _fmt(sensors.roll_deg, "°"))
            a2.metric("Pitch", _fmt(sensors.pitch_deg, "°"))
            a3.metric("Yaw", _fmt(sensors.yaw_deg, "°"))
            st.caption("手指數：" + str(gesture.hand_count))

        chart_col, log_col = st.columns([1.4, 1])
        with chart_col:
            st.subheader("感測器趨勢")
            chart_data = _sensor_chart_data(snap["sensor_history"])
            if chart_data:
                st.line_chart(chart_data, height=280)
            else:
                st.caption("等待感測器資料…")
        with log_col:
            st.subheader("飛行指令與錯誤紀錄")
            events = snap["events"]
            if not events:
                st.write("尚無事件")
            else:
                rows = []
                for event in events[:25]:
                    ts = datetime.fromtimestamp(event.timestamp).strftime("%H:%M:%S")
                    rows.append(
                        {
                            "時間": ts,
                            "等級": event.level,
                            "來源": event.source,
                            "訊息": event.message,
                        }
                    )
                st.dataframe(rows, use_container_width=True, hide_index=True, height=280)

    live_panels()

    st.subheader("控制")
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    if c1.button("連線", use_container_width=True):
        command_bus.publish_type(CommandType.CONNECT, source="ui")
    if c2.button("起飛", use_container_width=True):
        command_bus.publish_type(CommandType.TAKEOFF, source="ui")
    if c3.button("懸停", use_container_width=True):
        command_bus.publish_type(CommandType.HOVER, source="ui")
    if c4.button("降落", use_container_width=True):
        command_bus.publish_type(CommandType.LAND, source="ui")
    with c5:
        st.markdown('<div class="estop">', unsafe_allow_html=True)
        if st.button("緊急停止", use_container_width=True, type="primary"):
            command_bus.publish_type(CommandType.EMERGENCY_STOP, source="ui")
        st.markdown("</div>", unsafe_allow_html=True)
    if c6.button("斷線", use_container_width=True):
        command_bus.publish_type(CommandType.DISCONNECT, source="ui")

    st.caption(
        "連線路徑：電腦 USB → 遙控器（LINK）→ 無人機。"
        "「連線」會開啟遙控器序列埠；手動飛請離開 LINK。"
    )
