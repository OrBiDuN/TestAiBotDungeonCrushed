"""Physical-pixel calibration tied to one native window, not desktop coordinates."""
from dataclasses import dataclass
import winmouse as win


@dataclass
class GameArea:
    hwnd: int
    owner: tuple
    size: tuple
    dpi: int
    window_title: str
    crop: tuple

    @classmethod
    def create(cls, hwnd, crop):
        l, t, r, b = win.client_rect(hwnd)
        x, y, width, height = crop
        if min(x, y) < 0 or min(width, height) < 10 or x+width > r-l or y+height > b-t:
            raise RuntimeError('Область должна быть внутри снимка окна и не меньше 10×10 пикселей.')
        return cls(hwnd, win.identity(hwnd), (r-l, b-t), win.user32.GetDpiForWindow(hwnd),
                   win.title(hwnd), tuple(crop))

    def rectangle(self):
        if win.identity(self.hwnd) != self.owner or win.user32.IsIconic(self.hwnd):
            raise RuntimeError('Привязанное окно закрыто, заменено или свёрнуто.')
        l, t, r, b = win.client_rect(self.hwnd)
        if (r-l, b-t) != self.size or win.user32.GetDpiForWindow(self.hwnd) != self.dpi:
            raise RuntimeError('Размер окна или DPI изменился. Повторите калибровку игровой области.')
        if win.title(self.hwnd) != self.window_title:
            raise RuntimeError('Заголовок/вкладка изменились. Вернитесь к игре или повторите калибровку.')
        x, y, w, h = self.crop
        return l+x, t+y, w, h

    def relative(self, point):
        l, t, w, h = self.rectangle()
        x, y = point[0]-l, point[1]-t
        if not (0 <= x < w and 0 <= y < h):
            raise RuntimeError('Клик вне откалиброванной игровой области.')
        return x, y

    def absolute(self, point):
        l, t, w, h = self.rectangle()
        x, y = point
        if not (0 <= x < w and 0 <= y < h):
            raise RuntimeError('Относительная точка вне игровой области.')
        return l+x, t+y
