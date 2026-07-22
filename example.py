"""
Example Panda3D application demonstrating the panda3d-crowdcontrol SDK plugin.
"""

from direct.showbase.ShowBase import ShowBase
from panda3d.core import WindowProperties
from panda3d_crowdcontrol import (
    Panda3DCrowdControlManager,
    CrowdControlEffect,
    TimedCrowdControlEffect,
    CrowdControlConnectButton
)


class ExampleInstantEffect(CrowdControlEffect):
    """Sample one-shot effect."""

    def __init__(self):
        super().__init__("give_coins")

    def on_start(self, viewer: str, parameters: list) -> bool:
        print(f"[CrowdControl] Viewer '{viewer}' gave coins! Params: {parameters}")
        return True


class ExampleTimedEffect(TimedCrowdControlEffect):
    """Sample timed effect."""

    def __init__(self):
        super().__init__("low_gravity", duration=10.0)

    def on_timed_start(self, viewer: str, parameters: list) -> bool:
        print(f"[CrowdControl] Low Gravity triggered by '{viewer}' for {self.duration} seconds!")
        return True

    def on_timed_stop(self) -> bool:
        print("[CrowdControl] Low Gravity finished.")
        return True


class CrowdControlDemoApp(ShowBase):

    def __init__(self):
        super().__init__()
        if self.win:
            properties = WindowProperties()
            properties.setTitle("Panda3D Crowd Control Demo")
            self.win.requestProperties(properties)

        self.cc_manager = Panda3DCrowdControlManager(port=43384)

        self.cc_manager.register_effect("give_coins", ExampleInstantEffect)
        self.cc_manager.register_effect("low_gravity", ExampleTimedEffect)

        self.connect_btn = CrowdControlConnectButton(
            self.cc_manager,
            pos=(0, 0, -0.8)
        )

        print("Panda3D Crowd Control Demo Initialized. Click the UI button or start the manager to test.")

    def destroy(self):
        if hasattr(self, "cc_manager"):
            self.cc_manager.stop()
        super().destroy()


if __name__ == "__main__":
    app = CrowdControlDemoApp()
    app.run()
