"""
GlueScript Loader

Loads a ``.cglu`` GlueScript transcript into the MeerK40t element tree.

The transcript is validated by replaying it through a throwaway ``GlueScript``
instance (an unknown command or a missing ``end_job()`` raises). Each
``declare_layer`` becomes an operation; the following ``move/cut_xy_to``
sequences per layer become a path element referenced by that operation.
Live-only commands (``jog_*``, ``home``, ``pause``, ...) are ignored with a
warning.
"""

import ast
import logging
import os

logger = logging.getLogger(__name__)

_UNIT = 1000.0  # GlueScript coordinates are mm; MeerK40t scene units are µm.


def _logical_lines(lines):
    """Join continuation lines (unclosed bracket depth) into logical lines."""
    logical = []
    buf = ""
    depth = 0
    for line in lines:
        clean = line.strip()
        if not clean or clean.startswith("#"):
            continue
        buf = buf + line if buf else line
        depth += line.count("(") + line.count("[") + line.count("{")
        depth -= line.count(")") + line.count("]") + line.count("}")
        if depth <= 0:
            logical.append(buf)
            buf = ""
    if buf:
        logical.append(buf)
    return logical


def _parse_call(line):
    """Parse ``name(arg, kw=...)`` -> (name, args, kwargs) via literal_eval."""
    try:
        tree = ast.parse(line, mode="eval")
    except SyntaxError:
        return None, [], {}
    if not isinstance(tree.body, ast.Call):
        return None, [], {}
    node = tree.body
    name = None
    func = node.func
    if isinstance(func, ast.Attribute):
        name = func.attr
    elif isinstance(func, ast.Name):
        name = func.id
    if name is None:
        return None, [], {}
    args = [ast.literal_eval(a) for a in node.args]
    kw = {k.arg: ast.literal_eval(k.value) for k in node.keywords if k.arg is not None}
    return name, args, kw


class GlueScriptLoader:
    @staticmethod
    def load_types():
        yield "GlueScript", ("cglu",), "text/plain"

    @staticmethod
    def load(kernel, service, pathname, **kwargs):
        from ruidadriver.rd_gluescript import GlueScript

        with open(pathname, "r", encoding="utf-8") as f:
            text = f.read()
        physical = text.splitlines()
        logical = _logical_lines(physical)

        # Validate by replaying through a throwaway GlueScript instance.
        validator = GlueScript()
        validator.stage_gluescript(list(logical), require_complete=True)

        elements = service
        op_branch = elements.op_branch
        elem_branch = elements.elem_branch
        basename = os.path.basename(pathname)
        with elements.node_lock:
            context = elem_branch.add(type="file", filepath=pathname, label=basename)
            op_node = None
            points = []
            for line in logical:
                name, args, kw = _parse_call(line)
                if name == "declare_job":
                    continue
                elif name == "declare_layer":
                    op_node = GlueScriptLoader._layer_to_op(op_branch, args, kw)
                    points = []
                elif name in ("move_xy_to", "move_x_to", "move_y_to"):
                    GlueScriptLoader._append_move(points, name, args, kw)
                elif name in ("cut_xy_to", "cut_x_to", "cut_y_to"):
                    GlueScriptLoader._append_move(points, name, args, kw)
                elif name in ("air_assist_on", "air_assist_off"):
                    if op_node is not None:
                        op_node.coolant = 1 if name == "air_assist_on" else 2
                elif name == "end_job":
                    GlueScriptLoader._flush_layer(elem_branch, context, op_node, points)
                    op_node = None
                    points = []
                elif GlueScriptLoader._is_live_only(name):
                    logger.warning("Ignoring live-only .cglu command: %s", name)
                # Other saved-job commands (power, scan_rows, dwell, ...)
                # carry no geometry and are safely ignored on load.
            kernel.root.close(basename)
        return True

    @staticmethod
    def _is_live_only(name):
        return name in (
            "jog_set_xy_speed",
            "jog_set_z_speed",
            "jog_set_u_speed",
            "jog_set_xy_rel",
            "jog_xy_to",
            "jog_z_to",
            "jog_u_to",
            "jog_xy_rel",
            "home",
            "home_z",
            "home_u",
            "focus_z",
            "pause",
            "resume",
            "stop_job",
            "reset",
        )

    @staticmethod
    def _layer_to_op(op_branch, args, kw):
        label = args[0] if args else kw.get("label", "Layer")
        color = args[1] if len(args) > 1 else kw.get("color", "#000000")
        mode = kw.get("mode", "VECTOR")
        speed = kw.get("speed", 100.0)
        max_power = kw.get("max_power_1", 70.0)
        if mode in ("IMAGE", "DEPTHMAP", "RASTER", "DITHER"):
            op_type = "op raster"
        elif max_power >= 70.0:
            op_type = "op cut"
        else:
            op_type = "op engrave"
        return op_branch.add(
            type=op_type,
            label=label,
            color=color,
            speed=speed,
            power=max_power * 10.0,
        )

    @staticmethod
    def _append_move(points, name, args, kw):
        if name == "move_xy_to":
            x = args[0] if args else kw.get("x", 0.0)
            y = args[1] if len(args) > 1 else kw.get("y", 0.0)
            points.append((float(x) * _UNIT, float(y) * _UNIT))
        elif name == "move_x_to":
            x = args[0] if args else kw.get("x", 0.0)
            if points:
                points.append((float(x) * _UNIT, points[-1][1]))
        elif name == "move_y_to":
            y = args[0] if args else kw.get("y", 0.0)
            if points:
                points.append((points[-1][0], float(y) * _UNIT))
        elif name == "cut_xy_to":
            x = args[0] if args else kw.get("x", 0.0)
            y = args[1] if len(args) > 1 else kw.get("y", 0.0)
            points.append((float(x) * _UNIT, float(y) * _UNIT))
        elif name == "cut_x_to":
            x = args[0] if args else kw.get("x", 0.0)
            if points:
                points.append((float(x) * _UNIT, points[-1][1]))
        elif name == "cut_y_to":
            y = args[0] if args else kw.get("y", 0.0)
            if points:
                points.append((points[-1][0], float(y) * _UNIT))

    @staticmethod
    def _flush_layer(elem_branch, context, op_node, points):
        if op_node is None or len(points) < 2:
            return
        from meerk40t.core.geomstr import Geomstr

        pts = [complex(x, y) for x, y in points]
        geom = Geomstr()
        geom.polyline(pts)
        node = context.add(type="elem path", geometry=geom, stroke=op_node.color)
        op_node.add_reference(node)
