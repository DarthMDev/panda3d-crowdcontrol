"""Timed effects driven by Panda3D's frame clock."""

import math
from typing import Any, List

from direct.directnotify import DirectNotifyGlobal
from direct.showbase.MessengerGlobal import messenger
from direct.task.TaskManagerGlobal import taskMgr
from panda3d.core import ClockObject

from .effect import CrowdControlEffect


class TimedCrowdControlEffect(CrowdControlEffect):
    """Apply a change, then undo it when its timer ends or it is stopped."""

    notify = DirectNotifyGlobal.directNotify.newCategory("TimedCrowdControlEffect")

    def __init__(self, code: str, duration: float = 30.0):
        super().__init__(code)
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("duration must be a positive, finite number of seconds")
        self.duration = duration
        self.time_remaining = duration
        self.is_paused = False
        self.is_running = False
        self.task_name = f"cc-timed-effect-{code}-{id(self)}"
        self._finish_callback = None
        self._state_callback = None

    def on_start(self, viewer: str, parameters: List[Any]) -> bool:
        """Apply the effect once and schedule its countdown."""
        if self.is_running or not self.on_timed_start(viewer, parameters):
            return False
        self.time_remaining = self.duration
        self.is_paused = False
        self.is_running = True
        taskMgr.add(self._update_task, self.task_name)
        return True

    def on_stop(self) -> bool:
        """Remove the timer and undo the effect at most once."""
        if not self.is_running:
            return True
        taskMgr.remove(self.task_name)
        self.is_running = False
        self.is_paused = False
        return self.on_timed_stop()

    def pause(self) -> None:
        """Pause the countdown and report the remaining time."""
        if self.is_running and not self.is_paused:
            self.on_timed_pause()
            self.is_paused = True
            if self._state_callback:
                self._state_callback(True)

    def resume(self) -> None:
        """Resume a paused countdown."""
        if self.is_running and self.is_paused:
            self.on_timed_resume()
            self.is_paused = False
            if self._state_callback:
                self._state_callback(False)

    def _update_task(self, task):
        if not self.is_running:
            return task.done
        if self.is_paused:
            return task.cont
        self.time_remaining = max(0.0, self.time_remaining - ClockObject.getGlobalClock().getDt())
        if self.time_remaining > 0:
            return task.cont
        self.is_running = False
        try:
            success = bool(self.on_timed_stop())
        except Exception as exc:
            self.notify.warning(f"Error cleaning up timed effect '{self.code}': {exc}")
            success = False
        if self._finish_callback:
            self._finish_callback(success)
        messenger.send("cc-effect-finished", [self.code])
        return task.done

    def on_timed_start(self, viewer: str, parameters: List[Any]) -> bool:
        """Apply the game change; return False if it cannot run yet."""
        raise NotImplementedError("Timed effects must implement on_timed_start()")

    def on_timed_stop(self) -> bool:
        """Undo the game change made by on_timed_start()."""
        raise NotImplementedError("Timed effects must implement on_timed_stop()")

    def on_timed_pause(self) -> None:
        """Optionally suspend the game change while its timer is paused."""
        pass

    def on_timed_resume(self) -> None:
        """Optionally restore the game change after a pause."""
        pass
