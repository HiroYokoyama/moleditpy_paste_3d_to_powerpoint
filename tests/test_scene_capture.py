"""Scene capture against real VTK actors (no render window needed)."""

from types import SimpleNamespace

import pytest

np = pytest.importorskip("numpy")
vtk = pytest.importorskip("vtk")

from paste_3d_to_powerpoint import scene_capture  # noqa: E402


class FakePlotter:
    """The two things capture_scene uses from a pyvista Plotter."""

    def __init__(self, actors, parallel=True):
        cam = vtk.vtkCamera()
        cam.SetPosition(0, 0, 10)
        cam.SetFocalPoint(0, 0, 0)
        cam.SetViewUp(0, 1, 0)
        cam.SetParallelProjection(parallel)
        cam.SetParallelScale(5.0)
        self.renderer = SimpleNamespace(
            actors=dict(actors), GetActiveCamera=lambda: cam, GetSize=lambda: (400, 400)
        )


def _actor(source, color=(0.2, 0.4, 0.6), opacity=1.0, rep=2, line_width=1.0):
    source.Update()
    mapper = vtk.vtkPolyDataMapper()
    mapper.SetInputData(source.GetOutput())
    mapper.ScalarVisibilityOff()
    actor = vtk.vtkActor()
    actor.SetMapper(mapper)
    prop = actor.GetProperty()
    prop.SetColor(*color)
    prop.SetOpacity(opacity)
    prop.SetRepresentation(rep)
    prop.SetLineWidth(line_width)
    return actor


def test_flat_colored_surface_keeps_color_and_opacity():
    actor = _actor(vtk.vtkSphereSource(), color=(1.0, 0.0, 0.0), opacity=0.4)
    scene = scene_capture.capture_scene(FakePlotter({"s": actor}))
    (prim,) = scene.primitives
    assert list(prim.color) == pytest.approx([1.0, 0.0, 0.0, 0.4])
    assert prim.indices.shape[1] == 3 and len(prim.positions) == len(prim.normals)
    assert scene.fov_deg == 10.0


def test_point_colors_split_into_flat_groups():
    """Glyph atoms: one mesh with per-point colors -> one material per element."""
    a = vtk.vtkSphereSource()
    a.SetCenter(-2, 0, 0)
    b = vtk.vtkSphereSource()
    b.SetCenter(2, 0, 0)
    app = vtk.vtkAppendPolyData()
    app.AddInputConnection(a.GetOutputPort())
    app.AddInputConnection(b.GetOutputPort())
    app.Update()
    poly = app.GetOutput()
    n = poly.GetNumberOfPoints()
    colors = vtk.vtkUnsignedCharArray()
    colors.SetName("colors")
    colors.SetNumberOfComponents(3)
    for i in range(n):
        colors.InsertNextTuple((255, 0, 0) if i < n // 2 else (0, 0, 255))
    poly.GetPointData().SetScalars(colors)
    mapper = vtk.vtkPolyDataMapper()
    mapper.SetInputData(poly)
    mapper.SetColorModeToDirectScalars()
    actor = vtk.vtkActor()
    actor.SetMapper(mapper)
    scene = scene_capture.capture_scene(FakePlotter({"atoms": actor}))
    got = sorted(tuple(np.round(p.color, 3)) for p in scene.primitives)
    assert got == [(0.0, 0.0, 1.0, 1.0), (1.0, 0.0, 0.0, 1.0)]
    assert all(p.vertex_colors is None for p in scene.primitives)


def test_color_mapped_surface_keeps_vertex_colors():
    """An isosurface painted through a lookup table cannot be split into flat groups."""
    sphere = vtk.vtkSphereSource()
    sphere.SetThetaResolution(32)
    sphere.SetPhiResolution(32)
    elev = vtk.vtkElevationFilter()
    elev.SetInputConnection(sphere.GetOutputPort())
    elev.SetLowPoint(0, -0.5, 0)
    elev.SetHighPoint(0, 0.5, 0)
    elev.Update()
    mapper = vtk.vtkPolyDataMapper()
    mapper.SetInputData(elev.GetOutput())
    mapper.SetScalarRange(0, 1)
    actor = vtk.vtkActor()
    actor.SetMapper(mapper)
    (prim,) = scene_capture.capture_scene(FakePlotter({"iso": actor})).primitives
    assert prim.vertex_colors is not None and prim.vertex_colors.shape == (
        len(prim.positions),
        4,
    )
    assert len(np.unique(prim.vertex_colors, axis=0)) > scene_capture.MAX_COLOR_GROUPS


def test_lines_become_tubes_scaled_to_screen_width():
    line = vtk.vtkLineSource()
    line.SetPoint1(-1, 0, 0)
    line.SetPoint2(1, 0, 0)
    actor = _actor(line, line_width=4.0)
    plotter = FakePlotter({"cell_line": actor})
    (prim,) = scene_capture.capture_scene(plotter).primitives
    radius = np.abs(prim.positions[:, 1:]).max()
    # 4 px at 10 world units per 400 px -> 0.05 radius
    assert radius == pytest.approx(
        scene_capture.world_per_pixel(plotter) * 2.0, rel=0.05
    )


def test_geometry_is_rotated_into_the_camera_frame_and_centered():
    cube = vtk.vtkCubeSource()
    cube.SetXLength(4)
    cube.SetYLength(1)
    cube.SetZLength(1)
    cube.SetCenter(5, 5, 5)
    plotter = FakePlotter({"c": _actor(cube)})
    cam = plotter.renderer.GetActiveCamera()
    # Look down -X with +Z up: world X becomes depth, world Z becomes screen up.
    cam.SetPosition(20, 5, 5)
    cam.SetFocalPoint(5, 5, 5)
    cam.SetViewUp(0, 0, 1)
    (prim,) = scene_capture.capture_scene(plotter).primitives
    lo, hi = prim.positions.min(axis=0), prim.positions.max(axis=0)
    assert (hi - lo) == pytest.approx([1.0, 1.0, 4.0])
    assert (lo + hi) / 2 == pytest.approx([0.0, 0.0, 0.0], abs=1e-9)


def test_hidden_points_and_2d_actors_are_skipped():
    hidden = _actor(vtk.vtkSphereSource())
    hidden.VisibilityOff()
    points = _actor(vtk.vtkSphereSource(), rep=0)
    text = vtk.vtkTextActor()
    shown = _actor(vtk.vtkSphereSource())
    scene = scene_capture.capture_scene(
        FakePlotter({"hidden": hidden, "points": points, "label": text, "shown": shown})
    )
    assert len(scene.primitives) == 1
    assert scene.skipped == ["points"]


def test_empty_view_raises():
    with pytest.raises(ValueError):
        scene_capture.capture_scene(FakePlotter({}))


def test_perspective_camera_keeps_its_view_angle():
    plotter = FakePlotter({"s": _actor(vtk.vtkSphereSource())}, parallel=False)
    plotter.renderer.GetActiveCamera().SetViewAngle(25.0)
    assert scene_capture.capture_scene(plotter).fov_deg == 25.0


def test_roughness_follows_specular_strength():
    prop = SimpleNamespace(GetInterpolation=lambda: 2, GetSpecular=lambda: 0.2)
    assert scene_capture._roughness_from_vtk(prop) == pytest.approx(0.55)
    pbr = SimpleNamespace(GetInterpolation=lambda: 3, GetRoughness=lambda: 0.3)
    assert scene_capture._roughness_from_vtk(pbr) == 0.3


def test_only_line_actors_are_marked_as_lines():
    line = vtk.vtkLineSource()
    scene = scene_capture.capture_scene(
        FakePlotter({"edge": _actor(line), "ball": _actor(vtk.vtkSphereSource())})
    )
    marks = sorted(bool(p.extras.get("line")) for p in scene.primitives)
    assert marks == [False, True]
    wire = _actor(vtk.vtkSphereSource(), rep=1)
    assert scene_capture.is_line_actor(wire)
