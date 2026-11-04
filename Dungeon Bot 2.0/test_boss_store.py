"""Real Windows OCR on supplied frames; database is isolated from the user's catalog."""
import tempfile
import unittest
from pathlib import Path
import cv2
import numpy as np
from boss_store import BossStore,feature
from bossocr import BossReader,name_patch
from cardvision import CardDetector

ROOT=Path(__file__).parent/'tests'/'fixtures'

class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=BossStore(Path(self.tmp.name)/'bosses.db')
        self.reader=BossReader(self.store)
        self.images=[cv2.imdecode(np.fromfile(ROOT/f'codex-clipboard-{name}.png',np.uint8),1) for name in (
            'e6054eaf-6dc6-4750-b541-3c29ec305967','dc4ac507-5722-4322-83c6-a61820fe1fbe')]
        self.calls=[]
        original=self.reader.text
        async def counted(image,numeric=False):
            self.calls.append((image.shape,numeric))
            return await original(image,numeric)
        self.reader.text=counted

    def tearDown(self):
        self.store.close();self.tmp.cleanup()

    def read(self,frame,now=1000,image=None):
        image=self.images[0] if image is None else image
        rows=self.reader.read(image,CardDetector().detect(image),frame,now)
        return self.store.observe_instances(rows,'test-window','test-route',frame,now)

    def train(self):
        for i in range(3):rows=self.read(str(i),1000+i)
        return rows

    def test_full_ocr_then_catalog_without_points_ocr(self):
        rows=self.train()
        self.assertEqual([(r['name'],r['points']) for r in rows],[('Лаксир',2445),('Лаксир',2445),('Озехн',1785)])
        self.assertEqual(len(self.store.catalog()),2)
        self.assertTrue(all(r['verified'] for r in self.store.catalog()))
        self.calls.clear();rows=self.read('known',1003)
        self.assertEqual(len(self.calls),6)  # name + encounter timer, never points
        self.assertTrue(all(r['points_source']=='BOSS_CATALOG' for r in rows))
        self.assertTrue(all(r['raw_points']==[] for r in rows))

    def test_duplicate_types_are_distinct_instances_and_repeat_frames_are_not(self):
        self.train()
        instances=self.store.instances()
        self.assertEqual(len(instances),3)
        self.assertEqual(instances[0]['catalog_id'],instances[1]['catalog_id'])
        self.assertNotEqual(instances[0]['id'],instances[1]['id'])
        self.read('repeat',1003)
        self.assertEqual(len(self.store.instances()),3)

    def test_unknown_points_are_filled_without_reading_blank_patch(self):
        self.train();image=self.images[0].copy()
        for card in CardDetector().detect(image):
            x,y=card['anchor'];image[y-125:y-80,max(0,x-128):x+30]=0
        self.calls.clear();rows=self.read('blank',1003,image)
        self.assertEqual([r['points'] for r in rows],[2445,2445,1785])
        self.assertTrue(all(r['raw_points']==[] for r in rows))

    def test_one_letter_error_requires_visual_evidence_and_similar_names_do_not_merge(self):
        self.train();card=CardDetector().detect(self.images[0])[0]
        visual=feature(name_patch(self.images[0],card['anchor']))
        known,source=self.store.lookup('Лаксиp',visual)
        self.assertEqual(known['canonical_name'],'Лаксир')
        known,source=self.store.lookup('Лаксиа',visual)
        self.assertEqual(source,'VISUAL_MATCH')
        self.assertIsNone(self.store.lookup('Лаксиа',bytes(len(visual)))[0])
        self.assertIsNone(self.store.lookup('Лаксиа')[0])

    def test_scroll_and_disappearance_keep_identity_and_unknown_name(self):
        self.train();ids=[r['id'] for r in self.store.instances()]
        # Second actual screenshot was taken nine seconds later: timers and Y changed.
        rows=self.read('scrolled',1009,self.images[1])
        self.assertEqual([r['instance_id'] for r in rows[:3]],ids)
        blank=np.zeros_like(self.images[0]);self.read('missing',1010,blank)
        self.assertEqual([r['id'] for r in self.store.instances()],ids)
        image=self.images[1].copy()
        for card in CardDetector().detect(image):
            if not card['partial']:
                x,y=card['anchor'];image[y-170:y-125,max(0,x-235):x+110]=0
        rows=self.read('unknown-name',1010,image)
        self.assertEqual([r['instance_id'] for r in rows[:3]],ids)
        self.assertEqual([r['name'] for r in rows[:3]],['Лаксир','Лаксир','Озехн'])

    def test_conflict_preserves_reference_and_manual_correction_history(self):
        rows=self.train();r=rows[0];card=CardDetector().detect(self.images[0])[0]
        # Confirmed evidence from the other real card; ingestion must flag the
        # inconsistent association, never silently change the reference.
        other=rows[2]['points'];visual=feature(name_patch(self.images[0],card['anchor']))
        for i in range(3):self.store.observe_catalog(r['name'],other,visual,r['card_image'],'conflict'+str(i),1010+i)
        known,_=self.store.lookup('Лаксир')
        self.assertEqual(known['reward_points'],2445);self.assertEqual(known['review_required'],1)
        self.store.correct(known['id'],'Лаксир',2445)
        self.assertEqual(len(self.store.instances()),3)
        self.assertTrue(self.store.rows("SELECT * FROM history WHERE kind='MANUAL_CORRECTION'"))

    def test_completed_result_survives_reopen_and_new_encounter(self):
        rows=self.train();iid=rows[0]['instance_id']
        self.store.set_status(iid,'BOSS_FINISHED',{'confirmed':'result_screen'})
        self.store.close();self.store=BossStore(Path(self.tmp.name)/'bosses.db')
        self.reader=BossReader(self.store)
        self.assertEqual(self.store.instances()[0]['status'],'BOSS_FINISHED')
        self.read('new1',3000);self.read('new2',3001)
        self.assertEqual(len(self.store.instances()),6)
        self.assertEqual(len(self.store.catalog()),2)

    def test_same_frame_cannot_verify_catalog_or_instance(self):
        for i in range(4):self.read('same',1000)
        self.assertFalse(any(r['verified'] for r in self.store.catalog()))
        self.assertEqual(self.store.instances(),[])

    def test_fourth_confirmed_card_and_capacity(self):
        self.train()
        # Use an existing real card as a later encounter, with its real timer.
        # There are still only three simultaneous fully visible cards.
        image=self.images[1].copy()
        cards=CardDetector().detect(image)
        rows=self.reader.read(image,[cards[0]],'fourth1',1100)
        self.store.observe_instances(rows,'test-window','fourth-route','fourth1',1100)
        rows=self.reader.read(image,[cards[0]],'fourth2',1101)
        self.store.observe_instances(rows,'test-window','fourth-route','fourth2',1101)
        self.assertEqual(len(self.store.instances()),4)
        rows=self.reader.read(image,[cards[1]],'excess',1102)
        self.store.observe_instances(rows,'test-window','fourth-route','excess',1102)
        self.assertEqual(len(self.store.instances()),4)

    def test_real_completion_image_and_wrong_portrait_guard(self):
        from types import SimpleNamespace
        from bosscombat import CombatCycle
        from build_siege_assets import read_reference
        rows=self.train();card=CardDetector().detect(self.images[0])[2];x,y=card['anchor']
        portrait=self.images[0][y-150:y-55,x-350:x-260]
        route=SimpleNamespace(ui=SimpleNamespace(boss_store=self.store),selected_instance=rows[2]['instance_id'],
                              selected_portrait=portrait,run_id='test')
        cycle=CombatCycle(route)
        done=np.zeros((1080,1920,3),np.uint8);fixture=read_reference(6)
        done[:fixture.shape[0],640:640+fixture.shape[1]]=fixture
        cycle.check_identity(done)
        cycle.state_changed('BOSS_FINISHED')
        self.assertEqual(self.store.instances()[2]['status'],'BOSS_FINISHED')
        cycle=CombatCycle(route)
        with self.assertRaises(RuntimeError):cycle.check_identity(read_reference(4))
        self.assertEqual(self.store.instances()[2]['status'],'BOSS_FINISHED')

    def test_panel_shows_linked_correction_without_losing_instances(self):
        from PySide6.QtWidgets import QApplication
        from boss_panel import BossPanel
        app=QApplication.instance() or QApplication([])
        self.train();panel=BossPanel(self.store)
        self.assertEqual(panel.tables[0].rowCount(),2)
        self.assertEqual(panel.tables[1].rowCount(),3)
        cid=self.store.catalog()[0]['id']
        self.store.correct(cid,'Лаксир',2445)
        panel.refresh()
        self.assertEqual(panel.tables[1].item(0,3).text(),'2445')
        self.assertEqual(panel.tables[1].item(1,3).text(),'2445')
        panel.close();panel.timer.stop()

if __name__=='__main__':unittest.main()
