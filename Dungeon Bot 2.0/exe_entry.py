"""Windowed distribution entry point, with an offline packaging smoke check."""
import json
import sys
import traceback
from app_paths import APP_DIR


def smoke_check():
    import windows_capture
    from bossocr import BossReader
    from cardvision import CardDetector
    from siege import ButtonMatcher
    from launcher import Launcher
    from PySide6.QtWidgets import QApplication
    app = QApplication([])
    window = Launcher()
    try:
        matcher = ButtonMatcher()
        assert all(image is not None and image.size for image in matcher.templates.values())
        CardDetector()
        BossReader()
        result = {'ok': True, 'frozen': bool(getattr(sys, 'frozen', False)),
                  'templates': len(matcher.templates), 'ocr': 'ru',
                  'capture_import': bool(windows_capture), 'gui': window.windowTitle(),
                  'data_directory': str(APP_DIR)}
        (APP_DIR / 'exe-smoke-result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    finally:
        window.close()


if __name__ == '__main__':
    try:
        if '--build-smoke-test' in sys.argv:
            smoke_check()
        else:
            from launcher import main
            if '--telegram' not in sys.argv:
                sys.argv.append('--telegram')
            sys.exit(main())
    except Exception:
        (APP_DIR / 'exe-startup-error.log').write_text(traceback.format_exc(), encoding='utf-8')
        raise
