"""
ruida-pa Device Plugin

Registers the ruida-pa GlueScript device driver. The plugin depends on the
external ``ruida-pa`` package; when it is unavailable the plugin declines to
register (the rest of MeerK40t keeps working).
"""

import logging

logger = logging.getLogger(__name__)


def plugin(kernel, lifecycle=None):
    if lifecycle == "plugins" or lifecycle == "register":
        try:
            from meerk40t.ruida_pa.device import RuidaPADevice
            from meerk40t.ruida_pa.loader import GlueScriptLoader
        except ImportError as e:
            logger.warning("ruida-pa plugin unavailable: %s", e)
            return None

    if lifecycle == "plugins":
        from .gui import gui

        return [gui.plugin]
    if lifecycle == "register":
        _ = kernel.translation
        kernel.register("provider/device/ruida_pa", RuidaPADevice)
        kernel.register(
            "dev_info/ruida-pa",
            {
                "provider": "provider/device/ruida_pa",
                "friendly_name": _("Ruida Controller (ruida-pa driver)"),
                "extended_info": _(
                    "Controls Ruida controllers via the ruida-pa GlueScript driver."
                ),
                "priority": 0,
                "family": _("CO2-Laser"),
                "choices": [
                    {
                        "attr": "label",
                        "default": "ruida_pa",
                    },
                    {
                        "attr": "source",
                        "default": "co2",
                    },
                    {
                        "attr": "connection_mode",
                        "default": "auto",
                    },
                    {
                        "attr": "driver_mode",
                        "default": "direct",
                    },
                ],
            },
        )
        kernel.register("load/GlueScriptLoader", GlueScriptLoader)

    if lifecycle == "preboot":
        prefix = "ruida_pa"
        for d in kernel.section_startswith(prefix):
            kernel.root(f"service device start -p {d} {prefix}\n")
