"""Visible siege rows, including a fourth portrait peeking above the footer."""
from pathlib import Path
import cv2
import numpy as np

class CardDetector:
    def __init__(self):
        root=Path(__file__).parent/'assets'/'siege'
        self.attack=cv2.imdecode(np.fromfile(root/'card.png',np.uint8),1)
        self.crest=cv2.imdecode(np.fromfile(root/'card_crest.png',np.uint8),1)

    @staticmethod
    def hits(image, template, threshold):
        result=cv2.matchTemplate(image,template,cv2.TM_CCOEFF_NORMED)
        hits=[]
        for _ in range(8):
            _,score,_,(x,y)=cv2.minMaxLoc(result)
            if score<threshold: break
            h,w=template.shape[:2]
            error=float(np.mean(np.abs(image[y:y+h,x:x+w].astype(np.float32)-template)))
            if error<28: hits.append((x,y,score))
            result[max(0,y-45):y+46,:]=-1
        return sorted(hits,key=lambda p:p[1])

    def detect(self,image):
        h,w=image.shape[:2]
        if not (1020<=h<=1120 and (550<=w<=610 or 1850<=w<=1950)):
            return []
        x0=680 if w>1000 else 0
        x1=min(w,x0+560)
        top=210
        roi=image[top:h-140,x0:x1]
        hits=self.hits(roi,self.attack,.90)
        cards=[]
        for x,y,score in hits[:4]:
            x,y=x+x0,y+top
            cards.append({'rect':(max(x0,x-380),max(top,y-175),min(530,x1-max(x0,x-380)),min(215,h-140-max(top,y-175))),
                          'attack':(x+self.attack.shape[1]//2,y+self.attack.shape[0]//2),
                          'anchor':(x,y), 'partial':y-175<top})
        # Only accept the partial fourth row aligned with three proven attack rows.
        if len(cards)==3:
            last_bottom=hits[-1][1]+top+self.attack.shape[0]
            for x,y,score in self.hits(roi,self.crest,.85):
                x,y=x+x0,y+top
                if 10<y-last_bottom<100 and abs(x-(cards[-1]['rect'][0]+40))<30:
                    bottom=h-140
                    cards.append({'rect':(cards[-1]['rect'][0],y-8,cards[-1]['rect'][2],max(8,bottom-y+8)), 'partial':True})
                    break
        return cards
