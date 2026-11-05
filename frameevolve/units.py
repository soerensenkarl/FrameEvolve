"""Lengths are inches throughout, to match the IRC tables. These write them the way a framer reads them."""
from __future__ import annotations

from fractions import Fraction


def inches(x: float) -> str:
    """1 1/2", 92 5/8": whole inches and a fraction to the nearest 1/16."""
    sign = "-" if x < 0 else ""
    f = Fraction(round(abs(x) * 16), 16)
    whole, frac = divmod(f, 1)
    if frac == 0:
        return f'{sign}{whole}"'
    return f'{sign}{whole} {frac.numerator}/{frac.denominator}"' if whole else f'{sign}{frac.numerator}/{frac.denominator}"'


def ftin(x: float) -> str:
    """9'-6 1/2": feet and inches, for anything a foot or longer."""
    if abs(x) < 12:
        return inches(x)
    sign = "-" if x < 0 else ""
    f = Fraction(round(abs(x) * 16), 16)
    feet, rest = divmod(f, 12)
    return f"{sign}{feet}'-{inches(float(rest))}"
