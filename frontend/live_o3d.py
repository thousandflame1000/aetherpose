"""
live_o3d.py — Open3D SMPL mesh viewer (separate process).
Starts with T-pose so the window is never blank.
Frame-capped to 60 fps to avoid 100% CPU spin.
"""
import time
import numpy as np
import multiprocessing as mp


def run(queue: mp.Queue, v_template: np.ndarray, faces: np.ndarray) -> None:
    import open3d as o3d

    vis = o3d.visualization.Visualizer()
    vis.create_window("Aetherpose — SMPL Live Mesh", width=720, height=900)

    opt = vis.get_render_option()
    opt.background_color    = np.array([0.08, 0.10, 0.14])
    opt.mesh_show_back_face = True
    opt.light_on            = True

    # Init with T-pose
    mesh = o3d.geometry.TriangleMesh()
    mesh.vertices  = o3d.utility.Vector3dVector(v_template.astype(np.float64))
    mesh.triangles = o3d.utility.Vector3iVector(faces.astype(np.int32))
    mesh.paint_uniform_color([0.80, 0.62, 0.46])
    mesh.compute_vertex_normals()
    vis.add_geometry(mesh)

    # Floor grid
    floor_y = float(v_template[:, 1].min())
    pts, lines, idx = [], [], 0
    for v in np.arange(-1.0, 1.05, 0.2):
        pts += [[v, floor_y, -1.0], [v, floor_y, 1.0]]
        lines.append([idx, idx + 1]); idx += 2
        pts += [[-1.0, floor_y, v], [1.0, floor_y, v]]
        lines.append([idx, idx + 1]); idx += 2
    grid = o3d.geometry.LineSet()
    grid.points = o3d.utility.Vector3dVector(pts)
    grid.lines  = o3d.utility.Vector2iVector(lines)
    grid.paint_uniform_color([0.22, 0.22, 0.26])
    vis.add_geometry(grid)

    ctr = vis.get_view_control()
    ctr.set_lookat(v_template.mean(axis=0).tolist())
    ctr.set_up([0.0, 1.0, 0.0])
    ctr.set_front([0.0, 0.2, -1.0])
    ctr.set_zoom(0.6)

    FRAME_TIME = 1.0 / 60.0  # cap at 60 fps
    last_frame = time.perf_counter()

    while True:
        # Drain queue — keep only latest
        latest = None
        try:
            while True:
                latest = queue.get_nowait()
        except Exception:
            pass

        if latest is not None:
            verts, _ = latest
            mesh.vertices = o3d.utility.Vector3dVector(verts.astype(np.float64))
            vis.update_geometry(mesh)

        if not vis.poll_events():
            break
        vis.update_renderer()

        # Sleep remaining frame time — prevents 100% CPU spin
        elapsed = time.perf_counter() - last_frame
        sleep_t = FRAME_TIME - elapsed
        if sleep_t > 0:
            time.sleep(sleep_t)
        last_frame = time.perf_counter()

    vis.destroy_window()
