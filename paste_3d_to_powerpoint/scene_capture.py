"""Turn what the MoleditPy 3D view shows into glTF-ready primitives.

Everything visible in the main plotter is captured generically, so molecules,
CIF Viewer crystals, cube-file orbitals and other plugin overlays come out as
drawn, without per-plugin code:

* surfaces keep their actor color, opacity and gloss, or the per-point /
  per-cell colors the mapper paints (element colors, half-colored bonds,
  color-mapped isosurfaces);
* lines and wireframes become tubes as thick as they look on screen;
* the geometry is rotated into the current camera frame, so PowerPoint opens
  it from the same direction as the MoleditPy view.

Text labels, 2D overlays, point sprites and volume renderings have no mesh to
export and are skipped.
"""

import logging
from dataclasses import dataclass
from typing import Any, List, Optional

from .gltf_writer import Primitive

logger = logging.getLogger(__name__)

# Above this many distinct flat colors a mesh keeps per-vertex colors instead
# of being split into one material per color.
MAX_COLOR_GROUPS = 64

REP_POINTS, REP_WIREFRAME, REP_SURFACE = 0, 1, 2
INTERP_PBR = 3


@dataclass
class CapturedScene:
    primitives: List[Primitive]
    fov_deg: float
    skipped: List[str]


def _roughness_from_vtk(prop: Any) -> float:
    """Map VTK Phong specular strength onto a glTF roughness value."""
    if prop.GetInterpolation() == INTERP_PBR:
        return float(prop.GetRoughness())
    spec = float(prop.GetSpecular())
    return max(0.15, min(0.9, 0.65 - 0.5 * spec))


def _metallic_from_vtk(prop: Any) -> float:
    if prop.GetInterpolation() == INTERP_PBR:
        return float(prop.GetMetallic())
    return 0.0


def camera_frame(plotter: Any):
    """Rotation whose rows are the camera's right, up and back axes."""
    import numpy as np

    cam = plotter.renderer.GetActiveCamera()
    pos = np.array(cam.GetPosition(), float)
    focal = np.array(cam.GetFocalPoint(), float)
    up = np.array(cam.GetViewUp(), float)
    back = pos - focal
    back /= np.linalg.norm(back)
    right = np.cross(up, back)
    if np.linalg.norm(right) < 1e-9:
        # View-up parallel to the view direction: any perpendicular up will do,
        # whereas normalizing the zero vector would turn the model into NaN.
        fallback = np.eye(3)[np.argmin(np.abs(back))]
        right = np.cross(fallback, back)
    right /= np.linalg.norm(right)
    true_up = np.cross(back, right)
    return np.vstack([right, true_up, back])


def world_per_pixel(plotter: Any) -> float:
    """Approximate world length of one screen pixel at the focal point."""
    import math

    cam = plotter.renderer.GetActiveCamera()
    height = max(1, plotter.renderer.GetSize()[1])
    if cam.GetParallelProjection():
        return 2.0 * cam.GetParallelScale() / height
    return (
        2.0
        * cam.GetDistance()
        * math.tan(math.radians(cam.GetViewAngle()) / 2)
        / height
    )


def _polydata_of(actor: Any) -> Optional[Any]:
    import vtk

    mapper = actor.GetMapper()
    if mapper is None:
        return None
    data = (
        mapper.GetInputAsDataSet()
        if hasattr(mapper, "GetInputAsDataSet")
        else mapper.GetInput()
    )
    if data is None or data.GetNumberOfPoints() == 0:
        return None
    if isinstance(data, vtk.vtkPolyData):
        poly = vtk.vtkPolyData()
        poly.ShallowCopy(data)
        return poly
    geom = vtk.vtkGeometryFilter()
    geom.SetInputData(data)
    geom.Update()
    return geom.GetOutput()


def _attach_mapped_colors(actor: Any, poly: Any) -> Optional[str]:
    """Store the colors the mapper actually paints as a '__rgba' array.

    Returns "point" or "cell" for where the colors live, or None when the
    actor is drawn in its flat property color.
    """
    mapper = actor.GetMapper()
    if not mapper.GetScalarVisibility():
        return None
    # Map the surface actually exported, not the mapper input: for a volume
    # dataset the extracted surface has other cells (faces, not tetrahedra), so
    # colors mapped on the input would not line up and fall back to flat gray.
    try:
        colors = mapper.MapScalars(poly, 1.0)
    except TypeError:
        colors = mapper.MapScalars(1.0)
    if colors is None or colors.GetNumberOfTuples() == 0:
        return None
    rgba = colors.NewInstance()
    rgba.DeepCopy(colors)
    rgba.SetName("__rgba")
    mode = mapper.GetScalarModeAsString()
    npts, ncells = poly.GetNumberOfPoints(), poly.GetNumberOfCells()
    n = rgba.GetNumberOfTuples()
    if n == npts and (n != ncells or "Cell" not in mode):
        poly.GetPointData().AddArray(rgba)
        return "point"
    if n == ncells:
        poly.GetCellData().AddArray(rgba)
        return "cell"
    return None


def _to_triangles(actor: Any, poly: Any, tube_radius: float) -> Any:
    """Triangulate surfaces and turn lines/wireframes into tubes."""
    import vtk

    prop = actor.GetProperty()
    rep = prop.GetRepresentation()
    if rep == REP_WIREFRAME and poly.GetNumberOfPolys() + poly.GetNumberOfStrips() > 0:
        edges = vtk.vtkExtractEdges()
        edges.SetInputData(poly)
        edges.Update()
        poly = edges.GetOutput()

    pieces = vtk.vtkAppendPolyData()
    has_piece = False

    if poly.GetNumberOfPolys() + poly.GetNumberOfStrips() > 0:
        tri = vtk.vtkTriangleFilter()
        tri.SetInputData(poly)
        tri.PassLinesOff()
        tri.PassVertsOff()
        tri.Update()
        pieces.AddInputData(tri.GetOutput())
        has_piece = True

    if poly.GetNumberOfLines() > 0:
        lines = vtk.vtkPolyData()
        lines.SetPoints(poly.GetPoints())
        lines.SetLines(poly.GetLines())
        lines.GetPointData().ShallowCopy(poly.GetPointData())
        if poly.GetCellData().GetArray("__rgba") is not None:
            # Lines come after verts in VTK's cell order; take their slice.
            offset = poly.GetNumberOfVerts()
            src = poly.GetCellData().GetArray("__rgba")
            arr = src.NewInstance()
            arr.SetName("__rgba")
            arr.SetNumberOfComponents(src.GetNumberOfComponents())
            for i in range(poly.GetNumberOfLines()):
                arr.InsertNextTuple(src.GetTuple(offset + i))
            lines.GetCellData().AddArray(arr)
        clean = vtk.vtkCleanPolyData()
        clean.SetInputData(lines)
        tube = vtk.vtkTubeFilter()
        tube.SetInputConnection(clean.GetOutputPort())
        tube.SetRadius(max(tube_radius * prop.GetLineWidth() / 2.0, 1e-4))
        tube.SetNumberOfSides(12)
        tube.CappingOn()
        tri = vtk.vtkTriangleFilter()
        tri.SetInputConnection(tube.GetOutputPort())
        tri.Update()
        pieces.AddInputData(tri.GetOutput())
        has_piece = True

    if not has_piece:
        return None
    pieces.Update()
    out = pieces.GetOutput()

    if actor.GetMatrix() is not None and not _is_identity(actor.GetMatrix()):
        xf = vtk.vtkTransform()
        xf.SetMatrix(actor.GetMatrix())
        tf = vtk.vtkTransformPolyDataFilter()
        tf.SetTransform(xf)
        tf.SetInputData(out)
        tf.Update()
        out = tf.GetOutput()

    normals = vtk.vtkPolyDataNormals()
    normals.SetInputData(out)
    normals.SetFeatureAngle(60.0)
    normals.SplittingOn()
    normals.ConsistencyOn()
    normals.Update()
    return normals.GetOutput()


def _is_identity(matrix: Any) -> bool:
    return all(
        abs(matrix.GetElement(i, j) - (1.0 if i == j else 0.0)) < 1e-9
        for i in range(4)
        for j in range(4)
    )


def _arrays(poly: Any):
    from vtk.util.numpy_support import vtk_to_numpy

    pts = vtk_to_numpy(poly.GetPoints().GetData()).astype(float)
    nrm_arr = poly.GetPointData().GetNormals()
    nrm = vtk_to_numpy(nrm_arr).astype(float) if nrm_arr is not None else None
    conn = vtk_to_numpy(poly.GetPolys().GetConnectivityArray())
    tris = conn.reshape(-1, 3)
    return pts, nrm, tris


def _rgba_of(data: Any):
    import numpy as np
    from vtk.util.numpy_support import vtk_to_numpy

    arr = data.GetArray("__rgba")
    if arr is None:
        return None
    rgba = vtk_to_numpy(arr)
    if rgba.ndim == 1:
        rgba = rgba[:, None]
    if rgba.shape[1] == 3:
        rgba = np.hstack([rgba, np.full((len(rgba), 1), 255, rgba.dtype)])
    return rgba.astype(np.uint8)


def _split_by_color(name, pts, nrm, tris, tri_rgba, roughness, metallic, opacity):
    """One flat-colored primitive per distinct triangle color."""
    import numpy as np

    out = []
    keys, inverse = np.unique(tri_rgba, axis=0, return_inverse=True)
    inverse = np.asarray(inverse).ravel()
    for k, key in enumerate(keys):
        sel = tris[inverse == k]
        used, remap = np.unique(sel.ravel(), return_inverse=True)
        color = list(key[:3] / 255.0) + [key[3] / 255.0 * opacity]
        out.append(
            Primitive(
                name=f"{name}_{k}",
                positions=pts[used],
                normals=nrm[used],
                indices=remap.reshape(-1, 3),
                color=color,
                roughness=roughness,
                metallic=metallic,
            )
        )
    return out


def is_line_actor(actor: Any) -> bool:
    """True for actors drawn as lines (unit-cell edges, axes, wireframes)."""
    if actor.GetProperty().GetRepresentation() == REP_WIREFRAME:
        return True
    poly = _polydata_of(actor)
    if poly is None or not hasattr(poly, "GetNumberOfLines"):
        return False
    return (
        poly.GetNumberOfLines() > 0
        and poly.GetNumberOfPolys() + poly.GetNumberOfStrips() == 0
    )


def actor_primitives(actor: Any, name: str, tube_radius: float) -> List[Primitive]:
    """Primitives for one visible actor; tubes made from lines get extras["line"]."""
    prims = _actor_primitives(actor, name, tube_radius)
    if prims and is_line_actor(actor):
        for prim in prims:
            prim.extras["line"] = True
    return prims


def _actor_primitives(actor: Any, name: str, tube_radius: float) -> List[Primitive]:
    """Primitives for one visible actor (empty if it has no exportable mesh)."""
    import numpy as np

    prop = actor.GetProperty()
    poly = _polydata_of(actor)
    if poly is None or prop.GetRepresentation() == REP_POINTS:
        return []
    where = _attach_mapped_colors(actor, poly)
    tri_poly = _to_triangles(actor, poly, tube_radius)
    if tri_poly is None or tri_poly.GetNumberOfPolys() == 0:
        return []
    pts, nrm, tris = _arrays(tri_poly)
    if nrm is None:
        nrm = np.zeros_like(pts)
    roughness = _roughness_from_vtk(prop)
    metallic = _metallic_from_vtk(prop)
    opacity = float(prop.GetOpacity())

    if where == "cell":
        cell_rgba = _rgba_of(tri_poly.GetCellData())
        if cell_rgba is not None and len(cell_rgba) == len(tris):
            return _split_by_color(
                name, pts, nrm, tris, cell_rgba, roughness, metallic, opacity
            )
    if where == "point":
        rgba = _rgba_of(tri_poly.GetPointData())
        if rgba is not None and len(rgba) == len(pts):
            corner = rgba[tris]  # (M, 3, 4)
            flat = (corner == corner[:, :1]).all(axis=(1, 2))
            n_colors = len(np.unique(rgba, axis=0))
            if flat.all() and n_colors <= MAX_COLOR_GROUPS:
                return _split_by_color(
                    name, pts, nrm, tris, corner[:, 0], roughness, metallic, opacity
                )
            if opacity < 1.0:
                rgba = rgba.copy()
                rgba[:, 3] = (rgba[:, 3] * opacity).astype(np.uint8)
            return [
                Primitive(
                    name=name,
                    positions=pts,
                    normals=nrm,
                    indices=tris,
                    color=(1.0, 1.0, 1.0, 1.0),
                    roughness=roughness,
                    metallic=metallic,
                    vertex_colors=rgba,
                )
            ]
    color = list(prop.GetColor()) + [opacity]
    return [
        Primitive(
            name=name,
            positions=pts,
            normals=nrm,
            indices=tris,
            color=color,
            roughness=roughness,
            metallic=metallic,
        )
    ]


def capture_scene(plotter: Any, parallel_fov_deg: float = 10.0) -> CapturedScene:
    """Capture every visible 3D actor of ``plotter`` in camera-aligned coordinates.

    The result is centered on its bounding box with +X right, +Y up and +Z
    toward the viewer, which is how PowerPoint first looks at a model.
    """
    import numpy as np
    import vtk

    rot = camera_frame(plotter)
    tube_radius = world_per_pixel(plotter)
    prims: List[Primitive] = []
    skipped: List[str] = []
    for i, (name, actor) in enumerate(plotter.renderer.actors.items()):
        if not isinstance(actor, vtk.vtkActor) or not actor.GetVisibility():
            continue
        if actor.GetProperty().GetOpacity() <= 0.0:
            continue
        try:
            got = actor_primitives(actor, f"actor{i}", tube_radius)
        except Exception:  # one odd actor must not block the export
            logger.exception("Paste 3D: could not capture actor %s", name)
            skipped.append(str(name))
            continue
        if not got:
            skipped.append(str(name))
        prims.extend(got)
    if not prims:
        raise ValueError("Nothing exportable is shown in the 3D view.")

    for p in prims:
        p.positions = np.asarray(p.positions) @ rot.T
        p.normals = np.asarray(p.normals) @ rot.T
    lo = np.min([p.positions.min(axis=0) for p in prims], axis=0)
    hi = np.max([p.positions.max(axis=0) for p in prims], axis=0)
    center = (lo + hi) / 2
    for p in prims:
        p.positions = p.positions - center

    cam = plotter.renderer.GetActiveCamera()
    fov = parallel_fov_deg if cam.GetParallelProjection() else float(cam.GetViewAngle())
    return CapturedScene(primitives=prims, fov_deg=fov, skipped=skipped)
