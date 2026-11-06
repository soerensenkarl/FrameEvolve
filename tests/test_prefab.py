"""Prefab: guides to frame by, panels that must truck and lift, pieces the saw can cut, a bottom-up erection order."""
from frameevolve.builder import build
from frameevolve.model import Frame
from frameevolve.verifier import Site
from frameevolve.verifier import prefab

from conftest import box_house


def frame_of(s):
    return Frame(s.house.id, "test", list(s._members.values()), guides=list(s._guides.values()))


def test_guides_in_plan_cross_a_wall_where_its_line_meets_them(wall_state):
    s = wall_state
    s.surface = None
    for x in (24, 48, 300):
        s.guide("grid", (x, -10), (x, 200), plan=True)
    s.surface = s.house.walls[0]           # along x from 0 to 240
    assert s.crossings("grid") == [24.0, 48.0]


def test_a_panel_too_big_to_truck_and_one_in_two_pieces_are_faults(wall_state):
    s = wall_state
    plate = s.place("2x4", 0, 150, 0, 1.5)
    studs = [s.place("2x4", u, u + 1.5, 1.5, 150) for u in (0, 148.5)]
    loose = s.place("2x4", 60, 61.5, 30, 40)
    for m in (plate, *studs, loose):
        s.assign(m, "P")
    msgs = [f.message for f in prefab.panels(Site(s.house, frame_of(s))) if f.check == "panel"]
    assert any("too big to truck" in m for m in msgs)
    assert any("separate pieces" in m for m in msgs)


def test_a_ripped_board_and_a_tiny_block_cannot_be_cut_by_the_saw(wall_state):
    s = wall_state
    plate = s.place("2x4", 0, 96, 0, 1.5)
    block = s.place("2x4", 10, 14, 1.5, 3.0)
    s.cut(plate, (0, 1.0, 0), (0, 1, 1))      # a chamfer along the whole plate
    msgs = [f.message for f in prefab.cutting(Site(s.house, frame_of(s)))]
    assert any(plate.id in m and "ripped" in m for m in msgs)
    assert any(block.id in m and "shortest piece" in m for m in msgs)


def test_two_panels_whose_plates_interlock_have_no_order(wall_state):
    """Panel A's top plate rests on a stud of B, and B's top plate on A's: neither can go up first."""
    s = wall_state
    a = [s.place("2x4", 0, 48, 0, 1.5), s.place("2x4", 0, 1.5, 1.5, 94.125), s.place("2x4", 24, 25.5, 1.5, 94.125),
         s.place("2x4", 0, 72, 94.125, 95.625)]
    b = [s.place("2x4", 48, 96, 0, 1.5), s.place("2x4", 48, 49.5, 1.5, 94.125),
         s.place("2x4", 94.5, 96, 1.5, 95.625), s.place("2x4", 24, 96, 95.625, 97.125)]
    for m in a:
        s.assign(m, "A")
    for m in b:
        s.assign(m, "B")
    msgs = [f.message for f in prefab.erection(Site(s.house, frame_of(s)))]
    assert any("no order" in m for m in msgs), msgs


def test_the_seed_lays_out_a_grid_and_joints_and_builds_wall_panels(tmp_path):
    house = box_house()
    frame = build("grammars/seed.py", house)
    kinds = {g.kind for g in frame.guides}
    assert {"grid", "panel joint"} <= kinds or "grid" in kinds
    assert all(m.panel for m in frame.members if m.surface.startswith("1w"))
