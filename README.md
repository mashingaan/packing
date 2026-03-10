# packing-mvp

MVP tool for packing STEP geometry into a container using axis-aligned bounding boxes from `gmsh` / OpenCASCADE. The solver is bbox-based: it does not run exact mesh collision checks.

## What It Does

- reads `.step` / `.stp` files through `gmsh`
- extracts solids and their bounding boxes
- optionally auto-scales meter-based geometry to millimeters
- packs bounding boxes with an extreme-points heuristic
- writes:
  - `result.json`
  - `placements.csv`
  - `arranged.step`
  - `preview_top.png`
  - `preview_side.png`
  - `preview.gif`
  - `packing.log`

## Requirements

- Windows 11
- Python 3.10+

## Install

```powershell
cd C:\path\to\packing-mvp
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
```

`python -m pip install -e .` installs both `gmsh` for bbox extraction and `cadquery-ocp` (`OCP`) for single-root STEP export.

## CLI

Basic run:

```powershell
python -m packing_mvp.cli --input "part.step" --out out --maxW 2400 --maxH 1800 --maxL 4400 --gap 10
```

Search the minimal working length:

```powershell
python -m packing_mvp.cli --input "part.step" --out out --maxW 2400 --maxH 1800 --gap 10
```

Export `arranged.step` in source STEP units:

```powershell
python -m packing_mvp.cli --input "part.step" --out out --maxW 2400 --maxH 1800 --gap 10 --step-units source
```

Force only flat placements:

```powershell
python -m packing_mvp.cli --input "part.step" --out out --maxW 2400 --maxH 1800 --maxL 4400 --gap 10 --flat-only
```

Treat the whole STEP as one rigid assembly and keep it flat:

```powershell
python -m packing_mvp.cli --input "part.step" --out out --maxW 2400 --maxH 1800 --maxL 4400 --gap 10 --flat-only --treat-input-as-single-item
```

## Packing Modes

### Default `solids` mode

This is the existing behavior.

- the STEP file is split into separate solids
- each solid becomes its own packing item
- each solid can receive its own placement and rotation
- `placements.csv` keeps the original solid-oriented schema
- `arranged.step` is rebuilt from per-solid placements

Use this when the input file really contains independent parts that may be rearranged separately.

### `--treat-input-as-single-item`

This is the single-root-shape mode.

- the whole input STEP is treated as one rigid item
- the whole input STEP is preserved as one root shape / compound during export
- all source solids keep their internal relative positions
- the packer places and rotates only the aggregate bounding box of the whole model
- `placements.csv` contains one row per rigid group with:
  - `item_id`
  - `mode`
  - `source_count`
  - `source_tags`
  - `dx,dy,dz`
  - `x,y,z`
  - `rot`
  - `bbox_minx,bbox_miny,bbox_minz,bbox_maxx,bbox_maxy,bbox_maxz`
- `result.json` reports `packing_mode: "single_root_shape"`
- `arranged.step` writes one transformed root object, not an exploded list of child solids

Use this for welded assemblies, fixture nodes, pipe-plus-plate models, or any STEP that must not be split into independent parts.

## `--flat-only`

`--flat-only` restricts allowed orientations to lying-flat positions only.

MVP rule:

- take the original item dimensions
- compute the minimal original dimension
- after orientation, the resulting `Z` height must equal that minimal original dimension

Example:

- original dims: `(100, 200, 300)`
- allowed orientations: only those where the resulting height is `100`
- disallowed: standing on an edge or an end face

This rule applies to both:

- individual solids in default mode
- aggregate rigid-group dimensions in `--treat-input-as-single-item` mode

## `arranged.step`

`arranged.step` always uses real source solids from the STEP file, not synthetic boxes.

- in default mode, each source solid gets its own transform from `placements.csv`
- in `--treat-input-as-single-item` mode, the exporter reads the whole STEP as one root shape, applies one orientation to that root shape, recomputes the rotated root bbox, translates the root shape once, and writes that transformed root object back to STEP
- no per-child placement or exploded layout is allowed in single-root-shape mode
- if the STEP contains multiple solids internally, they remain inside one exported transformed root object

## `result.json`

The JSON report includes:

- input file information
- container constraints
- recommended packed dimensions
- used extents
- packing statistics
- scale information
- `treat_input_as_single_item`
- `flat_only`
- `packing_mode`

`packing_mode` is always one of:

- `solids`
- `single_root_shape`

`constraints` also stores:

- `flat_only`
- `treat_input_as_single_item`
- `packing_mode`

## GUI

GUI is still available:

```powershell
python -m packing_mvp.gui
```

The new rigid-group switch is currently documented and exposed through CLI only.

## Auto Updates

The desktop client can now check GitHub Releases and apply a new installer automatically.

- default releases repo: `mashingaan/packing`
- default installer asset name: `PackingMVP-Setup.exe`
- optional checksum asset name: `PackingMVP-Setup.exe.sha256`

The packaged Windows app shows a `Проверить обновления` button in the GUI header. In a built EXE, the app can:

- check the latest GitHub Release
- compare the release tag against the current app version
- download the installer
- verify SHA256 when the `.sha256` asset is present
- close the app, run the installer silently, and start the app again

If you need to point the client to a different repo or asset name, override:

- `PACKING_MVP_GITHUB_REPO`
- `PACKING_MVP_RELEASE_ASSET`

### Release Workflow

Build the installer:

```powershell
cd C:\path\to\packing-mvp
.\scripts\build_installer.ps1
```

The build now produces:

- `dist-installer\PackingMVP-Setup.exe`
- `dist-installer\PackingMVP-Setup.exe.sha256`

Publish a GitHub Release with a version tag like `v0.3.2` and upload both files. Once the client starts the packaged app, it can detect and install that release without manually sending a new setup file.

### GitHub Actions Release

The repository now includes `.github/workflows/release.yml`.

It does the following on `v*` tags:

- checks out the repository on `windows-latest`
- installs Python and Inno Setup
- verifies that the Git tag matches `packing_mvp.__version__`
- runs `python -m unittest discover -s tests -v`
- builds `PackingMVP-Setup.exe` and `PackingMVP-Setup.exe.sha256`
- uploads both files to the GitHub Release automatically

You can use it in two ways:

1. Update `src/packing_mvp/__init__.py` to the target version, commit, and push a tag like `v0.3.2`.
2. Or start the workflow manually in GitHub Actions and pass a tag like `v0.3.2`; the workflow will create the tag on the selected commit if it does not exist yet.

## Tests

Run the test suite:

```powershell
cd C:\path\to\packing-mvp
python -m unittest discover -s tests -v
```

## MVP Limits

- packing is bbox-based, not exact CAD collision detection
- rotations are limited to axis permutations from `ROTATION_ORDERS`
- `preview_top.png`, `preview_side.png`, and `preview.gif` are bbox previews
- in rigid-group mode, previews show the aggregate group bbox rather than internal solid geometry
