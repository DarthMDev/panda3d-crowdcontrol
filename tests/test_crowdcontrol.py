"""Protocol and lifecycle tests using real Panda3D tasks and local TCP sockets."""

import errno
import json
import socket
import time
import unittest
from unittest.mock import Mock, patch

from panda3d.core import ClockObject, loadPrcFileData

loadPrcFileData('', 'window-type none\naudio-library-name null\nnotify-level-device fatal')
from direct.showbase.ShowBase import ShowBase
from direct.showbase.DirectObject import DirectObject
from direct.showbase.MessengerGlobal import messenger
from direct.task.TaskManagerGlobal import taskMgr
from panda3d_crowdcontrol import CrowdControlEffect, TimedCrowdControlEffect, Panda3DCrowdControlManager


class Instant(CrowdControlEffect):
    starts = 0
    available = True

    def __init__(self):
        super().__init__('instant')

    def on_test(self, viewer, parameters):
        return self.available

    def on_start(self, viewer, parameters):
        type(self).starts += 1
        return True


class Timed(TimedCrowdControlEffect):
    starts = 0
    stops = 0
    cleanup_error = False

    def __init__(self):
        super().__init__('timed', duration=10.0)

    def on_timed_start(self, viewer, parameters):
        type(self).starts += 1
        return True

    def on_timed_stop(self):
        type(self).stops += 1
        if self.cleanup_error:
            raise RuntimeError('cleanup failed')
        return True


class CrowdControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = ShowBase()
        cls.clock = ClockObject.getGlobalClock()
        cls.clock.setMode(ClockObject.MNonRealTime)
        cls.clock.setDt(0.01)

    @classmethod
    def tearDownClass(cls):
        cls.base.destroy()

    def setUp(self):
        Instant.starts = Timed.starts = Timed.stops = 0
        Instant.available = True
        Timed.cleanup_error = False
        self.listener = socket.socket()
        self.listener.bind(('127.0.0.1', 0))
        self.listener.listen(1)
        self.listener.settimeout(1)
        self.manager = Panda3DCrowdControlManager(port=self.listener.getsockname()[1])
        self.manager.register_effect('instant', Instant)
        self.manager.register_effect('timed', Timed)
        self.events = []
        self.observer = DirectObject()
        self.observer.accept('cc-status-changed', self.events.append)
        self.assertTrue(self.manager.start())
        self.peer, _ = self.listener.accept()
        self.peer.setblocking(False)
        self.step_until(lambda: self.manager.is_connected)
        self.received = bytearray()

    def tearDown(self):
        self.manager.stop()
        self.observer.ignoreAll()
        self.peer.close()
        self.listener.close()

    def step_until(self, predicate, timeout=2):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            taskMgr.step()
            time.sleep(0.001)
        self.assertTrue(predicate(), 'task did not reach expected state')

    def send(self, request):
        self.peer.sendall((json.dumps(request) + '\0').encode())

    def responses(self, count=1):
        def ready():
            try:
                self.received.extend(self.peer.recv(65536))
            except BlockingIOError:
                pass
            return self.received.count(0) >= count
        self.step_until(ready)
        result = []
        for _ in range(count):
            index = self.received.index(0)
            result.append(json.loads(self.received[:index]))
            del self.received[:index + 1]
        return result

    def start_timed(self, req_id=1, duration=10000):
        self.send({'id': req_id, 'type': 1, 'code': 'timed', 'duration': duration})
        self.assertEqual(self.responses()[0], {
            'id': req_id, 'type': 0, 'status': 0, 'timeRemaining': duration
        })
        return self.manager.active_timed_effects['timed'][1]

    def test_confirmed_connection_and_disconnect_events(self):
        self.assertEqual(self.events, [True])
        self.assertFalse(self.manager.is_connecting)
        self.manager.stop()
        self.assertEqual(self.events, [True, False])

    def test_effect_test_does_not_activate_effect(self):
        self.send({'id': 1, 'type': 0, 'code': 'instant'})
        self.assertEqual(self.responses()[0]['status'], 0)
        self.assertEqual(Instant.starts, 0)
        self.send({'id': 2, 'type': 0, 'code': 'unknown'})
        self.assertEqual(self.responses()[0]['status'], 1)

    def test_temporary_unavailability_retries(self):
        Instant.available = False
        self.send({'id': 1, 'type': 1, 'code': 'instant'})
        self.assertEqual(self.responses()[0]['status'], 3)
        self.assertEqual(Instant.starts, 0)

    def test_keepalive_has_no_response(self):
        self.send({'id': 0, 'type': 255})
        self.send({'id': 1, 'type': 0, 'code': 'instant'})
        self.assertEqual(self.responses()[0]['id'], 1)
        self.assertFalse(self.received)

    def test_fragmented_and_coalesced_packets(self):
        self.peer.sendall(b'{"id":1,"type":1,')
        for _ in range(3):
            taskMgr.step()
        self.assertEqual(Instant.starts, 0)
        self.peer.sendall(b'"code":"instant"}\0{"id":2,"type":1,"code":"instant"}\0')
        self.assertEqual([r['id'] for r in self.responses(2)], [1, 2])
        self.assertEqual(Instant.starts, 2)

    def test_malformed_packets_do_not_break_next_request(self):
        self.peer.sendall(b'not-json\0[]\0{"id":true,"type":1,"code":"instant"}\0')
        self.send({'id': 5, 'type': 1, 'code': ['instant']})
        self.send({'id': 6, 'type': 1, 'code': 'instant'})
        self.assertEqual([r['status'] for r in self.responses(2)], [1, 0])
        self.assertEqual(Instant.starts, 1)

    def test_constructor_and_hook_errors_return_failure(self):
        class Broken(Instant):
            def __init__(self):
                raise RuntimeError('constructor failed')
        self.manager.register_effect('instant', Broken)
        self.send({'id': 1, 'type': 1, 'code': 'instant'})
        self.assertEqual(self.responses()[0]['status'], 1)
        class BrokenHook(Instant):
            def on_start(self, viewer, parameters):
                raise RuntimeError('hook failed')
        self.manager.register_effect('instant', BrokenHook)
        self.send({'id': 2, 'type': 1, 'code': 'instant'})
        self.assertEqual(self.responses()[0]['status'], 1)

    def test_false_start_returns_retry(self):
        class NotReady(Instant):
            def on_start(self, viewer, parameters):
                return False
        self.manager.register_effect('instant', NotReady)
        self.send({'id': 1, 'type': 1, 'code': 'instant'})
        self.assertEqual(self.responses()[0]['status'], 3)

    def test_requested_duration_and_expiry(self):
        self.start_timed(duration=100)
        response = self.responses()[0]
        self.assertEqual(response, {'id': 1, 'type': 0, 'status': 8, 'timeRemaining': 0})
        self.assertEqual(Timed.stops, 1)
        self.assertFalse(self.manager.active_timed_effects)

    def test_duplicate_timed_request_is_retried(self):
        effect = self.start_timed()
        self.send({'id': 2, 'type': 1, 'code': 'timed'})
        self.assertEqual(self.responses()[0]['status'], 3)
        self.assertIs(self.manager.active_timed_effects['timed'][1], effect)
        self.assertEqual(Timed.starts, 1)

    def test_pause_resume_reports_remaining_time(self):
        effect = self.start_timed()
        effect.pause()
        remaining = effect.time_remaining
        response = self.responses()[0]
        self.assertEqual(response['status'], 6)
        self.assertEqual(response['timeRemaining'], round(remaining * 1000))
        for _ in range(3):
            taskMgr.step()
        self.assertEqual(effect.time_remaining, remaining)
        effect.resume()
        self.assertEqual(self.responses()[0]['status'], 7)

    def test_early_stop_undoes_effect_once(self):
        effect = self.start_timed()
        self.send({'id': 2, 'type': 2, 'code': 'timed'})
        self.assertEqual([r['status'] for r in self.responses(2)], [8, 0])
        self.assertFalse(effect.is_running)
        self.assertFalse(taskMgr.hasTaskNamed(effect.task_name))
        self.manager.stop()
        self.assertEqual(Timed.stops, 1)

    def test_disconnect_undoes_effect(self):
        effect = self.start_timed()
        self.peer.close()
        self.step_until(lambda: not self.manager.is_connected)
        self.assertEqual(Timed.stops, 1)
        self.assertFalse(taskMgr.hasTaskNamed(effect.task_name))

    def test_cleanup_exception_is_reported_without_repeating(self):
        Timed.cleanup_error = True
        effect = self.start_timed(duration=100)
        self.assertEqual(self.responses()[0]['status'], 1)
        self.assertEqual(Timed.stops, 1)
        self.assertFalse(effect.is_running)
        self.assertFalse(self.manager.active_timed_effects)

    def test_invalid_duration_is_rejected(self):
        for duration in (0, -1, '1000', True):
            self.send({'id': 1, 'type': 1, 'code': 'timed', 'duration': duration})
            self.assertEqual(self.responses()[0]['status'], 1)
        self.assertEqual(Timed.starts, 0)

    def test_nonblocking_partial_writes_preserve_bytes(self):
        fake = Mock()
        fake.send.side_effect = [3, BlockingIOError(), 3]
        with patch.object(self.manager, 'socket', fake):
            self.manager._send_buffer.extend(b'abcdef')
            self.manager._flush_responses()
            self.assertEqual(self.manager._send_buffer, b'def')
            self.manager._flush_responses()
            self.assertEqual(self.manager._send_buffer, b'def')
            self.manager._flush_responses()
            self.assertFalse(self.manager._send_buffer)
        self.assertEqual([bytes(c.args[0]) for c in fake.send.call_args_list],
                         [b'abcdef', b'def', b'def'])

    def test_refused_connection_never_emits_connected(self):
        self.manager.stop()
        self.events.clear()
        unused = socket.socket()
        unused.bind(('127.0.0.1', 0))
        port = unused.getsockname()[1]
        manager = Panda3DCrowdControlManager(port=port)
        try:
            manager.start()
            # Windows may take several seconds to reject a connection. Allow
            # the manager's full timeout while keeping the unused port reserved.
            self.step_until(lambda: manager.socket is None,
                            timeout=manager.connect_timeout + 2)
            self.assertFalse(manager.is_connected)
            self.assertNotIn(True, self.events)
        finally:
            manager.stop()
            unused.close()

    def test_pending_connection_error_never_emits_connected(self):
        self.manager.stop()
        self.events.clear()
        manager = Panda3DCrowdControlManager()
        fake = Mock()
        fake.connect_ex.return_value = errno.EINPROGRESS
        try:
            with patch('panda3d_crowdcontrol.manager.socket.socket', return_value=fake):
                self.assertTrue(manager.start())
            # Winsock reports a rejected nonblocking connect in the exception set.
            with patch('panda3d_crowdcontrol.manager.select.select',
                       return_value=([], [], [fake])):
                result = manager._socket_task(Mock(done='done', cont='cont'))
            self.assertEqual(result, 'done')
            self.assertIsNone(manager.socket)
            self.assertFalse(manager.is_connected)
            self.assertNotIn(True, self.events)
            fake.close.assert_called_once()
        finally:
            manager.stop()

    def test_pending_connection_timeout(self):
        manager = Panda3DCrowdControlManager()
        fake = Mock()
        fake.connect_ex.return_value = errno.EINPROGRESS
        try:
            with patch('panda3d_crowdcontrol.manager.socket.socket', return_value=fake):
                self.assertTrue(manager.start())
            manager._connect_deadline = time.monotonic() - 1
            with patch('panda3d_crowdcontrol.manager.select.select', return_value=([], [], [])):
                manager._socket_task(Mock(done='done', cont='cont'))
            self.assertIsNone(manager.socket)
            self.assertFalse(manager.is_connected)
        finally:
            manager.stop()

    def test_multiple_managers_do_not_share_timers_or_finish_callbacks(self):
        effect = self.start_timed()
        other = Panda3DCrowdControlManager()
        other_effect = Timed()
        try:
            other_effect.on_start('viewer', [])
            other.active_timed_effects['timed'] = (9, other_effect)
            messenger.send('cc-effect-finished', ['timed'])
            self.assertIn('timed', self.manager.active_timed_effects)
            self.assertIn('timed', other.active_timed_effects)
            self.assertNotEqual(effect.task_name, other_effect.task_name)
            other.stop()
            self.assertTrue(taskMgr.hasTaskNamed(effect.task_name))
        finally:
            other.stop()

    def test_demo_initializes_and_button_tracks_connection(self):
        from panda3d_crowdcontrol import CrowdControlConnectButton
        button = CrowdControlConnectButton(self.manager)
        try:
            self.assertEqual(button['text'], 'Disconnect Crowd Control')
            self.manager.stop()
            self.assertEqual(button['text'], 'Connect Crowd Control')
        finally:
            button.destroy()


if __name__ == '__main__':
    unittest.main()
