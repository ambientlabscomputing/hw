from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# KiCad source formats
# ---------------------------------------------------------------------------

# KiCad BOM is semicolon-delimited with these headers:
#   Id;Designator;Footprint;Quantity;Designation;Supplier and ref
KICAD_BOM_DELIMITER = ";"


@dataclass
class KicadBomRow:
    id: str
    designator: str
    footprint: str
    quantity: str
    designation: str
    supplier_and_ref: str


# KiCad POS is comma-delimited with these headers:
#   Ref,Val,Package,PosX,PosY,Rot,Side
KICAD_POS_DELIMITER = ","


@dataclass
class KicadPosRow:
    ref: str
    val: str
    package: str
    pos_x: str
    pos_y: str
    rot: str
    side: str


# ---------------------------------------------------------------------------
# JLCPCB target formats
# ---------------------------------------------------------------------------

# BOM target headers: Comment,Designator,Footprint,JLCPCB Part #（optional）
JLCPCB_BOM_HEADERS = [
    "Comment",
    "Designator",
    "Footprint",
    "JLCPCB Part \uff03\uff08optional\uff09",
]


@dataclass
class JlcpcbBomRow:
    comment: str  # <- KiCad Designation
    designator: str  # <- KiCad Designator
    footprint: str  # <- KiCad Footprint
    jlcpcb_part: str = field(default="")  # user fills later

    def to_row(self) -> list[str]:
        return [self.comment, self.designator, self.footprint, self.jlcpcb_part]


# CPL target headers: Designator,Mid X,Mid Y,Layer,Rotation
JLCPCB_CPL_HEADERS = ["Designator", "Mid X", "Mid Y", "Layer", "Rotation"]

SIDE_MAP = {"top": "Top", "bottom": "Bottom"}


@dataclass
class JlcpcbCplRow:
    designator: str  # <- KiCad Ref
    mid_x: str  # <- KiCad PosX + "mm"
    mid_y: str  # <- KiCad PosY + "mm"
    layer: str  # <- KiCad Side mapped via SIDE_MAP
    rotation: str  # <- KiCad Rot

    def to_row(self) -> list[str]:
        return [self.designator, self.mid_x, self.mid_y, self.layer, self.rotation]
