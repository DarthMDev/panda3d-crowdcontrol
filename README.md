# Panda3D Crowd Control

A [Crowd Control](https://crowdcontrol.live/) plugin for Panda3D games. Handles
viewer requests over SimpleTCP using Panda3D's task manager, with instant effects,
timed effects, and an optional DirectGUI connection button.

Supports Python 3.8+ and Panda3D 1.10.15+, including Panda3D 1.11 builds.

## Installation

```bash
git clone https://github.com/DarthMDev/panda3d-crowdcontrol.git
cd panda3d-crowdcontrol
python -m pip install -e .
```

If your game already uses a custom Panda3D build, add `--no-deps` to keep it:

```bash
python -m pip install --no-deps -e .
```

## Crowd Control setup

Your game needs a Crowd Control effect pack configured with
`SimpleTCPServerConnector`, UTF-8 encoding, and no authentication. The Crowd
Control app hosts the server; the game connects to it. Match the pack's port and
effect codes to those registered in your game. The default port is `43384`.

See the [SimpleTCP documentation](https://developer.crowdcontrol.live/sdk/simpletcp/)
for pack configuration.

## Usage

Create the manager after initializing `ShowBase`, then register your effects:

```python
from direct.showbase.ShowBase import ShowBase
from panda3d_crowdcontrol import (
    Panda3DCrowdControlManager,
    CrowdControlEffect,
    CrowdControlConnectButton,
)


class HealEffect(CrowdControlEffect):
    def __init__(self):
        super().__init__("heal_player")

    def on_start(self, viewer, parameters):
        print(f"Heal requested by {viewer}")
        return True


class Game(ShowBase):
    def __init__(self):
        super().__init__()
        self.cc_manager = Panda3DCrowdControlManager(port=43384)
        self.cc_manager.register_effect("heal_player", HealEffect)
        self.cc_button = CrowdControlConnectButton(self.cc_manager, pos=(0, 0, -0.8))

    def destroy(self):
        if hasattr(self, "cc_manager"):
            self.cc_manager.stop()
        super().destroy()


if __name__ == "__main__":
    Game().run()
```

The example prints a message; replace the hook with your game's healing logic.
Run `python example.py` for a demo with both instant and timed effects.

To connect without a button, call `manager.start()`. This begins the connection
attempt; `manager.is_connected` becomes `True` once connected. Call
`manager.stop()` on shutdown to disconnect and clean up active timed effects.

## Writing effects

- Effect classes take no constructor arguments, and their code must match the
  code used in `register_effect()`.
- Return `True` from a start hook when applied, or `False` to retry later.
  Override `on_test(viewer, parameters)` to check availability without applying
  the effect. Keep hooks short since they run on the game thread.
- For timed effects, subclass `TimedCrowdControlEffect` and implement
  `on_timed_start(viewer, parameters)` and `on_timed_stop()`. Pass a default
  `duration` in seconds to the constructor; Crowd Control's requested duration
  overrides it. The stop hook should undo the change and return `True`.
- Requests for an already active timed effect are retried rather than stacked.
  Call `pause()` and `resume()` on `manager.active_timed_effects[code][1]` when
  the game pauses or resumes.

## Events

Listen with Panda3D's `accept()` method:

| Event | Arguments |
| --- | --- |
| `cc-status-changed` | `is_connected: bool` |
| `cc-connection-state-changed` | `state: str` (`connecting`, `connected`, `disconnected`) |
| `cc-effect-started` | `code: str, viewer: str` |
| `cc-effect-finished` | `code: str` (timer expired) |

## Tests

```bash
python -m unittest discover -s tests -v
```

## License

[MIT](LICENSE).
