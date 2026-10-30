# Paste 3D to PowerPoint

A [MoleditPy](https://github.com/HiroYokoyama/python_molecular_editor) plugin that copies the
3D view to the clipboard as a **native PowerPoint 3D model**. Paste it with Ctrl+V and it can be
rotated on the slide, and with the Turntable animation it spins during the slide show. It works
offline, needs no add-in at presentation time and does not drive PowerPoint.

## What it exports

The plugin exports whatever the 3D view shows, so it works with other plugins without
plugin-specific code:

- molecules in any 3D style, including element colors and half-colored bonds;
- CIF Viewer crystals, with unit-cell lines and axes drawn as tubes;
- orbitals and other cube-file isosurfaces, with their transparency;
- other meshes that plugins add to the 3D view.

The model keeps the current viewing direction, colors, gloss and opacity. A parallel-projection
view becomes a narrow (10°) perspective, because PowerPoint has only perspective cameras.

Text labels, 2D overlays, point sprites and volume renderings have no mesh and are left out. The
status bar reports how many objects were skipped.

## Usage

| Menu | What it does |
|---|---|
| **Export > Copy 3D to PowerPoint** | Puts the 3D view on the clipboard. Paste into PowerPoint with Ctrl+V. |
| **Export > Export 3D Scene as glTF (.glb)...** | Saves the same model as a `.glb` file (PowerPoint: Insert > 3D Models > This Device). |

To make the structure spin, select the pasted model in PowerPoint and choose
**Animations > Turntable**. Set **Repeat** to *Until End of Slide*.

## How the paste works

The clipboard receives three formats, and the paste target uses the richest one it supports:

| Format | Used by |
|---|---|
| `Art::GVML ClipFormat` | PowerPoint and other Office apps. A 3D model with the camera and field of view set by the plugin. |
| `model/gltf-binary` | Apps that accept a bare glTF model. Uses the default camera. |
| bitmap | Apps without 3D support. |

Colors are converted from sRGB to the linear values glTF requires. Without this conversion,
glTF exports look washed out in PowerPoint.

## Requirements

- MoleditPy 5.x
- The Office clipboard formats are Windows features. The `.glb` export works on every platform.

## License

GNU Lesser General Public License. See [LICENSE](LICENSE), [COPYING](COPYING) and
[LICENSING.md](LICENSING.md).
