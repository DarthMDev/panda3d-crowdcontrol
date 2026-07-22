"""
Pre-built DirectGUI widgets for Crowd Control integration in Panda3D.
"""

from direct.gui.DirectGui import DirectButton


class CrowdControlConnectButton(DirectButton):
    """
    A customizable DirectButton widget that toggles connection to Crowd Control
    and automatically updates its label based on status events.
    """

    def __init__(self, manager, parent=None, **kw):
        self.manager = manager

        optiondefs = (
            ("text", "Connect Crowd Control", None),
            ("scale", 0.07, None),
            ("command", self._toggle_connection, None),
            ("relief", 1, None),
        )
        self.defineoptions(kw, optiondefs)
        super().__init__(parent=parent)
        self.initialiseoptions(CrowdControlConnectButton)

        self.accept("cc-connection-state-changed", self._on_status_changed)
        self._update_text()

    def _toggle_connection(self):
        if self.manager.is_connected or self.manager.is_connecting:
            self.manager.stop()
        else:
            self.manager.start()

    def _on_status_changed(self, state: str):
        self._update_text()

    def _update_text(self):
        if self.manager.is_connecting:
            self["text"] = "Cancel Connection"
        elif self.manager.is_connected:
            self["text"] = "Disconnect Crowd Control"
        else:
            self["text"] = "Connect Crowd Control"

    def destroy(self):
        self.ignoreAll()
        super().destroy()
