"""Offline tests for the ruida-pa driver (no hardware / mock required)."""

import os
import tempfile
import unittest
from test import bootstrap


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


class FakeCut:
    """A minimal cut object exposing start/end/settings."""

    def __init__(self, x, y, settings=None):
        self.start = (0.0, 0.0)
        self.end = (x, y)
        self.settings = settings or {}


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


if __name__ == "__main__":
    unittest.main()
