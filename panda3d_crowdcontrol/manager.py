"""Crowd Control SimpleTCP client polled by Panda3D's task manager."""

import errno
import json
import math
import select
import socket
import time
from typing import Dict, Optional, Tuple, Type

from direct.directnotify import DirectNotifyGlobal
from direct.showbase.DirectObject import DirectObject
from direct.showbase.MessengerGlobal import messenger
from direct.task.TaskManagerGlobal import taskMgr

from .effect import CrowdControlEffect
from .timed_effect import TimedCrowdControlEffect


class Panda3DCrowdControlManager(DirectObject):
    """Connect to a Crowd Control pack using SimpleTCPServerConnector."""

    notify = DirectNotifyGlobal.directNotify.newCategory("Panda3DCrowdControlManager")

    STATUS_SUCCESS = 0
    STATUS_FAILURE = 1
    STATUS_UNAVAILABLE = 2
    STATUS_RETRY = 3
    STATUS_PAUSED = 6
    STATUS_RESUMED = 7
    STATUS_FINISHED = 8
    MAX_BUFFER_SIZE = 1024 * 1024
    BYTES_PER_FRAME = 64 * 1024

    def __init__(self, port: int = 43384, host: str = "127.0.0.1", connect_timeout: float = 5.0):
        super().__init__()
        if not math.isfinite(connect_timeout) or connect_timeout <= 0:
            raise ValueError("connect_timeout must be positive and finite")
        self.host = host
        self.port = port
        self.connect_timeout = connect_timeout
        self.socket: Optional[socket.socket] = None
        self.is_connected = False
        self.is_connecting = False
        self.registered_effects: Dict[str, Type[CrowdControlEffect]] = {}
        self.active_timed_effects: Dict[str, Tuple[int, TimedCrowdControlEffect]] = {}
        self._recv_buffer = bytearray()
        self._send_buffer = bytearray()
        self._task_name = f"cc-socket-poll-{id(self)}"
        self._connect_deadline = 0.0

    def register_effect(self, code: str, effect_class: Type[CrowdControlEffect]) -> None:
        """Register a no-argument effect class under its pack's effect code."""
        if not isinstance(code, str) or not code:
            raise ValueError("code must be a nonempty string")
        if not isinstance(effect_class, type) or not issubclass(effect_class, CrowdControlEffect):
            raise TypeError("effect_class must subclass CrowdControlEffect")
        self.registered_effects[code] = effect_class

    def start(self) -> bool:
        """Begin connecting; True means the attempt started, not that it finished."""
        self.stop()
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.setblocking(False)
            result = self.socket.connect_ex((self.host, self.port))
            pending = {errno.EINPROGRESS, errno.EWOULDBLOCK, errno.EALREADY,
                       getattr(errno, "WSAEWOULDBLOCK", 10035),
                       getattr(errno, "WSAEINPROGRESS", 10036)}
            if result != 0 and result not in pending:
                raise OSError(result, "Connection failed")
            self.is_connecting = True
            self._connect_deadline = time.monotonic() + self.connect_timeout
            taskMgr.add(self._socket_task, self._task_name)
            messenger.send("cc-connection-state-changed", ["connecting"])
            if result == 0:
                self._connected()
            return True
        except OSError as exc:
            self.notify.warning(f"Could not connect to Crowd Control: {exc}")
            self.stop()
            return False

    def _connected(self) -> None:
        self.is_connecting = False
        self.is_connected = True
        messenger.send("cc-status-changed", [True])
        messenger.send("cc-connection-state-changed", ["connected"])

    def stop(self) -> None:
        """Disconnect and undo all active timed effects."""
        taskMgr.remove(self._task_name)
        was_connected = self.is_connected
        was_active = was_connected or self.is_connecting
        self.is_connected = False
        self.is_connecting = False
        if self.socket is not None:
            self.socket.close()
            self.socket = None
        self._recv_buffer.clear()
        self._send_buffer.clear()
        effects = list(self.active_timed_effects.values())
        self.active_timed_effects.clear()
        for _, effect in effects:
            effect._finish_callback = None
            effect._state_callback = None
            try:
                if not effect.on_stop():
                    self.notify.warning(f"Cleanup failed for '{effect.code}'")
            except Exception as exc:
                self.notify.warning(f"Error cleaning up '{effect.code}': {exc}")
        if was_connected:
            messenger.send("cc-status-changed", [False])
        if was_active:
            messenger.send("cc-connection-state-changed", ["disconnected"])

    def _socket_task(self, task):
        if self.socket is None:
            return task.done
        try:
            writable_sockets = [self.socket] if self.is_connecting or self._send_buffer else []
            readable, writable, exceptional = select.select(
                [self.socket], writable_sockets, [self.socket], 0.0
            )
            if exceptional:
                raise OSError("Socket connection failed")
            if self.is_connecting:
                if readable or writable:
                    error = self.socket.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
                    if error:
                        raise OSError(error, "Connection failed")
                    self._connected()
                elif time.monotonic() >= self._connect_deadline:
                    raise TimeoutError("Crowd Control connection timed out")
                else:
                    return task.cont
            if readable:
                try:
                    data = self.socket.recv(self.BYTES_PER_FRAME)
                except (BlockingIOError, InterruptedError):
                    data = None
                if data == b"":
                    self.stop()
                    return task.done
                if data:
                    self._recv_buffer.extend(data)
                    self._process_messages()
                    if len(self._recv_buffer) > self.MAX_BUFFER_SIZE:
                        raise OSError("Incoming message exceeded buffer limit")
            if self.socket is not None and self._send_buffer:
                self._flush_responses()
        except OSError as exc:
            self.notify.warning(f"Crowd Control socket error: {exc}")
            self.stop()
            return task.done
        return task.cont if self.socket is not None else task.done

    def _process_messages(self) -> None:
        while self.socket is not None and b"\x00" in self._recv_buffer:
            index = self._recv_buffer.index(0)
            message = bytes(self._recv_buffer[:index])
            del self._recv_buffer[:index + 1]
            if not message:
                continue
            if len(message) > self.MAX_BUFFER_SIZE:
                raise OSError("Incoming message exceeded buffer limit")
            try:
                request = json.loads(message.decode("utf-8"))
            except (ValueError, UnicodeError) as exc:
                self.notify.warning(f"Invalid Crowd Control JSON: {exc}")
                continue
            self._process_request(request)

    def _process_request(self, req: dict) -> None:
        if not isinstance(req, dict):
            self.notify.warning("Crowd Control request must be a JSON object")
            return
        req_type = req.get("type")
        if type(req_type) is not int:
            return
        if req_type == 255:
            return  # Keepalives do not expect a response.
        req_id = req.get("id")
        if type(req_id) is not int or not 0 <= req_id <= 0xFFFFFFFF:
            self.notify.warning("Crowd Control request has an invalid id")
            return
        code = req.get("code")
        if not isinstance(code, str) or not code:
            self._send_response(req_id, self.STATUS_FAILURE)
            return
        if req_type == 2:
            active = self.active_timed_effects.pop(code, None)
            if active is None:
                self._send_response(req_id, self.STATUS_SUCCESS)
                return
            original_id, effect = active
            effect._finish_callback = None
            effect._state_callback = None
            try:
                success = bool(effect.on_stop())
            except Exception as exc:
                self.notify.warning(f"Error stopping '{code}': {exc}")
                success = False
            status = self.STATUS_FINISHED if success else self.STATUS_FAILURE
            self._send_response(original_id, status, 0)
            if req_id != original_id:
                self._send_response(req_id, self.STATUS_SUCCESS if success else self.STATUS_FAILURE)
            return
        if req_type not in (0, 1):
            self.notify.warning(f"Unsupported Crowd Control request type: {req_type}")
            return
        effect_cls = self.registered_effects.get(code)
        if effect_cls is None:
            self._send_response(req_id, self.STATUS_FAILURE)
            return
        if code in self.active_timed_effects:
            self._send_response(req_id, self.STATUS_RETRY)
            return
        viewer = req.get("viewer", "Anonymous")
        parameters = req.get("parameters", [])
        if not isinstance(viewer, str) or not isinstance(parameters, list):
            self._send_response(req_id, self.STATUS_FAILURE)
            return
        try:
            effect = effect_cls()
            if effect.code != code:
                raise ValueError("Registered code must match the effect's code")
            if not effect.on_test(viewer, parameters):
                self._send_response(req_id, self.STATUS_RETRY)
                return
            if req_type == 0:
                self._send_response(req_id, self.STATUS_SUCCESS)
                return
            timed = isinstance(effect, TimedCrowdControlEffect)
            if timed and "duration" in req:
                duration = req["duration"]
                if type(duration) is not int or duration <= 0:
                    raise ValueError("Request duration must be positive integer milliseconds")
                effect.duration = duration / 1000.0
            if not effect.on_start(viewer, parameters):
                self._send_response(req_id, self.STATUS_RETRY)
                return
            remaining = None
            if timed:
                self.active_timed_effects[code] = (req_id, effect)
                effect._finish_callback = lambda success: self._handle_effect_finished(code, effect, success)
                effect._state_callback = lambda paused: self._handle_effect_state(code, effect, paused)
                remaining = self._milliseconds(effect)
            self._send_response(req_id, self.STATUS_SUCCESS, remaining)
        except Exception as exc:
            self.notify.warning(f"Error executing '{code}': {exc}")
            self._send_response(req_id, self.STATUS_FAILURE)
            return
        messenger.send("cc-effect-started", [code, viewer])

    @staticmethod
    def _milliseconds(effect: TimedCrowdControlEffect) -> int:
        return max(0, round(effect.time_remaining * 1000))

    def _handle_effect_state(self, code, effect, paused) -> None:
        active = self.active_timed_effects.get(code)
        if active and active[1] is effect:
            status = self.STATUS_PAUSED if paused else self.STATUS_RESUMED
            self._send_response(active[0], status, self._milliseconds(effect))

    def _handle_effect_finished(self, code, effect, success) -> None:
        active = self.active_timed_effects.get(code)
        if active and active[1] is effect:
            del self.active_timed_effects[code]
            effect._finish_callback = None
            effect._state_callback = None
            status = self.STATUS_FINISHED if success else self.STATUS_FAILURE
            self._send_response(active[0], status, 0)

    def _send_response(self, req_id: int, status: int, time_remaining=None) -> None:
        if self.socket is None or not self.is_connected:
            return
        response = {"id": req_id, "type": 0, "status": status}
        if time_remaining is not None:
            response["timeRemaining"] = time_remaining
        self._send_buffer.extend((json.dumps(response) + "\x00").encode("utf-8"))
        if len(self._send_buffer) > self.MAX_BUFFER_SIZE:
            self.notify.warning("Outgoing responses exceeded buffer limit")
            self.stop()

    def _flush_responses(self) -> None:
        try:
            sent = self.socket.send(self._send_buffer[:self.BYTES_PER_FRAME])
        except (BlockingIOError, InterruptedError):
            return
        if sent == 0:
            raise OSError("Socket closed during send")
        del self._send_buffer[:sent]
