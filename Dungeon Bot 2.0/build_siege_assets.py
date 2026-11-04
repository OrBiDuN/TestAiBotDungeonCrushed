"""Extract button references from the user's five supplied screenshots."""
from pathlib import Path
import cv2
import numpy as np

ROOT = Path(__file__).parent
FILES = [
 '5192f376-f4ef-432e-87c2-79f4b594f58b',
 'd1dc1914-9b7a-40d8-9fe6-2d1031f36e38',
 '6e25461f-b59f-4819-9b7d-3633aebbe189',
 '93b97a85-93dd-4786-8666-41d1f0826c80',
 'e5b8ab82-6750-4e13-9233-60d2932aa0b8',
 'fd8f757d-abd5-4ad1-8dec-d253b487dde9',
 'b310d67e-2c9b-4f07-93fb-d89a367c036a']


def read_reference(index):
    p = ROOT / 'tests' / 'fixtures' / f'codex-clipboard-{FILES[index]}.png'
    image = cv2.imdecode(np.fromfile(p, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError(f'Cannot decode reference fixture: {p}')
    return image


if __name__ == '__main__':
    folder = ROOT / 'assets' / 'siege'
    folder.mkdir(parents=True, exist_ok=True)
    specs = dict(home=(0, (681, 643, 41, 69)), ranking=(1, (984, 979, 168, 42)),
                 track=(2, (847, 300, 209, 34)), card=(3, (1080, 402, 120, 28)),
                 normal=(4, (733, 892, 190, 31)), all=(4, (997, 892, 190, 31)),
                 battle_close=(5,(1852,21,65,62)), battle_turn=(5,(80,16,62,28)),
                 boss_done=(6,(114,831,403,29)), boss_back=(6,(242,987,147,30)))
    for name, (i, (x, y, w, h)) in specs.items():
        pixels = read_reference(i)
        cv2.imencode('.png', pixels[y:y+h, x:x+w])[1].tofile(folder / f'{name}.png')
