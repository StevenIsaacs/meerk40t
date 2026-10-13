"""
RuidaPA Device

Ruida device interfacing through the ``ruida-pa`` GlueScript driver API.
"""

import logging

from meerk40t.core.view import View
from meerk40t.device.devicechoices import get_effect_choices, get_operation_choices
from meerk40t.kernel import CommandSyntaxError, Service, signal_listener

from ..core.laserjob import LaserJob
from ..core.spoolers import Spooler
from ..core.units import Length, uM_PER_INCH
from ..device.mixins import Status
from .driver import RuidaPADriver
from .mk_adapter import rpc_support_available

logger = logging.getLogger(__name__)


class RuidaPADevice(Service, Status):
    """
    RuidaPADevice is the MeerK40t service for the ruida-pa GlueScript driver.
    """

    def __init__(self, kernel, path, *args, choices=None, **kwgs):
        Service.__init__(self, kernel, path)
        Status.__init__(self)
        self.name = "RuidaPADevice"
        self.extension = "rd"

        if choices is not None:
            for c in choices:
                attr = c.get("attr")
                default = c.get("default")
                if attr is not None and default is not None:
                    setattr(self, attr, default)

        self.setting(bool, "use_percent_for_power_display", False)
        self.setting(bool, "use_minute_for_speed_display", False)

        _ = self._

        choices = [
            {
                "attr": "label",
                "object": self,
                "default": path,
                "type": str,
                "label": _("Label"),
                "tip": _("What is this device called."),
                "section": "_00_General",
                "priority": "10",
            },
            {
                "attr": "bedwidth",
                "object": self,
                "default": "24in",
                "type": Length,
                "label": _("Width"),
                "tip": _("Width of the laser bed."),
                "nonzero": True,
                "section": "_10_" + _("Configuration"),
                "subsection": "_10_Dimensions",
            },
            {
                "attr": "bedheight",
                "object": self,
                "default": "16in",
                "type": Length,
                "label": _("Height"),
                "tip": _("Height of the laser bed."),
                "nonzero": True,
                "section": "_10_" + _("Configuration"),
                "subsection": "_10_Dimensions",
            },
            {
                "attr": "laserspot",
                "object": self,
                "default": "0.3mm",
                "type": Length,
                "label": _("Laserspot"),
                "tip": _("Laser spot size"),
                "section": "_10_" + _("Configuration"),
                "subsection": "_10_Dimensions",
                "nonzero": True,
            },
            {
                "attr": "scale_x",
                "object": self,
                "default": 1.000,
                "type": float,
                "label": _("X Scale Factor"),
                "tip": _(
                    "Scale factor for the X-axis. Board units to actual physical units."
                ),
                "section": "_10_" + _("Configuration"),
                "subsection": "_20_User Scale",
            },
            {
                "attr": "scale_y",
                "object": self,
                "default": 1.000,
                "type": float,
                "label": _("Y Scale Factor"),
                "tip": _(
                    "Scale factor for the Y-axis. Board units to actual physical units."
                ),
                "section": "_10_" + _("Configuration"),
                "subsection": "_20_User Scale",
            },
            {
                "attr": "user_margin_x",
                "object": self,
                "default": "0",
                "type": str,
                "label": _("X-Margin"),
                "tip": _(
                    "Margin for the X-axis. This will be a kind of unused "
                    "space at the left side."
                ),
                "section": "_10_" + _("Configuration"),
                "subsection": "_30_User Offset",
                "ignore": True,
            },
            {
                "attr": "user_margin_y",
                "object": self,
                "default": "0",
                "type": str,
                "label": _("Y-Margin"),
                "tip": _(
                    "Margin for the Y-axis. This will be a kind of unused "
                    "space at the top."
                ),
                "section": "_10_" + _("Configuration"),
                "subsection": "_30_User Offset",
                "ignore": True,
            },
            {
                "attr": "flip_x",
                "object": self,
                "default": False,
                "type": bool,
                "label": _("Flip X"),
                "tip": _("Flip the X axis for the device"),
                "section": "_10_" + _("Configuration"),
                "subsection": "_40_Axis corrections",
            },
            {
                "attr": "flip_y",
                "object": self,
                "default": False,
                "type": bool,
                "label": _("Flip Y"),
                "tip": _("Flip the Y axis for the device"),
                "section": "_10_" + _("Configuration"),
                "subsection": "_40_Axis corrections",
            },
            {
                "attr": "swap_xy",
                "object": self,
                "default": False,
                "type": bool,
                "label": _("Swap X and Y"),
                "tip": _(
                    "Swaps the X and Y axis. This happens before the FlipX and FlipY."
                ),
                "section": "_10_" + _("Configuration"),
                "subsection": "_10_" + _("Axis corrections"),
            },
            {
                "attr": "home_corner",
                "object": self,
                "default": "auto",
                "type": str,
                "style": "combo",
                "choices": [
                    "auto",
                    "top-left",
                    "top-right",
                    "bottom-left",
                    "bottom-right",
                    "center",
                ],
                "label": _("Force Declared Home"),
                "tip": _("Override native home location"),
                "section": "_10_" + _("Configuration"),
                "subsection": "_50_" + _("Home position"),
            },
            {
                "attr": "interpolate",
                "object": self,
                "default": 500,
                "type": int,
                "trailer": "μm",
                "label": _("Curve Interpolation"),
                "section": "_10_Parameters",
                "tip": _("Native units interpolation points."),
            },
            {
                "attr": "signal_updates",
                "object": self,
                "default": True,
                "type": bool,
                "label": _("Device Position"),
                "tip": _(
                    "Do you want to see some indicator about the current "
                    "device position?"
                ),
                "section": "_95_" + _("Screen updates"),
                "signals": "restart",
            },
        ]
        self.register_choices("bed_dim", choices)

        # Express bed dimensions in the global preferred units (Preferences ->
        # General -> Units) so the Dimensions fields display consistently.
        self._normalize_dim_units()

        choices = [
            {
                "attr": "default_power",
                "object": self,
                "default": 20.0,
                "type": float,
                "label": _("Laser Power"),
                "style": "power",
                "percent": lambda: bool(
                    getattr(self, "use_percent_for_power_display", True)
                ),
                "tip": _("What power level do we cut at?"),
            },
            {
                "attr": "default_speed",
                "object": self,
                "default": 40.0,
                "type": float,
                "style": "speed",
                "perminute": lambda: bool(
                    getattr(self, "use_minute_for_speed_display", False)
                ),
                "label": _("Cut Speed"),
                "tip": _("How fast do we cut?"),
            },
        ]
        self.register_choices("ruida_pa-global", choices)

        self.register_choices("ruida_pa-effects", get_effect_choices(self))
        self.register_choices(
            "ruida_pa-defaults",
            get_operation_choices(
                self,
                default_cut_speed=5,
                default_engrave_speed=25,
                default_raster_speed=250,
            ),
        )

        choices = [
            {
                "attr": "device_coolant",
                "object": self,
                "default": "",
                "type": str,
                "style": "option",
                "label": _("Coolant"),
                "tip": _(
                    "Does this device has a method to turn on / off a "
                    "coolant associated to it?"
                ),
                "section": "_99_" + _("Coolant Support"),
                "dynamic": self.cool_helper,
                "signals": "coolant_changed",
            },
        ]
        self.register_choices("coolant", choices)

        # Connection settings (plan §3).
        self.setting(str, "driver_mode", "direct")
        self.setting(str, "connection_mode", "auto")
        self.setting(str, "network_protocol", "udp")
        self.setting(str, "network_host", "")
        self.setting(str, "usb_device", "")
        self.setting(str, "rpc_host", "127.0.0.1")
        self.setting(int, "rpc_port", 18812)
        self.setting(str, "rpc_token", "")
        self.setting(float, "rpc_timeout", 30.0)

        # Power-scaling panel (plan §6).
        self.setting(bool, "enable_power_scaling", False)
        self.setting(float, "power_floor", 8.0)

        self.setting(int, "magic", 0x88)

        self.driver = RuidaPADriver(self)
        self.spooler = Spooler(self, driver=self.driver)
        self.add_service_delegate(self.spooler)
        self.add_service_delegate(self.driver)

        self.view = View(self.bedwidth, self.bedheight, dpi=uM_PER_INCH)
        self.realize()
        self.state = 0

        _ = self.kernel.translation
        self.kernel.root.coolant.claim_coolant(self, self.device_coolant)

        self.setting(bool, "connected", False)

        if self.driver_mode == "rpc" and not rpc_support_available():
            message = _(
                "ruida-pa RPC support is unavailable; switch Driver Mode to Direct."
            )
            logger.warning(message)
            try:
                self.kernel.channel("console")(message)
            except Exception:
                pass

        @self.console_command(
            "connect",
            hidden=True,
            help=_("Connects to the device."),
        )
        def device_connect(command, channel, _, data=None, **kwargs):
            self._start_connection(channel)

        @self.console_command(
            "reconnect",
            hidden=True,
            help=_("Rebuilds the driver and connects to the device."),
        )
        def device_reconnect(command, channel, _, data=None, **kwargs):
            self._start_connection(channel, rebuild=True)

        @self.console_command(
            "disconnect",
            hidden=True,
            help=_("Disconnects from the device."),
        )
        def device_disconnect(command, channel, _, data=None, **kwargs):
            self.driver.adapter.stop()
            channel(_("Disconnected."))

        @self.console_command(("estop", "abort"), help=_("Abort Job"))
        def pipe_abort(command, channel, _, data=None, **kwargs):
            self.driver.reset()
            channel(_("Emergency Stop."))
            self.signal("pipe;running", False)

        @self.console_command(
            "pause",
            help=_("realtime pause/resume of the machine"),
        )
        def realtime_pause(command, channel, _, data=None, **kwargs):
            if self.driver.paused:
                self.driver.resume()
            else:
                self.driver.pause()
            self.signal("pause")

        @self.console_command(
            "resume",
            help=_("realtime resume of the machine"),
        )
        def realtime_resume(command, channel, _, data=None, **kwargs):
            if self.driver.paused:
                self.driver.resume()
                self.signal("pause")
            else:
                channel(_("Device is not paused"))

        @self.console_command(
            "focusz",
            hidden=True,
            help=_("Initiates a FocusZ Operation"),
        )
        def focusz(command, channel, _, data=None, **kwargs):
            self.driver.focusz()

        @kernel.console_command("+xforward", hidden=True)
        def plus_x_forward(command, channel, _, data=None, **kwgs):
            self.driver.adapter.jog_xy_rel(0, -1000)

        @kernel.console_command("-xforward", hidden=True)
        def minus_x_forward(command, channel, _, data=None, **kwgs):
            self.driver.adapter.jog_xy_rel(0, 1000)

        @kernel.console_command("+xbackward", hidden=True)
        def plus_x_backward(data, **kwgs):
            self.driver.adapter.jog_xy_rel(0, 1000)

        @kernel.console_command("-xbackward", hidden=True)
        def minus_x_backward(data, **kwgs):
            self.driver.adapter.jog_xy_rel(0, -1000)

        @kernel.console_command("+yforward", hidden=True)
        def plus_y_forward(data, **kwgs):
            self.driver.adapter.jog_xy_rel(-1000, 0)

        @kernel.console_command("-yforward", hidden=True)
        def minus_y_forward(data, **kwgs):
            self.driver.adapter.jog_xy_rel(1000, 0)

        @kernel.console_command("+ybackward", hidden=True)
        def plus_y_backward(data, **kwgs):
            self.driver.adapter.jog_xy_rel(1000, 0)

        @kernel.console_command("-ybackward", hidden=True)
        def minus_y_backward(data, **kwgs):
            self.driver.adapter.jog_xy_rel(-1000, 0)

        @kernel.console_command(
            "ruida_pa_binds",
            hidden=True,
        )
        def ruida_pa_binds(data, **kwgs):
            self("bind a +xbackward")
            self("bind d +xforward")
            self("bind s +ybackward")
            self("bind w +yforward")

        @self.console_argument("filename", type=str)
        @self.console_option(
            "magic",
            "m",
            type=int,
            default=-1,
            help=_("magic number used to encode the file"),
        )
        @self.console_command("save_job", help=_("save job export"), input_type="plan")
        def ruida_pa_save(channel, _, filename, magic, data=None, **kwargs):
            if filename is None:
                raise CommandSyntaxError
            try:
                if magic == -1:
                    magic = self.magic
                driver = RuidaPADriver(self)
                job = LaserJob(filename, list(data.plan), driver=driver)
                script = driver.adapter.stage_script(list(data.plan))
                self._write_rd(filename, script, magic)
                driver.job_start(job)
                job.execute()
                driver.job_finish(job)
            except (PermissionError, OSError):
                channel(_("Could not save: {filename}").format(filename=filename))

    @staticmethod
    def _write_rd(filename, rpascript_lines, magic):
        """Encode staged rpascript lines into a swizzled ``.rd`` binary file."""
        from rpalib.rpa_swizzler import RpaSwizzler
        from rpalib.ruida_transcoder import RdEncoder
        from rpascript.encoding import encode_command
        from rpascript.interpreter import ScriptParser

        parser = ScriptParser()
        enc = RdEncoder()
        raw = bytearray()
        for cmd in parser.parse_lines(list(rpascript_lines)):
            if cmd.get("type") in ("new_packet", "SESSION_START", "SESSION_END"):
                continue
            mnemonic = cmd.get("mnemonic")
            if not mnemonic or mnemonic.startswith("GET_"):
                continue
            try:
                raw.extend(encode_command(cmd, parser.mnemonic_map, parser.mt_map, enc))
            except (ValueError, TypeError):
                continue
        swizzler = RpaSwizzler(magic=magic)
        swizzled = swizzler.swizzle(raw)
        with open(filename, "wb") as f:
            f.write(b"RDWORKV" + b"\x00" * 3)
            f.write(swizzled)

    @property
    def safe_label(self):
        if not hasattr(self, "label"):
            return self.name
        name = self.label.replace(" ", "-")
        return name.replace("/", "-")

    @property
    def has_endstops(self):
        return True

    @property
    def connected(self):
        adapter = getattr(self, "driver", None)
        return adapter.adapter.connected if adapter else False

    @property
    def is_connecting(self):
        return False

    def connect(self):
        try:
            self.driver.adapter.open()
        except Exception:
            pass

    def _start_connection(self, channel, rebuild=False):
        """
        Start the connection and report the result.

        When ``rebuild`` is set the existing driver is torn down and a new one
        is constructed before connecting; otherwise the existing driver is
        reused when one exists (a new one is created only if none exists).
        """
        adapter = self.driver.adapter
        try:
            result = adapter.open() if rebuild else adapter.start()
        except Exception as e:
            channel(self._("Connection failed: {}").format(e))
            self.update_connect_status()
            return
        channel(self._("Connection started: {}").format("True" if result else "False"))
        self.update_connect_status()

    def update_connect_status(self):
        self.signal(
            "pipe;usb_status", "Connected" if self.connected else "Disconnected"
        )

    def abort_connect(self):
        pass

    def set_disable_connect(self, should_disable):
        pass

    def set_timeout(self, seconds):
        pass

    @property
    def is_busy(self):
        return self.driver.adapter.job_running

    def service_attach(self, *args, **kwargs):
        self.realize()

    def service_detach(self, *args, **kwargs):
        try:
            self.driver.adapter.close()
        except Exception:
            pass

    @signal_listener("scale_x")
    @signal_listener("scale_y")
    @signal_listener("bedwidth")
    @signal_listener("bedheight")
    @signal_listener("flip_x")
    @signal_listener("flip_y")
    @signal_listener("home_corner")
    @signal_listener("swap_xy")
    @signal_listener("user_margin_x")
    @signal_listener("user_margin_y")
    def realize(self, origin=None, *args):
        if origin is not None and origin != self.path:
            return
        corner = self.setting(str, "home_corner")
        home_dx = 0
        home_dy = 0
        if corner == "auto":
            pass
        elif corner == "top-left":
            home_dx = 1 if self.flip_x else 0
            home_dy = 1 if self.flip_y else 0
        elif corner == "top-right":
            home_dx = 0 if self.flip_x else 1
            home_dy = 1 if self.flip_y else 0
        elif corner == "bottom-left":
            home_dx = 1 if self.flip_x else 0
            home_dy = 0 if self.flip_y else 1
        elif corner == "bottom-right":
            home_dx = 0 if self.flip_x else 1
            home_dy = 0 if self.flip_y else 1
        elif corner == "center":
            home_dx = 0.5
            home_dy = 0.5
        self.view.set_dims(self.bedwidth, self.bedheight)
        self.view.set_margins(self.user_margin_x, self.user_margin_y)
        self.view.transform(
            user_scale_x=self.scale_x,
            user_scale_y=self.scale_y,
            flip_x=self.flip_x,
            flip_y=self.flip_y,
            swap_xy=self.swap_xy,
            origin_x=home_dx,
            origin_y=home_dy,
        )
        self.signal("view;realized")

    def _global_units(self):
        return self.kernel.root.setting(str, "units_name", "mm")

    def _express_in_units(self, value):
        return str(Length(value, preferred_units=self._global_units()).preferred_length)

    def _normalize_dim_units(self, signal=False):
        """Re-express bed dimensions in the global preferred units."""
        changed = []
        for attr in ("bedwidth", "bedheight", "laserspot"):
            value = getattr(self, attr, None)
            if value is None:
                continue
            expr = self._express_in_units(value)
            if str(value) != expr:
                setattr(self, attr, expr)
                changed.append(attr)
        if signal:
            for attr in changed:
                self.signal(attr, getattr(self, attr))

    @signal_listener("units")
    def on_units_changed(self, origin, *args):
        self._normalize_dim_units(signal=True)

    @signal_listener("bedwidth")
    def on_bedwidth_changed(self, origin, *args):
        self._normalize_dim_units(signal=True)

    @signal_listener("bedheight")
    def on_bedheight_changed(self, origin, *args):
        self._normalize_dim_units(signal=True)

    @property
    def current(self):
        return self.view.iposition(self.driver.native_x, self.driver.native_y)

    @property
    def native(self):
        return self.driver.native_x, self.driver.native_y

    def cool_helper(self, choice_dict):
        self.kernel.root.coolant.coolant_choice_helper(self)(choice_dict)

    def get_operation_defaults(self, operation_type: str) -> dict:
        return self.get_operation_power_speed_defaults(operation_type)
