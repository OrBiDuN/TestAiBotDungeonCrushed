"""Bounded real WGC integration benchmark against our own animated Qt window."""
import hashlib
import json
import time
from pathlib import Path

import psutil
from PySide6.QtCore import QTimer, Qt
import winmouse as win


def run(app, launcher):
    process = psutil.Process()
    process.cpu_percent()
    data = dict(checks=[], samples=[], distinct_frame_changes=0, gui_ticks=0, max_gui_gap_ms=0)
    state = dict(phase='initial', since=time.perf_counter(), sequence=0, digest=None,
                 sample=0, last_tick=time.perf_counter(), cpu_start=time.process_time())
    timer = QTimer(launcher)

    def require(ok, label):
        if not ok:
            raise AssertionError(label)
        data['checks'].append(label)

    def change_phase(name):
        state.update(phase=name, since=time.perf_counter(), sequence=0)

    def finish(success, error=None):
        timer.stop()
        data.update(success=success, error=error)
        Path(__file__).with_name('live-benchmark.json').write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
        launcher.stop_live()
        # closeEvent asynchronously joins via GUI polling, never destroy a running QThread.
        launcher.close()

    def tick():
        now = time.perf_counter()
        data['max_gui_gap_ms'] = max(data['max_gui_gap_ms'], (now-state['last_tick'])*1000)
        state['last_tick'] = now
        data['gui_ticks'] += 1
        try:
            if not launcher.live:
                return
            snap = launcher.live.snapshot()
            frame = launcher.latest_video_frame()
            phase = state['phase']
            if frame and frame.sequence != state['sequence']:
                state['sequence'] = frame.sequence
                small = frame.image.scaled(64, 48, Qt.IgnoreAspectRatio, Qt.FastTransformation)
                digest = hashlib.sha256(bytes(small.constBits())).hexdigest()
                if state['digest'] is not None and digest != state['digest']:
                    data['distinct_frame_changes'] += 1
                state['digest'] = digest
            if now-state['sample'] >= 2:
                state['sample'] = now
                data['samples'].append(dict(phase=phase, count=snap['count'], fps=snap['fps'],
                                            rss_mb=process.memory_info().rss/2**20,
                                            cpu_one_core_percent=process.cpu_percent()))
            if phase == 'initial':
                if snap['error']:
                    raise RuntimeError(snap['error'])
                if frame:
                    change_phase('stream')
                elif now-state['since'] > 12:
                    raise RuntimeError('No real WGC frames within 12 seconds')
            elif phase == 'stream':
                if snap['error']:
                    raise RuntimeError(snap['error'])
                if now-state['since'] > 30:
                    require(snap['count'] > 250, 'Continuous WGC frames received')
                    require(data['distinct_frame_changes'] > 150, 'Pixels changed across consecutive captured frames')
                    require(snap['fps'] >= 10, 'Actual FPS >= 10')
                    require(launcher.live_sequence > 250, 'Launcher actually consumed live frames')
                    data['first_session'] = snap
                    data['cpu_seconds'] = time.process_time()-state['cpu_start']
                    launcher.grab().save(str(Path(__file__).with_name('live-preview.png')))
                    launcher.stop_live()
                    change_phase('stopping')
            elif phase == 'stopping':
                if not launcher.live.isRunning():
                    require(launcher.latest_video_frame() is None, 'Stop released latest frame and native session')
                    l, t, r, b = win.client_rect(launcher.bound)
                    launcher.set_area((20, 20, r-l-40, b-t-40))
                    launcher.fps_choice.setCurrentText('10')
                    launcher.start_live()
                    change_phase('restart_crop')
                elif now-state['since'] > 5:
                    raise RuntimeError('Stop timeout')
            elif phase == 'restart_crop':
                if snap['error']:
                    raise RuntimeError(snap['error'])
                if frame and snap['count'] > 35:
                    require((frame.image.width(), frame.image.height()) == launcher.area.crop[2:],
                            'Restart delivers calibrated game-area crop')
                    data['second_session'] = snap
                    launcher.demo_window.move(launcher.demo_window.x()+70, launcher.demo_window.y()+30)
                    change_phase('moving')
                elif now-state['since'] > 12:
                    raise RuntimeError('Restart did not deliver frames')
            elif phase == 'moving':
                if snap['error']:
                    raise RuntimeError(snap['error'])
                if now-state['since'] > 3:
                    require(snap['count'] > data['second_session']['count']+15,
                            'Capture continued after window movement')
                    launcher.demo_window.resize(700, 440)
                    change_phase('resize_crop')
            elif phase == 'resize_crop':
                if not launcher.live.isRunning():
                    require(snap['error'] and 'Размер' in snap['error'], 'Resize stops stale calibration with exact reason')
                    launcher.area = None  # Full-window mode follows resize automatically.
                    launcher.start_live()
                    change_phase('resize_full')
                elif now-state['since'] > 5:
                    raise RuntimeError('Resize failed to stop calibrated capture')
            elif phase == 'resize_full':
                if snap['error']:
                    raise RuntimeError(snap['error'])
                if snap['count'] > 15:
                    state['old_size'] = (frame.image.width(), frame.image.height())
                    launcher.demo_window.resize(760, 480)
                    change_phase('full_changed')
                elif now-state['since'] > 10:
                    raise RuntimeError('Third session failed to start')
            elif phase == 'full_changed':
                if snap['error']:
                    raise RuntimeError(snap['error'])
                if frame and (frame.image.width(), frame.image.height()) != state['old_size']:
                    require(True, 'Uncalibrated full-window capture follows real resize')
                    data['third_session'] = snap
                    launcher.demo_window.showMinimized()
                    change_phase('minimized')
                elif now-state['since'] > 8:
                    raise RuntimeError('Resized WGC frame never arrived')
            elif phase == 'minimized':
                if now-state['since'] > 2:
                    require('Пауза' in snap['state'] and launcher.live.isRunning(), 'Minimize pauses without killing session')
                    launcher.demo_window.showNormal()
                    state['before_restore'] = snap['count']
                    change_phase('restored')
            elif phase == 'restored':
                if snap['count'] > state['before_restore']+10:
                    require(True, 'Restoring window resumes live frames')
                    warm = [s['rss_mb'] for s in data['samples'] if s['phase'] == 'stream'][3:]
                    data['steady_rss_range_mb'] = max(warm)-min(warm) if warm else None
                    require(data['max_gui_gap_ms'] < 1500, 'GUI heartbeat remained responsive')
                    finish(True)
                elif now-state['since'] > 8:
                    raise RuntimeError('Restore did not resume capture')
        except Exception as exc:
            finish(False, str(exc))

    timer.timeout.connect(tick)
    timer.start(50)
