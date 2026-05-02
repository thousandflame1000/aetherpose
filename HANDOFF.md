# Handoff — 2026-05-02

## 固件已修改

`src/skeleton/tracker_firmware/tracker_firmware.ino`（Arduino Nano 33 BLE）

原版的 ino 備份在 `src/skeleton/tracker_firmware_original.ino.bak`。

### 主要變更

- 封包格式升級為 v2（`0x04`，61 bytes），新增 Mahony 四元數輸出 `quat[4]`
- Mahony AHRS 改為 split Kp：`Kp_acc=2.0`、`Kp_mag=0.3`、`Ki=0.005`
- 新增 BLE Write characteristic（UUID `19B10002`）供 host 回傳 EKF sync 四元數

### 燒錄

```bash
arduino-cli upload -p COM<N> --fqbn arduino:mbed_nano:nano33ble --input-dir .arduino-output
```
