"""
Base classes for one-shot Crowd Control effects.
"""

from typing import List, Any


class CrowdControlEffect:
    """Base class for instant/one-shot Crowd Control effects."""

    def __init__(self, code: str):
        self.code: str = code

    def on_test(self, viewer: str, parameters: List[Any]) -> bool:
        """Return whether this effect can run, without changing game state."""
        return True

    def on_start(self, viewer: str, parameters: List[Any]) -> bool:
        """
        Executed when the Crowd Control app requests this effect.

        :param viewer: Display name of the viewer who triggered the effect.
        :param parameters: Optional list of parameters passed from Crowd Control.
        :return: True if applied, False to ask Crowd Control to retry later.
        """
        raise NotImplementedError("CrowdControlEffect subclasses must implement on_start()")
