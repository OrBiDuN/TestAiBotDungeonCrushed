"""Small persistent catalog. Instance identity uses portrait + expiry, never screen Y."""
import json
import re
import sqlite3
import threading
import time
import uuid
from pathlib import Path
import cv2
import numpy as np


def normalize_name(value):
    value = ' '.join((value or '').strip().lower().split())
    # Only visually identical Latin/Cyrillic glyphs, not edit-distance guessing.
    if re.search('[а-яё]', value):
        value = value.translate(str.maketrans('aceopxykmt', 'асеорхукмт'))
    return value


def feature(image):
    return cv2.resize(image, (64, 16), interpolation=cv2.INTER_AREA).tobytes() if image.size else None


def difference(a, b):
    if not a or not b or len(a) != len(b):
        return 255
    return float(np.abs(np.frombuffer(a, np.uint8).astype(float)-np.frombuffer(b, np.uint8)).mean())


class BossStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.images = self.path.parent / (self.path.stem + '-images')
        self.images.mkdir(exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS boss_catalog (
              id INTEGER PRIMARY KEY, canonical_name TEXT NOT NULL, normalized_name TEXT UNIQUE NOT NULL,
              reward_points INTEGER, max_hp INTEGER, verified INTEGER NOT NULL DEFAULT 0,
              first_seen_at REAL NOT NULL, last_seen_at REAL NOT NULL, source_image_path TEXT,
              review_required INTEGER NOT NULL DEFAULT 0, name_feature BLOB);
            CREATE TABLE IF NOT EXISTS evidence (
              catalog_id INTEGER REFERENCES boss_catalog(id), frame TEXT, observed REAL, points INTEGER,
              PRIMARY KEY(catalog_id, frame));
            CREATE TABLE IF NOT EXISTS boss_instances (
              id TEXT PRIMARY KEY, catalog_id INTEGER REFERENCES boss_catalog(id), scope TEXT, route_id TEXT,
              discovery_order INTEGER, found_at REAL, last_seen_at REAL, status TEXT,
              expiry REAL, portrait BLOB, last_image_path TEXT, name_source TEXT, points_source TEXT);
            CREATE TABLE IF NOT EXISTS history (
              id INTEGER PRIMARY KEY, at REAL, kind TEXT, entity TEXT, detail TEXT);
        ''')
        self.db.commit()
        self.pending = {}
        self.saved_at = {}

    def rows(self, sql, args=()):
        with self.lock:
            return [dict(r) for r in self.db.execute(sql, args)]

    def event(self, kind, entity, detail):
        self.db.execute('INSERT INTO history(at,kind,entity,detail) VALUES(?,?,?,?)',
                        (time.time(), kind, str(entity), json.dumps(detail, ensure_ascii=False)))

    def lookup(self, name, visual=None):
        key = normalize_name(name)
        with self.lock:
            exact = self.db.execute('SELECT * FROM boss_catalog WHERE normalized_name=?', (key,)).fetchone()
            if exact:
                return dict(exact), 'OCR'
            # A visually unchanged name crop can recover an OCR substitution. A similar
            # spelling alone is never sufficient, nor is a shared boss portrait.
            candidates = self.rows('SELECT * FROM boss_catalog WHERE verified=1 AND review_required=0')
            hits = [r for r in candidates if difference(visual, r['name_feature']) < 2.0]
            if len(hits) == 1:
                known = hits[0]['normalized_name']
                if not key or (len(key) == len(known) and sum(a != b for a,b in zip(key,known)) == 1):
                    return hits[0], 'VISUAL_MATCH'
        return None, 'UNKNOWN'

    def save_image(self, key, image):
        path = self.images / (str(key) + '.png')
        ok, data = cv2.imencode('.png', image)
        if not ok:
            raise RuntimeError('Не удалось сохранить изображение карточки.')
        data.tofile(path)
        return str(path)

    def observe_catalog(self, name, points, visual, card_image, frame, observed=None):
        now = time.time() if observed is None else observed
        key = normalize_name(name)
        if not key or not re.fullmatch(r'[а-яёa-z -]{2,80}', key):
            return None
        with self.lock, self.db:
            row, _ = self.lookup(name, visual)
            if row is None:
                cur = self.db.execute('''INSERT INTO boss_catalog(canonical_name,normalized_name,first_seen_at,
                    last_seen_at,name_feature) VALUES(?,?,?,?,?)''', (name.strip(),key,now,now,visual))
                cid = cur.lastrowid
                path = self.save_image('catalog-'+str(cid), card_image)
                self.db.execute('UPDATE boss_catalog SET source_image_path=? WHERE id=?',(path,cid))
            else:
                cid = row['id']
            self.db.execute('UPDATE boss_catalog SET last_seen_at=? WHERE id=?',(now,cid))
            if points is not None:
                self.db.execute('INSERT OR IGNORE INTO evidence VALUES(?,?,?,?)',(cid,str(frame),now,points))
                self.db.execute('DELETE FROM evidence WHERE catalog_id=? AND observed<?',(cid,now-30))
                votes = self.rows('''SELECT points,COUNT(*) n,MAX(observed)-MIN(observed) span FROM evidence
                    WHERE catalog_id=? AND observed>=? GROUP BY points''',(cid,now-30))
                confirmed = [v['points'] for v in votes if v['n'] >= 3 and v['span'] >= 1.5]
                current = self.rows('SELECT * FROM boss_catalog WHERE id=?',(cid,))[0]
                if confirmed:
                    if len(confirmed)>1 or (current['verified'] and confirmed[0]!=current['reward_points']):
                        self.db.execute('UPDATE boss_catalog SET review_required=1 WHERE id=?',(cid,))
                        if not current['review_required']:
                            self.event('CONFLICT',cid,{'confirmed':confirmed,'previous':current['reward_points']})
                    elif not current['review_required']:
                        self.db.execute('UPDATE boss_catalog SET reward_points=?,verified=1 WHERE id=?',(confirmed[0],cid))
            return self.rows('SELECT * FROM boss_catalog WHERE id=?',(cid,))[0]

    def correct(self, cid, name, points):
        if not normalize_name(name) or points <= 0:
            raise ValueError('Укажите имя и положительное число очков.')
        with self.lock, self.db:
            old = self.rows('SELECT canonical_name,reward_points FROM boss_catalog WHERE id=?',(cid,))[0]
            self.db.execute('''UPDATE boss_catalog SET canonical_name=?,normalized_name=?,reward_points=?,
                verified=1,review_required=0 WHERE id=?''',(name.strip(),normalize_name(name),points,cid))
            self.db.execute('DELETE FROM evidence WHERE catalog_id=?',(cid,))
            self.event('MANUAL_CORRECTION',cid,{'before':old,'after':{'name':name,'points':points}})

    def observe_instances(self, rows, scope, route, frame, observed=None):
        now = time.time() if observed is None else observed
        with self.lock, self.db:
            existing = self.rows('SELECT * FROM boss_instances WHERE scope=? AND status<>? AND expiry>=?',(scope,'BOSS_FINISHED',now-6))
            used = set()
            for row in rows:
                if row.get('partial') or row.get('remaining_seconds') is None or not row.get('portrait'):
                    row['identity_status'] = 'UNKNOWN'; continue
                expiry = now + row['remaining_seconds']
                candidates = [r for r in existing if r['id'] not in used and abs(r['expiry']-expiry)<6
                              and difference(r['portrait'],row['portrait'])<5
                              and (not row.get('catalog_id') or not r['catalog_id'] or r['catalog_id']==row['catalog_id'])]
                if len(candidates)>1:
                    row['identity_status']='AMBIGUOUS'; continue
                if candidates:
                    instance = candidates[0]
                else:
                    if any(abs(r['expiry']-expiry)<6 and difference(r['portrait'],row['portrait'])<5 for r in existing):
                        row['identity_status']='AMBIGUOUS'; continue
                    if len(existing)>=4:
                        row['identity_status']='CAPACITY_OR_IDENTITY_UNKNOWN'; continue
                    # Two independent frame observations before creating an encounter.
                    keys = [k for k,v in self.pending.items() if v['scope']==scope and abs(v['expiry']-expiry)<6
                            and difference(v['portrait'],row['portrait'])<5]
                    if len(keys)>1:
                        row['identity_status']='AMBIGUOUS'; continue
                    if not keys:
                        self.pending[uuid.uuid4().hex] = dict(scope=scope,expiry=expiry,portrait=row['portrait'],frame=frame,at=now)
                        row['identity_status']='PENDING'; continue
                    candidate = self.pending[keys[0]]
                    if candidate['frame']==frame or now-candidate['at']<.5:
                        row['identity_status']='PENDING'; continue
                    iid = uuid.uuid4().hex
                    order = self.db.execute('SELECT COALESCE(MAX(discovery_order),0)+1 FROM boss_instances WHERE route_id=?',(route,)).fetchone()[0]
                    self.db.execute('''INSERT INTO boss_instances(id,catalog_id,scope,route_id,discovery_order,found_at,
                        last_seen_at,status,expiry,portrait,name_source,points_source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
                        (iid,row.get('catalog_id'),scope,route,order,now,now,'BOSS_ACTIVE',expiry,row['portrait'],
                         row.get('name_source','UNKNOWN'),row.get('points_source','UNKNOWN')))
                    self.event('DISCOVERED',iid,{'route':route,'order':order,'frame':frame})
                    instance = self.rows('SELECT * FROM boss_instances WHERE id=?',(iid,))[0]
                    existing.append(instance)
                    del self.pending[keys[0]]
                iid=instance['id'];used.add(iid)
                row['instance_id']=iid;row['identity_status']='CONFIRMED'
                if not row.get('catalog_id') and instance['catalog_id']:
                    known=self.rows('SELECT * FROM boss_catalog WHERE id=?',(instance['catalog_id'],))[0]
                    row.update(catalog_id=known['id'],name=known['canonical_name'],name_source='VISUAL_MATCH')
                    if known['verified'] and not known['review_required']:
                        row.update(points=known['reward_points'],points_source='BOSS_CATALOG')
                self.db.execute('''UPDATE boss_instances SET last_seen_at=?,catalog_id=COALESCE(?,catalog_id),
                    name_source=?,points_source=? WHERE id=?''',(now,row.get('catalog_id'),row.get('name_source','UNKNOWN'),row.get('points_source','UNKNOWN'),iid))
                if now-self.saved_at.get(iid,0)>=5 and row.get('card_image') is not None:
                    path=self.save_image('instance-'+iid,row['card_image'])
                    self.db.execute('UPDATE boss_instances SET last_image_path=? WHERE id=?',(path,iid))
                    self.saved_at[iid]=now
            self.pending={k:v for k,v in self.pending.items() if now-v['at']<10}
        return rows

    def set_status(self, iid, status, detail=None):
        if not iid: return
        with self.lock, self.db:
            self.db.execute("UPDATE boss_instances SET status=? WHERE id=? AND status<>'BOSS_FINISHED'",(status,iid))
            self.event(status,iid,detail or {})

    def record_combat(self, route_id, state, detail):
        with self.lock,self.db:self.event(state,'route:'+str(route_id),detail)

    def catalog(self):
        return self.rows('''SELECT c.*,COUNT(i.id) encounters FROM boss_catalog c LEFT JOIN boss_instances i
            ON i.catalog_id=c.id GROUP BY c.id ORDER BY c.id''')

    def instances(self):
        return self.rows('''SELECT i.*,c.canonical_name,c.reward_points,c.verified,c.review_required FROM boss_instances i
            LEFT JOIN boss_catalog c ON c.id=i.catalog_id ORDER BY i.found_at,i.discovery_order''')

    def close(self):
        with self.lock:self.db.close()
