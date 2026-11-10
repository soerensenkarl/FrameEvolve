"""The load takedown on the house's surfaces, and the layout phase that changes it."""
import pytest

from frameevolve import houses
from frameevolve.builder import build
from frameevolve.loads import Takedown
from frameevolve.model import Guide
from frameevolve.verifier.analysis import total


@pytest.mark.parametrize("seed", range(20))
def test_every_load_on_the_surfaces_reaches_the_ground(seed):
    td = Takedown(houses.generate(seed))
    assert not td.lost
    assert td.ground.sum == pytest.approx(td.applied.sum, rel=1e-9)


def test_a_roof_goes_to_its_eave_walls_and_an_opening_gathers_its_load_to_its_sides():
    """h001, a two-storey box with a gable roof: the eave walls take the roof and the gable walls none; what
    lands over a window comes down at its two sides, as points on the floor below."""
    house = houses.generate(1)
    td = Takedown(house)
    assert td.on("2w0").snow > 5000 and td.on("2w1").snow == 0
    o = house.wall("2w0").openings[0]
    over = td.on("2w0", o.u0 + 1, o.u1 - 1)
    sides = [p for p in td.points("f2") if p.source == f"opening {o.id}"]
    assert len(sides) == 2 and sum(p.load.sum for p in sides) == pytest.approx(over.sum)


def test_a_ridge_beam_takes_half_the_roof_to_the_gable_walls():
    house = houses.generate(1)
    r = house.roofs[0]
    ridge = next(x for x in r.seams if x.kind == "ridge")
    plain, td = Takedown(house), Takedown(house, [Guide("g1", "beam", r.id, ridge.a, ridge.b)])
    assert td.on("2w0").snow < 0.6 * plain.on("2w0").snow
    assert [p.source for p in td.points("2w1")] == ["beam g1"]
    assert td.ground.sum == pytest.approx(td.applied.sum) and not td.lost


def test_a_beam_on_no_wall_loses_its_load():
    house = houses.generate(1)
    td = Takedown(house, [Guide("g1", "beam", "f2", (60, 60), (120, 60))])
    assert any("rests on no wall" in why for _, _, why in td.lost)
    assert td.ground.sum + total(l for _, l, _ in td.lost).sum == pytest.approx(td.applied.sum)


GRAMMAR = '''
from frameevolve.builder import rule

@rule(10, match="seam", when=lambda s, x: x.kind == "ridge")
def ridge_beam(s, x):
    """A ridge beam, so the rafters hang from it and the gable walls carry half the roof."""
    s.guide("beam", x.a, x.b)

@rule(20, match="point", when=lambda s, p: p.source.startswith("beam") and s.surface.id.startswith("2"))
def post(s, p):
    """A post under each end of a beam, doubled past 4000 lb."""
    for i in range(2 if p.load.sum > 4000 else 1):
        s.place("2x6", p.u + 1.5 * i, p.u + 1.5 * (i + 1), 0, s.surface.height, role="post")

@rule(30, match="opening", when=lambda s, o: o.kind == "window")
def header(s, o):
    """A header sized by what lands over the opening."""
    s.place("2x12" if s.load(o.u0, o.u1).sum > 2000 else "2x6", o.u0, o.u1, o.v1, o.v1 + (11.25 if s.load(o.u0, o.u1).sum > 2000 else 5.5), role="header")
'''


def test_a_rule_lays_out_the_load_path_and_later_rules_frame_to_its_forces(tmp_path):
    g = tmp_path / "g.py"
    g.write_text(GRAMMAR)
    frame = build(g, houses.generate(1))
    assert not frame.errors
    assert [x.kind for x in frame.guides] == ["beam"]
    posts = [m for m in frame.members if m.role == "post"]
    assert len(posts) == 4 and {m.surface for m in posts} == {"2w1", "2w3"}       # 10,000 lb each end: doubled
    assert {m.section for m in frame.members if m.role == "header"} == {"2x12", "2x6"}


def test_a_rule_that_reads_a_force_before_the_beam_is_laid_gets_the_old_load_path(tmp_path):
    """Order is the grammar's: the same two rules, the reader before or after the beam."""
    def posts(reader, beam):
        g = tmp_path / f"g{reader}.py"
        g.write_text(GRAMMAR.replace("@rule(20,", f"@rule({reader},").replace("@rule(10,", f"@rule({beam},"))
        return [m for m in build(g, houses.generate(1), max_passes=1).members if m.role == "post"]
    assert len(posts(20, 10)) == 4 and not posts(5, 10)


def test_the_wind_racks_the_walls_along_it_and_lower_storeys_more():
    """h001, a two-storey box: each storey's shear is shared among its walls; the ground storey gets more."""
    td = Takedown(houses.generate(1))
    assert all(td.shear[w] > 0 for w in ("1w0", "1w1", "2w0", "2w1")) and not td.short
    assert td.shear["1w0"] > td.shear["2w0"] and td.shear["1w1"] > td.shear["2w1"]


def test_a_wall_with_studs_too_far_apart_is_not_braced(tmp_path):
    from frameevolve.verifier import analysis
    from frameevolve.verifier.site import Site
    house = houses.generate(1)
    src = open("grammars/seed.py").read()
    assert not analysis.bracing(Site(house, build("grammars/seed.py", house)))
    g = tmp_path / "wide.py"
    g.write_text(src.replace("SPACING = 24", "SPACING = 48"))
    faults = analysis.bracing(Site(house, build(g, house)))
    assert faults and all(f.check == "bracing" and f.hard for f in faults)
