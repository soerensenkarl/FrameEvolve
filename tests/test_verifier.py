"""The verifier: taking members out of a clean frame makes the faults it should."""
from dataclasses import replace

from frameevolve.graph import build_graph
from frameevolve.model import Frame
from frameevolve.verifier import verify


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
    b = house.wall(m.surface).local_box(m)
    return (b.lo[0] + b.hi[0]) / 2


def test_missing_jack_leaves_the_header_unsupported(seeded):
    """Without one jack the header has nothing under one end."""
    house, frame = seeded
    jack = next(m for m in frame.members if m.role == "jack")
    header = next(m for m in frame.members if m.role == "header" and m.surface == jack.surface
                  and frame_bears(frame, m, jack))
    r = verify(house, without(frame, jack))
    # The verifier calls a header with one end loose an overhang: it runs past its last support.
    assert [f for f in hard(r) if f.check in ("span", "floating", "overhang") and header.id in f.members]


def test_missing_stud_leaves_a_field_gap_and_a_long_top_plate_span(seeded):
    """Taking a stud out of a plain wall leaves the sheathing and the top plate spanning too far."""
    house, frame = seeded
    wall = next(w for w in house.walls if not w.openings)
    studs = [m for m in frame.members if m.role == "stud" and m.surface == wall.id]
    stud = min(studs, key=lambda m: abs(u_of(house, m) - wall.length / 2))
    r = verify(house, without(frame, stud))
    assert [f for f in hard(r, "backing") if f.surface == wall.id and "nothing behind it" in f.message]
    plates = {m.id for m in frame.members if m.role == "top plate" and m.surface == wall.id}
    assert [f for f in hard(r, "span") if plates & set(f.members)]


def test_missing_header_leaves_the_head_open_and_cripples_floating(seeded):
    """Without its header an opening has no head and the cripples above it rest on nothing."""
    house, frame = seeded
    header = next(m for m in frame.members if m.role == "header")
    plies = [m for m in frame.members if m.role == "header" and m.surface == header.surface
             and m.box.lo[2] == header.box.lo[2] and abs(m.length - header.length) < 1e-6
             and min(abs(m.box.lo[k] - header.box.lo[k]) for k in range(2)) < 1e-6]
    cripples = [m for m in frame.members if m.role == "cripple" and any(frame_bears(frame, m, p) for p in plies)]
    assert plies and cripples
    r = verify(house, without(frame, *plies))
    assert [f for f in hard(r, "head") if f.surface == header.surface]
    floating = {i for f in hard(r, "floating") for i in f.members}
    assert {m.id for m in cripples} <= floating


def test_duplicate_stud_clashes(seeded):
    """Two studs in the same place clash, and the fault names both."""
    house, frame = seeded
    stud = next(m for m in frame.members if m.role == "stud")
    dup = replace(stud, id="dup")
    r = verify(house, edited(frame, [*frame.members, dup]))
    assert [f for f in hard(r, "clash") if {stud.id, "dup"} <= set(f.members)]


def test_text_says_no_faults_only_for_a_clean_frame(seeded):
    house, frame = seeded
    assert "No faults." in verify(house, frame).text()


def test_removing_members_lowers_bought_timber(seeded):
    """Fewer members means less timber bought."""
    house, frame = seeded
    before = verify(house, frame).metrics["bought_ft"]
    cripples = [m for m in frame.members if m.role == "cripple"]
    after = verify(house, without(frame, *cripples)).metrics["bought_ft"]
    assert after < before
