"""Local Windows OCR, called only by the vision worker, at most once a second."""
import asyncio
import re
import hashlib
import time
import uuid
import cv2
from winrt.windows.media.ocr import OcrEngine
from winrt.windows.globalization import Language
from winrt.windows.graphics.imaging import SoftwareBitmap, BitmapPixelFormat, BitmapAlphaMode
from winrt.windows.storage.streams import Buffer


def name_patch(image, anchor):
    x,y=anchor
    return image[max(0,y-170):y-125,max(0,x-235):x+110]


def fingerprint(image, anchor):
    return hashlib.sha256(name_patch(image,anchor).tobytes()).hexdigest()


def agree_points(readings):
    """Never invent a missing leading digit or select the larger OCR guess."""
    values = set()
    for reading in readings:
        text = reading.strip()
        if re.fullmatch(r'[0-9]{1,7}', text):
            value = int(text)
            if value > 0:
                values.add(value)
    return next(iter(values)) if len(values) == 1 else None


def remaining_seconds(text):
    minutes=re.search(r'(\d{1,2})\s*[мm]',text.lower())
    seconds=re.search(r'(\d{1,2})\s*[сc]',text.lower())
    return int(minutes[1])*60+int(seconds[1]) if minutes and seconds and int(seconds[1])<60 else None


class BossReader:
    def __init__(self, store=None):
        self.store=store
        self.engine=OcrEngine.try_create_from_language(Language('ru'))
        if self.engine is None:
            raise RuntimeError('Русский язык Windows OCR не установлен.')

    async def text(self, image, numeric=False):
        if not image.size: return ''
        hsv=cv2.cvtColor(image,cv2.COLOR_BGR2HSV)
        mask=cv2.inRange(hsv,(0,0,210 if numeric else 165),(180,90 if numeric else 110,255))
        image=cv2.cvtColor(255-mask,cv2.COLOR_GRAY2BGR)
        image=cv2.copyMakeBorder(image,20,20,20,20,cv2.BORDER_CONSTANT,value=(255,255,255))
        image=cv2.resize(image,None,fx=2,fy=2,interpolation=cv2.INTER_CUBIC)
        bgra=cv2.cvtColor(image,cv2.COLOR_BGR2BGRA)
        data=bgra.tobytes()
        buffer=Buffer(len(data))
        buffer.length=len(data)
        memoryview(buffer)[:]=data
        bitmap=SoftwareBitmap.create_copy_from_buffer(buffer,BitmapPixelFormat.BGRA8,bgra.shape[1],bgra.shape[0],BitmapAlphaMode.IGNORE)
        try:
            result=await self.engine.recognize_async(bitmap)
            return result.text.strip()
        finally:
            bitmap.close()

    async def read_async(self,image,cards,frame=None,observed=None):
        from boss_store import feature
        frame=frame or uuid.uuid4().hex
        observed=time.time() if observed is None else observed
        rows=[]
        for index,card in enumerate(cards,1):
            row={'order':index,'partial':card['partial'],'name':None,'points':None,'attack':card.get('attack')}
            if not card['partial'] and card.get('anchor'):
                x,y=card['anchor']
                name=await self.text(name_patch(image,(x,y)))
                visual=feature(name_patch(image,(x,y)))
                rx,ry,rw,rh=card['rect']
                card_image=image[ry:ry+rh,rx:rx+rw].copy()
                known,source=self.store.lookup(name,visual) if self.store else (None,'OCR')
                readings=[]
                # A wider crop includes a leading digit clipped by layout shifts.
                # Keep the old crop too: the coin edge can confuse wide-crop OCR.
                if not known or not known['verified'] or known['review_required']:
                    for left in (115,128):
                        patch=image[y-125:y-80,max(0,x-left):x+30]
                        for numeric in (True,False):
                            readings.append(await self.text(patch,numeric=numeric))
                row.update(name=name or None,raw_points=readings,
                           points=agree_points(readings),fingerprint=fingerprint(image,(x,y)))
                row.update(name_source='OCR' if name else 'UNKNOWN',points_source='OCR' if row['points'] else 'UNKNOWN')
                if self.store:
                    known=self.store.observe_catalog(known['canonical_name'] if known else name,row['points'],visual,card_image,frame,observed)
                    if known:
                        row.update(catalog_id=known['id'],name=known['canonical_name'],name_source=source if source!='UNKNOWN' else 'OCR')
                        if known['verified'] and not known['review_required']:
                            row.update(points=known['reward_points'],points_source='BOSS_CATALOG')
                    # Remaining duration is used only to distinguish encounters, never
                    # stored as a permanent boss characteristic. No HP recognition.
                    timer=await self.text(image[y-100:y-65,max(0,x-235):x+80])
                    duration=remaining_seconds(timer)
                    row.update(remaining_seconds=duration,timer_raw=timer,card_image=card_image,
                               portrait=feature(image[y-150:y-55,max(0,x-350):max(0,x-260)]))
                row['valid']=bool(name and re.search('[А-Яа-яЁё]',name) and row['points'])
            rows.append(row)
        return rows

    def read(self,image,cards,frame=None,observed=None):
        return asyncio.run(self.read_async(image,cards,frame,observed))
