def plugin(service, lifecycle):
    if lifecycle == "invalidate":
        return not service.has_feature("wx")
    if lifecycle == "service":
        return "provider/device/ruida_pa"
    if lifecycle == "added":
        from meerk40t.gui.icons import (
            icons8_computer_support,
            icons8_connected,
            icons8_info,
        )

        _ = service._

        service.register(
            "button/control/Controller",
            {
                "label": _("Controller"),
                "icon": icons8_connected,
                "tip": _("Opens Controller Window"),
                "action": lambda e: service("window toggle Controller\n"),
            },
        )
        kernel = service.kernel
        if not (
            hasattr(kernel.args, "lock_device_config")
            and kernel.args.lock_device_config
        ):
            service.register(
                "button/device/Configuration",
                {
                    "label": _("Config"),
                    "icon": icons8_computer_support,
                    "tip": _("Opens device-specific configuration window"),
                    "action": lambda v: service("window toggle Configuration\n"),
                },
            )
        service.register(
            "button/control/FocusZ",
            {
                "label": _("Focus Z"),
                "icon": icons8_info,
                "tip": _("Send a FocusZ command"),
                "help": "deviceruidapa",
                "action": lambda v: service("focusz\n"),
            },
        )

        from meerk40t.ruida_pa.gui.ruidapaconfig import RuidaPaConfiguration
        from meerk40t.ruida_pa.gui.ruidapacontroller import RuidaPaController

        service.register("window/Controller", RuidaPaController)
        service.register("window/Configuration", RuidaPaConfiguration)

        service.register("winpath/Controller", service)
        service.register("winpath/Configuration", service)
