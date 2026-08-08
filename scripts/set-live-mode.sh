#!/usr/bin/env bash
# Enable or disable physical (live) CoDrone control in settings.yaml.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

MODE="${1:-}"
if [[ -z "$MODE" || "$MODE" == "-h" || "$MODE" == "--help" ]]; then
  cat <<'EOF'
用法:
  ./scripts/set-live-mode.sh on     # 實體控制（simulation_mode: false）
  ./scripts/set-live-mode.sh off    # 模擬模式（simulation_mode: true）
  ./scripts/set-live-mode.sh status # 顯示目前設定與序列埠

切換後請重啟 Streamlit:
  source .venv/bin/activate && streamlit run app.py
EOF
  exit 0
fi

if [[ ! -d .venv ]]; then
  echo "Missing .venv — create it first."
  exit 1
fi

# shellcheck disable=SC1091
source .venv/bin/activate

python - "$MODE" <<'PY'
from __future__ import annotations

import sys

from src.core.settings_io import list_controller_ports, read_settings, write_live_control_settings

mode = sys.argv[1]
settings = read_settings()
ports = list_controller_ports()
likely = [p for p in ports if p.get("likely_codrone")]

if mode == "status":
    print("simulation_mode =", settings.get("simulation_mode"))
    print("port_name       =", (settings.get("drone") or {}).get("port_name"))
    print("serial ports:")
    for port in ports:
        mark = " ★ CoDrone?" if port.get("likely_codrone") else ""
        label = port.get("product") or port.get("description")
        print(f"  {port['device']}  vid={port['vid']}  {label}{mark}")
    raise SystemExit(0)

if mode == "on":
    port = (settings.get("drone") or {}).get("port_name")
    if not port and likely:
        port = likely[0]["device"]
        print(f"Auto-selected controller port: {port}")
    path = write_live_control_settings(simulation_mode=False, port_name=port)
    print(f"Wrote live mode → {path}")
    print("simulation_mode: false")
    print("port_name:", port)
    print()
    print("下一步:")
    print("  1. 遙控器 USB + LINK，無人機開機")
    print("  2. Ctrl+C 停掉舊 Streamlit")
    print("  3. streamlit run app.py")
    print("  4. 儀表板按「連線」；先無槳測試")
    raise SystemExit(0)

if mode == "off":
    path = write_live_control_settings(simulation_mode=True)
    print(f"Wrote simulation mode → {path}")
    print("simulation_mode: true")
    print("重啟 Streamlit 後會回到模擬。")
    raise SystemExit(0)

print(f"Unknown mode: {mode}", file=sys.stderr)
raise SystemExit(1)
PY
