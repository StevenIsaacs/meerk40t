"""
MKAdapter

The central rewrite for the ``ruida-pa`` MeerK40t driver. Provides the same
high-level controller API that the legacy ``ruida/controller.py`` +
``ruida/rdjob.py`` pair exposed to the driver, but implemented on top of the
GlueScript API of the ``ruida-pa`` package.

Depending on ``service.driver_mode`` the adapter wraps either:

- ``RdDriver``   — in-process, the MeerK40t process opens the session itself.
- ``RpcRdDriver`` — over RPyC to the ``ruida-pa`` TUI server (``rpa-script
  --tui --rpc``); the session lives on the TUI process.

Unit conversion: MeerK40t native units are µm (micrometers); GlueScript uses
mm, so coordinates are divided by 1000 before authoring.
"""

import threading

# ruida-pa is optional; the plugin refuses to load when it is unavailable.
from ruidadriver.ruida_driver import RdDriver

from meerk40t.core.units import Length

try:
    from rpalib.rpyc_client import RpcRdDriver
except ImportError as e:  # pragma: no cover
    RpcRdDriver = None
    _rpc_import_error = e
else:
    _rpc_import_error = None


def rpc_support_available():
    """Return True when ruida-pa RPC (rpyc) support is importable."""
    return RpcRdDriver is not None


class MKAdapter:
    """
    GlueScript-based controller adapter.

    The RuidaPADriver talks to this object exactly as the legacy driver talked
    to ``RuidaController``/``RDJob``. All coordinate arguments are in MeerK40t
    native units (µm).
    """

    def __init__(self, service):
        self.service = service
        self._driver = None
        self._lock = threading.Lock()
        self._current_layer = 0
        self._listener_stop = False

        # Reflection of the controller state (updated from status listeners).
        self.connected = False
        self.transport_type = None  # "udp" | "tcp" | "usb"
        self.job_running = False
        self.card_id = None
        self.machine_status = 0
        self.native_x = 0
        self.native_y = 0
        self.bed_x = None
        self.bed_y = None

    # ------------------------------------------------------------------ #
    # Connection lifecycle
    # ------------------------------------------------------------------ #

    def _make_driver(self):
        if self.service.driver_mode == "rpc":
            if RpcRdDriver is None:
                raise RuntimeError(
                    f"ruida-pa RPC support is unavailable: {_rpc_import_error}"
                )
            return RpcRdDriver(
                host=self.service.rpc_host,
                port=self.service.rpc_port,
                token=self.service.rpc_token or None,
                timeout=self.service.rpc_timeout,
            )
        return RdDriver()

    def resolve_start_args(self):
        """
        Resolve the requested connection mode into ``start()`` arguments
        (network_host, usb_device, protocol) per plan §1.2.
        """
        mode = self.service.connection_mode
        host = self.service.network_host or None
        usb = self.service.usb_device or None
        protocol = self.service.network_protocol
        if mode == "network":
            return host, None, protocol
        if mode == "usb":
            return None, usb, protocol
        # Auto: the driver prefers USB, then falls back to the network host.
        return host, usb, protocol

    def open(self):
        """
        (Re)create the underlying driver and open the connection.
        """
        self.close()
        self._driver = self._make_driver()
        self._driver.register_status_listener(self._on_status)
        self._driver.register_error_listener(self._on_error)
        self._driver.register_reply_listener(self._on_reply)
        return self.start()

    def start(self):
        """Start the connection using current service settings."""
        if self._driver is None:
            self.open()
        host, usb, protocol = self.resolve_start_args()
        return self._driver.start(
            network_host=host,
            usb_device=usb,
            magic=self.service.magic,
            protocol=protocol,
        )

    def stop(self):
        if self._driver is not None:
            self._driver.stop()
        self.connected = False

    def close(self):
        if self._driver is not None:
            try:
                self._driver.unregister_status_listener(self._on_status)
            except Exception:
                pass
            try:
                self._driver.unregister_error_listener(self._on_error)
            except Exception:
                pass
            try:
                self._driver.unregister_reply_listener(self._on_reply)
            except Exception:
                pass
            if hasattr(self._driver, "close"):
                self._driver.close()
            self._driver = None
        self.connected = False

    # ------------------------------------------------------------------ #
    # ruida-pa → MeerK40t listener translation (plan §5)
    # ------------------------------------------------------------------ #

    def _on_error(self, message):
        channel = self.service.channel(f"{self.service.safe_label}/events")
        channel(message)

    def _on_reply(self, replies):
        # Replies for addresses the driver handles itself are already decoded
        # into status; nothing to forward by default.
        pass

    def _on_status(self, event):
        if isinstance(event, dict):
            self._handle_status_dict(event)
            return
        # RdStatusEvent member (direct) or event name string (over RPC).
        name = getattr(event, "name", None)
        if name is None and isinstance(event, str):
            name = event
        self._handle_status_event(name)

    def _handle_status_event(self, name):
        if name is None:
            return
        service = self.service
        if name in ("CONNECTED", "RECONNECTED"):
            self.connected = True
            service.connected = True
            service.signal("pipe;usb_status", "Connected")
        elif name in ("DISCONNECTED", "TERMINATED"):
            self.connected = False
            service.connected = False
            service.signal("pipe;usb_status", "Disconnected")
        elif name == "TRANSPORT_UDP":
            self.transport_type = "udp"
            service.signal("pipe;usb_status", "Connected")
        elif name == "TRANSPORT_TCP":
            self.transport_type = "tcp"
            service.signal("pipe;usb_status", "Connected")
        elif name == "TRANSPORT_USB":
            self.transport_type = "usb"
            service.signal("pipe;usb_status", "Connected")

    def _handle_status_dict(self, status):
        service = self.service
        driver = getattr(service, "driver", None)
        if "POSITION_X" in status:
            value = status["POSITION_X"]
            self.native_x = float(value[0]) * 1000.0
            if driver:
                driver.native_x = self.native_x
        if "POSITION_Y" in status:
            value = status["POSITION_Y"]
            self.native_y = float(value[0]) * 1000.0
            if driver:
                driver.native_y = self.native_y
        if "POSITION_X" in status or "POSITION_Y" in status:
            if driver is not None and hasattr(driver, "position_updated"):
                driver.position_updated()
        if "BED_SIZE_X" in status:
            self.bed_x = float(status["BED_SIZE_X"][0])
            service.bedwidth = Length(f"{self.bed_x:.1f}mm")
            service.signal("bedwidth", service.bedwidth)
        if "BED_SIZE_Y" in status:
            self.bed_y = float(status["BED_SIZE_Y"][0])
            service.bedheight = Length(f"{self.bed_y:.1f}mm")
            service.signal("bedheight", service.bedheight)
        if "MACHINE_STATUS_JOB_RUNNING" in status:
            self.job_running = bool(status["MACHINE_STATUS_JOB_RUNNING"])
        if "CARD_ID" in status:
            self.card_id = status["CARD_ID"][1]
            service.signal("pipe;usb_status", "Connected")

    # ------------------------------------------------------------------ #
    # Job authoring (RDJob → GlueScript mapping, plan §2)
    # ------------------------------------------------------------------ #

    def write_header(self, queue):
        """
        Start a new job: new_gluescript() + declare_job() and, when power
        scaling is enabled, the GlueScript config setters.
        """
        if self._driver is None:
            # Offline authoring (e.g. `.rd` export) does not require a session.
            self._driver = self._make_driver()
        driver = self._driver
        driver.new_gluescript()
        label = getattr(self.service, "label", "RuidaPA")
        driver.declare_job(label, ref_point="MACHINE")
        if self.service.enable_power_scaling:
            driver.set_power_scaling_enabled(True)
            driver.set_power_floor(self.service.power_floor)

    def write_settings(self, settings, raster=False):
        """
        Declare one GlueScript layer for the given MeerK40t settings dict.
        """
        driver = self._driver
        part = settings.get("part", 0)
        layer = int(part) + 1
        self._current_layer = layer
        label = settings.get("desc") or f"Layer {layer}"
        color = self._format_color(settings.get("color"))
        mode = "IMAGE" if raster else "VECTOR"
        speed = settings.get("speed", 100.0)
        if speed <= 0:
            speed = 100.0
        frequency = settings.get("frequency", 20.0)
        power = settings.get("power", self.service.default_power * 10.0) / 10.0
        overscan = self._overscan_for(settings)
        driver.declare_layer(
            label,
            color,
            mode=mode,
            overscan=overscan,
            speed=speed,
            frequency=frequency,
            min_power_1=power,
            max_power_1=power,
        )
        coolant = settings.get("coolant", 0)
        if coolant == 1:
            driver.air_assist_on()
        elif coolant == 2:
            driver.air_assist_off()

    def power_range(self, min_power, max_power):
        """Set an immediate power range percent (0-100) for the current layer."""
        self._driver.power_range(min_power, max_power)

    def cut_speed(self, speed):
        """Set the current layer cut speed mid-job (mm/s)."""
        self._driver.cut_speed(speed)

    def mark(self, x, y):
        """Cut to absolute position (µm) — a laser-on move."""
        self._driver.cut_xy_to(x / 1000.0, y / 1000.0)

    def jump(self, x, y):
        """Move (laser off) to absolute position (µm)."""
        self._driver.move_xy_to(x / 1000.0, y / 1000.0)

    def write_tail(self):
        """
        Finish the job: end_job(), stage, and run through the driver.
        """
        driver = self._driver
        driver.end_job()
        driver.stage_gluescript()
        driver.run_job(auto_checksum=True)

    # ------------------------------------------------------------------ #
    # Live / control commands
    # ------------------------------------------------------------------ #

    def focus_z(self):
        self._driver.focus_z()

    def home(self):
        self._driver.home()

    def home_z(self):
        self._driver.home_z()

    def dwell(self, time_in_ms):
        self._driver.dwell(time_in_ms)

    def add_delay(self, time_in_ms):
        self._driver.add_delay(time_in_ms)

    def laser_on_delay(self, time_in_ms):
        self._driver.laser_on_delay(time_in_ms)

    def laser_off_delay(self, time_in_ms):
        self._driver.laser_off_delay(time_in_ms)

    def pause(self):
        self._driver.pause()

    def resume(self):
        self._driver.resume()

    def stop_job(self):
        self._driver.stop_job()

    def jog_xy_to(self, x, y):
        self._driver.jog_xy_to(x / 1000.0, y / 1000.0)

    def jog_xy_rel(self, dx, dy):
        self._driver.jog_xy_rel(dy / 1000.0, dx / 1000.0)

    # ------------------------------------------------------------------ #
    # Offline .rd export (no session required)
    # ------------------------------------------------------------------ #

    def stage_script(self, queue):
        """
        Build a staged GlueScript job for the given queue and return the
        assembled rpascript lines. The driver does not need to be connected.
        """
        self.write_header(queue)
        last_settings = None
        for q in queue:
            if hasattr(q, "settings"):
                current_settings = q.settings
                _raster = type(q).__name__ == "RasterCut"
                if current_settings is not last_settings:
                    self.write_settings(current_settings, _raster)
                    last_settings = current_settings
            start_x, start_y = q.start
            self.jump(start_x, start_y)
            self.mark(*q.end)
        self._driver.end_job()
        self._driver.stage_gluescript()
        return list(self._driver.rpascript)

    @staticmethod
    def _format_color(color):
        if color is None:
            return "#000000"
        if isinstance(color, str):
            if color.startswith("#"):
                return color if len(color) == 7 else "#000000"
            try:
                value = int(color)
            except ValueError:
                return "#000000"
        else:
            try:
                value = int(color)
            except (TypeError, ValueError):
                return "#000000"
        return f"#{value & 0xFFFFFF:06x}"

    @staticmethod
    def _overscan_for(settings):
        step_x = settings.get("raster_step_x", 0)
        step_y = settings.get("raster_step_y", 0)
        direction = settings.get("raster_direction", 1)
        if step_x:
            return "X_BI" if direction == 1 else "X"
        if step_y:
            return "Y_BI" if direction == 1 else "Y"
        return "NONE"


__all__ = ["MKAdapter"]
