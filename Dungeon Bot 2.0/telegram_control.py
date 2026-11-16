"""Private Telegram remote. Network threads never access Qt or send game input."""
import json
import os
import queue
import secrets
import threading
import time
import urllib.request
import urllib.error
from pathlib import Path

MENU = {'keyboard': [['▶️ Запустить'], ['📷 Экран', '📊 Статистика']],
        'resize_keyboard': True}
MODE_MENU = {'keyboard': [['♾ Бесконечный режим'], ['⏹ Остановить']], 'resize_keyboard': True}
ACTIVE_MENU = {'keyboard': [['⏹ Остановить', '📷 Экран'], ['📊 Статистика']], 'resize_keyboard': True}
SETUP_MENU = {'keyboard': [['🔎 Найти игру', '🔄 Подготовить область'], ['📊 Статус', '⏹ Остановить']],
              'resize_keyboard': True}
WAIT_MENU = {'keyboard': [['⏹ Остановить', '📊 Статус']], 'resize_keyboard': True}
RELOGIN_MENU = {'keyboard': [['🔑 Перезайти'], ['📷 Экран', '📊 Статус'], ['⏹ Остановить']], 'resize_keyboard': True}
for keyboard in (SETUP_MENU, WAIT_MENU, RELOGIN_MENU):
    keyboard['keyboard'].append(['🖥 Восстановить рабочий стол'])
COMMANDS = {'▶️ Запустить': 'run', '⏹ Остановить': 'stop',
            '♾ Бесконечный режим': 'endless', '/endless': 'endless',
            '📊 Статистика': 'status',
            '🖥 Восстановить рабочий стол': 'desktop', '/desktop': 'desktop',
            '🔑 Перезайти': 'relogin', '/relogin': 'relogin',
            '🔎 Найти игру': 'find', '🔄 Подготовить область': 'setup',
            '/find': 'find', '/setup': 'setup',
            '📷 Экран': 'screen', '📊 Статус': 'status',
            '/run': 'run', '/stop': 'stop', '/screen': 'screen', '/status': 'status',
            '/start': 'menu', '/help': 'menu'}


class TelegramAPI:
    def __init__(self, token):
        self.token = token

    def call(self, method, payload, photo=None):
        if photo is None:
            body = json.dumps(payload).encode()
            headers = {'Content-Type': 'application/json'}
        else:
            boundary = secrets.token_hex(24)
            parts = []
            for key, value in payload.items():
                parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
            parts += [f'--{boundary}\r\nContent-Disposition: form-data; name="photo"; filename="game.jpg"\r\nContent-Type: image/jpeg\r\n\r\n'.encode(),
                      photo, f'\r\n--{boundary}--\r\n'.encode()]
            body = b''.join(parts)
            headers = {'Content-Type': f'multipart/form-data; boundary={boundary}'}
        request = urllib.request.Request(f'https://api.telegram.org/bot{self.token}/{method}',
                                         data=body, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                result = json.load(response)
            if not result.get('ok'):
                raise RuntimeError('Telegram отклонил запрос')
            return result['result']
        except urllib.error.HTTPError as exc:
            # Exception URLs contain the secret; never propagate them.
            raise RuntimeError(f'Telegram HTTP {exc.code}') from None
        except Exception:
            raise RuntimeError('Нет ответа Telegram') from None


class TelegramRemote:
    def __init__(self, folder, api=None):
        self.folder = Path(folder)
        self.owner_path = self.folder / '.telegram-owner.json'
        token = os.environ.get('DUNGEON_TELEGRAM_TOKEN', '').strip()
        if not token and (self.folder / '.env.telegram').exists():
            for line in (self.folder / '.env.telegram').read_text(encoding='utf-8-sig').splitlines():
                if line.startswith('DUNGEON_TELEGRAM_TOKEN='):
                    token = line.split('=', 1)[1].strip()
        if api is None and not token:
            raise RuntimeError('Задайте DUNGEON_TELEGRAM_TOKEN в .env.telegram')
        self.api = api or TelegramAPI(token)
        self.owner = None
        if self.owner_path.exists():
            owner = json.loads(self.owner_path.read_text(encoding='utf-8'))
            if not isinstance(owner.get('user'), int) or not isinstance(owner.get('chat'), int):
                raise RuntimeError('Повреждена привязка Telegram')
            self.owner = owner
        self.code = secrets.token_hex(8)
        self.code_expires = time.monotonic() + 600
        self.started_at = time.time()
        self.last_contact = time.monotonic()
        self.connected = False
        self.connection_error = ''
        self.offset = 0
        self.commands = queue.Queue(maxsize=16)
        self.outgoing = queue.Queue(maxsize=20)
        self.stop_requested = threading.Event()
        self.closed = threading.Event()
        self.last_screen = 0
        self.last_notice = {}
        self.lock_file = None

    def start(self):
        # Windows releases this byte lock even if the process crashes.
        import msvcrt
        self.lock_file = (self.folder / '.telegram.lock').open('a+b')
        self.lock_file.seek(0)
        if not self.lock_file.read(1):
            self.lock_file.write(b'0')
            self.lock_file.flush()
        self.lock_file.seek(0)
        try:
            msvcrt.locking(self.lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            self.lock_file.close()
            self.lock_file = None
            raise RuntimeError('Telegram уже подключён в другом Launcher') from None
        self.threads = [threading.Thread(target=self._poll, daemon=True),
                        threading.Thread(target=self._send, daemon=True)]
        for thread in self.threads:
            thread.start()

    def close(self):
        self.closed.set()
        # Lock stays held until in-flight polling exits (no overlapping consumers).
        def release():
            for thread in getattr(self, 'threads', []):
                thread.join()
            if self.lock_file:
                self.lock_file.close()
                self.lock_file = None
        threading.Thread(target=release, daemon=True).start()

    def notify(self, text, photo=None, menu=False):
        if not self.owner or self.closed.is_set():
            return
        payload = {'chat_id': self.owner['chat']}
        payload['caption' if photo is not None else 'text'] = text[:1000 if photo is not None else 4000]
        if menu and photo is None:
            payload['reply_markup'] = menu if isinstance(menu, dict) else MENU
        try:
            self.outgoing.put_nowait((payload, photo, time.monotonic()))
        except queue.Full:
            pass

    def notice(self, text):
        now = time.monotonic()
        if now - self.last_notice.get(text, -1000) < 60:
            return
        if len(self.last_notice) > 100:
            self.last_notice.clear()
        self.last_notice[text] = now
        self.notify(text)

    def accept(self, update):
        uid = update.get('update_id', -1)
        if uid < self.offset:
            return
        self.offset = uid + 1
        message = update.get('message', {})
        chat, sender = message.get('chat', {}), message.get('from', {})
        if chat.get('type') != 'private' or sender.get('is_bot'):
            return
        age = time.time() - message.get('date', 0)
        if age > 30 or age < -10 or message.get('date', 0) < self.started_at:
            return
        text = message.get('text', '').strip()
        if self.owner is None:
            if (time.monotonic() <= self.code_expires and
                    secrets.compare_digest(text.encode('utf-8'), ('/pair ' + self.code).encode('utf-8')) and
                    isinstance(sender.get('id'), int) and isinstance(chat.get('id'), int)):
                owner = {'user': sender['id'], 'chat': chat['id']}
                temporary = self.owner_path.with_suffix('.tmp')
                temporary.write_text(json.dumps(owner), encoding='utf-8')
                temporary.replace(self.owner_path)
                self.owner = owner
                self.code = ''
                self.notify('Владелец привязан. Управление доступно только вам.')
                self.commands.put_nowait(('menu', time.monotonic()))
            return
        if sender.get('id') != self.owner['user'] or chat.get('id') != self.owner['chat']:
            return
        command = COMMANDS.get(text)
        if command == 'stop':
            self.stop_requested.set()
            return
        if command is None:
            command = 'menu'
        if self.stop_requested.is_set():
            return
        if command == 'screen':
            if time.monotonic() - self.last_screen < 3:
                return
            self.last_screen = time.monotonic()
        try:
            self.commands.put_nowait((command, time.monotonic()))
        except queue.Full:
            self.notice('Очередь команд заполнена. СТОП остаётся доступен.')

    def next_command(self):
        if self.stop_requested.is_set():
            while True:
                try:
                    self.commands.get_nowait()
                except queue.Empty:
                    break
            self.stop_requested.clear()
            return 'stop'
        try:
            command, received = self.commands.get_nowait()
            return command if time.monotonic() - received < 10 else None
        except queue.Empty:
            return None

    def _poll(self):
        delay = 1
        while not self.closed.is_set():
            try:
                updates = self.api.call('getUpdates', {'offset': self.offset, 'timeout': 10,
                                                     'allowed_updates': ['message']})
                if self.closed.is_set():
                    break
                self.last_contact = time.monotonic()
                self.connected = True
                self.connection_error = ''
                delay = 1
                for update in updates:
                    self.accept(update)
            except Exception:
                self.connected = False
                self.connection_error = 'Нет связи; проверьте сеть, токен и отсутствие webhook/другого бота.'
                self.closed.wait(delay)
                delay = min(delay * 2, 15)

    def _send(self):
        while not self.closed.is_set():
            try:
                payload, photo, created = self.outgoing.get(timeout=.5)
            except queue.Empty:
                continue
            for attempt in range(3):
                if self.closed.is_set() or time.monotonic() - created > 60:
                    break
                try:
                    self.api.call('sendPhoto' if photo is not None else 'sendMessage', payload, photo)
                    break
                except Exception:
                    self.closed.wait(2 ** attempt)
