# SPDX-License-Identifier: GPL-2.0-or-later
# The ctypes mirrors below are adapted from Node Arrange 1.12.1 (arrange/structs.py),
# https://extensions.blender.org/add-ons/node-arrange/ , licensed GPL-2.0-or-later.
"""Read socket positions that Blender computes while drawing a node editor.

Blender does not expose socket positions through the Python API. After a node tree has been
drawn, each socket's runtime data holds its location in view space (node units times UI scale);
the ctypes mirrors below read it. verify() checks the mirrors against a drawn tree before any
position is read, so a Blender with another data layout stops with a clear message.
"""

import ctypes
import platform

import bpy


class bNodeStack(ctypes.Structure):
    """Mirror of Blender's bNodeStack (only for the layout of bNodeSocket)."""

    vec: ctypes.c_float * 4
    min: ctypes.c_float
    max: ctypes.c_float
    data: ctypes.c_void_p
    hasinput: ctypes.c_short
    hasoutput: ctypes.c_short
    datatype: ctypes.c_short
    sockettype: ctypes.c_short
    is_copy: ctypes.c_short
    external: ctypes.c_short
    _pad: ctypes.c_char * 4


class bNodeSocketRuntime(ctypes.Structure):
    """Mirror of the start of Blender's bNodeSocketRuntime, up to `location`."""

    if platform.system() == "Windows":
        _pad0: ctypes.c_char * 8
    declaration: ctypes.c_void_p
    if bpy.app.version >= (5, 2, 0):
        identifier_ustr: ctypes.c_char * 8
    changed_flag: ctypes.c_uint32
    total_inputs: ctypes.c_short
    if bpy.app.version >= (5, 0, 0):
        inferred_structure_type: ctypes.c_int8
    _pad1: ctypes.c_byte * 1
    location: ctypes.c_float * 2


class bNodeSocket(ctypes.Structure):
    """Mirror of Blender's bNodeSocket (DNA), up to its runtime pointer."""

    next: ctypes.c_void_p
    prev: ctypes.c_void_p
    prop: ctypes.c_void_p
    identifier: ctypes.c_char * 64
    name: ctypes.c_char * 64
    storage: ctypes.c_void_p
    type: ctypes.c_short
    flag: ctypes.c_short
    limit: ctypes.c_short
    in_out: ctypes.c_short
    typeinfo: ctypes.c_void_p
    idname: ctypes.c_char * 64
    default_value: ctypes.c_void_p
    if bpy.app.version >= (5, 0, 0):
        stack_index: ctypes.c_int
    else:
        stack_index: ctypes.c_short
    display_shape: ctypes.c_char
    attribute_domain: ctypes.c_char
    if bpy.app.version >= (5, 0, 0):
        _pad: ctypes.c_char * 2
    else:
        _pad: ctypes.c_char * 4
    label: ctypes.c_char * 64
    description: ctypes.c_char * 64
    if bpy.app.version < (5, 1, 0):
        short_label: ctypes.c_char * 64
    default_attribute_name: ctypes.POINTER(ctypes.c_char)
    own_index: ctypes.c_int
    to_index: ctypes.c_int
    link: ctypes.c_void_p
    ns: bNodeStack
    runtime: ctypes.POINTER(bNodeSocketRuntime)


for _cls in (bNodeStack, bNodeSocketRuntime, bNodeSocket):
    _cls._fields_ = list(_cls.__annotations__.items())


class UnsupportedBlender(RuntimeError):
    """Blender's socket data does not have the layout these mirrors expect."""


def verify(nt):
    """Check the mirrors on the first node with visible sockets of a drawn tree: the identifier
    read through ctypes must be the socket's own and its location must lie on the node. Raises
    UnsupportedBlender otherwise, rather than placing nodes from garbage."""
    ui = bpy.context.preferences.system.ui_scale
    for n in nt.nodes:
        socks = [s for s in list(n.inputs) + list(n.outputs) if s.enabled and not s.hide]
        if n.bl_idname in ("NodeFrame", "NodeReroute") or n.hide or not socks:
            continue
        for s in socks[:2]:
            c = bNodeSocket.from_address(s.as_pointer())
            ok = c.identifier.decode("utf-8", "replace") == s.identifier and bool(c.runtime)
            if ok:
                x, y = c.runtime.contents.location
                x0, y1 = n.location_absolute
                w, h = n.dimensions.x / ui, n.dimensions.y / ui
                ok = x0 - 20 <= x / ui <= x0 + w + 20 and y1 - h - 20 <= y / ui <= y1 + 20
            if not ok:
                raise UnsupportedBlender(
                    f"nodefmt cannot read socket positions in Blender "
                    f"{'.'.join(map(str, bpy.app.version))} (checked up to 5.2): update nodefmt"
                )
        return


def socket_location(sock):
    """Location of a drawn socket in node units (valid only after the tree was drawn)."""
    ui = bpy.context.preferences.system.ui_scale
    loc = bNodeSocket.from_address(sock.as_pointer()).runtime.contents.location
    return loc[0] / ui, loc[1] / ui
