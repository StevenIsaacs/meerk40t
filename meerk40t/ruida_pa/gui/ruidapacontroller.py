"""RuidaPA Controller / status window."""

import wx

from meerk40t.gui.mwindow import MWindow
from meerk40t.gui.wxutils import TextCtrl, wxButton
from meerk40t.kernel import signal_listener

_ = wx.GetTranslation

SETTINGS_OUT = ("idle", "moving", "busy", "plotting", "disconnected")

IDLE_COLOR = "#AAAAAA"
BUSY_COLOR = "#FFFF00"
MOVING_COLOR = "#E02020"
PLOTTING_COLOR = "#0000AA"
DISCONNECTED_COLOR = "#000000"


class RuidaPaControllerPanel(wx.ScrolledWindow):
    def __init__(self, *args, context=None, **kwds):
        super().__init__(*args, **kwds)
        self.context = context
        self.service = context.device
        themes = getattr(self.service, "themes", None)
        if themes is not None:
            themes.set_window_colors(self)
        self.buffer = []
        self._state_color = DISCONNECTED_COLOR

        sizer = wx.BoxSizer(wx.VERTICAL)
        self.button_connect = wxButton(self, wx.ID_ANY, _("Connect"))
        self.button_connect.Bind(wx.EVT_BUTTON, self.button_connect_clicked)
        sizer.Add(self.button_connect, 0, wx.EXPAND, 0)

        self.text_status = TextCtrl(
            self,
            wx.ID_ANY,
            style=wx.TE_MULTILINE | wx.TE_READONLY,
        )
        sizer.Add(self.text_status, 1, wx.EXPAND, 0)
        self.SetSizer(sizer)
        self.Layout()
        self.service.update_connect_status()

    def button_connect_clicked(self, event):
        if self.service.connected:
            self.service("disconnect\n")
        else:
            self.service("connect\n")

    @signal_listener("pipe;usb_status")
    def on_usb_update(self, origin, *args):
        if origin != self.service.path:
            return
        if args and len(args) > 0:
            if args[0] == "Connected":
                self.button_connect.SetLabel(_("Disconnect"))
            else:
                self.button_connect.SetLabel(_("Connect"))

    def update_text(self, data):
        self.buffer.append(data)
        if len(self.buffer) > 1000:
            self.buffer.pop(0)
        self.context.signal("ruida_pa_controller_update")

    @signal_listener("ruida_pa_controller_update")
    def update_text_gui(self, origin, *args):
        text = "\n".join(self.buffer)
        self.text_status.SetValue(text)

    def pane_show(self):
        name = self.service.safe_label
        self.context.channel(f"{name}/events").watch(self.update_text)
        self.button_connect.SetLabel(
            _("Disconnect") if self.service.connected else _("Connect")
        )

    def pane_hide(self):
        name = self.service.safe_label
        self.context.channel(f"{name}/events").unwatch(self.update_text)


class RuidaPaController(MWindow):
    def __init__(self, *args, **kwds):
        super().__init__(499, 170, *args, **kwds)
        self.service = self.context.device
        self.SetTitle(_("RuidaPA Controller"))
        self.panel = RuidaPaControllerPanel(self, wx.ID_ANY, context=self.context)
        self.sizer.Add(self.panel, 1, wx.EXPAND, 0)
        self.add_module_delegate(self.panel)
        self.Layout()
        self.restore_aspect()

    def window_open(self):
        self.panel.pane_show()

    def window_close(self):
        self.panel.pane_hide()

    @staticmethod
    def submenu():
        # Hint for translation: _("Device-Control"), _("RuidaPA Controller")
        return "Device-Control", "RuidaPA Controller"

    @staticmethod
    def helptext():
        return _("Display the RuidaPA controller window")
