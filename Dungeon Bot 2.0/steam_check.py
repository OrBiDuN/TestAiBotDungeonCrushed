"""Read-only bounded measurement of selected Steam HWND. Leaves stream running."""
import hashlib
import json
import time
from pathlib import Path
import psutil
from PySide6.QtCore import QTimer, Qt


def run(launcher):
    import winmouse as win
    process = psutil.Process()
    process.cpu_percent()
    state = dict(start=time.perf_counter(), first=None, sequence=0, digest=None,
                 changes=0, samples=[], last_sample=0)
    timer = QTimer(launcher)

    def finish(error=None):
        timer.stop()
        l, t, r, b = win.client_rect(launcher.bound) if launcher.bound else (0, 0, 0, 0)
        metrics = launcher.live.snapshot() if launcher.live else {}
        result = dict(pid=win.identity(launcher.bound)[1] if launcher.bound else None,
                      hwnd=launcher.bound, client_size=[r-l, b-t], metrics=metrics,
                      changed_samples=state['changes'], samples=state['samples'], error=error,
                      success=error is None and state['changes'] > 10 and metrics.get('count', 0) > 100)
        Path(__file__).with_name('steam-capture-result.json').write_text(
            json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
        launcher.grab().save(str(Path(__file__).with_name('steam-live-preview.png')))
        launcher.report('Проверка Steam завершена; трансляция оставлена включённой.' if result['success']
                        else f'Проверка Steam: {error or "недостаточно изменяющихся кадров"}')

    def tick():
        now = time.perf_counter()
        if not launcher.live:
            if now-state['start'] > 12:
                finish('Захват не запущен: проверьте наличие Steam-процесса.')
            return
        snap = launcher.live.snapshot()
        if snap['error']:
            finish(snap['error'])
            return
        frame = launcher.latest_video_frame()
        if frame and frame.sequence != state['sequence']:
            state['first'] = state['first'] or now
            state['sequence'] = frame.sequence
            # Read-only pixel test; no OCR or game actions. Only tiny downscaled sample.
            small = frame.image.scaled(96, 64, Qt.IgnoreAspectRatio, Qt.FastTransformation)
            digest = hashlib.sha256(bytes(small.constBits())).hexdigest()
            if state['digest'] and state['digest'] != digest:
                state['changes'] += 1
            state['digest'] = digest
        if now-state['last_sample'] >= 2:
            state['last_sample'] = now
            state['samples'].append(dict(count=snap['count'], fps=snap['fps'],
                                          rss_mb=process.memory_info().rss/2**20,
                                          cpu_one_core_percent=process.cpu_percent()))
        if state['first'] and now-state['first'] > 20:
            finish()
        elif now-state['start'] > 35:
            finish('Не получен устойчивый поток за 35 с.')

    timer.timeout.connect(tick)
    timer.start(50)
