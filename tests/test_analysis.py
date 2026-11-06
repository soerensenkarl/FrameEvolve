"""The structural analysis: textbook numbers on hand-placed members, and loads that all reach the ground."""
import pytest

from frameevolve.builder import State
from frameevolve.graph import GROUND
from frameevolve.model import Floor, Frame, House, Wall
from frameevolve.verifier import analysis
from frameevolve.verifier.site import Site, vertical

DEPTH = 180.0   # the box's depth, front wall to back: the joists' length


def box(header: str | None = None) -> tuple[Site, dict]:
    """A one-storey 2x4 box, 20 x 15 ft, its front and back walls carrying 2x12 floor joists at 24" that run
    front to back. With a header, the front wall has a 6 ft opening under that header (one ply, on edge)."""
    pts = [(0.0, 0.0), (240.0, 0.0), (240.0, DEPTH), (0.0, DEPTH)]
    walls = [Wall(f"w{i}", pts[i], pts[(i + 1) % 4], 97.125) for i in range(4)]
    house = House("t", walls, [Floor("f", pts, 97.125 + 11.25)])
    s, named = State(house), {}
    for w in (walls[0], walls[2]):
        s.surface = w
        s.place("2x4", 0, 240, 0, 1.5)
        s.place("2x4", 0, 240, 95.625, 97.125)
        opening = (81.0, 159.0) if header and w is walls[0] else None
        for u in [*range(0, 240, 24), 238.5]:
            if not opening or not opening[0] - 1.5 < u < opening[1]:
                named[f"{w.id} {u}"] = s.place("2x4", u, u + 1.5, 1.5, 95.625)
        if opening:
            named["header"] = s.place(header, 82.5, 157.5, 80, 80 + s.SECTIONS[header][1])
            for u in (81.0, 157.5):
                s.place("2x4", u, u + 1.5, 1.5, 95.625)                    # kings
            for u in (82.5, 156.0):
                s.place("2x4", u, u + 1.5, 1.5, 80)                        # jacks
            for u in (96, 120, 144):
                s.place("2x4", u, u + 1.5, 80 + s.SECTIONS[header][1], 95.625)   # cripples
    s.surface = house.floors[0]
    for u in [*range(0, 240, 24), 238.5]:
        named.setdefault(f"joist {u}", s.place("2x12", u, u + 1.5, 0, DEPTH))
    return Site(house, Frame("t", "test", s.members("*"))), named


def test_a_joist_under_a_floor_bends_by_the_textbook():
    """A 2x12 at 24" spanning 14'-6 1/2" under 50 psf: M = wL^2/8 over the span face to face plus half a 1 1/2"
    bearing at each end, half the load to each wall, and close to what SPF No. 2 allows."""
    site, named = box()
    joist = named["joist 120"]
    beams = analysis.takedown(site)
    b = beams[joist.id]
    w = 50 / 144 * 24                                  # lb per inch
    span = DEPTH - 2 * (3.5 - 0.75)                    # 174.5"
    pieces = [p for p in b.pieces if p.kind == "span"]
    assert len(pieces) == 1 and pieces[0].x1 - pieces[0].x0 == pytest.approx(span)
    moment, x = analysis.peak_moment(pieces[0], (1, 1, 0))
    assert moment == pytest.approx(w * span ** 2 / 8)
    assert x == pytest.approx(DEPTH / 2)
    assert sorted(r.under((1, 1, 1)) for r in b.reactions.values()) == pytest.approx([w * DEPTH / 2] * 2)
    stress = moment / (1.5 * 11.25 ** 2 / 6)
    assert 0.95 < stress / analysis.bending_allowed(site, joist, 1.0) < 1.0
    assert not [f for f in analysis.loads(site) if joist.id in f.members]


def test_a_stud_under_one_floor_holds():
    """A 2x4 stud at 24" under the floor carries about a joist's end, 750 lb (the plate shares it out a little to
    the next studs), well within its buckling strength (by hand: CP = 0.39, Fc' = 515 psi, about 2,700 lb)."""
    site, named = box()
    stud = named["w2 120"]
    b = analysis.takedown(site)[stud.id]
    assert b.load.under((1, 1, 1)) == pytest.approx(50 / 144 * 24 * DEPTH / 2, rel=0.1)
    assert analysis.compression_allowed(stud, 1.0) == pytest.approx(515, rel=0.01)
    assert not [f for f in analysis.loads(site) if vertical(site.by_id[f.members[0]])]


def test_a_single_2x4_header_under_a_floor_fails():
    """Three joists' ends (about 2,000 lb) on a 6 ft single 2x4 header bend it far past what it allows, and its
    ends crush the jacks; a single 2x12 there holds."""
    site, named = box("2x4")
    faults = analysis.loads(site)
    on_header = {f.check for f in faults if f.members[0] == named["header"].id}
    assert {"strength", "crushing", "deflection"} <= on_header
    site, named = box("2x12")
    assert not [f for f in analysis.loads(site) if f.check == "strength" and named["header"].id in f.members]


def test_every_load_reaches_the_ground(toy_seeded):
    """On the seed's toy house, what the frame carries comes out at the ground: no load is lost on the way down
    (a ridge board's own weight aside)."""
    house, frame = toy_seeded
    beams = analysis.takedown(Site(house, frame))
    applied = sum((b.w * (b.length if b.run > 0 else 1.0)).under((1, 1, 1)) for b in beams.values())
    grounded = sum(b.reactions.get(GROUND, analysis.NONE).under((1, 1, 1)) for b in beams.values())
    assert grounded == pytest.approx(applied, rel=0.01)


def test_a_short_bearing_away_from_an_end_may_press_harder():
    """NDS 3.10.4: a stud's 1 1/2" on a plate it stops in the middle of allows Cb = 1.875 / 1.5 = 1.25; at the
    plate's end, 1.0."""
    site, named = box()
    plate = next(site.by_id[n] for n in site.g.bears[named["w2 120"].id])
    for u, cb in ((120, 1.25), (0, 1.0)):
        stud = named[f"w2 {u}"]
        area = site.g.bears[stud.id][plate.id]
        assert analysis.bearing_factor(site, plate, stud, plate, area) == pytest.approx(cb)
