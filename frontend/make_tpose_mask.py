"""
生成 T-pose 靜態 mask，供 TransPoseRunner 使用。

T-pose 定義（Y-up world frame）：
  - 所有 IMU 方向矩陣 = Identity（sensor 與世界對齊）
  - 所有加速度 = [0, 9.81, 0]（只有 Y 方向重力）

用法：
  python make_tpose_mask.py
  → 生成 tpose_mask.npz

在 main_o3d.py 裡替換 DIP mask 載入的部分即可。
"""

import numpy as np

N = 2000          # 幀數（會被 loop，數量不重要）
N_SLOTS = 6       # TransPose 6 個 IMU 槽

g = 9.81

# acc: (N, 6, 3) — 每個 sensor 只感受到重力 [0, g, 0]
acc = np.zeros((N, N_SLOTS, 3), dtype=np.float32)
acc[:, :, 1] = g  # Y 軸 = 重力方向

# ori: (N, 6, 3, 3) — 每個 sensor 方向為 Identity
ori = np.tile(np.eye(3, dtype=np.float32), (N, N_SLOTS, 1, 1))

np.savez("tpose_mask.npz", imu_acc=acc, imu_ori=ori)
print(f"Saved tpose_mask.npz  acc{acc.shape}  ori{ori.shape}")
print(f"acc sample: {acc[0,0]}")
print(f"ori sample:\n{ori[0,0]}")
