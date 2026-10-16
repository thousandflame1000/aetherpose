"""
SMPL forward kinematics and single-frame linear blend skinning.

Moved into the project from the earlier bone_data_anylasis/dip_loader.py so the
inference service no longer imports code from a folder outside the repository.
The SMPL model file itself stays external (see external_paths.py).
"""

import numpy as np


def axis_angle_to_matrix(aa: np.ndarray) -> np.ndarray:
    """Convert axis-angle (3,) to rotation matrix (3,3). Rodrigues formula."""
    angle = np.linalg.norm(aa)
    if angle < 1e-8:
        return np.eye(3)
    axis = aa / angle
    K = np.array([[0, -axis[2], axis[1]],
                  [axis[2], 0, -axis[0]],
                  [-axis[1], axis[0], 0]])
    return np.eye(3) + np.sin(angle) * K + (1 - np.cos(angle)) * (K @ K)


def batch_axis_angle_to_matrix(poses: np.ndarray) -> np.ndarray:
    """Convert (N, 72) pose params to (N, 24, 3, 3) rotation matrices."""
    N = len(poses)
    R = np.zeros((N, 24, 3, 3))
    for i in range(N):
        for j in range(24):
            R[i, j] = axis_angle_to_matrix(poses[i, j*3:j*3+3])
    return R


class SMPLForwardKinematics:
    def __init__(self, smpl_npz_path: str):
        data = np.load(smpl_npz_path, allow_pickle=True)

        self.v_template   = data["v_template"].astype(np.float32)    # (6890, 3)
        self.J_regressor  = data["J_regressor"].astype(np.float32)   # (24, 6890)
        self.shapedirs    = data["shapedirs"].astype(np.float32)      # (6890, 3, 300)
        self.posedirs     = data["posedirs"].astype(np.float32)       # (6890, 3, 207)
        self.weights      = data["weights"].astype(np.float32)        # (6890, 24)
        self.faces        = data["f"].astype(np.int32)                # (13776, 3)

        self.parents = data["kintree_table"][0].astype(int)           # (24,)
        self.parents[0] = -1

        # T-pose joint positions from the regressor (betas=0 → v_shaped = v_template)
        self.J_rest = (self.J_regressor @ self.v_template).astype(np.float32)  # (24, 3)

        print(f"  [SMPL] loaded: {self.v_template.shape[0]} verts, "
              f"{len(self.parents)} joints, "
              f"shapedirs {self.shapedirs.shape[2]} dims")

    def lbs_frame(self, R_frame: np.ndarray) -> np.ndarray:
        """
        Single-frame LBS mesh.
        R_frame : (24, 3, 3) local rotation matrices.
        Returns  : (6890, 3) vertex world positions (same frame as J_rest[0]).
        """
        G = np.zeros((24, 4, 4), dtype=np.float32)
        G[:, 3, 3] = 1.0
        for j in range(24):
            p = self.parents[j]
            G[j, :3, :3] = R_frame[j]
            if p < 0:
                G[j, :3, 3] = self.J_rest[j]
            else:
                G[j, :3, 3] = self.J_rest[j] - self.J_rest[p]
                G[j] = G[p] @ G[j]
        # bone transforms: subtract rest joint position
        T = G[:, :3, :].copy()                                               # (24, 3, 4)
        T[:, :, 3] -= (G[:, :3, :3] @ self.J_rest[:, :, None]).squeeze(-1)  # (24, 3)
        # weighted LBS
        T_w = (self.weights @ T.reshape(24, 12)).reshape(len(self.v_template), 3, 4)
        v_h = np.empty((len(self.v_template), 4), dtype=np.float32)
        v_h[:, :3] = self.v_template
        v_h[:, 3]  = 1.0
        return (T_w @ v_h[:, :, None])[:, :, 0]

    def page_skin(self) -> dict:
        """What the page needs to skin the mesh itself like lbs_frame (webui/skinning.js): the
        template, rest joints, parents and each vertex's four largest bone weights (every SMPL
        vertex has at most four)."""
        bones = np.argsort(-self.weights, axis=1)[:, :4]
        weights = np.take_along_axis(self.weights, bones, axis=1)
        weights = weights / weights.sum(axis=1, keepdims=True)
        # Rounded as float64: rounded float32 values still print with about 17 digits.
        rounded = lambda values, digits: np.round(np.asarray(values, np.float64), digits).ravel().tolist()
        return {'template': rounded(self.v_template, 5),
                'joints': rounded(self.J_rest, 5),
                'parents': [int(p) for p in self.parents],
                'bones': bones.ravel().tolist(),
                'weights': rounded(weights, 6)}

    def forward(self, poses: np.ndarray, betas: np.ndarray = None) -> np.ndarray:
        """
        poses: (N, 72) axis-angle pose parameters
        betas: (N, 10) or (10,) shape parameters (optional, default = zero)
        returns: (N, 24, 3) world-space joint positions
        """
        N = len(poses)

        # Shape blend shapes
        if betas is not None:
            b = np.atleast_2d(betas)
            if b.shape[0] == 1:
                b = np.tile(b, (N, 1))
            n_betas = min(b.shape[1], self.shapedirs.shape[2])
            v_shaped = self.v_template + np.einsum(
                "vck,nk->nvc", self.shapedirs[:, :, :n_betas], b[:, :n_betas]
            )  # (N, 6890, 3)
            J_rest = np.einsum("jv,nvc->njc", self.J_regressor, v_shaped)  # (N, 24, 3)
        else:
            J_rest = np.broadcast_to(self.J_rest, (N, 24, 3)).copy()

        R_all = batch_axis_angle_to_matrix(poses)  # (N, 24, 3, 3)

        # G[j] = G[parent(j)] @ A[j]
        # A[j] = [R[j], J[j] - J[parent(j)]; 0, 1]   (non-root)
        # A[0] = [R[0], J[0];                  0, 1]  (root)
        G = np.zeros((N, 24, 4, 4), dtype=np.float32)
        G[:, :, 3, 3] = 1.0
        for j in range(24):
            p = self.parents[j]
            G[:, j, :3, :3] = R_all[:, j]
            if p < 0:
                G[:, j, :3, 3] = J_rest[:, j]
            else:
                G[:, j, :3, 3] = J_rest[:, j] - J_rest[:, p]
                G[:, j] = G[:, p] @ G[:, j]

        return G[:, :, :3, 3]  # (N, 24, 3) joint world positions
