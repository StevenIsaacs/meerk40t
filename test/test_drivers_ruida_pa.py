"""Offline tests for the ruida-pa driver (no hardware / mock required)."""

import os
import tempfile
import unittest
from test import bootstrap


class FakeChannel:
    """Records messages written to a named channel on a FakeService."""

    def __init__(self, service, name):
        self.service = service
        self.name = name

    def __call__(self, message=None):
        self.service.messages.append((self.name, message))

    def watch(self, fn):
        pass

    def unwatch(self, fn):
        pass


class FakeService:
    """Minimal stand-in for a RuidaPADevice for adapter unit tests."""

    driver_mode = "direct"
    connection_mode = "auto"
    network_protocol = "udp"
    network_host = ""
    usb_device = ""
    rpc_host = "127.0.0.1"
    rpc_port = 18812
    rpc_token = ""
    rpc_timeout = 30.0
    magic = 0x88
    enable_power_scaling = False
    power_floor = 8.0
    default_power = 20.0
    label = "ruida_pa"
    safe_label = "ruida_pa"
    connected = False

    def __init__(self):
        self.messages = []

    def channel(self, name):
        return FakeChannel(self, name)

    def signal(self, *args, **kwargs):
        pass


class FakeCut:
    """A minimal cut object exposing start/end/settings."""

    def __init__(self, x, y, settings=None):
        self.start = (0.0, 0.0)
        self.end = (x, y)
        self.settings = settings or {}


class StrictDriver:
    """Driver enforcing the ruida-pa server contract: start before listeners."""

    def __init__(self):
        self.started = False
        self.order = []

    def start(self, **kwargs):
        self.started = True
        self.order.append("start")
        return True

    def register_status_listener(self, listener):
        self.order.append("reg_status")

    def register_error_listener(self, listener):
        self.order.append("reg_error")

    def register_reply_listener(self, listener):
        self.order.append("reg_reply")

    def unregister_status_listener(self, listener):
        self.order.append("unreg_status")

    def unregister_error_listener(self, listener):
        self.order.append("unreg_error")

    def unregister_reply_listener(self, listener):
        self.order.append("unreg_reply")

    def stop(self):
        self.order.append("stop")

    def close(self):
        self.order.append("close")


class TestMockAdapter(unittest.TestCase):
    def setUp(self):
        from meerk40t.ruida_pa.mk_adapter import MKAdapter

        self.service = FakeService()
        self.adapter = MKAdapter(self.service)

    def test_01_start_args_auto(self):
        self.service.connection_mode = "auto"
        self.assertEqual(self.adapter.resolve_start_args(), (None, None, "udp"))

    def test_02_start_args_network(self):
        self.service.connection_mode = "network"
        self.service.network_host = "192.168.1.100"
        self.service.network_protocol = "tcp"
        self.assertEqual(
            self.adapter.resolve_start_args(), ("192.168.1.100", None, "tcp")
        )

    def test_03_start_args_usb(self):
        self.service.connection_mode = "usb"
        self.service.usb_device = "0403:6001"
        self.assertEqual(self.adapter.resolve_start_args(), (None, "0403:6001", "udp"))

    def test_04_rpc_driver_timeout(self):
        from unittest import mock

        from meerk40t.ruida_pa.mk_adapter import MKAdapter, RpcRdDriver

        def fake_init(
            self,
            svc=None,
            *,
            host="127.0.0.1",
            port=18812,
            token=None,
            config=None,
            timeout=5,
        ):
            self._timeout = timeout

        self.service.driver_mode = "rpc"
        adapter = MKAdapter(self.service)
        with mock.patch.object(RpcRdDriver, "__init__", fake_init):
            driver = adapter._make_driver()
        self.assertIsInstance(driver, RpcRdDriver)
        self.assertEqual(driver._timeout, 30.0)

    def test_05_power_scaling_emitted(self):
        self.service.enable_power_scaling = True
        self.service.power_floor = 8.0
        self.adapter.write_header([])
        transcript = self.adapter._driver.gluescript
        self.assertTrue(
            any(line.startswith("set_power_scaling_enabled") for line in transcript)
        )
        self.assertEqual(self.adapter._driver.power_floor, 8.0)

    def test_10_register_before_start(self):
        from meerk40t.ruida_pa.mk_adapter import MKAdapter

        self.service.driver_mode = "rpc"
        adapter = MKAdapter(self.service)
        strict = StrictDriver()
        adapter._make_driver = lambda: strict
        result = adapter.start()
        self.assertTrue(result)
        self.assertEqual(
            strict.order, ["reg_status", "reg_error", "reg_reply", "start"]
        )

    def test_10_close_stops_before_deregister(self):
        from meerk40t.ruida_pa.mk_adapter import MKAdapter

        adapter = MKAdapter(self.service)
        strict = StrictDriver()
        adapter._make_driver = lambda: strict
        adapter.open()
        strict.order = []
        adapter.close()
        self.assertEqual(
            strict.order,
            ["stop", "unreg_status", "unreg_error", "unreg_reply", "close"],
        )
        self.assertIsNone(adapter._driver)
        self.assertFalse(adapter.connected)

    def test_11_status_words_emitted(self):
        self.adapter._handle_status_event("CONNECTED")
        self.assertTrue(self.service.connected)
        self.adapter._handle_status_event("DISCONNECTED")
        self.assertFalse(self.service.connected)
        self.adapter._handle_status_dict({"MACHINE_STATUS_JOB_RUNNING": True})
        self.adapter._handle_status_dict({"MACHINE_STATUS_JOB_RUNNING": True})
        self.adapter._handle_status_dict({"MACHINE_STATUS_JOB_RUNNING": False})
        recorded = [m[1] for m in self.service.messages]
        self.assertIn("Connected", recorded)
        self.assertIn("Disconnected", recorded)
        self.assertEqual(recorded.count("Busy"), 1)
        self.assertEqual(recorded.count("Idle"), 1)

    def test_06_dwell_and_add_delay(self):
        self.adapter.write_header([])
        self.adapter.write_settings(
            {"part": 0, "power": 1000.0, "speed": 40.0, "color": 0}, raster=False
        )
        self.adapter.dwell(100.0)
        self.adapter.add_delay(5.0)
        self.adapter._driver.end_job()
        self.adapter._driver.stage_gluescript()
        script = self.adapter._driver.rpascript
        self.assertIn("CUT_DWELL 100.000mS", script)
        self.assertIn("ADD_CUT_DELAY 5.000mS", script)

    def test_07_scan_rows(self):
        self.adapter.write_header([])
        self.adapter.write_settings(
            {
                "part": 0,
                "power": 1000.0,
                "speed": 100.0,
                "color": 0,
                "raster_step_x": 100,
                "raster_step_y": 100,
            },
            raster=True,
        )
        self.adapter._driver.scan_rows(
            [[50.0, 50.0]], (10.0, 10.0), (0.1, 0.1), True, True
        )
        self.adapter._driver.end_job()
        self.adapter._driver.stage_gluescript()
        script = self.adapter._driver.rpascript
        self.assertTrue(any(line.startswith("CUT_") for line in script))

    def test_08_rd_export(self):
        from meerk40t.ruida_pa.device import RuidaPADevice

        cut = FakeCut(
            50000.0,
            75000.0,
            settings={"part": 0, "power": 1000.0, "speed": 40.0, "color": 0},
        )
        script = self.adapter.stage_script([cut])
        self.assertTrue(script)
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "test.rd")
            RuidaPADevice._write_rd(out, script, 0x88)
            self.assertTrue(os.path.exists(out))
            with open(out, "rb") as f:
                data = f.read()
            self.assertTrue(data.startswith(b"RDWORKV"))
            self.assertTrue(len(data) > 8)


class TestLoader(unittest.TestCase):
    def test_loader_builds_ops_and_elements(self):
        kernel = bootstrap.bootstrap(plugins=[self._ruida_pa_plugin()])
        try:
            cglu = (
                "declare_job('test', 'MACHINE', [0.0, 0.0], 1, 1, 0.0, 0.0)\n"
                "declare_layer('Cut', '#ff0000', mode='VECTOR', overscan='NONE', "
                "speed=40.0, frequency=20.0, min_power_1=70.0, max_power_1=70.0)\n"
                "move_xy_to(0.0, 0.0)\n"
                "cut_xy_to(10.0, 10.0)\n"
                "cut_xy_to(20.0, 10.0)\n"
                "end_job()\n"
            )
            from meerk40t.ruida_pa.loader import GlueScriptLoader

            elements = kernel.elements
            with tempfile.NamedTemporaryFile("w", suffix=".cglu", delete=False) as f:
                f.write(cglu)
                pathname = f.name
            try:
                self.assertTrue(GlueScriptLoader.load(kernel, elements, pathname))
                ops = list(elements.op_branch.children)
                self.assertTrue(any(op.type == "op cut" for op in ops))
                elems = list(elements.elem_branch.children)
                self.assertTrue(any("file" == node.type for node in elems))
            finally:
                os.unlink(pathname)
        finally:
            kernel()

    @staticmethod
    def _ruida_pa_plugin():
        from meerk40t.ruida_pa import plugin as ruida_pa_driver

        return ruida_pa_driver.plugin


class TestDevice(unittest.TestCase):
    def test_device_start(self):
        kernel = bootstrap.bootstrap(plugins=[self._ruida_pa_plugin()])
        try:
            kernel.console("service device start -i ruida_pa 0\n")
            device = kernel.device
            self.assertIsNotNone(device)
            self.assertEqual(device.name, "RuidaPADevice")
        finally:
            kernel()

    @staticmethod
    def _ruida_pa_plugin():
        from meerk40t.ruida_pa import plugin as ruida_pa_driver

        return ruida_pa_driver.plugin


class TestDeviceUnits(unittest.TestCase):
    """Bed dimensions follow the global preferred units (Preferences -> Units)."""

    def setUp(self):
        from meerk40t.core.units import Length

        self.Length = Length
        self.kernel = bootstrap.bootstrap(plugins=[self._ruida_pa_plugin()])
        self.kernel.console("service device start -i ruida_pa 0\n")
        self.device = self.kernel.device

    def tearDown(self):
        self.kernel()

    def test_bed_dims_expressed_in_global_units(self):
        device = self.device
        units = device._global_units()
        self.assertEqual(
            str(device.bedwidth),
            str(self.Length("24in", preferred_units=units).preferred_length),
        )
        self.assertEqual(
            str(device.bedheight),
            str(self.Length("16in", preferred_units=units).preferred_length),
        )
        self.assertIn("mm", str(device.bedwidth))

    def test_edit_renormalized_to_global_units(self):
        device = self.device
        units = device._global_units()
        device.bedwidth = self.Length("24in").preferred_length
        device.signal("bedwidth", device.bedwidth, device)
        self.kernel.process_queue()
        self.assertEqual(
            str(device.bedwidth),
            str(self.Length("24in", preferred_units=units).preferred_length),
        )

    def test_units_change_reexpresses(self):
        device = self.device
        self.kernel.root.units_name = "cm"
        self.kernel.signal("units", "cm")
        self.kernel.process_queue()
        self.assertEqual(
            str(device.bedwidth),
            str(self.Length("24in", preferred_units="cm").preferred_length),
        )
        self.assertTrue(str(device.bedwidth).endswith("cm"))

    @staticmethod
    def _ruida_pa_plugin():
        from meerk40t.ruida_pa import plugin as ruida_pa_driver

        return ruida_pa_driver.plugin


class TestRpcSupport(unittest.TestCase):
    """RPC (rpyc) support detection and graceful failure reporting."""

    def test_rpc_support_available_reflects_import(self):
        from meerk40t.ruida_pa import mk_adapter

        self.assertEqual(
            mk_adapter.rpc_support_available(), mk_adapter.RpcRdDriver is not None
        )
        self.assertIsInstance(mk_adapter.rpc_support_available(), bool)

    def test_connect_rpc_unavailable_reports_gracefully(self):
        from unittest import mock

        from meerk40t.ruida_pa import mk_adapter

        kernel = bootstrap.bootstrap(plugins=[self._ruida_pa_plugin()])
        try:
            kernel.console("service device start -i ruida_pa 0\n")
            device = kernel.device
            messages = []
            kernel.channel("console").watch(lambda m: messages.append(m))
            device.driver_mode = "rpc"
            with mock.patch.object(mk_adapter, "RpcRdDriver", None), mock.patch.object(
                mk_adapter, "_rpc_import_error", ImportError("no rpyc")
            ):
                device("connect\n")
            self.assertTrue(
                any("Connection failed" in str(m) for m in messages),
                messages,
            )
        finally:
            kernel()

    @staticmethod
    def _ruida_pa_plugin():
        from meerk40t.ruida_pa import plugin as ruida_pa_driver

        return ruida_pa_driver.plugin


class TestControllerPanel(unittest.TestCase):
    """RuidaPA Controller panel color/label/icon driven by ruida-pa status words."""

    def test_controller_state_updates(self):
        import wx

        from meerk40t.ruida_pa.gui.ruidapacontroller import RuidaPaControllerPanel

        kernel = bootstrap.bootstrap(plugins=[self._ruida_pa_plugin()])
        try:
            kernel.console("service device start -i ruida_pa 0\n")
            device = kernel.root.device
            app = wx.App(False)
            frame = wx.Frame(None)

            def bg_hex():
                return (
                    panel.button_device_connect.GetBackgroundColour()
                    .GetAsString(wx.C2S_HTML_SYNTAX)
                    .upper()
                )

            panel = RuidaPaControllerPanel(frame, wx.ID_ANY, context=device)
            self.assertEqual(panel.color, panel.idle_color)

            panel.set_button_disconnected()
            self.assertEqual(bg_hex(), panel.disconnected_color.upper())

            device.driver.adapter.connected = True
            panel.update_text("Connected")
            self.assertEqual(bg_hex(), panel.idle_color.upper())
            panel.on_usb_update(device.path, "Connected")
            self.assertEqual(panel.button_device_connect.GetLabel(), "Connected")
            self.assertEqual(bg_hex(), panel.idle_color.upper())

            panel.update_text("Busy")
            self.assertTrue(panel.busy)
            self.assertEqual(bg_hex(), panel.busy_color.upper())
            panel.update_text("Plotting")
            self.assertEqual(bg_hex(), panel.plotting_color.upper())
            panel.update_text("Idle")
            self.assertFalse(panel.busy)
            self.assertEqual(bg_hex(), panel.idle_color.upper())
            panel.update_text_gui(None)
            log = panel.text_usb_log.GetValue()
            self.assertIn("Busy", log)
            self.assertIn("Idle", log)

            device.driver.adapter.connected = False
            panel.on_usb_update(device.path, "Disconnected")
            self.assertEqual(panel.button_device_connect.GetLabel(), "Disconnected")
            self.assertEqual(bg_hex(), panel.disconnected_color.upper())

            frame.Destroy()
            app.Destroy()
        finally:
            kernel()

    @staticmethod
    def _ruida_pa_plugin():
        from meerk40t.ruida_pa import plugin as ruida_pa_driver

        return ruida_pa_driver.plugin


class TestDriverJobIdle(unittest.TestCase):
    """RuidaPADriver reports Idle when a plot job finishes."""

    def test_plot_start_emits_idle(self):
        from meerk40t.core.cutcode.linecut import LineCut

        kernel = bootstrap.bootstrap(plugins=[self._ruida_pa_plugin()])
        try:
            kernel.console("service device start -i ruida_pa 0\n")
            device = kernel.root.device

            class StubAdapter:
                def __init__(self):
                    self.tails = 0

                def write_header(self, queue):
                    pass

                def write_settings(self, settings, raster=False):
                    pass

                def write_tail(self):
                    self.tails += 1

                def power_range(self, *a):
                    pass

                def cut_speed(self, *a):
                    pass

                def mark(self, *a):
                    pass

                def jump(self, *a):
                    pass

                def dwell(self, *a):
                    pass

            stub = StubAdapter()
            device.driver.adapter = stub
            events = []
            device.channel(f"{device.safe_label}/events").watch(events.append)
            cut = LineCut(
                (0, 0),
                (10000, 10000),
                settings={"power": 700.0, "speed": 40.0, "color": "#ff0000"},
            )
            device.driver.queue.append(cut)
            device.driver.plot_start()
            self.assertEqual(stub.tails, 1)
            self.assertTrue(events and events[-1].endswith("Idle"), events)
        finally:
            kernel()

    @staticmethod
    def _ruida_pa_plugin():
        from meerk40t.ruida_pa import plugin as ruida_pa_driver

        return ruida_pa_driver.plugin


if __name__ == "__main__":
    unittest.main()
