# SPDX-License-Identifier: GPL-3.0-or-later
"""The layout graph of one container: items (boxes and points), edges, and shared helpers.

Coordinates: x to the right, y DOWN (y = -blender_y), an item's position is its top-left corner.
"""

from collections import namedtuple

from . import params as P

# Everything that decides the layout of a ranked container: the order of each column (lists of
# items), the input keys of the commutative pairs, the links the placement must leave bent, the
# placement method ('blocks', 'relax'), where the order came from
# ('cross', 'force', 'current') and how a zone's output finds its height (params.ZONE_OUT).
Cand = namedtuple("Cand", "layers comm banned placer origin zone", defaults=("cross", "level"))

PORT_DIRECT = "<port:direct>"  # a container port that sits at a socket of its first column


def slot_of(key):
    """The multi-input slot key behind an input key (unwrapping direct ports), or None."""
    while isinstance(key, tuple) and len(key) == 3 and key[0] == PORT_DIRECT:
        key = key[2]
    return key if isinstance(key, tuple) and len(key) == 4 else None


SNAP_TOL = 1e-3  # sizes read from Blender carry float noise (140.00002 or 139.99993 for 140)


def snap_up(v):
    """The smallest multiple of GRID that is >= v, within SNAP_TOL (so the float noise of a
    measure never moves a column by a whole grid step)."""
    return -((-(v - SNAP_TOL)) // P.GRID) * P.GRID


def snap_down(v):
    """The largest multiple of GRID that is <= v (within SNAP_TOL)."""
    return ((v + SNAP_TOL) // P.GRID) * P.GRID


class Item:
    """A box in the layout: a node, a compound (frame/zone laid out already), a port or a dummy."""

    def __init__(self, id, kind, w=0.0, h=0.0, ins=None, outs=None, ox=None, oy=None, main_in=None, pin=None):
        """An item: its id, kind ('node', 'compound', 'dummy', 'pin_in', 'pin_out', 'label'), size,
        socket offsets {key: (dx, dy)}, original position, main input key and pin ('first',
        'last' or None)."""
        self.id, self.kind, self.w, self.h = id, kind, w, h
        self.ins = ins or {}  # key -> (dx, dy)
        self.outs = outs or {}  # key -> (dx, dy)
        self.ox, self.oy = ox, oy  # original position (for ordering and the keep mode)
        self.main_in = main_in
        self.pin = pin  # 'first' | 'last' | None
        self.rank = 0
        self.x = 0.0
        self.y = 0.0
        self.tag = None  # dummies and ports: the source socket they carry

    @property
    def is_point(self):
        """True for items without a box: dummies, ports and labels."""
        return self.kind in ("dummy", "pin_in", "pin_out", "label")

    def __repr__(self):
        """Short text for debugging."""
        return f"<{self.kind} {self.id}>"


class Edge:
    """A link between two items: from output key uk of u to input key vk of v. tag is the source
    socket it carries (links of one tag share a reroute tree), geo is True for geometry."""

    def __init__(self, u, uk, v, vk, tag, geo=False):
        """A link from (u, uk) to (v, vk) carrying source socket `tag`."""
        self.u, self.uk, self.v, self.vk, self.tag, self.geo = u, uk, v, vk, tag, geo

    @property
    def main(self):
        """True if this link enters the main input of a node or block (its first linked geometry
        input, else its first linked input); a multi-input slot counts as its socket."""
        return (
            self.v.kind in ("node", "compound")
            and self.v.main_in is not None
            and self.vk is not None
            and self.vk[:3] == self.v.main_in[:3]
        )

    def __repr__(self):
        """Short text for debugging."""
        return f"{self.u.id}:{self.uk}->{self.v.id}:{self.vk}"


class Result:
    """The layout of one container (attributes set by _Layout.finish and layout())."""


class LayoutBase:
    """Helpers shared by the parts of the layout engine."""

    def _gap(self, a, b):
        """Vertical space required between two neighbours of a column. In a zone, a lane above
        the first node or below the last one runs outside the zone's outline, not on it (NF032)."""
        if a.is_point or b.is_point:
            if (id(a), id(b)) in getattr(self, "outer", ()):
                return P.ZONE_LANE_GAP
            return P.LANE_GAP
        return P.NODE_GAP

    def _sock_y(self, i, key, out):
        """Height of a socket of item i: an output if `out`, else an input."""
        d = (i.outs if out else i.ins).get(key, (0, 0))
        return i.y + d[1]

    def _turn_y(self, e):
        """None if link e is straight, else the height where its vertical run ends: the input
        socket's (or multi-input slot's) height. A bent link turns twice at right angles."""
        ya, yb = self._sock_y(e.u, e.uk, True), self._sock_y(e.v, e.vk, False)
        if abs(ya - yb) <= P.EPS:
            return None
        return yb

    def _zone_pair(self):
        """(zone input, zone output, offset) of a zone container in relayout mode, else None.
        The output is level when its top is at the input's top + offset, which puts a zone item
        they share (geometry first) at one height; with none shared, offset is 0."""
        a = self._zone_input()
        if a is None:
            return None
        b = [i for i in self.items if i.pin == "last" and i.kind == "node" and getattr(i, "zmatch", None) is not None]
        if len(b) != 1:
            return None
        b = b[0]
        common = [k for k in a.zmatch if k in b.zmatch]
        common.sort(key=lambda k: (not a.zgeo.get(k, False), k))
        off = a.outs[a.zmatch[common[0]]][1] - b.ins[b.zmatch[common[0]]][1] if common else 0.0
        return a, b, off

    def _zone_free(self):
        """True if the zone output of this container may leave the zone input's line."""
        return getattr(self, "zone", "level") != "level" and self._zone_pair() is not None

    def _zone_input(self):
        """The zone input node heading this container, if it is a zone laid out in relayout mode."""
        if self.mode == "keep":
            return None
        z = [i for i in self.items if i.pin == "first" and i.kind == "node" and getattr(i, "zmatch", None) is not None]
        return z[0] if len(z) == 1 else None


def _name(i):
    """Sort key of an item by its id, so orders never depend on Python object identity."""
    return repr(i.id)


class CycleError(Exception):
    """The items of a container have a cycle (a frame that cannot be laid out as one block)."""

    def __init__(self, items):
        """Keep the items of the cycle."""
        super().__init__(f"cycle among {items[:6]}")
        self.items = items
