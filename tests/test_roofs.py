"""Roofs: members at any angle, cut and notched; roof planes, gable walls and ceilings; rafter checks."""
import pytest

from frameevolve import houses, solid
from frameevolve.graph import build_graph
from frameevolve.model import Frame
from frameevolve.verifier import verify


def test_cuts_and_notches_take_off_exact_volumes():
    box = dict(start=(0, 0, 1.75), end=(10, 0, 1.75), up=(0, 0, 1), width=1.5, depth=3.5)
    n = solid.unit((1, 0, 1))
    cut = solid.solid(**box, cuts=[(n, solid.dot(n, (8, 0, 1.75)))])          # a 45 degree cut near one end
    assert solid.volume(cut[0]) == pytest.approx(52.5 - 10.5)
    notch = [((1, 0, 0), 6), ((-1, 0, 0), -4), ((0, 0, -1), -2)]               # everything above z = 2, x 4 to 6
    pieces = solid.solid(**box, notches=[notch])
    assert sum(map(solid.volume, pieces)) == pytest.approx(52.5 - 2 * 1.5 * 1.5)


def test_a_sloped_rafter_clashes_with_a_plate_until_notched_then_rests_on_it(toy_state):
    house, s = toy_state
    s.surface = house.wall("2w0")
    plate = s.place("2x6", 0, 168, 95.625, 97.125)
    s.surface = house.surface("r1")
    rafter = s.place("2x10", 24.75, 26.25, 0, 60, role="rafter")
    assert [m.id for m in s.overlapping(rafter)] == [plate.id]
    s.notch(rafter, plate, below=True)
    assert not s.overlapping(rafter)
    g = build_graph([plate, rafter])
    assert not g.clashes and plate.id in g.bears[rafter.id]
    assert 1.5 * 1.5 < g.bears[rafter.id][plate.id] < 1.5 * 5.5      # a seat on part of the plate's width


def test_trim_cuts_a_rafter_plumb_against_the_ridge(toy_state):
    house, s = toy_state
    s.surface = house.surface("r1")
    rafter = s.place("2x10", 24.75, 26.25, 0, house.surface("r1").size[1], role="rafter")
    up = s.surface.local_dir((0, 0, 1))
    v = house.surface("r1").size[1]
    ridge = s.put("2x12", (0, v - up[1] * 5.625, -up[2] * 5.625), (168, v - up[1] * 5.625, -up[2] * 5.625), up)
    s.trim(rafter, ridge)
    g = build_graph([rafter, ridge])
    assert not g.clashes and ridge.id in g.side[rafter.id]
    assert abs(g.facing[(rafter.id, ridge.id)][2]) < 1e-6                     # the plumb cut is vertical


def test_box_houses_get_a_gable_roof_gable_walls_and_a_ceiling():
    house = next(h for h in map(houses.generate, range(20)) if h.kind == "box")
    r1, r2 = house.roofs
    assert [(x.other, x.kind) for x in r1.seams] == [("r2", "ridge")]
    gables = [w for w in house.walls if w.outline]
    assert len(gables) == 2 and all(max(v for _, v in w.outline) > w.height for w in gables)
    ceiling = next(f for f in house.floors if f.role == "ceiling")
    assert {w.id for w in house.walls if w.above == ceiling.id} >= {b.wall for b in ceiling.bearers}
    assert ceiling.ew == (0.0, 0.0, 1.0) and ceiling.faces == ("outer",)
    for w in gables:            # the gable's top follows the roof plane at its outside face
        u = w.length / 4
        top = w.world(u, max(v for _, v in w.outline) - (w.length / 2 - u) * r1.slope, 0)
        assert min(r.height(top[0], top[1]) for r in house.roofs) == pytest.approx(top[2])


def test_seed_frames_the_toy_roof_cleanly_and_ties_every_rafter(toy_seeded):
    house, frame = toy_seeded
    report = verify(house, frame)
    assert not frame.errors and not [f for f in report.faults if f.check in ("clash", "floating", "thrust")], report.text()
    rafters = [m for m in frame.members if m.role == "rafter"]
    assert rafters and all(m.notches or m.cuts for m in rafters)
    untied = Frame(house.id, frame.grammar, [m for m in frame.members if m.role != "ceiling joist"])
    assert any(f.check == "thrust" for f in verify(house, untied).faults)


def test_rafters_meeting_head_on_have_no_ridge_to_check(toy_state):
    """Opposite rafters plumb cut to meet each other (with a gusset, IRC R802.3) need no ridge board, so the ridge
    check does not mistake one for a ridge too shallow for the other."""
    from frameevolve.verifier import Site
    from frameevolve.verifier.physical import rafters
    house, s = toy_state
    ms, x = [], house.surface("r1").world(25.5, 0, 0)[0]
    for rid in ("r1", "r2"):
        s.surface = r = house.surface(rid)
        u = r.local((x, r.origin[1], r.origin[2]))[0]            # the same x in plan on both slopes
        v = r.size[1]
        m = s.place("2x12", u - 0.75, u + 0.75, 0, v + 12, role="rafter")
        s.cut(m, (u, v, 0), r.local_dir((0, 1 if rid == "r1" else -1, 0)))
        ms.append(m)
    site = Site(house, Frame(house.id, "test", ms))
    site.held = set(site.by_id)                                         # as if they sat on their walls
    assert ms[1].id in site.g.side[ms[0].id]                         # they meet head on
    assert not [f for f in rafters(site) if f.check == "ridge"]
