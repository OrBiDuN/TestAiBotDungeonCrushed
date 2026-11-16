"""Recognize the other-device login dialog and perform one verified click."""
import asyncio
import re
import time
import cv2
from siege import SiegeRoute, pixels
import winmouse as win


def normalize(text):
    return ' '.join(re.findall(r'[а-яёa-z]+', text.lower()))


def parse_dialog(lines, image):
    text = normalize(' '.join(line['text'] for line in lines))
    if not all(part in text for part in ('другого устройства', 'вам нужно', 'перезайти')):
        return None
    def red_button(line):
        x, y, w, h = (int(v) for v in line['rect'])
        patch = image[max(0,y-5):y+h+5, max(0,x-10):x+w+10]
        if not patch.size:
            return False
        hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
        red = ((hsv[:,:,0] < 12) | (hsv[:,:,0] > 170)) & (hsv[:,:,1] > 120) & (hsv[:,:,2] > 65)
        return red.mean() > .25
    buttons = [line for line in lines if normalize(line['text']) == 'перезайти' and red_button(line)]
    if len(buttons) != 1:
        return None
    x, y, w, h = buttons[0]['rect']
    ih, iw = image.shape[:2]
    x, y, w, h = int(x), int(y), int(w), int(h)
    if w < 20 or h < 8 or x < 0 or y < 0 or x+w > iw or y+h > ih:
        return None
    # Match the actual lettering again immediately before input, not a fixed point.
    return {'point': (x+w//2, y+h//2), 'rect': (x, y, w, h),
            'template': image[y:y+h, x:x+w].copy()}


async def detect_async(image):
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.globalization import Language
    from winrt.windows.graphics.imaging import SoftwareBitmap, BitmapPixelFormat, BitmapAlphaMode
    from winrt.windows.storage.streams import Buffer
    engine = OcrEngine.try_create_from_language(Language('ru'))
    if engine is None:
        raise RuntimeError('Русский Windows OCR недоступен')
    scale = min(1., 1600 / max(image.shape[:2]))
    small = cv2.resize(image, None, fx=scale, fy=scale) if scale < 1 else image
    bgra = cv2.cvtColor(small, cv2.COLOR_BGR2BGRA)
    data = bgra.tobytes()
    buffer = Buffer(len(data))
    buffer.length = len(data)
    memoryview(buffer)[:] = data
    bitmap = SoftwareBitmap.create_copy_from_buffer(buffer, BitmapPixelFormat.BGRA8,
              bgra.shape[1], bgra.shape[0], BitmapAlphaMode.IGNORE)
    try:
        result = await engine.recognize_async(bitmap)
        lines = []
        for line in result.lines:
            boxes = [word.bounding_rect for word in line.words]
            if not boxes:
                continue
            x, y = min(b.x for b in boxes), min(b.y for b in boxes)
            right, bottom = max(b.x+b.width for b in boxes), max(b.y+b.height for b in boxes)
            lines.append({'text': line.text, 'rect': (x/scale, y/scale, (right-x)/scale, (bottom-y)/scale)})
        return parse_dialog(lines, image)
    finally:
        bitmap.close()


def detect(image):
    return asyncio.run(detect_async(image))


def still_matches(image, match):
    x, y, w, h = match['rect']
    patch = image[y:y+h, x:x+w]
    template = match['template']
    return (patch.shape == template.shape and patch.size > 0 and
            float(cv2.matchTemplate(patch, template, cv2.TM_CCOEFF_NORMED)[0, 0]) >= .95)


class ReloginRoute(SiegeRoute):
    def start_relogin(self):
        super().start(True)
        self.log('Перезаход: ожидаю свежее подтверждение кнопки.')
        self.sent = False
        self.succeeded = False
        self.absent = 0
        self.last_checked = -1

    def pre_click_relogin(self, match):
        if not still_matches(pixels(self.frame().image), match):
            raise RuntimeError('Кнопка «Перезайти» изменилась. Нажатие отменено.')
        if self.sent:
            raise RuntimeError('Повторное нажатие запрещено.')
        self.sent = True

    def tick(self):
        if not self.active:
            return
        try:
            if win.user32.GetAsyncKeyState(0x1B) & 0x8000:
                self.ui.stop()
                return
            now = time.monotonic()
            if self.wait_for_video():
                return
            if self.phase == 'wake':
                if not self.wake.poll():
                    return
                frame = self.ui.latest_video_frame()
                if not frame or frame.received < self.wake.ready_at:
                    if time.perf_counter()-self.wake.started > 8:
                        raise RuntimeError('Нет кадра после пробуждения окна.')
                    return
                self.phase = 'find'
                self.deadline = now + 8
            frame = self.frame()
            observation = getattr(self.ui.vision, 'relogin_result', None)
            fresh = observation and time.perf_counter()-observation['received'] < 2
            if self.phase == 'find':
                match = observation.get('match') if fresh else None
                if match and observation['received'] >= self.wake.ready_at and still_matches(pixels(frame.image), match):
                    self.ui.relative_point = match['point']
                    self.ui.point = self.area.absolute(match['point'])
                    self.ui.begin(True, from_route=True, fast=True)
                    self.ui.operation['check_before_click'] = lambda: self.pre_click_relogin(match)
                    self.phase = 'click'
                elif now > self.deadline:
                    raise RuntimeError('Кнопка «Перезайти» не подтверждена на свежем кадре.')
            elif self.phase == 'click' and self.ui.operation is None:
                self.after_click = time.perf_counter()
                self.phase = 'confirm'
                self.deadline = now + 20
            elif self.phase == 'confirm':
                if fresh and observation['received'] > self.after_click and observation['sequence'] != self.last_checked:
                    self.last_checked = observation['sequence']
                    self.absent = self.absent + 1 if observation.get('match') is None and not observation.get('error') else 0
                    if self.absent >= 2:
                        self.ui.relogin_required = False
                        self.succeeded = True
                        self.cancel('Окно перезахода исчезло. Ожидаю загрузки игры.')
                        return
                if now > self.deadline:
                    self.cancel('Перезаход: нажатие отправлено, исчезновение окна не подтверждено. Повтора нет.')
        except Exception as exc:
            self.cancel(f'Ошибка перезахода: {exc}')
            self.ui.cancel()
