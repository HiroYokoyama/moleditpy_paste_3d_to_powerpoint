"""Minimal glTF 2.0 binary (.glb) writer for captured scene primitives.

One glTF mesh with one primitive per :class:`Primitive`; every primitive gets
its own PBR material so PowerPoint (and any other glTF viewer) shows the
colors, gloss and transparency of the MoleditPy view.
"""

import json
import struct
from dataclasses import dataclass, field
from typing import Any, List, Optional, Sequence

GLB_MAGIC = 0x46546C67
CHUNK_JSON = 0x4E4F534A
CHUNK_BIN = 0x004E4942

ARRAY_BUFFER = 34962
ELEMENT_ARRAY_BUFFER = 34963
FLOAT = 5126
UNSIGNED_INT = 5125


@dataclass
class Primitive:
    """A triangle mesh with one material.

    ``positions``/``normals`` are (N, 3) float arrays, ``indices`` an (M, 3)
    integer array.  ``vertex_colors`` is an optional (N, 4) uint8 array used
    for color maps that cannot be split into flat-colored groups.
    """

    name: str
    positions: Any
    normals: Any
    indices: Any
    color: Sequence[float] = (0.8, 0.8, 0.8, 1.0)
    roughness: float = 0.5
    metallic: float = 0.0
    vertex_colors: Optional[Any] = None
    extras: dict = field(default_factory=dict)

    @property
    def is_transparent(self) -> bool:
        if self.color[3] < 0.999:
            return True
        if self.vertex_colors is not None:
            return bool((self.vertex_colors[:, 3] < 255).any())
        return False


def srgb_to_linear(c: float) -> float:
    """glTF base colors are linear; MoleditPy/VTK colors are sRGB.

    Writing sRGB values unconverted is what makes molecules look washed out in
    PowerPoint (dark carbon turns mid-grey).
    """
    c = min(max(float(c), 0.0), 1.0)
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _material(prim: Primitive) -> dict:
    rgb = [srgb_to_linear(c) for c in prim.color[:3]]
    mat = {
        "name": prim.name,
        "doubleSided": True,
        "pbrMetallicRoughness": {
            "baseColorFactor": rgb + [float(prim.color[3])],
            "metallicFactor": float(prim.metallic),
            "roughnessFactor": float(prim.roughness),
        },
    }
    if prim.is_transparent:
        mat["alphaMode"] = "BLEND"
    return mat


def build_glb(primitives: List[Primitive], generator: str = "MoleditPy") -> bytes:
    """Serialize primitives into GLB bytes."""
    import numpy as np

    blob = bytearray()
    views: List[dict] = []
    accessors: List[dict] = []
    materials: List[dict] = []
    gl_prims: List[dict] = []

    def add_view(data: bytes, target: int) -> int:
        blob.extend(b"\0" * (-len(blob) % 4))
        views.append(
            {
                "buffer": 0,
                "byteOffset": len(blob),
                "byteLength": len(data),
                "target": target,
            }
        )
        blob.extend(data)
        return len(views) - 1

    for prim in primitives:
        pos = np.ascontiguousarray(prim.positions, dtype=np.float32).reshape(-1, 3)
        nrm = np.ascontiguousarray(prim.normals, dtype=np.float32).reshape(-1, 3)
        idx = np.ascontiguousarray(prim.indices, dtype=np.uint32).ravel()
        if len(pos) == 0 or len(idx) == 0:
            continue
        lengths = np.linalg.norm(nrm, axis=1, keepdims=True)
        nrm = np.where(
            lengths > 1e-12, nrm / np.maximum(lengths, 1e-12), [0.0, 0.0, 1.0]
        )
        nrm = nrm.astype(np.float32)

        attributes = {}
        attributes["POSITION"] = len(accessors)
        accessors.append(
            {
                "bufferView": add_view(pos.tobytes(), ARRAY_BUFFER),
                "componentType": FLOAT,
                "count": len(pos),
                "type": "VEC3",
                "min": pos.min(axis=0).tolist(),
                "max": pos.max(axis=0).tolist(),
            }
        )
        attributes["NORMAL"] = len(accessors)
        accessors.append(
            {
                "bufferView": add_view(nrm.tobytes(), ARRAY_BUFFER),
                "componentType": FLOAT,
                "count": len(nrm),
                "type": "VEC3",
            }
        )
        if prim.vertex_colors is not None:
            srgb = (
                np.asarray(prim.vertex_colors, dtype=np.float64).reshape(-1, 4) / 255.0
            )
            rgb = np.where(
                srgb[:, :3] <= 0.04045,
                srgb[:, :3] / 12.92,
                ((srgb[:, :3] + 0.055) / 1.055) ** 2.4,
            )
            col = np.ascontiguousarray(np.hstack([rgb, srgb[:, 3:]]), dtype=np.float32)
            attributes["COLOR_0"] = len(accessors)
            accessors.append(
                {
                    "bufferView": add_view(col.tobytes(), ARRAY_BUFFER),
                    "componentType": FLOAT,
                    "count": len(col),
                    "type": "VEC4",
                }
            )
        index_accessor = len(accessors)
        accessors.append(
            {
                "bufferView": add_view(idx.tobytes(), ELEMENT_ARRAY_BUFFER),
                "componentType": UNSIGNED_INT,
                "count": len(idx),
                "type": "SCALAR",
            }
        )
        materials.append(_material(prim))
        gl_prims.append(
            {
                "attributes": attributes,
                "indices": index_accessor,
                "material": len(materials) - 1,
            }
        )

    if not gl_prims:
        raise ValueError("No triangles to export.")

    blob.extend(b"\0" * (-len(blob) % 4))
    gltf = {
        "asset": {"version": "2.0", "generator": generator},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0, "name": "scene"}],
        "meshes": [{"primitives": gl_prims}],
        "materials": materials,
        "accessors": accessors,
        "bufferViews": views,
        "buffers": [{"byteLength": len(blob)}],
    }
    js = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    js += b" " * (-len(js) % 4)
    total = 12 + 8 + len(js) + 8 + len(blob)
    return b"".join(
        [
            struct.pack("<III", GLB_MAGIC, 2, total),
            struct.pack("<II", len(js), CHUNK_JSON),
            js,
            struct.pack("<II", len(blob), CHUNK_BIN),
            bytes(blob),
        ]
    )


def bounds(primitives: List[Primitive]):
    """Axis-aligned (min, max) over all primitive positions."""
    import numpy as np

    pts = [
        np.asarray(p.positions).reshape(-1, 3) for p in primitives if len(p.positions)
    ]
    if not pts:
        raise ValueError("No geometry.")
    allp = np.vstack(pts)
    return allp.min(axis=0), allp.max(axis=0)
