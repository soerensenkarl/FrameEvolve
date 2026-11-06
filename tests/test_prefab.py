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


def test_the_reference_grammar_lays_out_a_grid_and_builds_wall_panels(tmp_path):
    house = box_house()
    frame = build("grammars/advanced.py", house)
    kinds = {g.kind for g in frame.guides}
    assert {"grid", "panel joint"} <= kinds or "grid" in kinds
    assert all(m.panel for m in frame.members if m.surface.startswith("1w"))


def test_an_end_cut_to_two_planes_is_not_a_saw_cut(wall_state):
    """A stud peaked to fit under a valley (two cuts meeting at its top) is refused; one cut per end is fine."""
    s = wall_state
    stud = s.place("2x4", 10, 11.5, 1.5, 100)
    s.cut(stud, (10.75, 90, 0), (1, 1, 0))
    s.cut(stud, (10.75, 90, 0), (-1, 1, 0))
    once = s.place("2x4", 40, 41.5, 1.5, 100)
    s.cut(once, (40.75, 90, 0), (1, 1, 0))
    msgs = [f.message for f in prefab.cutting(Site(s.house, frame_of(s)))]
    assert any(stud.id in m and "cut to 2 planes" in m for m in msgs)
    assert not any(once.id in m for m in msgs)


def test_a_wall_in_more_panels_than_it_needs_is_a_soft_fault(wall_state):
    """A 20 ft wall split in two panels when one would truck: one soft fault for the extra panel."""
    from frameevolve.verifier import design
    s = wall_state
    for a, b, p in ((0, 120, "A"), (120, 240, "B")):
        for m in (s.place("2x4", a, b, 0, 1.5), s.place("2x4", a, a + 1.5, 1.5, 96), s.place("2x4", b - 1.5, b, 1.5, 96)):
            s.assign(m, p)
    fs = design.panel_count(Site(s.house, frame_of(s)))
    assert len(fs) == 1 and not fs[0].hard and "1 would truck" in fs[0].message
