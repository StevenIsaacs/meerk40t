"""
RuidaPA Driver

Implements the MeerK40t spooler driver interface by translating cutcode onto
the GlueScript job API exposed by MKAdapter (which wraps ``ruida-pa``).
"""

import time

from meerk40t.core.cutcode.cubiccut import CubicCut
from meerk40t.core.cutcode.dwellcut import DwellCut
from meerk40t.core.cutcode.gotocut import GotoCut
from meerk40t.core.cutcode.homecut import HomeCut
from meerk40t.core.cutcode.inputcut import InputCut
from meerk40t.core.cutcode.linecut import LineCut
from meerk40t.core.cutcode.outputcut import OutputCut
from meerk40t.core.cutcode.plotcut import PlotCut
from meerk40t.core.cutcode.quadcut import QuadCut
from meerk40t.core.cutcode.rastercut import RasterCut
from meerk40t.core.cutcode.waitcut import WaitCut
from meerk40t.core.geomstr import Geomstr
from meerk40t.core.parameters import Parameters
from meerk40t.core.plotplanner import PlotPlanner
from meerk40t.device.basedevice import PLOT_FINISH, PLOT_JOG, PLOT_RAPID, PLOT_SETTING
from meerk40t.ruida_pa.mk_adapter import MKAdapter


class RuidaPADriver(Parameters):
    def __init__(self, service, **kwargs):
        super().__init__(**kwargs)
        self.service = service
        self.events = service.channel(f"{service.safe_label}/events")
        self.native_x = 0
        self.native_y = 0

        self.name = str(self.service)

        self.adapter = MKAdapter(service)

        self.on_value = 0
        self.power_dirty = True
        self._current_power = -1.0

        self._jog_speed = 600.0
        self.speed_dirty = True
        self.absolute_dirty = True
        self._absolute = True
        self.paused = False
        self.is_relative = False
        self.laser = False

        self._shutdown = False

        self.queue = list()
        self._queue_current = 0
        self._queue_total = 0
        self.plot_planner = PlotPlanner(
            dict(), single=True, ppi=False, shift=False, group=True
        )
        self._aborting = False
        self._signal_updates = False

    def __repr__(self):
        return f"RuidaPADriver({self.name})"

    def position_updated(self):
        """
        Called by the adapter when a status position update arrives.
        """
        if not self._signal_updates:
            return
        current = self.service.current
        self.service.signal(
            "driver;position",
            (current[0], current[1], current[0], current[1]),
        )

    def get_internal_queue_status(self):
        return self._queue_current, self._queue_total

    def _set_queue_status(self, current, total):
        self._queue_current = current
        self._queue_total = total

    #############
    # DRIVER COMMANDS
    #############

    def job_start(self, job):
        pass

    def job_finish(self, job):
        pass

    def hold_work(self, priority):
        return priority <= 0 and self.paused

    def get(self, key, default=None):
        return default

    def set(self, key, value):
        pass

    def status(self):
        state_major = "moving" if self.adapter.job_running else "idle"
        return (self.native_x, self.native_y), state_major, "idle"

    def laser_off(self, *values):
        self.laser = False

    def laser_on(self, *values):
        self.laser = True

    def plot(self, plot):
        self.queue.append(plot)

    def plot_start(self):
        self.events("Plotting")
        self._signal_updates = self.service.setting(bool, "signal_updates", True)
        self.adapter.write_header(self.queue)
        first = True
        last_settings = None
        total = len(self.queue)
        current = 0
        for q in self.queue:
            current += 1
            self._set_queue_status(current, total)
            if hasattr(q, "settings"):
                current_settings = q.settings
                _raster = isinstance(q, RasterCut)
                if current_settings is not last_settings:
                    self.adapter.write_settings(current_settings, _raster)
                    last_settings = current_settings
            x = self.native_x
            y = self.native_y
            start_x, start_y = q.start
            if x != start_x or y != start_y or first:
                first = False
                self._move(start_x, start_y, cut=False)
            if self.on_value != 1.0:
                self.power_dirty = True
            self.on_value = 1.0
            qpower = q.settings.get("power", self.power)
            qspeed = q.settings.get("speed", self.speed)
            qraster_step_x = q.settings.get("raster_step_x")
            qraster_step_y = q.settings.get("raster_step_y")
            if qpower != self.power:
                self.set("power", qpower)
            if (
                qspeed != self.speed
                or qraster_step_x != self.raster_step_x
                or qraster_step_y != self.raster_step_y
            ):
                self.set("speed", qspeed)
            self.settings.update(q.settings)
            if isinstance(q, LineCut):
                self._move(*q.end, cut=True)
            elif isinstance(q, QuadCut):
                interp = self.service.interpolate
                g = Geomstr()
                g.quad(complex(*q.start), complex(*q.c()), complex(*q.end))
                for p in list(g.as_equal_interpolated_points(distance=interp))[1:]:
                    while self.paused:
                        time.sleep(0.05)
                    self._move(p.real, p.imag, cut=True)
            elif isinstance(q, CubicCut):
                interp = self.service.interpolate
                g = Geomstr()
                g.cubic(
                    complex(*q.start),
                    complex(*q.c1()),
                    complex(*q.c2()),
                    complex(*q.end),
                )
                for p in list(g.as_equal_interpolated_points(distance=interp))[1:]:
                    while self.paused:
                        time.sleep(0.05)
                    self._move(p.real, p.imag, cut=True)
            elif isinstance(q, WaitCut):
                self.adapter.add_delay(q.dwell_time)
            elif isinstance(q, HomeCut):
                self.home()
            elif isinstance(q, GotoCut):
                start = q.start
                self._move(start[0], start[1], cut=True)
            elif isinstance(q, DwellCut):
                self.adapter.dwell(q.dwell_time)
            elif isinstance(q, (InputCut, OutputCut)):
                pass
            elif isinstance(q, PlotCut):
                self.set("power", 1000)
                for ox, oy, on, x, y in q.plot:
                    while self.hold_work(0):
                        time.sleep(0.05)
                    if self.on_value != on:
                        self.power_dirty = True
                    self.on_value = on
                    self._move(x, y, cut=self.on_value > 0)
            else:
                # RasterCut
                self.plot_planner.push(q)
                _lines = 0
                for x, y, on in self.plot_planner.gen():
                    while self.hold_work(0):
                        time.sleep(0.05)
                    time.sleep(0)
                    if on > 1:
                        if isinstance(on, float):
                            on = int(on)
                        if on & PLOT_FINISH:
                            break
                        elif on & PLOT_SETTING:
                            p_set = Parameters(self.plot_planner.settings)
                            if p_set.power != self.power:
                                self.set("power", p_set.power)
                            if (
                                p_set.speed != self.speed
                                or p_set.raster_step_x != self.raster_step_x
                                or p_set.raster_step_y != self.raster_step_y
                            ):
                                self.set("speed", p_set.speed)
                            self.settings.update(p_set.settings)
                        elif on & (PLOT_RAPID | PLOT_JOG):
                            self._move(x, y, cut=False)
                        continue
                    if self.on_value != on:
                        self.power_dirty = True
                    self.on_value = on
                    _lines += 1
                    _update = _lines % 100 == 0
                    self._move(x, y, cut=self.on_value > 0, update=_update)
        self.queue.clear()
        self._set_queue_status(0, 0)
        self.adapter.write_tail()
        self._signal_updates = False
        return False

    def move_abs(self, x, y):
        x, y = self.service.view.position(x, y)
        self.adapter.jog_xy_to(x, y)

    def move_rel(self, dx, dy, confined=False):
        dx, dy = self.service.view.position(dx, dy, vector=True)
        self.adapter.jog_xy_rel(dx, dy)

    def focusz(self):
        self.adapter.focus_z()

    def home(self):
        self.adapter.home()

    def physical_home(self):
        self.adapter.home()
        # self.adapter.home_z()
        self.events("Idle")

    def rapid_mode(self):
        pass

    def program_mode(self):
        pass

    def raster_mode(self, *args):
        pass

    def wait_finished(self):
        pass

    def function(self, function):
        function()

    def wait(self, time_in_ms):
        time.sleep(time_in_ms / 1000.0)

    def console(self, value):
        self.service(value)

    def beep(self):
        self.service("beep\n")

    def signal(self, signal, *args):
        self.service.signal(signal, *args)

    def pause(self):
        if self.paused:
            self.resume()
            return
        self.paused = True
        self.adapter.pause()
        self.service.signal("pause")

    def resume(self):
        self.paused = False
        self.adapter.resume()
        self.service.signal("pause")

    def reset(self):
        self.adapter.stop_job()
        self.paused = False
        self.service.signal("pause")

    def dwell(self, time_in_ms):
        self.adapter.dwell(time_in_ms)

    def set_abort(self):
        self._aborting = True

    ####################
    # PROTECTED DRIVER CODE
    ####################

    def _move(self, x, y, cut=True, update=True):
        old_current = self.service.current
        if self.power_dirty:
            if self.power is not None:
                if self.on_value <= 0:
                    cut = False
                else:
                    if self.power != self._current_power:
                        power = self.power / 10.0 * self.on_value
                        self.adapter.power_range(power, power)
                        self._current_power = self.power
            self.power_dirty = False
        if self.speed_dirty:
            self.adapter.cut_speed(self.speed)
            self.speed_dirty = False
        if cut:
            self.adapter.mark(x, y)
        else:
            self.adapter.jump(x, y)
        self.native_x = x
        self.native_y = y
        new_current = self.service.current
        if update and self._signal_updates:
            self.service.signal(
                "driver;position",
                (old_current[0], old_current[1], new_current[0], new_current[1]),
            )
