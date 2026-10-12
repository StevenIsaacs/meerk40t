"""RuidaPA Configuration Window."""

import wx
import wx.aui

from meerk40t.device.gui.defaultactions import DefaultActionPanel
from meerk40t.device.gui.formatterpanel import FormatterPanel
from meerk40t.device.gui.warningpanel import WarningPanel
from meerk40t.gui.choicepropertypanel import ChoicePropertyPanel
from meerk40t.gui.icons import icons8_administrative_tools
from meerk40t.gui.mwindow import MWindow
from meerk40t.gui.wxutils import ScrolledPanel, StaticBoxSizer, TextCtrl, wxButton
from meerk40t.kernel import signal_listener

from ..mk_adapter import rpc_support_available

_ = wx.GetTranslation


def _add_text_field(sizer, parent, label, textctrl, tip=None):
    row = wx.BoxSizer(wx.HORIZONTAL)
    text = wx.StaticText(parent, wx.ID_ANY, label)
    row.Add(text, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
    if tip:
        textctrl.SetToolTip(tip)
    row.Add(textctrl, 1, wx.EXPAND, 0)
    sizer.Add(row, 0, wx.EXPAND, 0)


class ConnectionPanel(ScrolledPanel):
    """
    Connection and driver-mode panel (plan §6).

    - connection_mode: Auto (USB preferred) / Network / USB
    - network_protocol: UDP / TCP (used in Network mode)
    - network_host, usb_device (device path or VID:PID), magic
    - driver_mode: Direct / RPC/TUI; rpc_host/port/token/timeout in RPC mode
    - power-scaling: enable_power_scaling + power_floor
    """

    def __init__(self, *args, context=None, **kwds):
        self.service = context
        super().__init__(*args, **kwds)
        self.service.themes.set_window_colors(self)

        main_sizer = wx.BoxSizer(wx.VERTICAL)

        # --- Driver mode ---
        sizer_driver = StaticBoxSizer(self, wx.ID_ANY, _("Driver Mode"), wx.VERTICAL)
        self.radio_direct = wx.RadioButton(
            self, wx.ID_ANY, _("Direct"), style=wx.RB_GROUP
        )
        self.radio_rpc = wx.RadioButton(self, wx.ID_ANY, _("RPC/TUI"))
        self.radio_direct.SetValue(self.service.driver_mode != "rpc")
        self.radio_rpc.SetValue(self.service.driver_mode == "rpc")
        if not rpc_support_available():
            self.radio_rpc.Enable(False)
            self.radio_rpc.SetToolTip(
                _("RPC support is unavailable (rpyc / ruida-pa RPC import failed).")
            )
        for rb, mode in ((self.radio_direct, "direct"), (self.radio_rpc, "rpc")):
            rb.Bind(wx.EVT_RADIOBUTTON, lambda e, m=mode: self._set_driver_mode(m))
        sizer_driver.Add(self.radio_direct, 0, wx.EXPAND, 0)
        sizer_driver.Add(self.radio_rpc, 0, wx.EXPAND, 0)
        main_sizer.Add(sizer_driver, 0, wx.EXPAND, 0)

        # --- Connection mode ---
        sizer_mode = StaticBoxSizer(self, wx.ID_ANY, _("Connection Mode"), wx.VERTICAL)
        self.radio_auto = wx.RadioButton(
            self, wx.ID_ANY, _("Auto (USB preferred)"), style=wx.RB_GROUP
        )
        self.radio_network = wx.RadioButton(self, wx.ID_ANY, _("Network"))
        self.radio_usb = wx.RadioButton(self, wx.ID_ANY, _("USB"))
        for rb, mode in (
            (self.radio_auto, "auto"),
            (self.radio_network, "network"),
            (self.radio_usb, "usb"),
        ):
            rb.SetValue(self.service.connection_mode == mode)
            rb.Bind(wx.EVT_RADIOBUTTON, lambda e, m=mode: self._set_connection_mode(m))
        sizer_mode.Add(self.radio_auto, 0, wx.EXPAND, 0)
        sizer_mode.Add(self.radio_network, 0, wx.EXPAND, 0)
        sizer_mode.Add(self.radio_usb, 0, wx.EXPAND, 0)
        main_sizer.Add(sizer_mode, 0, wx.EXPAND, 0)

        # --- Protocol (Network mode) ---
        sizer_proto = StaticBoxSizer(
            self, wx.ID_ANY, _("Network Protocol"), wx.HORIZONTAL
        )
        self.radio_udp = wx.RadioButton(self, wx.ID_ANY, _("UDP"), style=wx.RB_GROUP)
        self.radio_tcp = wx.RadioButton(self, wx.ID_ANY, _("TCP"))
        self.radio_udp.SetValue(self.service.network_protocol != "tcp")
        self.radio_tcp.SetValue(self.service.network_protocol == "tcp")
        self.radio_udp.Bind(wx.EVT_RADIOBUTTON, lambda e: self._set_protocol("udp"))
        self.radio_tcp.Bind(wx.EVT_RADIOBUTTON, lambda e: self._set_protocol("tcp"))
        sizer_proto.Add(self.radio_udp, 0, wx.EXPAND, 0)
        sizer_proto.Add(self.radio_tcp, 0, wx.EXPAND, 0)
        main_sizer.Add(sizer_proto, 0, wx.EXPAND, 0)

        # --- Network / USB / magic fields ---
        sizer_host = StaticBoxSizer(self, wx.ID_ANY, _("Connection"), wx.VERTICAL)
        self.text_host = TextCtrl(self, wx.ID_ANY, self.service.network_host)
        self.text_usb = TextCtrl(self, wx.ID_ANY, self.service.usb_device)
        self.text_magic = TextCtrl(self, wx.ID_ANY, hex(self.service.magic))
        _add_text_field(sizer_host, self, _("Network Host"), self.text_host)
        _add_text_field(
            sizer_host,
            self,
            _("USB Device (path or VID:PID)"),
            self.text_usb,
            _("e.g. ttyUSB0, /dev/ttyACM0, COM3, or 0403:6001"),
        )
        _add_text_field(
            sizer_host,
            self,
            _("Magic"),
            self.text_magic,
            _("Magic number used to encode files (hex, e.g. 0x88)"),
        )
        main_sizer.Add(sizer_host, 0, wx.EXPAND, 0)

        # --- RPC fields ---
        sizer_rpc = StaticBoxSizer(self, wx.ID_ANY, _("RPC/TUI Server"), wx.VERTICAL)
        self.text_rpc_host = TextCtrl(self, wx.ID_ANY, self.service.rpc_host)
        self.text_rpc_port = TextCtrl(self, wx.ID_ANY, str(self.service.rpc_port))
        self.text_rpc_token = TextCtrl(self, wx.ID_ANY, self.service.rpc_token)
        self.text_rpc_timeout = TextCtrl(self, wx.ID_ANY, str(self.service.rpc_timeout))
        _add_text_field(sizer_rpc, self, _("Host"), self.text_rpc_host)
        _add_text_field(sizer_rpc, self, _("Port"), self.text_rpc_port)
        _add_text_field(sizer_rpc, self, _("Token"), self.text_rpc_token)
        _add_text_field(sizer_rpc, self, _("Timeout (s)"), self.text_rpc_timeout)
        main_sizer.Add(sizer_rpc, 0, wx.EXPAND, 0)

        # --- Power scaling ---
        sizer_power = StaticBoxSizer(self, wx.ID_ANY, _("Power Scaling"), wx.VERTICAL)
        self.check_scaling = wx.CheckBox(
            self, wx.ID_ANY, _("Enable effective-min power scaling")
        )
        self.check_scaling.SetValue(self.service.enable_power_scaling)
        self.text_floor = TextCtrl(self, wx.ID_ANY, str(self.service.power_floor))
        sizer_power.Add(self.check_scaling, 0, wx.EXPAND, 0)
        _add_text_field(sizer_power, self, _("Power Floor (%)"), self.text_floor)
        main_sizer.Add(sizer_power, 0, wx.EXPAND, 0)

        # --- Actions ---
        self.button_apply = wxButton(self, wx.ID_ANY, _("Apply/Connect"))
        self.button_apply.Bind(wx.EVT_BUTTON, self.on_button_apply)
        main_sizer.Add(self.button_apply, 0, wx.EXPAND, 0)

        self.SetSizer(main_sizer)
        self.Layout()
        self._update_rpc_visibility()

    def _set_driver_mode(self, mode):
        self.service.driver_mode = mode
        self._update_rpc_visibility()

    def _set_connection_mode(self, mode):
        self.service.connection_mode = mode

    def _set_protocol(self, protocol):
        self.service.network_protocol = protocol

    def _update_rpc_visibility(self):
        rpc = self.service.driver_mode == "rpc"
        for child in [
            self.text_rpc_host,
            self.text_rpc_port,
            self.text_rpc_token,
            self.text_rpc_timeout,
        ]:
            child.Enable(rpc)

    def on_button_apply(self, event):
        try:
            self.service.network_host = self.text_host.GetValue()
            self.service.usb_device = self.text_usb.GetValue()
            magic_text = self.text_magic.GetValue().strip()
            if magic_text.lower().startswith("0x"):
                magic_text = magic_text[2:]
            self.service.magic = int(magic_text, 16)
            self.service.rpc_host = self.text_rpc_host.GetValue()
            self.service.rpc_port = int(self.text_rpc_port.GetValue())
            self.service.rpc_token = self.text_rpc_token.GetValue()
            self.service.rpc_timeout = float(self.text_rpc_timeout.GetValue())
            self.service.enable_power_scaling = self.check_scaling.GetValue()
            self.service.power_floor = float(self.text_floor.GetValue())
        except ValueError:
            return
        self.service("connect\n")

    def pane_show(self):
        pass

    def pane_hide(self):
        pass


class RuidaPaConfiguration(MWindow):
    def __init__(self, *args, **kwds):
        super().__init__(420, 570, *args, **kwds)
        self.context = self.context.device
        self.service = self.context
        self.SetTitle(_("RuidaPA Configuration"))
        _icon = wx.NullIcon
        _icon.CopyFromBitmap(icons8_administrative_tools.GetBitmap())
        self.SetIcon(_icon)

        self.notebook_main = wx.aui.AuiNotebook(
            self,
            -1,
            style=wx.aui.AUI_NB_TAB_EXTERNAL_MOVE
            | wx.aui.AUI_NB_SCROLL_BUTTONS
            | wx.aui.AUI_NB_TAB_SPLIT
            | wx.aui.AUI_NB_TAB_MOVE,
        )
        self.sizer.Add(self.notebook_main, 1, wx.EXPAND, 0)

        self.panels = []

        newpanel = ChoicePropertyPanel(
            self, wx.ID_ANY, context=self.context, choices="bed_dim"
        )
        self.panels.append(newpanel)
        newpanel.Reparent(self.notebook_main)
        self.notebook_main.AddPage(newpanel, _("Dimensions"))

        newpanel = ConnectionPanel(self, wx.ID_ANY, context=self.context)
        self.panels.append(newpanel)
        newpanel.Reparent(self.notebook_main)
        self.notebook_main.AddPage(newpanel, _("Connection"))

        newpanel = ChoicePropertyPanel(
            self, wx.ID_ANY, context=self.context, choices=("ruida_pa-global",)
        )
        self.panels.append(newpanel)
        newpanel.Reparent(self.notebook_main)
        self.notebook_main.AddPage(newpanel, _("Configuration"))

        newpanel = ChoicePropertyPanel(
            self, wx.ID_ANY, context=self.context, choices="ruida_pa-effects"
        )
        self.panels.append(newpanel)
        newpanel.Reparent(self.notebook_main)
        self.notebook_main.AddPage(newpanel, _("Effects"))

        newpanel = ChoicePropertyPanel(
            self, wx.ID_ANY, context=self.context, choices="ruida_pa-defaults"
        )
        self.panels.append(newpanel)
        newpanel.Reparent(self.notebook_main)
        self.notebook_main.AddPage(newpanel, _("Operation Defaults"))

        newpanel = WarningPanel(self, wx.ID_ANY, context=self.context)
        self.panels.append(newpanel)
        newpanel.Reparent(self.notebook_main)
        self.notebook_main.AddPage(newpanel, _("Warning"))

        newpanel = DefaultActionPanel(self, wx.ID_ANY, context=self.context)
        self.panels.append(newpanel)
        newpanel.Reparent(self.notebook_main)
        self.notebook_main.AddPage(newpanel, _("Default Actions"))

        newpanel = FormatterPanel(self, wx.ID_ANY, context=self.context)
        self.panels.append(newpanel)
        newpanel.Reparent(self.notebook_main)
        self.notebook_main.AddPage(newpanel, _("Display Options"))

        for panel in self.panels:
            self.add_module_delegate(panel)
        self.Layout()
        self.restore_aspect()

    def window_open(self):
        for panel in self.panels:
            panel.pane_show()

    def window_close(self):
        for panel in self.panels:
            panel.pane_hide()

    def window_preserve(self):
        return False

    @staticmethod
    def submenu():
        # Hint for translation: _("Device-Settings"), _("Configuration")
        return "Device-Settings", "Configuration"

    @staticmethod
    def helptext():
        return _("Display the device configuration window")

    @signal_listener("activate;device")
    def on_device_changes(self, *args):
        if self.context.name != "RuidaPADevice":
            wx.CallAfter(self.Close)
