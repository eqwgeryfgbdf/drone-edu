"""CoDrone EDU controller with simulation mode and safety gating."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Optional

from src.core.command_bus import CommandBus, CommandType, FlightCommand
from src.core.logging_utils import append_csv_event, get_logger
from src.core.state import AppState, ConnectionStatus, FlightPhase
from src.drone.safety import SafetyGuard, SafetyLimits
from src.drone.sensors import SensorReader, SimulatedSensorReader

logger = get_logger()


class DroneController:
    """
    Sole facade for CoDrone EDU SDK calls.

    Vision modules must never import or call the SDK directly.
    All commands arrive via CommandBus and support simulation_mode.
    """

    def __init__(
        self,
        state: AppState,
        command_bus: CommandBus,
        *,
        simulation_mode: bool,
        drone_settings: dict[str, Any],
        sensor_settings: dict[str, Any],
        csv_path: Path,
    ) -> None:
        self.state = state
        self.command_bus = command_bus
        self.simulation_mode = simulation_mode
        self.settings = drone_settings
        self.sensor_settings = sensor_settings
        self.csv_path = csv_path

        self._drone: Any = None
        self._sensor_reader: Optional[SensorReader] = None
        self._sim_sensors = SimulatedSensorReader()
        self._safety = SafetyGuard(
            SafetyLimits(
                min_height_cm=float(drone_settings.get("min_height_cm", 20)),
                max_height_cm=float(drone_settings.get("max_height_cm", 150)),
                min_front_range_cm=float(drone_settings.get("min_front_range_cm", 40)),
            )
        )
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._is_flying = False
        self._last_sensor_times: dict[str, float] = {}
        self._pulse_m = float(drone_settings.get("pulse_distance_m", 0.25))
        self._pulse_speed = float(drone_settings.get("pulse_speed_mps", 0.5))

        if simulation_mode:
            self.state.simulation_mode = True
            self.state.set_connection(ConnectionStatus.SIMULATION)

    def start(self) -> None:
        """Start the drone command + sensor worker thread."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="drone-worker", daemon=True)
        self._thread.start()
        self.state.add_event("Drone worker started", source="drone")

    def stop(self) -> None:
        """Stop worker and attempt a safe disconnect."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        self._safe_disconnect()

    def _run(self) -> None:
        """Main worker loop: drain commands and poll sensors."""
        while not self._stop_event.is_set():
            command = self.command_bus.get(timeout=0.05)
            if command is not None:
                self._handle_command(command)
            self._poll_sensors_if_due()

    def _handle_command(self, command: FlightCommand) -> None:
        """Execute one flight command after safety evaluation."""
        decision = self._safety.evaluate(
            command.command_type,
            self.state.sensors,
            is_flying=self._is_flying,
        )
        if not decision.allowed:
            message = f"Blocked {command.command_type.value}: {decision.reason}"
            logger.warning(message)
            self.state.add_event(message, level="WARN", source="safety")
            append_csv_event(
                self.csv_path,
                level="WARN",
                source="safety",
                message=message,
                extra={"command": command.command_type.value},
            )
            return

        try:
            handler = {
                CommandType.CONNECT: self._connect,
                CommandType.DISCONNECT: self._disconnect,
                CommandType.TAKEOFF: self._takeoff,
                CommandType.LAND: self._land,
                CommandType.HOVER: self._hover,
                CommandType.FORWARD: lambda: self._pulse_move(forward=self._pulse_m),
                CommandType.BACKWARD: lambda: self._pulse_move(forward=-self._pulse_m),
                CommandType.LEFT: lambda: self._pulse_move(left=self._pulse_m),
                CommandType.RIGHT: lambda: self._pulse_move(left=-self._pulse_m),
                CommandType.UP: lambda: self._pulse_move(up=self._pulse_m),
                CommandType.DOWN: lambda: self._pulse_move(up=-self._pulse_m),
                CommandType.EMERGENCY_STOP: self._emergency_stop,
                CommandType.RESET_AXES: self._reset_axes,
            }.get(command.command_type)

            if handler is None:
                raise ValueError(f"Unhandled command type: {command.command_type}")

            handler()
            message = (
                f"{'[SIM] ' if self.simulation_mode else ''}"
                f"{command.command_type.value} via {command.source}"
            )
            logger.info(message)
            self.state.add_event(message, source=command.source)
            append_csv_event(
                self.csv_path,
                level="INFO",
                source=command.source,
                message=message,
                extra={
                    "command": command.command_type.value,
                    "simulation": self.simulation_mode,
                },
            )
        except Exception as exc:
            error_message = f"Command {command.command_type.value} failed: {exc}"
            logger.exception(error_message)
            self.state.add_event(error_message, level="ERROR", source="drone")
            self.state.set_flight_phase(FlightPhase.ERROR)
            self.state.set_connection(
                ConnectionStatus.ERROR if not self.simulation_mode else ConnectionStatus.SIMULATION,
                error=str(exc),
            )
            append_csv_event(
                self.csv_path,
                level="ERROR",
                source="drone",
                message=error_message,
            )
            if self.settings.get("prefer_soft_land_on_error", True) and self._is_flying:
                try:
                    self._land()
                except Exception as land_exc:  # noqa: BLE001
                    logger.error("Soft land after error failed: %s", land_exc)
                    self._emergency_stop()

    def _connect(self) -> None:
        """
        Open a serial link to the CoDrone EDU *controller*, then verify the drone.

        Hardware path (required for live mode):
          Computer --USB data cable--> Controller (LINK mode) --radio--> Drone

        SDK `connect()` / `pair()` open the controller serial port (not the drone
        directly). The controller must already be radio-paired with the aircraft.
        """
        if self.simulation_mode:
            self.state.set_connection(ConnectionStatus.SIMULATION)
            self.state.add_event("Simulation mode armed (no hardware)", source="drone")
            return

        self.state.set_connection(ConnectionStatus.CONNECTING)
        try:
            from src.drone.sdk_compat import load_drone_class

            droneClass = load_drone_class()
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(f"Failed to import CoDrone EDU SDK: {exc}") from exc

        port_name = self.settings.get("port_name")
        port_label = str(port_name) if port_name else "auto-detect"
        self.state.add_event(
            f"Opening controller serial port ({port_label}) — ensure LINK mode",
            source="drone",
        )

        drone = droneClass()
        timeout = float(self.settings.get("pair_timeout_sec", 8.0))
        deadline = time.time() + timeout
        last_error: Optional[Exception] = None
        while time.time() < deadline:
            try:
                # Prefer connect(); pair() is an alias that also opens the controller.
                connected = False
                if hasattr(drone, "connect"):
                    connected = bool(drone.connect(port_name) if port_name else drone.connect())
                elif hasattr(drone, "pair"):
                    connected = bool(drone.pair(port_name) if port_name else drone.pair())
                else:
                    raise RuntimeError("codrone-edu Drone has neither connect() nor pair()")

                if not connected:
                    raise RuntimeError(
                        "Controller serial open returned False. "
                        "Check USB data cable, LINK mode, and port_name."
                    )

                self._drone = drone
                self._sensor_reader = SensorReader(drone)
                self.state.set_connection(ConnectionStatus.CONNECTED)
                self.state.add_event(
                    "Connected via controller (USB serial → radio link)",
                    source="drone",
                )
                return
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                time.sleep(0.25)

        raise TimeoutError(
            f"Failed to open controller within {timeout:.1f}s"
            + (f": {last_error}" if last_error else "")
            + ". Checklist: (1) 遙控器用原廠資料線接電腦 "
            "(2) 遙控器切到 LINK 模式 "
            "(3) 無人機已開機且與遙控器已配對 "
            "(4) 必要時在 settings.yaml 設定 drone.port_name"
        )

    def _disconnect(self) -> None:
        """Land if needed and close the SDK connection."""
        if self._is_flying:
            self._land()
        self._safe_disconnect()
        self.state.set_connection(
            ConnectionStatus.SIMULATION if self.simulation_mode else ConnectionStatus.DISCONNECTED
        )
        self.state.add_event("Disconnected", source="drone")

    def _safe_disconnect(self) -> None:
        """Close SDK resources without raising."""
        if self._drone is None:
            return
        try:
            if hasattr(self._drone, "close"):
                self._drone.close()
        except Exception as exc:  # noqa: BLE001
            logger.warning("drone.close() failed: %s", exc)
        finally:
            self._drone = None
            self._sensor_reader = None
            self._is_flying = False

    def _takeoff(self) -> None:
        """Take off and enter hover phase."""
        self.state.set_flight_phase(FlightPhase.TAKING_OFF)
        if self.simulation_mode:
            time.sleep(0.4)
            self._is_flying = True
            self._sim_sensors.set_flying(True)
        else:
            self._require_drone().takeoff()
            self._is_flying = True
        self.state.set_flight_phase(FlightPhase.HOVERING)

    def _land(self) -> None:
        """Soft land."""
        self.state.set_flight_phase(FlightPhase.LANDING)
        if self.simulation_mode:
            time.sleep(0.4)
            self._is_flying = False
            self._sim_sensors.set_flying(False)
        else:
            if self._drone is not None:
                self._drone.land()
            self._is_flying = False
        self.state.emergency_latched = False
        self.state.set_flight_phase(FlightPhase.IDLE)

    def _hover(self) -> None:
        """Hover / zero horizontal motion."""
        if not self._is_flying:
            return
        self.state.set_flight_phase(FlightPhase.HOVERING)
        if self.simulation_mode:
            self._sim_sensors.nudge("hover")
            return
        drone = self._require_drone()
        self._reset_axes_on(drone)
        if hasattr(drone, "hover"):
            drone.hover(0.5)

    def _pulse_move(
        self,
        *,
        forward: float = 0.0,
        left: float = 0.0,
        up: float = 0.0,
    ) -> None:
        """Execute a short relative move, then return to hover."""
        if not self._is_flying:
            return
        self.state.set_flight_phase(FlightPhase.MOVING)
        if self.simulation_mode:
            if forward > 0:
                self._sim_sensors.nudge("forward")
            if up > 0:
                self._sim_sensors.nudge("up")
            if up < 0:
                self._sim_sensors.nudge("down")
            time.sleep(0.2)
            self.state.set_flight_phase(FlightPhase.HOVERING)
            return

        drone = self._require_drone()
        if hasattr(drone, "move_distance"):
            drone.move_distance(forward, left, up, self._pulse_speed)
        else:
            # Fallback: set axes briefly then reset.
            if forward:
                drone.set_pitch(40 if forward > 0 else -40)
            if left:
                drone.set_roll(-40 if left > 0 else 40)
            if up:
                drone.set_throttle(40 if up > 0 else -40)
            drone.move(0.6)
            self._reset_axes_on(drone)
        self.state.set_flight_phase(FlightPhase.HOVERING)

    def _emergency_stop(self) -> None:
        """Cut motors immediately — use only for true emergencies."""
        self.state.emergency_latched = True
        self.state.set_flight_phase(FlightPhase.EMERGENCY)
        if self.simulation_mode:
            self._is_flying = False
            self._sim_sensors.set_flying(False)
            self.state.add_event("[SIM] emergency_stop — motors cut", level="ERROR", source="drone")
            return
        if self._drone is not None and hasattr(self._drone, "emergency_stop"):
            self._drone.emergency_stop()
        self._is_flying = False

    def _reset_axes(self) -> None:
        """Zero roll/pitch/yaw/throttle when no hand is detected."""
        if self.simulation_mode:
            return
        if self._drone is None or not self._is_flying:
            return
        self._reset_axes_on(self._drone)
        self.state.set_flight_phase(FlightPhase.HOVERING)

    def _reset_axes_on(self, drone: Any) -> None:
        """Call reset_move / reset_move_values if available."""
        if hasattr(drone, "reset_move"):
            drone.reset_move()
        elif hasattr(drone, "reset_move_values"):
            drone.reset_move_values()
        else:
            for setter, value in (
                ("set_roll", 0),
                ("set_pitch", 0),
                ("set_yaw", 0),
                ("set_throttle", 0),
            ):
                if hasattr(drone, setter):
                    getattr(drone, setter)(value)

    def _require_drone(self) -> Any:
        """Return the live drone instance or raise."""
        if self._drone is None:
            raise RuntimeError("Drone is not connected. Press 連線 first.")
        return self._drone

    def _poll_sensors_if_due(self) -> None:
        """Rate-limited sensor polling for battery / attitude / range."""
        now = time.time()
        # Use the fastest interval as the poll cadence; filter fields by age if needed.
        attitude_hz = float(self.sensor_settings.get("attitude_hz", 8))
        interval = 1.0 / max(attitude_hz, 0.1)
        last = self._last_sensor_times.get("all", 0.0)
        if now - last < interval:
            return
        self._last_sensor_times["all"] = now

        if self.simulation_mode or self._sensor_reader is None:
            snapshot = self._sim_sensors.read()
        else:
            snapshot = self._sensor_reader.read()
        self.state.update_sensors(snapshot)
