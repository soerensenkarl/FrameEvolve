"""The near-empty starting grammar: plates and studs only. Knows nothing about corners or openings. Inches."""
from frameevolve.builder import rule

T = 1.5


@rule(10, match="wall")
def plates(s, wall):
    """A bottom and a top plate the full length of the wall."""
    s.place("2x4", 0, wall.length, 0, T, role="bottom plate")
    s.place("2x4", 0, wall.length, wall.height - T, wall.height, role="top plate")


@rule(20, match="wall")
def studs(s, wall):
    """Studs every 16", skipped where they would cross an opening."""
    u = 0.0
    while u + T <= wall.length:
        if s.free(u, u + T, T, wall.height - T):
            s.place("2x4", u, u + T, T, wall.height - T, role="stud")
        u += 16
