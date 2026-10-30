"""Build the "Art::GVML ClipFormat" payload PowerPoint pastes as a 3D model.

The payload is a small OPC zip (the same shape PowerPoint itself puts on the
clipboard when a 3D model is copied): a DrawingML locked canvas holding one
``am3d:model3d`` graphic frame plus the embedded .glb.  Unlike the plain
``model/gltf-binary`` clipboard format it carries the camera, so the pasted
model keeps the field of view chosen in the plugin.

No preview raster is included on purpose: with one, PowerPoint shows that
picture until the model is touched; without one it renders the model itself.
"""

import io
import math
import zipfile

EMU_PER_METER = 36_000_000
EMU_PER_POINT = 12_700
ANGLE_UNIT = 60_000  # DrawingML angles are in 1/60000 degree

CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="glb" ContentType="model/gltf.binary"/>'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/clipboard/drawings/drawing1.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.drawing+xml"/>'
    "</Types>"
)

ROOT_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing" '
    'Target="clipboard/drawings/drawing1.xml"/>'
    "</Relationships>"
)

DRAWING_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" '
    'Type="http://schemas.microsoft.com/office/2017/06/relationships/model3d" '
    'Target="../media/model3d1.glb"/>'
    "</Relationships>"
)

DRAWING = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
    '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/lockedCanvas">'
    '<lc:lockedCanvas xmlns:lc="http://schemas.openxmlformats.org/drawingml/2006/lockedCanvas">'
    '<a:nvGrpSpPr><a:cNvPr id="0" name=""/><a:cNvGrpSpPr/></a:nvGrpSpPr>'
    '<a:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/>'
    '<a:chOff x="0" y="0"/><a:chExt cx="{cx}" cy="{cy}"/></a:xfrm></a:grpSpPr>'
    "<a:graphicFrame><a:nvGraphicFramePr>"
    '<a:cNvPr id="2" name="{name}"/><a:cNvGraphicFramePr><a:graphicFrameLocks/></a:cNvGraphicFramePr>'
    "</a:nvGraphicFramePr><a:graphic>"
    '<a:graphicData uri="http://schemas.microsoft.com/office/drawing/2017/model3d">'
    '<am3d:model3d xmlns:am3d="http://schemas.microsoft.com/office/drawing/2017/model3d" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" r:embed="rId1">'
    '<am3d:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/></a:xfrm>'
    '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></am3d:spPr>'
    '<am3d:camera><am3d:pos x="0" y="0" z="{cam_z}"/>'
    '<am3d:up dx="0" dy="{emu_m}" dz="0"/><am3d:lookAt x="0" y="0" z="0"/>'
    '<am3d:perspective fov="{fov}"/></am3d:camera>'
    "<am3d:trans>"
    '<am3d:meterPerModelUnit n="{mpu_n}" d="1000000"/>'
    '<am3d:preTrans dx="{pre_x}" dy="{pre_y}" dz="{pre_z}"/>'
    '<am3d:scale><am3d:sx n="1000000" d="1000000"/><am3d:sy n="1000000" d="1000000"/>'
    '<am3d:sz n="1000000" d="1000000"/></am3d:scale>'
    '<am3d:rot/><am3d:postTrans dx="0" dy="0" dz="0"/>'
    "</am3d:trans>"
    '<am3d:objViewport viewportSz="{viewport}"/>'
    "{lights}"
    "</am3d:model3d></a:graphicData></a:graphic>"
    '<a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
    "</a:graphicFrame></lc:lockedCanvas></a:graphicData></a:graphic>"
)

# PowerPoint's own default studio rig, as it writes it for a freshly inserted model.
DEFAULT_LIGHTS = (
    '<am3d:ambientLight><am3d:clr><a:scrgbClr r="50000" g="50000" b="50000"/></am3d:clr>'
    '<am3d:illuminance n="500000" d="1000000"/></am3d:ambientLight>'
    '<am3d:ptLight rad="0"><am3d:clr><a:scrgbClr r="100000" g="75000" b="50000"/></am3d:clr>'
    '<am3d:intensity n="9765625" d="1000000"/>'
    '<am3d:pos x="21959998" y="70920001" z="16344003"/></am3d:ptLight>'
    '<am3d:ptLight rad="0"><am3d:clr><a:scrgbClr r="40000" g="60000" b="95000"/></am3d:clr>'
    '<am3d:intensity n="12250000" d="1000000"/>'
    '<am3d:pos x="-37964106" y="51130435" z="57631972"/></am3d:ptLight>'
    '<am3d:ptLight rad="0"><am3d:clr><a:scrgbClr r="86837" g="72700" b="100000"/></am3d:clr>'
    '<am3d:intensity n="3125000" d="1000000"/>'
    '<am3d:pos x="-37739122" y="58056624" z="-34769649"/></am3d:ptLight>'
)

# Ratio PowerPoint writes between objViewport/viewportSz and the frame size.
VIEWPORT_PER_FRAME = 7708053 / 5080000


def camera_distance(half_diagonal: float, fov_deg: float) -> float:
    """Distance at which a sphere of radius ``half_diagonal`` fills the view."""
    return half_diagonal / math.sin(math.radians(fov_deg) / 2)


def build_gvml(
    glb: bytes,
    extent,
    center=(0.0, 0.0, 0.0),
    fov_deg: float = 15.0,
    size_pt: float = 360.0,
    name: str = "3D Model",
) -> bytes:
    """Return the GVML zip bytes for ``glb``.

    ``extent`` is the model's axis-aligned size (dx, dy, dz) in model units and
    ``center`` the bounding-box center.  PowerPoint normalizes a model so its
    largest extent is one meter; the camera is placed so the bounding sphere
    fits the requested field of view, which leaves room for a turntable spin.
    """
    largest = max(float(e) for e in extent)
    if largest <= 0:
        raise ValueError("Model has no extent.")
    meter_per_unit = 1.0 / largest
    half_diag = math.sqrt(sum((float(e) * meter_per_unit) ** 2 for e in extent)) / 2
    frame = int(round(size_pt * EMU_PER_POINT))
    drawing = DRAWING.format(
        cx=frame,
        cy=frame,
        name=_xml_escape(name),
        cam_z=int(round(camera_distance(half_diag, fov_deg) * EMU_PER_METER)),
        emu_m=EMU_PER_METER,
        fov=int(round(fov_deg * ANGLE_UNIT)),
        mpu_n=int(round(meter_per_unit * 1_000_000)),
        pre_x=int(round(-center[0] * meter_per_unit * EMU_PER_METER)),
        pre_y=int(round(-center[1] * meter_per_unit * EMU_PER_METER)),
        pre_z=int(round(-center[2] * meter_per_unit * EMU_PER_METER)),
        viewport=int(round(frame * VIEWPORT_PER_FRAME)),
        lights=DEFAULT_LIGHTS,
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", ROOT_RELS)
        z.writestr("clipboard/drawings/drawing1.xml", drawing)
        z.writestr("clipboard/drawings/_rels/drawing1.xml.rels", DRAWING_RELS)
        z.writestr(
            "clipboard/media/model3d1.glb", glb, compress_type=zipfile.ZIP_STORED
        )
    return buf.getvalue()


def _xml_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
