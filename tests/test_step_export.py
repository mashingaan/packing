from __future__ import annotations

import itertools
import math
from pathlib import Path
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from packing_mvp.step_export import (
    _OcpModules,
    build_permutation_affine_matrix,
    export_arranged_step,
    load_placements_csv,
)
from packing_mvp.utils import (
    orientation_to_rigid_rotation,
    rotation_matrix_determinant,
    rotation_matrix_is_orthonormal,
)


def _write_csv(tmp_path: Path, content: str, filename: str = "placements.csv") -> Path:
    csv_path = tmp_path / filename
    csv_path.write_text(textwrap.dedent(content).strip() + "\n", encoding="utf-8")
    return csv_path


class PlacementCsvTests(unittest.TestCase):
    def test_load_placements_csv_parses_valid_rows_and_defaults_rotation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            csv_path = _write_csv(
                tmp_path,
                """
                part_id,solid_tag,dx,dy,dz,x,y,z,rot,bbox_minx,bbox_miny,bbox_minz,bbox_maxx,bbox_maxy,bbox_maxz
                part_001,7,100,200,300,10,20,30,,10,20,30,110,220,330
                """,
            )

            placements = load_placements_csv(csv_path)

            self.assertEqual(len(placements), 1)
            self.assertEqual(placements[0].part_id, "part_001")
            self.assertEqual(placements[0].solid_tag, 7)
            self.assertEqual(placements[0].rot, "XYZ")
            self.assertEqual((placements[0].x, placements[0].y, placements[0].z), (10.0, 20.0, 30.0))

    def test_load_placements_csv_parses_rigid_group_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            csv_path = _write_csv(
                tmp_path,
                """
                item_id,mode,copy_index,source_count,source_tags,dx,dy,dz,x,y,z,rot,planar_angle_deg,bbox_minx,bbox_miny,bbox_minz,bbox_maxx,bbox_maxy,bbox_maxz
                assembly_0_copy_000,rigid_group,0,2,"[7, 8]",100,200,300,10,20,30,,5,10,20,30,110,220,330
                """,
            )

            placements = load_placements_csv(csv_path)

            self.assertEqual(len(placements), 1)
            self.assertEqual(placements[0].part_id, "assembly_0_copy_000")
            self.assertEqual(placements[0].mode, "rigid_group")
            self.assertIsNone(placements[0].solid_tag)
            self.assertEqual(placements[0].copy_index, 0)
            self.assertEqual(placements[0].source_count, 2)
            self.assertEqual(placements[0].source_tags, (7, 8))
            self.assertEqual(placements[0].rot, "XYZ")
            self.assertEqual(placements[0].planar_angle_deg, 5.0)

    def test_load_placements_csv_requires_part_id_header(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            csv_path = _write_csv(
                tmp_path,
                """
                solid_tag,dx,dy,dz,x,y,z,rot,bbox_minx,bbox_miny,bbox_minz,bbox_maxx,bbox_maxy,bbox_maxz
                7,100,200,300,10,20,30,XYZ,10,20,30,110,220,330
                """,
            )

            with self.assertRaisesRegex(RuntimeError, "part_id"):
                load_placements_csv(csv_path)

    def test_load_placements_csv_requires_solid_tag_header(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            csv_path = _write_csv(
                tmp_path,
                """
                part_id,dx,dy,dz,x,y,z,rot,bbox_minx,bbox_miny,bbox_minz,bbox_maxx,bbox_maxy,bbox_maxz
                part_001,100,200,300,10,20,30,XYZ,10,20,30,110,220,330
                """,
            )

            with self.assertRaisesRegex(RuntimeError, "solid_tag"):
                load_placements_csv(csv_path)

    def test_load_placements_csv_rejects_non_numeric_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            csv_path = _write_csv(
                tmp_path,
                """
                part_id,solid_tag,dx,dy,dz,x,y,z,rot,bbox_minx,bbox_miny,bbox_minz,bbox_maxx,bbox_maxy,bbox_maxz
                part_001,7,100,200,300,abc,20,30,XYZ,10,20,30,110,220,330
                """,
            )

            with self.assertRaisesRegex(RuntimeError, "invalid number"):
                load_placements_csv(csv_path)


class RotationMatrixTests(unittest.TestCase):
    def test_build_permutation_affine_matrix_supports_all_rotations(self) -> None:
        expected = {
            "XYZ": [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0],
            "XZY": [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, -1.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0],
            "YXZ": [0.0, 1.0, 0.0, 0.0, -1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0],
            "YZX": [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0],
            "ZXY": [0.0, 0.0, 1.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0],
            "ZYX": [0.0, 0.0, 1.0, 0.0, 0.0, 1.0, 0.0, 0.0, -1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0],
        }

        for label, matrix in expected.items():
            with self.subTest(label=label):
                self.assertEqual(build_permutation_affine_matrix(label), matrix)

    def test_build_permutation_affine_matrix_rejects_unknown_rotation(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsupported rotation label"):
            build_permutation_affine_matrix("BAD")


class RigidOrientationTests(unittest.TestCase):
    def test_orientation_matrices_are_rigid(self) -> None:
        for label in ("XYZ", "XZY", "YXZ", "YZX", "ZXY", "ZYX"):
            with self.subTest(label=label):
                rotation = orientation_to_rigid_rotation(label)
                self.assertTrue(rotation_matrix_is_orthonormal(rotation.matrix))
                self.assertAlmostEqual(rotation_matrix_determinant(rotation.matrix), 1.0, places=6)

    def test_no_reflection_in_orientation_mapping(self) -> None:
        for label in ("XYZ", "XZY", "YXZ", "YZX", "ZXY", "ZYX"):
            with self.subTest(label=label):
                determinant = rotation_matrix_determinant(
                    orientation_to_rigid_rotation(label).matrix
                )
                self.assertGreater(determinant, 0.0)


class _FakeOption:
    def setNumber(self, name: str, value: float) -> None:
        self.last_call = (name, value)


class _FakeOcc:
    def __init__(self, entities: dict[int, list[float]] | None = None) -> None:
        self.synchronize_calls = 0
        self.get_bounding_box_calls = 0
        self.entities: dict[int, list[float]] = {
            tag: list(bbox)
            for tag, bbox in (entities or {1: [0.0, 0.0, 0.0, 100.0, 200.0, 300.0]}).items()
        }
        self.original_tags = sorted(self.entities)
        self.removed: tuple[list[tuple[int, int]], bool] | None = None

    def importShapes(self, path: str, highestDimOnly: bool = True, format: str = "step"):
        return [(3, tag) for tag in self.original_tags]

    def synchronize(self) -> None:
        self.synchronize_calls += 1

    def copy(self, dimtags: list[tuple[int, int]]):
        source_tag = dimtags[0][1]
        copied_tag = source_tag + 100
        self.entities[copied_tag] = list(self.entities[source_tag])
        return [(3, copied_tag)]

    def dilate(self, dimtags, x, y, z, sx, sy, sz) -> None:
        pass

    def affineTransform(self, dimtags, matrix) -> None:
        pass

    def rotate(
        self,
        dimtags: list[tuple[int, int]],
        x: float,
        y: float,
        z: float,
        ax: float,
        ay: float,
        az: float,
        angle: float,
    ) -> None:
        matrix = _rotation_matrix_from_axis_angle((ax, ay, az), angle)
        transform = (
            (matrix[0][0], matrix[0][1], matrix[0][2], 0.0),
            (matrix[1][0], matrix[1][1], matrix[1][2], 0.0),
            (matrix[2][0], matrix[2][1], matrix[2][2], 0.0),
            (0.0, 0.0, 0.0, 1.0),
        )
        for _, tag in dimtags:
            self.entities[tag] = list(_apply_matrix_to_bbox(tuple(self.entities[tag]), transform))

    def getBoundingBox(self, dim: int, tag: int):
        self.get_bounding_box_calls += 1
        return tuple(self.entities[tag])

    def translate(self, dimtags: list[tuple[int, int]], dx: float, dy: float, dz: float) -> None:
        for _, tag in dimtags:
            bbox = self.entities[tag]
            self.entities[tag] = [
                bbox[0] + dx,
                bbox[1] + dy,
                bbox[2] + dz,
                bbox[3] + dx,
                bbox[4] + dy,
                bbox[5] + dz,
            ]

    def remove(self, dimtags: list[tuple[int, int]], recursive: bool = False) -> None:
        self.removed = (list(dimtags), recursive)


class _FakeModel:
    def __init__(self, entities: dict[int, list[float]] | None = None) -> None:
        self.occ = _FakeOcc(entities)
        self.added_names: list[str] = []

    def add(self, name: str) -> None:
        self.added_names.append(name)

    def getEntities(self, dim: int):
        if dim == 3:
            return [(3, tag) for tag in self.occ.original_tags]
        return []


class _FakeGmsh:
    def __init__(self, entities: dict[int, list[float]] | None = None) -> None:
        self.option = _FakeOption()
        self.model = _FakeModel(entities)
        self.initialize_calls = 0
        self.finalize_calls = 0
        self.clear_calls = 0
        self.writes: list[str] = []

    def initialize(self) -> None:
        self.initialize_calls += 1

    def finalize(self) -> None:
        self.finalize_calls += 1

    def clear(self) -> None:
        self.clear_calls += 1

    def write(self, path: str) -> None:
        self.writes.append(path)
        Path(path).write_text("fake-step", encoding="utf-8")


class _FakeShape:
    def __init__(self, bbox: tuple[float, float, float, float, float, float]) -> None:
        self.bbox = tuple(float(value) for value in bbox)

    def IsNull(self) -> bool:
        return False


class _FakeCompound(_FakeShape):
    def __init__(self) -> None:
        super().__init__((0.0, 0.0, 0.0, 0.0, 0.0, 0.0))
        self._is_null = True
        self.children: list[_FakeShape] = []

    def IsNull(self) -> bool:
        return self._is_null


class _FakeBRepBuilder:
    def MakeCompound(self, compound: _FakeCompound) -> None:
        compound._is_null = False
        compound.bbox = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

    def Add(self, compound: _FakeCompound, shape: _FakeShape) -> None:
        if compound._is_null:
            raise RuntimeError("Compound must be initialized before adding shapes.")
        compound.children.append(shape)
        if compound.bbox == (0.0, 0.0, 0.0, 0.0, 0.0, 0.0):
            compound.bbox = shape.bbox
            return
        compound.bbox = (
            min(compound.bbox[0], shape.bbox[0]),
            min(compound.bbox[1], shape.bbox[1]),
            min(compound.bbox[2], shape.bbox[2]),
            max(compound.bbox[3], shape.bbox[3]),
            max(compound.bbox[4], shape.bbox[4]),
            max(compound.bbox[5], shape.bbox[5]),
        )


class _FakeBndBox:
    def __init__(self) -> None:
        self.bounds: tuple[float, float, float, float, float, float] | None = None

    def Get(self) -> tuple[float, float, float, float, float, float] | None:
        return self.bounds


class _FakeBRepBndLib:
    @staticmethod
    def Add_s(shape: _FakeShape, box: _FakeBndBox, *args) -> None:
        box.bounds = shape.bbox


class _FakeGpTrsf:
    def __init__(self) -> None:
        self.matrix = (
            (1.0, 0.0, 0.0, 0.0),
            (0.0, 1.0, 0.0, 0.0),
            (0.0, 0.0, 1.0, 0.0),
            (0.0, 0.0, 0.0, 1.0),
        )

    def SetScale(self, point, scale: float) -> None:
        self.matrix = (
            (float(scale), 0.0, 0.0, 0.0),
            (0.0, float(scale), 0.0, 0.0),
            (0.0, 0.0, float(scale), 0.0),
            (0.0, 0.0, 0.0, 1.0),
        )

    def SetValues(
        self,
        a11: float,
        a12: float,
        a13: float,
        a14: float,
        a21: float,
        a22: float,
        a23: float,
        a24: float,
        a31: float,
        a32: float,
        a33: float,
        a34: float,
    ) -> None:
        self.matrix = (
            (float(a11), float(a12), float(a13), float(a14)),
            (float(a21), float(a22), float(a23), float(a24)),
            (float(a31), float(a32), float(a33), float(a34)),
            (0.0, 0.0, 0.0, 1.0),
        )

    def SetTranslation(self, vector) -> None:
        self.matrix = (
            (1.0, 0.0, 0.0, float(vector[0])),
            (0.0, 1.0, 0.0, float(vector[1])),
            (0.0, 0.0, 1.0, float(vector[2])),
            (0.0, 0.0, 0.0, 1.0),
        )

    def SetRotation(self, ax1, angle: float) -> None:
        axis = ax1[1]
        rotation = _rotation_matrix_from_axis_angle(axis, angle)
        self.matrix = (
            (rotation[0][0], rotation[0][1], rotation[0][2], 0.0),
            (rotation[1][0], rotation[1][1], rotation[1][2], 0.0),
            (rotation[2][0], rotation[2][1], rotation[2][2], 0.0),
            (0.0, 0.0, 0.0, 1.0),
        )

    def PreMultiply(self, other: "_FakeGpTrsf") -> None:
        self.matrix = _multiply_4x4(other.matrix, self.matrix)


def _apply_matrix_to_bbox(
    bbox: tuple[float, float, float, float, float, float],
    matrix: tuple[tuple[float, float, float, float], ...],
) -> tuple[float, float, float, float, float, float]:
    corners = itertools.product(
        (bbox[0], bbox[3]),
        (bbox[1], bbox[4]),
        (bbox[2], bbox[5]),
    )
    transformed: list[tuple[float, float, float]] = []
    for x, y, z in corners:
        transformed.append(
            (
                matrix[0][0] * x + matrix[0][1] * y + matrix[0][2] * z + matrix[0][3],
                matrix[1][0] * x + matrix[1][1] * y + matrix[1][2] * z + matrix[1][3],
                matrix[2][0] * x + matrix[2][1] * y + matrix[2][2] * z + matrix[2][3],
            )
        )

    xs = [point[0] for point in transformed]
    ys = [point[1] for point in transformed]
    zs = [point[2] for point in transformed]
    return (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))


def _multiply_4x4(
    left: tuple[tuple[float, float, float, float], ...],
    right: tuple[tuple[float, float, float, float], ...],
) -> tuple[tuple[float, float, float, float], ...]:
    return tuple(
        tuple(
            sum(left[row_index][k] * right[k][column_index] for k in range(4))
            for column_index in range(4)
        )
        for row_index in range(4)
    )


def _rotation_matrix_from_axis_angle(
    axis: tuple[float, float, float],
    angle: float,
) -> tuple[tuple[float, float, float], ...]:
    quarter_turns = int(round(angle / (math.pi / 2.0)))
    normalized = quarter_turns % 4
    if axis == (1.0, 0.0, 0.0):
        matrices = (
            ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
            ((1.0, 0.0, 0.0), (0.0, 0.0, -1.0), (0.0, 1.0, 0.0)),
            ((1.0, 0.0, 0.0), (0.0, -1.0, 0.0), (0.0, 0.0, -1.0)),
            ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, -1.0, 0.0)),
        )
        return matrices[normalized]
    if axis == (0.0, 1.0, 0.0):
        matrices = (
            ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
            ((0.0, 0.0, 1.0), (0.0, 1.0, 0.0), (-1.0, 0.0, 0.0)),
            ((-1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, -1.0)),
            ((0.0, 0.0, -1.0), (0.0, 1.0, 0.0), (1.0, 0.0, 0.0)),
        )
        return matrices[normalized]
    if axis == (0.0, 0.0, 1.0):
        matrices = (
            ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
            ((0.0, -1.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
            ((-1.0, 0.0, 0.0), (0.0, -1.0, 0.0), (0.0, 0.0, 1.0)),
            ((0.0, 1.0, 0.0), (-1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
        )
        return matrices[normalized]
    raise AssertionError(f"Unsupported axis {axis!r}")


class _FakeBRepBuilderAPITransform:
    def __init__(self, shape: _FakeShape, trsf: _FakeGpTrsf, copy: bool = True) -> None:
        self._shape = _FakeShape(_apply_matrix_to_bbox(shape.bbox, trsf.matrix))

    def Build(self) -> None:
        return None

    def Shape(self) -> _FakeShape:
        return self._shape


class _FakeStepControlReader:
    last_instance: "_FakeStepControlReader | None" = None

    def __init__(self) -> None:
        self.read_paths: list[str] = []
        self.transfer_roots_calls = 0
        self.one_shape_calls = 0
        self.shape_calls: list[int] = []
        self.shapes = [_FakeShape((0.0, 0.0, 0.0, 10.0, 20.0, 30.0))]
        self.root_shape = self.shapes[0]
        _FakeStepControlReader.last_instance = self

    def ReadFile(self, path: str) -> int:
        self.read_paths.append(path)
        return 1

    def TransferRoots(self) -> int:
        self.transfer_roots_calls += 1
        return 1

    def NbShapes(self) -> int:
        return len(self.shapes)

    def Shape(self, index: int) -> _FakeShape:
        self.shape_calls.append(index)
        return self.shapes[index - 1]

    def OneShape(self) -> _FakeShape:
        self.one_shape_calls += 1
        return self.root_shape


class _FakeMultiRootStepControlReader(_FakeStepControlReader):
    def __init__(self) -> None:
        super().__init__()
        self.shapes = [
            _FakeShape((0.0, 0.0, 0.0, 10.0, 20.0, 30.0)),
            _FakeShape((20.0, 5.0, 0.0, 40.0, 10.0, 5.0)),
        ]
        self.root_shape = self.shapes[0]


class _FakeStepControlWriter:
    last_instance: "_FakeStepControlWriter | None" = None

    def __init__(self) -> None:
        self.transferred_shapes: list[_FakeShape] = []
        self.write_paths: list[str] = []
        _FakeStepControlWriter.last_instance = self

    def Transfer(self, shape: _FakeShape, mode) -> int:
        self.transferred_shapes.append(shape)
        return 1

    def Write(self, path: str) -> int:
        self.write_paths.append(path)
        Path(path).write_text("fake-single-root-step", encoding="utf-8")
        return 1


def _fake_ocp_modules(
    reader_cls: type[_FakeStepControlReader] = _FakeStepControlReader,
) -> _OcpModules:
    _FakeStepControlReader.last_instance = None
    _FakeStepControlWriter.last_instance = None
    return _OcpModules(
        BRep_Builder=_FakeBRepBuilder,
        BRepBndLib=_FakeBRepBndLib,
        BRepBuilderAPI_Transform=_FakeBRepBuilderAPITransform,
        Bnd_Box=_FakeBndBox,
        IFSelect_RetDone=1,
        STEPControl_AsIs="AsIs",
        STEPControl_Reader=reader_cls,
        STEPControl_Writer=_FakeStepControlWriter,
        TopoDS_Compound=_FakeCompound,
        gp_Ax1=lambda point, direction: (point, direction),
        gp_Dir=lambda x, y, z: (float(x), float(y), float(z)),
        gp_Pnt=lambda x, y, z: (x, y, z),
        gp_Trsf=_FakeGpTrsf,
        gp_Vec=lambda x, y, z: (x, y, z),
    )


class ExportArrangedStepTests(unittest.TestCase):
    def test_export_arranged_step_uses_occ_bounding_box_without_loop_sync(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            input_step = tmp_path / "input.step"
            input_step.write_text("dummy", encoding="utf-8")
            placements_csv = _write_csv(
                tmp_path,
                """
                part_id,solid_tag,dx,dy,dz,x,y,z,rot,bbox_minx,bbox_miny,bbox_minz,bbox_maxx,bbox_maxy,bbox_maxz
                part_001,1,100,200,300,10,20,30,XYZ,10,20,30,110,220,330
                """,
            )
            output_step = tmp_path / "arranged.step"
            fake_gmsh = _FakeGmsh()

            with patch.dict(sys.modules, {"gmsh": fake_gmsh}):
                export_arranged_step(
                    input_step,
                    placements_csv,
                    output_step,
                    scale=1.0,
                    units_mode="packed",
                    packing_mode="solids",
                )

            self.assertTrue(output_step.exists())
            self.assertEqual(fake_gmsh.model.occ.synchronize_calls, 2)
            self.assertEqual(fake_gmsh.model.occ.get_bounding_box_calls, 1)
            self.assertEqual(fake_gmsh.model.occ.entities[101][:3], [10.0, 20.0, 30.0])
            self.assertEqual(fake_gmsh.finalize_calls, 1)

    def test_export_pipeline_branches_by_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            input_step = tmp_path / "input.step"
            input_step.write_text("dummy", encoding="utf-8")
            solids_csv = _write_csv(
                tmp_path,
                """
                part_id,solid_tag,dx,dy,dz,x,y,z,rot,bbox_minx,bbox_miny,bbox_minz,bbox_maxx,bbox_maxy,bbox_maxz
                part_001,1,100,200,300,10,20,30,XYZ,10,20,30,110,220,330
                """,
                "solids.csv",
            )
            single_root_csv = _write_csv(
                tmp_path,
                """
                item_id,mode,source_count,source_tags,dx,dy,dz,x,y,z,rot,bbox_minx,bbox_miny,bbox_minz,bbox_maxx,bbox_maxy,bbox_maxz
                assembly_0,rigid_group,2,"[1, 2]",30,20,10,100,200,300,ZYX,100,200,300,130,220,310
                """,
                "single_root.csv",
            )
            multi_root_csv = _write_csv(
                tmp_path,
                """
                item_id,mode,source_count,source_tags,dx,dy,dz,x,y,z,rot,bbox_minx,bbox_miny,bbox_minz,bbox_maxx,bbox_maxy,bbox_maxz
                file_001,rigid_group,1,"[1]",10,20,30,100,200,300,XYZ,100,200,300,110,220,330
                file_002,rigid_group,1,"[2]",20,40,60,200,0,0,XYZ,200,0,0,220,40,60
                """,
                "multi_root.csv",
            )
            second_input = tmp_path / "second.step"
            second_input.write_text("dummy-2", encoding="utf-8")
            output_step = tmp_path / "arranged.step"

            with patch("packing_mvp.step_export._export_arranged_step_solids") as solids_mock:
                with patch("packing_mvp.step_export._export_arranged_step_single_root_shape") as single_root_mock:
                    with patch("packing_mvp.step_export._export_arranged_step_multi_root_shapes") as multi_root_mock:
                        export_arranged_step(
                            input_step,
                            solids_csv,
                            output_step,
                            packing_mode="solids",
                        )

            solids_mock.assert_called_once()
            single_root_mock.assert_not_called()
            multi_root_mock.assert_not_called()

            with patch("packing_mvp.step_export._export_arranged_step_solids") as solids_mock:
                with patch("packing_mvp.step_export._export_arranged_step_single_root_shape") as single_root_mock:
                    with patch("packing_mvp.step_export._export_arranged_step_multi_root_shapes") as multi_root_mock:
                        export_arranged_step(
                            input_step,
                            single_root_csv,
                            output_step,
                            packing_mode="single_root_shape",
                        )

            solids_mock.assert_not_called()
            single_root_mock.assert_called_once()
            multi_root_mock.assert_not_called()

            with patch("packing_mvp.step_export._export_arranged_step_solids") as solids_mock:
                with patch("packing_mvp.step_export._export_arranged_step_single_root_shape") as single_root_mock:
                    with patch("packing_mvp.step_export._export_arranged_step_multi_root_shapes") as multi_root_mock:
                        export_arranged_step(
                            input_step,
                            multi_root_csv,
                            output_step,
                            packing_mode="multi_root_shapes",
                            input_steps=[input_step, second_input],
                            item_scales=[1.0, 2.0],
                        )

            solids_mock.assert_not_called()
            single_root_mock.assert_not_called()
            multi_root_mock.assert_called_once()

    def test_single_root_export_writes_one_root_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            input_step = tmp_path / "input.step"
            input_step.write_text("dummy", encoding="utf-8")
            placements_csv = _write_csv(
                tmp_path,
                """
                item_id,mode,source_count,source_tags,dx,dy,dz,x,y,z,rot,bbox_minx,bbox_miny,bbox_minz,bbox_maxx,bbox_maxy,bbox_maxz
                assembly_0,rigid_group,2,"[1, 2]",30,20,40,100,200,300,ZYX,100,200,300,130,220,340
                """,
            )
            output_step = tmp_path / "arranged.step"

            with patch(
                "packing_mvp.step_export._load_ocp_modules",
                return_value=_fake_ocp_modules(_FakeMultiRootStepControlReader),
            ):
                with patch("packing_mvp.step_export._export_arranged_step_solids") as solids_mock:
                    export_arranged_step(
                        input_step,
                        placements_csv,
                        output_step,
                        scale=1.0,
                        units_mode="packed",
                        packing_mode="single_root_shape",
                    )

            self.assertTrue(output_step.exists())
            solids_mock.assert_not_called()
            reader = _FakeStepControlReader.last_instance
            writer = _FakeStepControlWriter.last_instance
            self.assertIsNotNone(reader)
            self.assertIsNotNone(writer)
            assert reader is not None
            assert writer is not None
            self.assertEqual(reader.transfer_roots_calls, 1)
            self.assertEqual(reader.one_shape_calls, 1)
            self.assertEqual(reader.shape_calls, [1, 2])
            self.assertEqual(len(writer.transferred_shapes), 1)
            self.assertEqual(
                writer.transferred_shapes[0].bbox,
                (100.0, 200.0, 300.0, 130.0, 220.0, 340.0),
            )
            self.assertEqual(writer.write_paths, [str(output_step)])

    def test_single_root_shape_uses_shared_rigid_rotation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            input_step = tmp_path / "input.step"
            input_step.write_text("dummy", encoding="utf-8")
            placements_csv = _write_csv(
                tmp_path,
                """
                item_id,mode,source_count,source_tags,dx,dy,dz,x,y,z,rot,bbox_minx,bbox_miny,bbox_minz,bbox_maxx,bbox_maxy,bbox_maxz
                assembly_0,rigid_group,2,"[1, 2]",30,20,40,100,200,300,ZYX,100,200,300,130,220,340
                """,
            )
            output_step = tmp_path / "arranged.step"

            with patch(
                "packing_mvp.step_export._load_ocp_modules",
                return_value=_fake_ocp_modules(_FakeMultiRootStepControlReader),
            ):
                with patch(
                    "packing_mvp.step_export.orientation_to_rigid_rotation",
                    wraps=orientation_to_rigid_rotation,
                ) as rotation_helper:
                    export_arranged_step(
                        input_step,
                        placements_csv,
                        output_step,
                        scale=1.0,
                        units_mode="packed",
                        packing_mode="single_root_shape",
                    )

            self.assertTrue(output_step.exists())
            rotation_helper.assert_called_with("ZYX")

    def test_export_multi_copy_root_shape_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            input_step = tmp_path / "input.step"
            input_step.write_text("dummy", encoding="utf-8")
            placements_csv = _write_csv(
                tmp_path,
                """
                item_id,mode,copy_index,source_count,source_tags,dx,dy,dz,x,y,z,rot,planar_angle_deg,bbox_minx,bbox_miny,bbox_minz,bbox_maxx,bbox_maxy,bbox_maxz
                assembly_0_copy_000,rigid_group,0,2,"[1, 2]",20,30,10,100,200,300,YZX,0,100,200,300,120,230,310
                assembly_0_copy_001,rigid_group,1,2,"[1, 2]",30,20,10,200,210,300,YZX,90,200,210,300,230,230,310
                """,
            )
            output_step = tmp_path / "arranged.step"

            with patch(
                "packing_mvp.step_export._load_ocp_modules",
                return_value=_fake_ocp_modules(),
            ):
                with patch("packing_mvp.step_export._export_arranged_step_solids") as solids_mock:
                    export_arranged_step(
                        input_step,
                        placements_csv,
                        output_step,
                        scale=1.0,
                        units_mode="packed",
                        packing_mode="single_root_shape",
                    )

            self.assertTrue(output_step.exists())
            solids_mock.assert_not_called()
            reader = _FakeStepControlReader.last_instance
            writer = _FakeStepControlWriter.last_instance
            self.assertIsNotNone(reader)
            self.assertIsNotNone(writer)
            assert reader is not None
            assert writer is not None
            self.assertEqual(reader.read_paths, [str(input_step)])
            self.assertEqual(reader.transfer_roots_calls, 1)
            self.assertEqual(len(writer.transferred_shapes), 1)
            exported = writer.transferred_shapes[0]
            self.assertEqual(exported.bbox, (100.0, 200.0, 300.0, 230.0, 230.0, 310.0))
            self.assertEqual(len(exported.children), 2)
            self.assertEqual(exported.children[0].bbox, (100.0, 200.0, 300.0, 120.0, 230.0, 310.0))
            self.assertEqual(exported.children[1].bbox, (200.0, 210.0, 300.0, 230.0, 230.0, 310.0))

    def test_single_item_export_for_multiple_copies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            input_step = tmp_path / "input.step"
            input_step.write_text("dummy", encoding="utf-8")
            placements_csv = _write_csv(
                tmp_path,
                """
                item_id,mode,copy_index,source_count,source_tags,dx,dy,dz,x,y,z,rot,planar_angle_deg,bbox_minx,bbox_miny,bbox_minz,bbox_maxx,bbox_maxy,bbox_maxz
                assembly_0_copy_000,rigid_group,0,2,"[1, 2]",10,20,30,100,200,300,XYZ,0,100,200,300,110,220,330
                assembly_0_copy_001,rigid_group,1,2,"[1, 2]",10,20,30,120,200,300,XYZ,0,120,200,300,130,220,330
                assembly_0_copy_002,rigid_group,2,2,"[1, 2]",10,20,30,140,200,300,XYZ,0,140,200,300,150,220,330
                assembly_0_copy_003,rigid_group,3,2,"[1, 2]",10,20,30,160,200,300,XYZ,0,160,200,300,170,220,330
                assembly_0_copy_004,rigid_group,4,2,"[1, 2]",10,20,30,180,200,300,XYZ,0,180,200,300,190,220,330
                """,
                "multi_copy.csv",
            )
            output_step = tmp_path / "arranged.step"

            with patch(
                "packing_mvp.step_export._load_ocp_modules",
                return_value=_fake_ocp_modules(),
            ):
                with patch("packing_mvp.step_export._export_arranged_step_solids") as solids_mock:
                    export_arranged_step(
                        input_step,
                        placements_csv,
                        output_step,
                        scale=1.0,
                        units_mode="packed",
                        packing_mode="single_root_shape",
                    )

            self.assertTrue(output_step.exists())
            solids_mock.assert_not_called()
            writer = _FakeStepControlWriter.last_instance
            self.assertIsNotNone(writer)
            assert writer is not None
            self.assertEqual(len(writer.transferred_shapes), 1)
            exported = writer.transferred_shapes[0]
            self.assertEqual(len(exported.children), 5)
            self.assertEqual(exported.children[0].bbox, (100.0, 200.0, 300.0, 110.0, 220.0, 330.0))
            self.assertEqual(exported.children[4].bbox, (180.0, 200.0, 300.0, 190.0, 220.0, 330.0))

    def test_multi_root_shape_export_writes_combined_compound(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            first_input = tmp_path / "first.step"
            second_input = tmp_path / "second.step"
            first_input.write_text("dummy-1", encoding="utf-8")
            second_input.write_text("dummy-2", encoding="utf-8")
            placements_csv = _write_csv(
                tmp_path,
                """
                item_id,mode,source_count,source_tags,dx,dy,dz,x,y,z,rot,bbox_minx,bbox_miny,bbox_minz,bbox_maxx,bbox_maxy,bbox_maxz
                file_001,rigid_group,1,"[1]",10,20,30,100,200,300,XYZ,100,200,300,110,220,330
                file_002,rigid_group,1,"[2]",20,40,60,200,0,0,XYZ,200,0,0,220,40,60
                """,
            )
            output_step = tmp_path / "arranged.step"

            with patch(
                "packing_mvp.step_export._load_ocp_modules",
                return_value=_fake_ocp_modules(),
            ):
                export_arranged_step(
                    first_input,
                    placements_csv,
                    output_step,
                    packing_mode="multi_root_shapes",
                    input_steps=[first_input, second_input],
                    item_scales=[1.0, 2.0],
                )

            self.assertTrue(output_step.exists())
            writer = _FakeStepControlWriter.last_instance
            self.assertIsNotNone(writer)
            assert writer is not None
            self.assertEqual(len(writer.transferred_shapes), 1)
            self.assertEqual(
                writer.transferred_shapes[0].bbox,
                (100.0, 0.0, 0.0, 220.0, 220.0, 330.0),
            )


if __name__ == "__main__":
    unittest.main()
