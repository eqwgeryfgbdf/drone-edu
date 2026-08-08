# CoDrone EDU Gesture Control Demo

在 Cursor 內啟動的手勢控制無人機即時儀表板。第一版使用 **MediaPipe Gesture Recognizer** 辨識手勢，再透過 **CoDrone EDU Python SDK** 發送飛行指令；介面為 **Streamlit**。

```text
電腦攝影機 → OpenCV → MediaPipe → GestureFilter → CommandBus → DroneController → CoDrone EDU
                                                              ↘ Sensor poll → Dashboard
```

## 快速開始（Cursor）

```bash
cd /Users/roylung/Projects/drone-edu
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/download-model.py
streamlit run app.py
```

瀏覽器開啟後：

1. 側欄開啟「啟用攝影機／手勢」
2. 預設為**模擬模式**（不會對實體無人機下指令）
3. 用 UI 按鈕測試起飛／懸停／降落／緊急停止
4. 對準攝影機比 👍／✋／✊，確認進度條滿後才會進佇列

## 第一版完成標準（MVP）

| 項目 | 狀態 |
|---|---|
| 模擬模式預設開啟 | ✅ |
| 張手＝懸停、拇指上＝起飛、握拳＝降落 | ✅ |
| 手勢需持續約 0.8 秒才觸發 | ✅ |
| 無手 > 0.5 秒 → 歸零軸／懸停 | ✅ |
| 緊急停止（UI 紅鈕／雙手張開） | ✅ |
| 感測器儀表與趨勢圖 | ✅ |
| CSV 飛行紀錄 `logs/flight_log.csv` | ✅ |
| 方向控制（前後左右上下） | 預設關閉，可於設定啟用 |

## 手勢對照

| 手勢 | 動作 |
|---|---|
| `Thumb_Up` | 起飛 |
| `Open_Palm` | 懸停 |
| `Closed_Fist` | 降落 |
| `Victory` | 向前（需啟用） |
| `Pointing_Up` | 上升（需啟用） |
| 食指朝下（關鍵點） | 下降（需啟用） |
| 手掌左右滑動 | 左右（需啟用） |
| 雙手張開 | 緊急停止 |

啟用方向控制：編輯 `config/gestures.yaml`，在 `enabled_intents` 取消註解 `forward` / `up` / `down` / `left` / `right`。

## 安全邏輯

- **確認**：同一意圖持續 ~0.8s 或 8/10 幀
- **冷卻**：移動指令間隔 ~1.0s
- **短脈衝**：每次移動約 25 cm 後自動懸停
- **無手**：0.5s 無手 → `RESET_AXES` + `HOVER`
- **障礙**：前方 < 40 cm 禁止向前；高度 < 20 cm 禁止下降；> 150 cm 禁止上升
- **緊急停止**：UI 按鈕／雙手張開；優先用 `land()`，`emergency_stop()` 只切馬達

## 如何設定實體控制

預設是**模擬模式**（不會對無人機下指令）。要改成實體控制：

### 方法 A：終端機（建議）

```bash
cd /Users/roylung/Projects/drone-edu
source .venv/bin/activate

# 查看目前模式與遙控器埠
./scripts/set-live-mode.sh status

# 開啟實體控制（寫入 settings.yaml）
./scripts/set-live-mode.sh on

# 重啟儀表板
streamlit run app.py
```

回到模擬：

```bash
./scripts/set-live-mode.sh off
streamlit run app.py
```

### 方法 B：側欄 UI

1. 開啟 Streamlit 後看左側「實體控制設定」
2. 選「實體 LIVE」、確認序列埠（VID 1155 通常是遙控器）
3. 按「儲存實體控制設定」
4. 終端機 `Ctrl+C`，再執行 `streamlit run app.py`

### 方法 C：手動改 YAML

編輯 `config/settings.yaml`：

```yaml
simulation_mode: false

drone:
  port_name: /dev/cu.usbmodem3983377831341   # 你的遙控器埠
  pair_timeout_sec: 8.0
```

然後重啟 Streamlit。

### 硬體檢查清單

```text
電腦 --USB 資料線--> 遙控器（LINK 模式）--無線--> 無人機
```

1. **第一次請取下螺旋槳**做無槳測試
2. 無人機／遙控器開機且已配對（燈號常亮）
3. 原廠／可傳資料的 USB 接**遙控器**（不是機身）
4. 遙控器切到 **LINK**（程式用；手動飛要離開 LINK）
5. 電量建議 > 50%
6. 儀表板按「連線」，確認電量、前方距離等有讀值
7. 先用 UI 按鈕測起飛／懸停／降落，再開攝影機手勢

`drone.connect()` 開的是**遙控器序列埠**，不是電腦直接無線連無人機。

## 實體連線：一定要經過遙控器

若自動偵測失敗，列出 macOS 候選埠：

```bash
ls /dev/cu.usb* /dev/tty.usb* 2>/dev/null
./scripts/set-live-mode.sh status
```

## 實體機測試階段

1. **無槳**：實體連線後只測感測器、按鈕、緊急停止
2. **只手勢**：可先回模擬模式開攝影機
3. **模擬指令**：手勢 → CSV／UI 紀錄
4. **起飛／懸停／降落**：無槳或防護網內
5. **方向控制**：最後在 `config/gestures.yaml` 啟用

## 專案結構

```text
app.py
config/settings.yaml
config/gestures.yaml
src/core/          # state, command_bus, config, logging
src/drone/         # controller, sensors, safety
src/vision/        # camera, gesture_detector, gesture_filter, worker
src/dashboard/ui.py
models/gesture_recognizer.task
logs/
tests/
.cursor/rules/
```

## 架構約束（Cursor Rules）

見 `.cursor/rules/codrone-gesture-architecture.mdc`：

- 飛行命令只能透過 `DroneController`
- 影像模組不得直接呼叫 CoDrone SDK
- 手勢命令必須經過 `GestureFilter`
- 所有命令支援 `simulation_mode`
- 例外時優先 `land()`

## 測試

```bash
source .venv/bin/activate
pytest -q
```

## 疑難排解

- **找不到模型**：執行 `python scripts/download-model.py`
- **攝影機黑屏**：檢查系統隱私權限；試著改 `camera.device_index`
- **MediaPipe 匯入失敗**：確認 Python ≥ 3.10，並在 `.venv` 內安裝
- **連線後整頁退出**：已修（`codrone-edu` 會破壞 `asyncio.sleep`）。請更新程式後重啟：`streamlit run app.py`
- **連線逾時**：確認是遙控器（非機身）插 USB、已進 **LINK**、無人機已與遙控器配對；必要時設 `drone.port_name`；可用官方 `drone.connect()` 範例先驗證
- **Drone is not connected**：先按「連線」，成功後再起飛／手勢

## 授權與安全聲明

此 DEMO 僅供教學與受控環境展示。實際飛行請取下螺旋槳做無槳驗證，並遵守室內安全規範。緊急情況使用紅色「緊急停止」；正常結束請用「降落」。
