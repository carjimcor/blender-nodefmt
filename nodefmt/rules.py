# SPDX-License-Identifier: GPL-3.0-or-later
"""Rules: every behaviour of the formatter has a code and a short name, as in ruff.

Guarantees (NF00x) always hold and cannot be switched off. Style rules can be selected or
ignored, from a nodefmt.toml file, the command line (--select / --ignore) or the add-on
preferences. A rule that is off is neither applied when formatting nor reported by a check.

Configuration (nodefmt.toml next to the .blend file or in a folder above it, for example the
repository root; the first one found wins; [tool.nodefmt] in a pyproject.toml works too):

    select = ["ALL"]          # or a list of codes; prefixes work: "NF03" selects NF030-NF039
    ignore = ["NF011"]        # codes or prefixes to switch off
    ui-scale = 1.4            # optional: the Resolution Scale to format for (default: Blender's)
    straight-tolerance = 2    # optional: pixels a wire may be off straight without a bend (0: none)
"""

import os

# code, name, kind ('guarantee' | 'style'), summary
RULES = [
    (
        "NF001",
        "no-curved-links",
        "guarantee",
        "A link that is not straight turns on reroutes: no link is drawn as a curve or a diagonal.",
    ),
    ("NF002", "no-links-behind-nodes", "guarantee", "No wire passes behind a node."),
    (
        "NF003",
        "orthogonal-segments",
        "guarantee",
        (
            "Every drawn wire segment is exactly horizontal or vertical (within half a unit, or the "
            "straight tolerance: 2 px by default) at the UI "
            "scale the tree is formatted for."
        ),
    ),
    (
        "NF004",
        "no-overlapping-reroutes",
        "guarantee",
        "No two reroutes of different wires sit on top of each other (closer than 10 units).",
    ),
    (
        "NF005",
        "logic-unchanged",
        "guarantee",
        "Formatting never changes what the tree computes; a format that would is undone.",
    ),
    (
        "NF010",
        "duplicate-input-nodes",
        "style",
        (
            "Input-like nodes (Group Input, Named Attribute, constants, ...) get a copy next to each "
            "distant group of consumers instead of long wires from one node."
        ),
    ),
    (
        "NF011",
        "commutative-swaps",
        "style",
        (
            "The two inputs of a commutative node (Add, Multiply, AND, Equal, ...) may be swapped when "
            "that removes a crossing."
        ),
    ),
    (
        "NF020",
        "free-zone-outputs",
        "style",
        "A zone's output may sit where its inputs are instead of level with the zone input.",
    ),
    (
        "NF021",
        "blocks-next-to-consumer",
        "style",
        (
            "A frame or zone with nothing linked into it sits in the column right before the node it "
            "feeds, above or below the main flow, instead of at the far left; one with nothing linked at "
            "all sits compactly under the tree."
        ),
    ),
    (
        "NF022",
        "converging-shape",
        "style",
        (
            "A tree that converges on one output may take a '>' shape with the output in the middle of "
            "its inputs. Off by default."
        ),
    ),
    (
        "NF023",
        "stacked-fields",
        "style",
        (
            "A short chain of field nodes (up to three, such as Index -> Compare) that feeds one input "
            "of a node and nothing else sits in that node's column, stacked right above or below it, "
            "with its wires running round the side. Off by default."
        ),
    ),
    (
        "NF030",
        "staircase-bundles",
        "style",
        ("Wires that leave one node or enter one node are nested like stairs and never cross each other."),
    ),
    (
        "NF031",
        "no-u-jogs",
        "style",
        (
            "A route does not reverse its vertical direction unless a node is in the way, has no "
            "landing that could merge with the level before or after it, and no step so small that "
            "its two reroutes sit on one spot."
        ),
    ),
    (
        "NF032",
        "wire-clearance",
        "style",
        "Wires keep clear of node edges, frame borders and zone outlines (no wire runs along them).",
    ),
    (
        "NF033",
        "avoid-crossings",
        "style",
        (
            "A crossing that can be avoided (a lane on the other side, a wire entering a zone above its "
            "input) is avoided."
        ),
    ),
    (
        "NF034",
        "no-junction-look",
        "style",
        (
            "Different wires never share a point or run on one line, and no reroute sits in the middle "
            "of a straight run: nothing looks like a junction."
        ),
    ),
    (
        "NF035",
        "fanned-multi-inputs",
        "style",
        (
            "The links into a multi-input socket (Join Geometry, Join Strings, ...) arrive a widget unit "
            "apart and converge only in a short fan right before the socket, instead of running a "
            "quarter widget unit apart; the fan's last stretches are drawn diagonal (or curved, with "
            "Blender's noodle curving). Off by default."
        ),
    ),
    (
        "NF036",
        "shared-tracks",
        "style",
        (
            "Vertical runs in one gap between columns that lie one above the other, at least 10 units "
            "apart (as far as two reroutes must be), share one x instead of each taking its own track, "
            "so the gap reads as a few clean lines and stays narrow."
        ),
    ),
    (
        "NF040",
        "label-first-reroute",
        "style",
        "The label of a labelled reroute goes on the first reroute of its wire, near the source.",
    ),
    (
        "NF041",
        "label-clearance",
        "style",
        (
            "A reroute label, and every greyed copy of it that Blender shows on the later reroutes of its "
            "wire, overlaps no other label, no node and no wire."
        ),
    ),
]
# one-line tooltips for the add-on (the summaries above are the full text)
SHORT = {
    "NF010": "Put a copy of an input node (Group Input, Named Attribute, ...) next to distant users",
    "NF011": "Swap the inputs of commutative nodes (Add, Multiply, AND, ...) to avoid crossings",
    "NF020": "Let a zone's output move to the height of its inputs",
    "NF021": "Place a self-contained frame right before the node it feeds",
    "NF022": "Allow a '>' shape, with the output centred among its inputs (off by default)",
    "NF023": "Stack a short chain of field nodes above or below the node it feeds (off by default)",
    "NF030": "Nest the wires that leave or enter one node like stairs, without crossings",
    "NF031": "No U-turns or tiny steps in wires",
    "NF032": "Keep wires away from the edges of nodes, frames and zones",
    "NF033": "Avoid crossings that another route can remove",
    "NF034": "Different wires never share a point, so nothing looks like a junction",
    "NF035": "Spread the links into a Join Geometry or Join Strings, converging in a fan (off by default)",
    "NF036": "Vertical runs one above the other in a gap share one x",
    "NF040": "Put a reroute label on the first reroute of its wire",
    "NF041": "Keep reroute labels, and their greyed copies, clear of other labels, nodes and wires",
}
CODES = [r[0] for r in RULES]
NAMES = {r[0]: r[1] for r in RULES}
KIND = {r[0]: r[2] for r in RULES}
SUMMARY = {r[0]: r[3] for r in RULES}
GUARANTEES = [c for c in CODES if KIND[c] == "guarantee"]
STYLE = [c for c in CODES if KIND[c] == "style"]
OPT_IN = {"NF022", "NF023", "NF035"}  # style rules that are off unless selected (by code, prefix, name or ALL)
CONFIG_NAMES = ("nodefmt.toml", "pyproject.toml")
STRAIGHT_PX = 2.0  # default straight tolerance (screen pixels)


def _match(code, pats):
    """True if a code is named by one of the patterns: 'ALL', a code, a prefix or a rule name."""
    for p in pats:
        p = p.strip()
        if p.upper() == "ALL" or (p and code.startswith(p.upper())) or p == NAMES.get(code):
            return True
    return False


def resolve(select=None, ignore=None):
    """The set of enabled codes: guarantees, plus the selected style rules (default: all but the
    opt-in ones) minus the ignored ones. Unknown codes raise ValueError."""
    for p in list(select or []) + list(ignore or []):
        if p.strip() and p.strip().upper() != "ALL" and not any(_match(c, [p]) for c in CODES):
            raise ValueError(f"unknown rule {p!r}")
    if select:
        sel = [c for c in STYLE if _match(c, select)]
    else:
        sel = [c for c in STYLE if c not in OPT_IN]
    sel = [c for c in sel if not _match(c, ignore or [])]
    return frozenset(GUARANTEES + sel)


DEFAULT = resolve()


class Config:
    """Settings of one run: enabled rules, UI scale (None: Blender's) and straight tolerance (screen
    pixels a wire may be off the horizontal or vertical without a bend)."""

    def __init__(self, rules=DEFAULT, ui_scale=None, source=None, straight=STRAIGHT_PX):
        """Enabled rule codes, UI scale, the file the settings came from and straight tolerance."""
        self.rules = frozenset(rules)
        self.ui_scale = ui_scale
        self.source = source
        self.straight = straight

    def on(self, code):
        """True if rule `code` is enabled."""
        return code in self.rules

    def __repr__(self):
        """Short text: the rules that are off, and the options."""
        off = [c for c in STYLE if c not in self.rules]
        return f"Config(off={off}, ui_scale={self.ui_scale}, straight={self.straight}, source={self.source})"


def _parse_toml(text):
    """A dict from TOML text (tomllib; a small fallback parser for flat key = value files)."""
    try:
        import tomllib

        return tomllib.loads(text)
    except ImportError:
        pass
    out_root = {}
    out = out_root
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("["):
            out = out_root
            for part in line.strip("[]").split("."):
                out = out.setdefault(part.strip(), {})
            continue
        k, _, v = line.partition("=")
        v = v.strip()
        if v.startswith("["):
            val = [x.strip().strip("\"'") for x in v.strip("[]").split(",") if x.strip()]
        elif v in ("true", "false"):
            val = v == "true"
        else:
            try:
                val = float(v)
            except ValueError:
                val = v.strip("\"'")
        out[k.strip()] = val
    return out_root


def find_config(start):
    """The settings table of the first nodefmt.toml (or pyproject.toml with [tool.nodefmt]) in
    folder `start` or above it: (path, dict), or (None, {})."""
    d = os.path.abspath(start or os.getcwd())
    while True:
        for name in CONFIG_NAMES:
            p = os.path.join(d, name)
            if os.path.isfile(p):
                with open(p, encoding="utf-8") as fh:
                    data = _parse_toml(fh.read())
                if name == "pyproject.toml":
                    data = data.get("tool", {}).get("nodefmt")
                    if data is None:
                        continue
                return p, data
        up = os.path.dirname(d)
        if up == d:
            return None, {}
        d = up


def load(start=None, select=None, ignore=None, extend_ignore=None, ui_scale=None, straight=None):
    """A Config from the first config file found from folder `start` upwards, with command line
    values on top (select replaces the file's select; ignore adds to the file's ignore)."""
    path, data = find_config(start)
    sel = select if select else data.get("select")
    ign = list(data.get("ignore", [])) + list(ignore or []) + list(extend_ignore or [])
    sc = ui_scale if ui_scale is not None else data.get("ui-scale", data.get("ui_scale"))
    st = straight if straight is not None else data.get("straight-tolerance", data.get("straight_tolerance"))
    st = STRAIGHT_PX if st is None else st
    return Config(resolve(sel, ign), float(sc) if sc else None, path, float(st))


def _scale(cfg):
    """The UI scale a run is for: the Config's, else Blender's (1.0 without Blender)."""
    if cfg.ui_scale:
        return cfg.ui_scale
    try:
        import bpy

        return bpy.context.preferences.system.ui_scale
    except (ImportError, AttributeError):
        return 1.0


class applied:
    """Context manager: the layout parameters (params.py) set for a Config, restored after.
    Style rules that live in the layout engine switch parameters; the others are read by the
    modules that apply them (Formatter, wires.tidy, routes.place_labels)."""

    def __init__(self, cfg):
        """Remember the Config to apply."""
        self.cfg = cfg
        self.saved = {}

    def __enter__(self):
        """Set the parameters."""
        from . import params as P

        on = self.cfg.on
        new = {
            "SATELLITES": on("NF021"),
            "ZONE_OUT": ("level", "median", "mean") if on("NF020") else ("level",),
            "PLACERS": ("blocks", "balanced", "relax") if on("NF022") else ("blocks", "relax"),
            "TRACK_BUNDLE": 4.0 if on("NF030") else 1.0,
            "W_CROSS_BUNDLE": 15.0 if on("NF030") else 0.0,
            "W_CROSS": 4.0 if on("NF033") else 1.5,
            "LANE_SIDES": on("NF033"),
            "PORTS_ABOVE": on("NF033"),
            "W_HLEN": 0.002 if on("NF021") else 0.0,
            "W_BORDER": 2.0 if on("NF032") else 0.0,
            "ZONE_LANE_GAP": 34.0 if on("NF032") else 20.0,
            "FAN": on("NF035"),
            "TRACK_SHARE": 10.0 if on("NF036") else 0.0,
            "STRAIGHT": self.cfg.straight / _scale(self.cfg),
        }
        for k, v in new.items():
            self.saved[k] = getattr(P, k)
            setattr(P, k, v)
        return self.cfg

    def __exit__(self, *exc):
        """Restore the parameters."""
        from . import params as P

        for k, v in self.saved.items():
            setattr(P, k, v)
        return False
