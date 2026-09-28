# 單顆 IMU / Fusion AHRS 三軸測試

這個工具直接顯示 `tracker_firmware` 的 `[x,y,z,w]` 四元數，沒有 IK、TransPose 或額外姿態濾波。
原點固定，顯示的是旋轉姿態，不是平移位置。只用陀螺儀不能量得絕對位置。

## 1. 燒錄韌體

Arduino IDE 開啟 `src/skeleton/tracker_firmware/tracker_firmware.ino`；
同資料夾的 `src/Fusion/`（[x-io Fusion](https://github.com/xioTechnologies/Fusion) 原始碼，MIT）必須一併保留。
板子選 **Arduino Nano 33 BLE**，使用 `Arduino_LSM9DS1`、`ArduinoBLE`，再上傳。
（`madgwick_ahrs.h` 已不再使用。）

每次開機把板子放著不動約 5 秒。韌體先取 240 個靜止樣本估計 gyro bias，然後開始 BLE。
若移動太大會放棄 bias 校正，Serial Monitor 會印出樣本數與各軸變異量；請靜置並重開機。
之後 Fusion 會在板子靜止 3 秒以上時持續追蹤 gyro bias 漂移。

濾波器是 x-io Fusion（Madgwick 的後繼版本）：加速度或磁場偏離超過 10° 時暫時忽略該感測器
（甩動、磁干擾），連續 5 秒後強制恢復。加速度計量程由函式庫預設的 ±4 g 改為 ±16 g。

韌體保留 61-byte v2 payload / 66-byte frame；gyro、mag 仍是原始量測，accel 已依 ±16 g 正確換算。
只有濾波輸入會扣除 gyro bias、把陀螺儀換算成 datasheet 的 70 mdps/LSB，
並把 accel/gyro 的 X 軸反向：LSM9DS1 的 accel/gyro 軸是左手座標，磁力計是右手座標，
反向後三者都在磁力計座標系（同 [jremington/LSM9DS1-AHRS](https://github.com/jremington/LSM9DS1-AHRS)）。
因此畫面上的紅色 X 軸與板子上印的 accel X 箭頭方向**相反**。
改用其他 IMU 或其他驅動程式時，須重新確認軸向，不能直接沿用此映射。

## 2. 啟動

在 `aetherpose` 目錄執行（以下用同一個 `python` 安裝及執行）：

```powershell
python -m pip install bleak
python tools/imu_axes.py
```

自動開啟 <http://127.0.0.1:8767>。不用另外啟動原本的全身動捕程式。
直接 BLE 模式請先關閉會連接該 IMU 的 Aetherpose 後端；工具不會替你終止其他程式。
有多顆時明確選擇一顆：

```powershell
python tools/imu_axes.py --id 76
# MAC 尾碼形成的 ID 可能重複，這時改用完整 BLE 位址：
python tools/imu_axes.py --address AA:BB:CC:DD:EE:FF
```

如果已在跑 Rust 後端，可改讀它轉送的原始裝置 rotation：

```powershell
python -m pip install websockets
python tools/imu_axes.py --ws ws://127.0.0.1:9009/ws --id 76
```

沒有硬體時先檢查畫面（畫面會明確標示 DEMO）：

```powershell
python tools/imu_axes.py --demo
```

`--no-browser` 不自動開網頁，`--port 8768` 可換連接埠；終端按 Ctrl+C 關閉。
畫面只在本機提供，不需要 CDN 或額外 3D 套件。

## 3. 實際比對

1. 紅 X、綠 Y、藍 Z 是 IMU 座標軸；細灰線是固定世界座標。Z 朝上。
2. IMU 靜置穩定後按「記參考（R）」，虛線會保留當下三軸。
3. 選參考姿態的 X、Y 或 Z 軸，輸入預期角度（例如 +90°）。
4. 依右手定則轉動板子；用量角器或固定角度治具量得實際角度，才有外部比較基準。
5. 穩定後按「記錄此筆比對」，重複多個姿態後匯出 CSV。

「角度誤差」比較目前四元數與 `參考四元數 × 預期繞軸旋轉`，是 0–180° 的最小姿態差，
不是逐項 Euler 角相減。相對旋轉角同样是最短角，不能用來計算多圈旋轉總量。
CSV 包含時間、資料來源、參考/目前四元數、預期軸/角度、roll/pitch/yaw 與角度誤差。
DEMO 資料在 CSV 的 source 欄也會標示，不可當作實機測試結果。
若超過 1 秒沒有新資料，箭頭變淡並禁止新增比對紀錄。

## 磁力計與「絕對空間」

Madgwick 的世界座標是由重力與磁場建立，不是房間內的定位座標。
`USE_MAGNETOMETER = true` 時朝向會受當地磁場影響；不保證等於真北。
每顆板子都要各自校正磁力計（板上的電池、零件造成的硬鐵偏移每顆都不同），一條指令完成：

```powershell
python tools/calibrate_tracker.py --id 76
```

需先開著後端；板子接在 USB 上才能燒錄。腳本會即時顯示各軸轉動涵蓋率，轉到約 85% 就自動停止，
用橢球擬合算出校正值，品質不夠（轉得不完整、磁場干擾）會拒絕寫入。通過後寫進韌體的
`MAG_CALIBRATIONS` 表（依追蹤器 ID 查找，原生磁力計座標），燒錄並讀開機訊息確認已啟用。
表裡沒有的 ID 會自動停用磁力計（yaw 會慢慢漂移，但不會被往錯的方向拉）。
只想燒錄不重錄：`--flash-only`；只寫入不燒錄：`--no-flash`。
若要先隔離磁場干擾，可把 `USE_MAGNETOMETER` 改為 `false` 後重刷；此時 yaw 會漂移。
快速平移時加速度包含動態成分，請先以靜態角度與緩慢旋轉測試。

參考：[Arduino Madgwick 實作](https://github.com/arduino-libraries/MadgwickAHRS/blob/master/src/MadgwickAHRS.cpp)、
[LSM9DS1 軸向參考實作](https://github.com/kriswiner/LSM9DS1/blob/master/LSM9DS1_MS5611_BasicAHRS_t3.ino)。
