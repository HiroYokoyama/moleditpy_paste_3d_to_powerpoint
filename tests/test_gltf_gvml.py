import io
import json
import math
import struct
import zipfile

import pytest

np = pytest.importorskip("numpy")

from paste_3d_to_powerpoint.gltf_writer import (
    Primitive,
    bounds,
    build_glb,
    srgb_to_linear,
)  # noqa: E402
from paste_3d_to_powerpoint.gvml import (  # noqa: E402
    ANGLE_UNIT,
    EMU_PER_METER,
    build_gvml,
    camera_distance,
)


def _triangle(color=(1.0, 0.0, 0.0, 1.0), offset=0.0, **kw):
    pos = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], float) + offset
    nrm = np.array([[0, 0, 1]] * 3, float)
    return Primitive("tri", pos, nrm, np.array([[0, 1, 2]]), color=color, **kw)


def _parse(glb):
    magic, version, total = struct.unpack("<III", glb[:12])
    assert magic == 0x46546C67 and version == 2 and total == len(glb)
    js_len, js_type = struct.unpack("<II", glb[12:20])
    assert js_type == 0x4E4F534A and js_len % 4 == 0
    gltf = json.loads(glb[20 : 20 + js_len])
    bin_len, bin_type = struct.unpack("<II", glb[20 + js_len : 28 + js_len])
    assert bin_type == 0x004E4942 and bin_len == gltf["buffers"][0]["byteLength"]
    return gltf, glb[28 + js_len : 28 + js_len + bin_len]


def test_glb_structure_and_bounds():
    gltf, blob = _parse(build_glb([_triangle(), _triangle(offset=2.0)]))
    prims = gltf["meshes"][0]["primitives"]
    assert len(prims) == 2 and len(gltf["materials"]) == 2
    pos = gltf["accessors"][prims[1]["attributes"]["POSITION"]]
    assert pos["min"] == [2.0, 2.0, 2.0] and pos["max"] == [3.0, 3.0, 2.0]
    for view in gltf["bufferViews"]:
        assert view["byteOffset"] % 4 == 0
        assert view["byteOffset"] + view["byteLength"] <= len(blob)


def test_base_color_is_converted_to_linear():
    """sRGB written as-is is the washed-out-in-PowerPoint bug."""
    gltf, _ = _parse(build_glb([_triangle(color=(0.5, 0.0, 1.0, 1.0))]))
    base = gltf["materials"][0]["pbrMetallicRoughness"]["baseColorFactor"]
    assert base[0] == pytest.approx(0.2140, abs=1e-3)
    assert base[1] == 0.0 and base[2] == pytest.approx(1.0)
    assert srgb_to_linear(0.04) == pytest.approx(0.04 / 12.92)


def test_transparency_sets_blend_mode():
    gltf, _ = _parse(build_glb([_triangle(color=(1, 0, 0, 0.4)), _triangle()]))
    assert gltf["materials"][0]["alphaMode"] == "BLEND"
    assert gltf["materials"][0]["pbrMetallicRoughness"]["baseColorFactor"][
        3
    ] == pytest.approx(0.4)
    assert "alphaMode" not in gltf["materials"][1]


def test_vertex_colors_are_linear_floats():
    tri = _triangle(color=(1, 1, 1, 1))
    tri.vertex_colors = np.array(
        [[255, 0, 0, 255], [0, 128, 0, 255], [0, 0, 255, 100]], np.uint8
    )
    gltf, blob = _parse(build_glb([tri]))
    acc = gltf["accessors"][gltf["meshes"][0]["primitives"][0]["attributes"]["COLOR_0"]]
    assert acc["componentType"] == 5126 and acc["type"] == "VEC4"
    view = gltf["bufferViews"][acc["bufferView"]]
    cols = np.frombuffer(
        blob[view["byteOffset"] : view["byteOffset"] + view["byteLength"]], np.float32
    )
    cols = cols.reshape(-1, 4)
    assert cols[1, 1] == pytest.approx(srgb_to_linear(128 / 255), abs=1e-5)
    assert cols[2, 3] == pytest.approx(100 / 255, abs=1e-5)
    assert gltf["materials"][0]["alphaMode"] == "BLEND"


def test_zero_normals_do_not_produce_nan():
    tri = _triangle()
    tri.normals = np.zeros((3, 3))
    gltf, blob = _parse(build_glb([tri]))
    acc = gltf["accessors"][gltf["meshes"][0]["primitives"][0]["attributes"]["NORMAL"]]
    view = gltf["bufferViews"][acc["bufferView"]]
    nrm = np.frombuffer(
        blob[view["byteOffset"] : view["byteOffset"] + view["byteLength"]], np.float32
    )
    assert np.isfinite(nrm).all()


def test_empty_scene_is_rejected():
    empty = Primitive("e", np.zeros((0, 3)), np.zeros((0, 3)), np.zeros((0, 3), int))
    with pytest.raises(ValueError):
        build_glb([empty])
    lo, hi = bounds([_triangle(), _triangle(offset=-1.0)])
    assert lo.tolist() == [-1, -1, -1] and hi.tolist() == [1, 1, 0]


def test_gvml_package_parts_and_camera():
    glb = build_glb([_triangle()])
    payload = build_gvml(glb, extent=(4.0, 2.0, 1.0), fov_deg=15.0, size_pt=360)
    z = zipfile.ZipFile(io.BytesIO(payload))
    names = set(z.namelist())
    assert names == {
        "[Content_Types].xml",
        "_rels/.rels",
        "clipboard/drawings/drawing1.xml",
        "clipboard/drawings/_rels/drawing1.xml.rels",
        "clipboard/media/model3d1.glb",
    }
    assert z.read("clipboard/media/model3d1.glb") == glb
    drawing = z.read("clipboard/drawings/drawing1.xml").decode()
    # No preview raster: PowerPoint would show a stale picture until touched.
    assert (
        "am3d:raster" not in drawing
        and "image" not in z.read("[Content_Types].xml").decode()
    )
    assert f'fov="{15 * ANGLE_UNIT}"' in drawing
    assert 'meterPerModelUnit n="250000"' in drawing  # largest extent 4 -> 1 m
    half_diag = math.sqrt(1.0 + 0.25 + 0.0625) / 2
    cam_z = round(camera_distance(half_diag, 15.0) * EMU_PER_METER)
    assert f'<am3d:pos x="0" y="0" z="{cam_z}"/>' in drawing
    assert '<a:ext cx="4572000" cy="4572000"/>' in drawing  # 360 pt


def test_gvml_escapes_name_and_rejects_flat_extent():
    payload = build_gvml(build_glb([_triangle()]), (1, 1, 1), name='A & "B" <c>')
    drawing = (
        zipfile.ZipFile(io.BytesIO(payload))
        .read("clipboard/drawings/drawing1.xml")
        .decode()
    )
    assert 'name="A &amp; &quot;B&quot; &lt;c&gt;"' in drawing
    with pytest.raises(ValueError):
        build_gvml(b"", (0, 0, 0))
