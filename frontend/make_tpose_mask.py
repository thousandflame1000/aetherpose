"""
生成 T-pose 靜態 mask，供 TransPoseRunner 使用。

T-pose 定義（Y-up world frame）：
  - 所有 IMU 方向矩陣 = Identity（sensor 與世界對齊）
  - 所有加速度 = [0, 9.81, 0]（只有 Y 方向重力）

用法（在哪個資料夾執行都可以）：
  python frontend/make_tpose_mask.py
  → 生成 frontend/tpose_mask.npz

推論服務（mesh_bridge.py）會優先載入 frontend/tpose_mask.npz，
取代 DIP-IMU 示範資料（見 TransPoseRunner._init）。沒有 DIP-IMU 資料時，
推論服務本來就會改用同樣的靜止 T-pose，不必先產生這個檔案。
"""

from pathlib import Path

import numpy as np

N = 2000          # 幀數（會被 loop，數量不重要）
N_SLOTS = 6       # TransPose 6 個 IMU 槽

g = 9.81

# acc: (N, 6, 3) — 每個 sensor 只感受到重力 [0, g, 0]
acc = np.zeros((N, N_SLOTS, 3), dtype=np.float32)
acc[:, :, 1] = g  # Y 軸 = 重力方向

# ori: (N, 6, 3, 3) — 每個 sensor 方向為 Identity
ori = np.tile(np.eye(3, dtype=np.float32), (N, N_SLOTS, 1, 1))

out = Path(__file__).resolve().with_name("tpose_mask.npz")  # where TransPoseRunner looks
np.savez(out, imu_acc=acc, imu_ori=ori)
print(f"Saved {out}  acc{acc.shape}  ori{ori.shape}")
print(f"acc sample: {acc[0,0]}")
print(f"ori sample:\n{ori[0,0]}")
