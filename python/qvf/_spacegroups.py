"""Crystallographic symmetry operators from Hall symbols, standard library only.

A small Hall-symbol parser (S. R. Hall, Acta Cryst. A37, 517-525, 1981) and
the Hall symbols of the 65 chiral (Sohncke) space groups under their wwPDB
CRYST1 names, with the settings macromolecular PDB files commonly use. An
operator is (R, t): R a 3x3 integer matrix on fractional coordinates and t a
fractional translation in [0, 1) as Fractions.
"""

from fractions import Fraction

# wwPDB CRYST1 space-group symbol -> Hall symbol. "H" names the hexagonal
# setting of a rhombohedral group and "R" the rhombohedral axes.
PDB_HALL = {
    "P 1": "P 1", "P 1 2 1": "P 2y", "P 1 21 1": "P 2yb", "C 1 2 1": "C 2y",
    "I 1 2 1": "I 2y", "A 1 2 1": "A 2y", "P 2 2 2": "P 2 2", "P 2 2 21": "P 2c 2",
    "P 2 21 2": "P 2 2b", "P 21 2 2": "P 2a 2a", "P 21 21 2": "P 2 2ab",
    "P 21 2 21": "P 2ac 2ac", "P 2 21 21": "P 2bc 2", "P 21 21 21": "P 2ac 2ab",
    "C 2 2 21": "C 2c 2", "C 2 2 2": "C 2 2", "F 2 2 2": "F 2 2", "I 2 2 2": "I 2 2",
    "I 21 21 21": "I 2b 2c", "P 4": "P 4", "P 41": "P 4w", "P 42": "P 4c",
    "P 43": "P 4cw", "I 4": "I 4", "I 41": "I 4bw", "P 4 2 2": "P 4 2",
    "P 4 21 2": "P 4ab 2ab", "P 41 2 2": "P 4w 2c", "P 41 21 2": "P 4abw 2nw",
    "P 42 2 2": "P 4c 2", "P 42 21 2": "P 4n 2n", "P 43 2 2": "P 4cw 2c",
    "P 43 21 2": "P 4nw 2abw", "I 4 2 2": "I 4 2", "I 41 2 2": "I 4bw 2bw",
    "P 3": "P 3", "P 31": "P 31", "P 32": "P 32", "H 3": "R 3", "R 3": "P 3*",
    "P 3 1 2": "P 3 2", "P 3 2 1": 'P 3 2"', "P 31 1 2": "P 31 2 (0 0 4)",
    "P 31 2 1": 'P 31 2"', "P 32 1 2": "P 32 2 (0 0 2)", "P 32 2 1": 'P 32 2"',
    "H 3 2": 'R 3 2"', "R 3 2": "P 3* 2", "P 6": "P 6", "P 61": "P 61", "P 65": "P 65",
    "P 62": "P 62", "P 64": "P 64", "P 63": "P 6c", "P 6 2 2": "P 6 2",
    "P 61 2 2": "P 61 2 (0 0 5)", "P 65 2 2": "P 65 2 (0 0 1)",
    "P 62 2 2": "P 62 2 (0 0 4)", "P 64 2 2": "P 64 2 (0 0 2)", "P 63 2 2": "P 6c 2c",
    "P 2 3": "P 2 2 3", "F 2 3": "F 2 2 3", "I 2 3": "I 2 2 3", "P 21 3": "P 2ac 2ab 3",
    "I 21 3": "I 2b 2c 3", "P 4 3 2": "P 4 2 3", "P 42 3 2": "P 4n 2 3",
    "F 4 3 2": "F 4 2 3", "F 41 3 2": "F 4d 2 3", "I 4 3 2": "I 4 2 3",
    "P 43 3 2": "P 4acd 2ab 3", "P 41 3 2": "P 4bd 2ab 3", "I 41 3 2": "I 4bd 2c 3",
    # Short monoclinic symbols some programs write.
    "P 2": "P 2y", "P 21": "P 2yb", "C 2": "C 2y", "I 2": "I 2y",
}

_HALF, _THIRD, _QUARTER = Fraction(1, 2), Fraction(1, 3), Fraction(1, 4)
_CENTRING = {
    "P": [], "A": [(0, _HALF, _HALF)], "B": [(_HALF, 0, _HALF)], "C": [(_HALF, _HALF, 0)],
    "I": [(_HALF, _HALF, _HALF)], "R": [(2 * _THIRD, _THIRD, _THIRD), (_THIRD, 2 * _THIRD, 2 * _THIRD)],
    "F": [(0, _HALF, _HALF), (_HALF, 0, _HALF), (_HALF, _HALF, 0)],
}
_SHIFT = {"a": (_HALF, 0, 0), "b": (0, _HALF, 0), "c": (0, 0, _HALF), "n": (_HALF, _HALF, _HALF),
          "u": (_QUARTER, 0, 0), "v": (0, _QUARTER, 0), "w": (0, 0, _QUARTER),
          "d": (_QUARTER, _QUARTER, _QUARTER)}
_AXIS = {
    "x": {1: ((1, 0, 0), (0, 1, 0), (0, 0, 1)), 2: ((1, 0, 0), (0, -1, 0), (0, 0, -1)),
          3: ((1, 0, 0), (0, 0, -1), (0, 1, -1)), 4: ((1, 0, 0), (0, 0, -1), (0, 1, 0)),
          6: ((1, 0, 0), (0, 1, -1), (0, 1, 0))},
    "y": {1: ((1, 0, 0), (0, 1, 0), (0, 0, 1)), 2: ((-1, 0, 0), (0, 1, 0), (0, 0, -1)),
          3: ((-1, 0, 1), (0, 1, 0), (-1, 0, 0)), 4: ((0, 0, 1), (0, 1, 0), (-1, 0, 0)),
          6: ((0, 0, 1), (0, 1, 0), (-1, 0, 1))},
    "z": {1: ((1, 0, 0), (0, 1, 0), (0, 0, 1)), 2: ((-1, 0, 0), (0, -1, 0), (0, 0, 1)),
          3: ((0, -1, 0), (1, -1, 0), (0, 0, 1)), 4: ((0, -1, 0), (1, 0, 0), (0, 0, 1)),
          6: ((1, -1, 0), (1, 0, 0), (0, 0, 1))},
}
# Two-fold axes along a face diagonal, relative to the preceding axis.
_DIAGONAL = {
    ("z", "'"): ((0, -1, 0), (-1, 0, 0), (0, 0, -1)), ("z", '"'): ((0, 1, 0), (1, 0, 0), (0, 0, -1)),
    ("x", "'"): ((-1, 0, 0), (0, 0, -1), (0, -1, 0)), ("x", '"'): ((-1, 0, 0), (0, 0, 1), (0, 1, 0)),
    ("y", "'"): ((0, 0, -1), (0, -1, 0), (-1, 0, 0)), ("y", '"'): ((0, 0, 1), (0, -1, 0), (1, 0, 0)),
}
_BODY_DIAGONAL = ((0, 0, 1), (1, 0, 0), (0, 1, 0))
_UNIT = {"x": 0, "y": 1, "z": 2}


def _mod(t):
    return tuple(v % 1 for v in t)


def _apply(r, t):
    return tuple(sum(r[i][k] * t[k] for k in range(3)) for i in range(3))


def _compose(a, b):
    """The operator a after b."""
    (ra, ta), (rb, tb) = a, b
    r = tuple(tuple(sum(ra[i][k] * rb[k][j] for k in range(3)) for j in range(3))
              for i in range(3))
    return r, _mod(tuple(x + y for x, y in zip(_apply(ra, tb), ta)))


def _matrix(token, index, previous):
    """(operator, axis) of one Hall matrix symbol such as 2ac, -4bw or 3*."""
    improper = token.startswith("-")
    body = token.lstrip("-")
    order = int(body[0])
    if order not in (1, 2, 3, 4, 6):
        raise ValueError(f"unsupported Hall rotation {token!r}")
    rest = body[1:]
    axis = rest[0] if rest[:1] in ("x", "y", "z", "'", '"', "*") else None
    if axis:
        rest = rest[1:]
    if axis is None:
        if index == 0:
            axis = "z"
        elif index == 1 and order == 2:
            axis = "x" if previous[0] in (2, 4) else "'"
        elif index == 2 and order == 3:
            axis = "*"
        elif order != 1:
            raise ValueError(f"Hall rotation {token!r} needs an explicit axis")
    if axis in ("'", '"'):
        r = _DIAGONAL[(previous[1], axis)]
    elif axis == "*":
        r = _BODY_DIAGONAL
    else:
        r = _AXIS[axis or "z"][order]
    t = [Fraction(0)] * 3
    for symbol in rest:
        if symbol.isdigit():
            if axis not in _UNIT:
                raise ValueError(f"Hall screw {token!r} needs an x, y or z axis")
            t[_UNIT[axis]] += Fraction(int(symbol), order)
        elif symbol in _SHIFT:
            t = [a + b for a, b in zip(t, _SHIFT[symbol])]
        else:
            raise ValueError(f"unsupported Hall translation in {token!r}")
    if improper:
        r = tuple(tuple(-v for v in row) for row in r)
    return (r, _mod(t)), (order, axis if axis in _UNIT else previous[1])


def operators(hall):
    """The space group's operators in a fixed order: the identity first, then
    the point operators in generation order, each block repeated for every
    lattice centring vector."""
    text, _, basis = hall.partition("(")
    tokens = text.split()
    lattice = tokens[0]
    centric = lattice.startswith("-")
    if lattice.lstrip("-") not in _CENTRING:
        raise ValueError(f"unsupported Hall lattice {lattice!r}")
    centring = [(Fraction(0),) * 3] + [tuple(Fraction(v) for v in c)
                                       for c in _CENTRING[lattice.lstrip("-")]]
    generators, previous = [], (None, "z")
    for index, token in enumerate(tokens[1:]):
        op, previous = _matrix(token, index, previous)
        generators.append(op)
    identity = (((1, 0, 0), (0, 1, 0), (0, 0, 1)), (Fraction(0),) * 3)
    if centric:
        generators.append((((-1, 0, 0), (0, -1, 0), (0, 0, -1)), (Fraction(0),) * 3))
    if basis:
        # Change of basis by an origin shift v (in twelfths): (R, t + v - R v).
        v = tuple(Fraction(int(x), 12) for x in basis.rstrip(") ").split())
        generators = [(r, _mod(tuple(a + b - c for a, b, c in zip(t, v, _apply(r, v)))))
                      for r, t in generators]
    generators += [(identity[0], c) for c in centring[1:]]
    group, seen = [identity], {identity}
    for op in group:
        for g in generators:
            new = _compose(g, op)
            if new not in seen:
                seen.add(new); group.append(new)
                if len(group) > 192:
                    raise ValueError(f"Hall symbol {hall!r} does not close")
    points, covered = [], set()
    for r, t in group:
        if (r, t) not in covered:
            points.append((r, t))
            covered |= {(r, _mod(tuple(a + b for a, b in zip(t, c)))) for c in centring}
    return [(r, _mod(tuple(a + b for a, b in zip(t, c)))) for c in centring for r, t in points]
