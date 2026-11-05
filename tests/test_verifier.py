from dataclasses import replace
from pathlib import Path

from frameevolve import houses
from frameevolve.builder import build
from frameevolve.graph import build_graph
from frameevolve.model import Frame
from frameevolve.verifier import CHECKS, verify

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "grammars/seed.py"
MINIMAL = ROOT / "grammars/minimal.py"


def seeded(n=1):   # h001 is a two-storey box, which the seed frames cleanly
    house = houses.generate(n)
    return house, build(SEED, house)


def edited(frame, members):
    return Frame(frame.house, frame.grammar, members)


def without(frame, *gone):
    ids = {m.id for m in gone}
    return edited(frame, [m for m in frame.members if m.id not in ids])


def hard(report, check=None):
    return [f for f in report.faults if f.hard and (check is None or f.check == check)]


def frame_bears(frame, top, bottom):
    """True if `top` rests directly on `bottom`."""
    return bottom.id in build_graph(frame.members).bears[top.id]


def u_of(house, m):
    """A member's centre along its wall."""
    b = house.wall(m.surface).local_box(m.box)
    return (b.lo[0] + b.hi[0]) / 2


def test_minimal_grammar_has_the_expected_hard_faults():
    """The minimal grammar knows nothing about corners or openings, and the verifier says so."""
    house = houses.generate(0)
    r = verify(house, build(MINIMAL, house))
    assert {"clash", "too long", "opening", "backing", "head", "sill", "span"} <= {f.check for f in hard(r)}


def test_missing_jack_leaves_the_header_unsupported():
    """Without one jack the header has nothing under one end."""
    house, frame = seeded()
    jack = next(m for m in frame.members if m.role == "jack")
    header = next(m for m in frame.members if m.role == "header" and m.surface == jack.surface
                  and frame_bears(frame, m, jack))
    r = verify(house, without(frame, jack))
    # The verifier calls a header with one end loose an overhang: it runs past its last support.
    assert [f for f in hard(r) if f.check in ("span", "floating", "overhang") and header.id in f.members]


def test_missing_stud_leaves_a_field_gap_and_a_long_top_plate_span():
    """Taking a stud out of a plain wall leaves the sheathing and the top plate spanning too far."""
    house, frame = seeded()
    wall = next(w for w in house.walls if not w.openings)
    studs = [m for m in frame.members if m.role == "stud" and m.surface == wall.id]
    stud = min(studs, key=lambda m: abs(u_of(house, m) - wall.length / 2))
    r = verify(house, without(frame, stud))
    assert [f for f in hard(r, "backing") if f.wall == wall.id and "nothing behind it" in f.message]
    plates = {m.id for m in frame.members if m.role == "top plate" and m.surface == wall.id}
    assert [f for f in hard(r, "span") if plates & set(f.members)]


def test_missing_header_leaves_the_head_open_and_cripples_floating():
    """Without its header an opening has no head and the cripples above it rest on nothing."""
    house, frame = seeded()
    header = next(m for m in frame.members if m.role == "header")
    plies = [m for m in frame.members if m.role == "header" and m.surface == header.surface
             and m.box.lo[2] == header.box.lo[2] and abs(m.length - header.length) < 1e-6
             and min(abs(m.box.lo[k] - header.box.lo[k]) for k in range(2)) < 1e-6]
    cripples = [m for m in frame.members if m.role == "cripple" and any(frame_bears(frame, m, p) for p in plies)]
    assert plies and cripples
    r = verify(house, without(frame, *plies))
    assert [f for f in hard(r, "head") if f.wall == header.surface]
    floating = {i for f in hard(r, "floating") for i in f.members}
    assert {m.id for m in cripples} <= floating


def test_duplicate_stud_clashes():
    """Two studs in the same place clash, and the fault names both."""
    house, frame = seeded()
    stud = next(m for m in frame.members if m.role == "stud")
    dup = replace(stud, id="dup")
    r = verify(house, edited(frame, [*frame.members, dup]))
    assert [f for f in hard(r, "clash") if {stud.id, "dup"} <= set(f.members)]


def test_text_names_every_hard_check():
    """The text report mentions every hard check that occurs."""
    house = houses.generate(0)
    r = verify(house, build(MINIMAL, house))
    text = r.text()
    for check in {f.check for f in hard(r)}:
        assert f"HARD {check} " in text
    assert "No faults." not in text


def test_text_says_no_faults_only_when_there_are_none():
    """'No faults.' appears for a clean frame and not for one with faults."""
    house, frame = seeded()
    assert "No faults." in verify(house, frame).text()
    assert "No faults." not in verify(house, build(MINIMAL, house)).text()


def test_removing_members_lowers_bought_timber():
    """Fewer members means less timber bought."""
    house, frame = seeded()
    before = verify(house, frame).metrics["bought_ft"]
    cripples = [m for m in frame.members if m.role == "cripple"]
    after = verify(house, without(frame, *cripples)).metrics["bought_ft"]
    assert after < before


def test_waste_is_never_negative():
    """Waste stays at or above zero, including the minimal grammar's plates longer than any stock."""
    for n in range(5):
        house = houses.generate(n)
        for grammar in (SEED, MINIMAL):
            frame = build(grammar, house)
            m = verify(house, frame).metrics
            assert m["waste_ft"] >= 0, (house.id, grammar.stem, m)
    house = houses.generate(0)
    assert max(m.length for m in build(MINIMAL, house).members) == max(w.length for w in house.walls) > 240
