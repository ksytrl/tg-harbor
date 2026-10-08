"""TG Harbor: a local desktop Telegram media manager.

All HTTP routes are loopback-only and capability protected. Telegram access is
performed on one dedicated asyncio loop. The demo is a separate local provider.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import ctypes
import io
import json
import mimetypes
import os
import re
import secrets
import shutil
import sqlite3
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

VERSION = '1.0.0'
CHUNK = 512 * 1024
RESOURCES = Path(getattr(sys, '_MEIPASS', Path(__file__).parent))
WEB = RESOURCES / 'web'
STATUS_ACTIVE = ('queued', 'resolving', 'downloading', 'waiting')


class AppError(Exception):
    pass


class Interrupted(Exception):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_name(value: str, fallback: str = 'media') -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', str(value)).strip(' .')
    if not value:
        value = fallback
    if re.match(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)', value, re.I):
        value = '_' + value
    if len(value) > 150:
        suffix = Path(value).suffix[:16]
        value = value[:150 - len(suffix)] + suffix
    return value


def parse_link(value: str) -> tuple[str | int, int]:
    raw = value.strip()
    if not raw.startswith(('https://', 'http://')):
        raw = 'https://' + raw
    parsed = urlparse(raw)
    if parsed.hostname not in ('t.me', 'telegram.me', 'www.t.me') or parsed.username or parsed.password:
        raise AppError('请使用 t.me 或 telegram.me 的 Telegram 消息链接。')
    parts = [p for p in parsed.path.strip('/').split('/') if p]
    if parts and parts[0] == 's':
        parts = parts[1:]
    if parts and parts[0] == 'c':
        if len(parts) not in (3, 4) or not all(p.isdigit() for p in parts[1:]):
            raise AppError('私有消息链接格式应为 t.me/c/频道编号/消息编号。')
        peer = int('-100' + parts[1])
    else:
        if len(parts) not in (2, 3) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{3,}', parts[0]):
            raise AppError('链接需要包含消息编号；仅有频道地址时请使用批量下载。')
        if not all(p.isdigit() for p in parts[1:]):
            raise AppError('消息编号格式不正确。')
        peer = parts[0]
    mid = int(parts[-1])
    if mid < 1:
        raise AppError('消息编号必须大于零。')
    return peer, mid


def parse_peer(value):
    value = str(value).strip()
    if re.fullmatch(r'-?\d+', value):
        return int(value)
    if value.startswith('@'):
        value = value[1:]
    if '/' in value:
        parsed = urlparse(value if '://' in value else 'https://' + value)
        if parsed.hostname not in ('t.me', 'telegram.me', 'www.t.me'):
            raise AppError('请输入 Telegram 频道名称、链接或对话编号。')
        value = parsed.path.strip('/').split('/')[0]
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{3,}', value):
        raise AppError('请输入有效的频道名称或对话编号。')
    return value


def protects(raw: str, decrypt=False) -> str:
    """Windows DPAPI, bound to the current Windows user, no embedded key."""
    if os.name != 'nt':
        raise AppError('此版本使用 Windows 本地凭据加密，请在 Windows 上运行。')
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]

    payload = base64.b64decode(raw) if decrypt else raw.encode('utf-8')
    buff = (ctypes.c_ubyte * len(payload)).from_buffer_copy(payload)
    source, target = Blob(len(payload), buff), Blob()
    crypto, kernel = ctypes.WinDLL('crypt32', use_last_error=True), ctypes.WinDLL('kernel32')
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    fn = crypto.CryptUnprotectData if decrypt else crypto.CryptProtectData
    fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                  ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    fn.restype = wintypes.BOOL
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise AppError('本地凭据加密失败，请检查 Windows 用户权限。')
    try:
        result = ctypes.string_at(target.data, target.size)
        return result.decode('utf-8') if decrypt else base64.b64encode(result).decode('ascii')
    finally:
        kernel.LocalFree(ctypes.cast(target.data, ctypes.c_void_p))


def describe_message(message, chat_id, chat_title=''):
    file = message.file
    if not file:
        return None
    kind = ('video' if message.video or message.video_note else 'image' if message.photo
            else 'audio' if message.audio or message.voice else 'file')
    filename = file.name or f'{kind}_{message.id}{file.ext or ".bin"}'
    return {'id': message.id, 'chat_id': chat_id, 'chat_title': chat_title,
            'name': safe_name(filename), 'kind': kind, 'size': file.size or 0,
            'duration': file.duration or 0, 'date': message.date.isoformat(),
            'caption': (message.raw_text or '')[:1200], 'source': 'telegram',
            'media_id': str(getattr(message.document or message.photo, 'id', ''))}


def matches(item, options):
    kind = options.get('kind', 'all')
    if kind != 'all' and item['kind'] != kind:
        return False
    query = str(options.get('keyword', '')).strip().casefold()
    if query and query not in (item['name'] + ' ' + item.get('caption', '')).casefold():
        return False
    maximum = float(options.get('max_size', 0) or 0) * 1024 * 1024
    if maximum and item['size'] > maximum:
        return False
    day = item['date'][:10]
    if options.get('date_from') and day < options['date_from']:
        return False
    if options.get('date_to') and day > options['date_to']:
        return False
    return True


class Store:
    def __init__(self, root: Path):
        root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(root / 'harbor.sqlite3', check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS jobs(
                id TEXT PRIMARY KEY, source TEXT, chat_id TEXT, message_id INTEGER,
                name TEXT, kind TEXT, size INTEGER, downloaded INTEGER DEFAULT 0,
                status TEXT, speed REAL DEFAULT 0, error TEXT DEFAULT '',
                payload TEXT, path TEXT DEFAULT '', created TEXT,
                UNIQUE(source, chat_id, message_id));
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE IF NOT EXISTS rules(id TEXT PRIMARY KEY, payload TEXT);
        ''')
        self.db.execute("UPDATE jobs SET status='paused', speed=0 WHERE status IN ('queued','resolving','downloading','waiting')")
        self.db.commit()

    def setting(self, key, default=None):
        with self.lock:
            row = self.db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def save_setting(self, key, value):
        with self.lock:
            self.db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)', (key, json.dumps(value, ensure_ascii=False)))
            self.db.commit()

    def add(self, item):
        jid = uuid.uuid4().hex[:12]
        payload = json.dumps(item, ensure_ascii=False)
        with self.lock:
            cur = self.db.execute('''INSERT OR IGNORE INTO jobs
                (id,source,chat_id,message_id,name,kind,size,status,payload,created)
                VALUES(?,?,?,?,?,?,?,?,?,?)''',
                (jid, item['source'], str(item['chat_id']), item['id'], item['name'], item['kind'],
                 item['size'], 'queued', payload, now()))
            self.db.commit()
            return jid if cur.rowcount else None

    def rows(self, source=None):
        with self.lock:
            rows = self.db.execute('SELECT * FROM jobs ' + ('WHERE source=? ' if source else '')
                                   + 'ORDER BY created DESC', (source,) if source else ()).fetchall()
        return [dict(row) for row in rows]

    def get(self, jid):
        with self.lock:
            row = self.db.execute('SELECT * FROM jobs WHERE id=?', (jid,)).fetchone()
        if not row:
            raise AppError('任务不存在。')
        return dict(row)

    def update(self, jid, **fields):
        allowed = {'name', 'kind', 'size', 'downloaded', 'status', 'speed', 'error', 'payload', 'path'}
        if set(fields) - allowed:
            raise ValueError('Unknown job fields')
        with self.lock:
            self.db.execute('UPDATE jobs SET ' + ','.join(k + '=?' for k in fields) + ' WHERE id=?',
                            (*fields.values(), jid))
            self.db.commit()

    def claim(self, jid):
        with self.lock:
            cursor = self.db.execute("UPDATE jobs SET status='downloading', speed=0, error='' WHERE id=? AND status='queued'", (jid,))
            self.db.commit()
            return bool(cursor.rowcount)

    def rules(self):
        with self.lock:
            return [json.loads(row[0]) for row in self.db.execute('SELECT payload FROM rules').fetchall()]

    def save_rule(self, rule):
        with self.lock:
            self.db.execute('INSERT OR REPLACE INTO rules VALUES(?,?)',
                            (rule['id'], json.dumps(rule, ensure_ascii=False)))
            self.db.commit()


DEMO_CHATS = [
    {'id': 'studio', 'title': '城市影像手记', 'subtitle': '原创城市视觉 · 本地演示', 'color': '#6e63df', 'letter': '城'},
    {'id': 'design', 'title': '设计灵感收藏', 'subtitle': '色彩与版式 · 本地演示', 'color': '#de9b73', 'letter': '设'},
    {'id': 'notes', 'title': '我的资料夹', 'subtitle': '项目资料与使用指南', 'color': '#539b92', 'letter': '资'},
]


def demo_items():
    catalog = [('night', '夜行 · 城市光谱', 'studio', 'image', 'png'),
               ('coast', '海岸 · 蓝色时刻', 'studio', 'image', 'png'),
               ('dune', '旷野 · 日落之后', 'studio', 'image', 'png'),
               ('wave', '流光 · 动态练习', 'studio', 'video', 'mp4'),
               ('shape', '几何 · 色彩实验', 'design', 'image', 'png'),
               ('paper', '留白 · 版式研究', 'design', 'image', 'png'),
               ('guide', '星港资源助手使用指南', 'notes', 'file', 'txt')]
    result = []
    for index, (asset, name, chat, kind, ext) in enumerate(catalog, 1):
        file = WEB / 'assets' / f'{asset}.{ext}'
        if file.exists():
            result.append({'id': index, 'chat_id': chat, 'chat_title': next(c['title'] for c in DEMO_CHATS if c['id'] == chat),
                           'name': f'{name}.{ext}', 'kind': kind, 'size': file.stat().st_size,
                           'duration': 6 if kind == 'video' else 0, 'date': f'2026-10-08T0{9-index}:24:00+08:00',
                           'caption': '软件随附的原创演示素材。下载会真实保存到本地，不连接 Telegram。',
                           'source': 'demo', 'asset': f'{asset}.{ext}',
                           'thumb': f'{asset if kind != "video" else "night"}.png'})
    return result


class Harbor:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.store = Store(self.root)
        self.download_root = Path(self.store.setting('download_root', str(self.root / 'downloads'))).resolve()
        self.download_root.mkdir(parents=True, exist_ok=True)
        self.token = secrets.token_urlsafe(32)
        self.mode = self.store.setting('mode', 'demo')
        self.auth = {'state': 'disconnected', 'message': '连接 Telegram 后载入你的对话', 'user': None, 'qr': None}
        self.client = None
        self.qr_task = None
        self.dialogs_cache = []
        self.thumb_cache = {}
        self.window = None
        self.server = None
        self.stopped = False
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        self.worker = asyncio.run_coroutine_threadsafe(self._worker(), self.loop)
        if self.store.setting('credentials'):
            asyncio.run_coroutine_threadsafe(self._restore(), self.loop)

    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def run(self, coroutine, timeout=45):
        future = asyncio.run_coroutine_threadsafe(coroutine, self.loop)
        try:
            return future.result(timeout)
        except TimeoutError:
            future.cancel()
            raise AppError('操作超时，请检查代理或稍后重试。') from None

    def _require_auth(self):
        if not self.client or self.auth['state'] != 'connected':
            raise AppError('请先在「连接 Telegram」中完成账号授权。')

    async def _restore(self):
        try:
            await self._connect(self.store.setting('credentials'))
        except Exception:
            self.auth.update(state='disconnected', message='已保存账号设置，请重新连接。', qr=None)

    async def _connect(self, config):
        from telethon import TelegramClient, events
        if self.qr_task:
            self.qr_task.cancel()
            self.qr_task = None
        if self.client:
            await self.client.disconnect()
        proxy = None
        if config.get('proxy_enabled'):
            import socks
            proxy = (socks.SOCKS5, config['proxy_host'], int(config['proxy_port']), True)
        api_hash = protects(config['api_hash'], decrypt=True)
        self.auth.update(state='connecting', message='正在连接 Telegram…', qr=None, user=None)
        self.client = TelegramClient(str(self.root / 'telegram'), int(config['api_id']), api_hash,
                                     proxy=proxy, connection_retries=2, request_retries=2,
                                     timeout=12, flood_sleep_threshold=0, device_model='TG Harbor Desktop',
                                     app_version=VERSION)
        try:
            await asyncio.wait_for(self.client.connect(), 32)
            self.client.add_event_handler(self._new_message, events.NewMessage())
            if await self.client.is_user_authorized():
                await self._connected()
            else:
                self.auth.update(state='ready', message='连接成功，可以生成登录二维码。')
            return self.auth
        except Exception as e:
            self.auth.update(state='error', message='连接失败，请确认代理可用，并核对 API ID / Hash。', qr=None)
            raise AppError(self.auth['message']) from e

    async def connect(self, data):
        old = self.store.setting('credentials', {})
        api_id = str(data.get('api_id', '')).strip()
        api_hash = str(data.get('api_hash', '')).strip()
        if not api_id.isdigit() or int(api_id) <= 0:
            raise AppError('API ID 应为正整数。')
        if api_hash and not re.fullmatch(r'[0-9a-fA-F]{32}', api_hash):
            raise AppError('API Hash 应为 32 位十六进制字符。')
        if not api_hash and not old.get('api_hash'):
            raise AppError('请填写你自己的 API Hash。')
        port = int(data.get('proxy_port', 7890) or 7890)
        if not 1 <= port <= 65535:
            raise AppError('代理端口应在 1–65535 之间。')
        host = str(data.get('proxy_host', '127.0.0.1')).strip()
        if not host or re.search(r'[\s/\\]', host):
            raise AppError('代理地址格式不正确。')
        if old.get('api_id') and str(old['api_id']) != api_id and (self.root / 'telegram.session').exists():
            raise AppError('现有会话使用另一组 API ID。请先退出账号，再更改 API ID。')
        config = {'api_id': api_id, 'api_hash': protects(api_hash) if api_hash else old['api_hash'],
                  'proxy_enabled': bool(data.get('proxy_enabled')), 'proxy_host': host, 'proxy_port': port}
        self.store.save_setting('credentials', config)
        return await self._connect(config)

    async def qr_login(self):
        if not self.client or not self.client.is_connected():
            raise AppError('请先填写 API 设置并连接 Telegram。')
        if self.auth['state'] == 'connected':
            return self.auth
        import qrcode
        if self.qr_task:
            self.qr_task.cancel()
            await asyncio.gather(self.qr_task, return_exceptions=True)
        qr = await self.client.qr_login()
        image = qrcode.make(qr.url)
        buf = io.BytesIO()
        image.save(buf, format='PNG')
        self.auth.update(state='qr', message='请在手机 Telegram 的「设置 → 设备」中扫码授权。',
                         qr='data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode(),
                         expires=qr.expires.isoformat())
        self.qr_task = asyncio.create_task(self._wait_qr(qr))
        return self.auth

    async def _wait_qr(self, qr):
        from telethon import errors
        try:
            await qr.wait()
            await self._connected()
        except errors.SessionPasswordNeededError:
            self.auth.update(state='password', message='该账号启用了两步验证，请在下方输入密码。', qr=None)
        except asyncio.TimeoutError:
            self.auth.update(state='expired', message='二维码已过期，请点击刷新二维码。', qr=None)
        except asyncio.CancelledError:
            pass
        except Exception:
            self.auth.update(state='error', message='授权未完成，请重新生成二维码。', qr=None)

    async def password(self, data):
        if self.auth['state'] != 'password':
            raise AppError('当前不需要两步验证密码。')
        try:
            await self.client.sign_in(password=data.get('password', ''))
            await self._connected()
        except Exception:
            raise AppError('密码验证未成功，请检查后重试。') from None
        return self.auth

    async def _connected(self):
        me = await self.client.get_me()
        self.auth.update(state='connected', message='Telegram 已连接', qr=None,
                         user={'name': ' '.join(filter(None, [me.first_name, me.last_name])), 'username': me.username or ''})
        self.mode = 'telegram'
        self.store.save_setting('mode', self.mode)

    async def disconnect(self):
        if self.qr_task:
            self.qr_task.cancel()
            await asyncio.gather(self.qr_task, return_exceptions=True)
        if self.client:
            await self.client.disconnect()
        self.auth.update(state='disconnected', message='已断开连接，会话保留在本机。', qr=None, user=None)
        return self.auth

    async def logout(self):
        if self.qr_task:
            self.qr_task.cancel()
        if self.client:
            await self.client.log_out()
            self.client = None
        self.store.save_setting('credentials', None)
        self.auth.update(state='disconnected', message='账号已退出。', qr=None, user=None)
        self.mode = 'demo'
        self.store.save_setting('mode', self.mode)
        return self.auth

    async def dialogs(self):
        if self.mode == 'demo':
            return DEMO_CHATS
        self._require_auth()
        result = []
        async for dialog in self.client.iter_dialogs(limit=200):
            result.append({'id': dialog.id, 'title': dialog.name or '未命名对话',
                           'subtitle': '频道' if dialog.is_channel else '群组' if dialog.is_group else '私聊',
                           'color': ['#6e63df','#539b92','#de9b73'][len(result) % 3],
                           'letter': (dialog.name or 'T')[0]})
        self.dialogs_cache = result
        return result

    async def media(self, data):
        if self.mode == 'demo':
            items = [x for x in demo_items() if str(x['chat_id']) == str(data.get('chat_id')) and matches(x, data)]
            return {'items': items, 'scanned': len(items), 'next_offset': 0}
        self._require_auth()
        peer = parse_peer(data.get('chat_id', ''))
        title = next((x['title'] for x in self.dialogs_cache if str(x['id']) == str(peer)), str(peer))
        offset, scanned, last, items = int(data.get('offset', 0)), 0, 0, []
        async for message in self.client.iter_messages(peer, limit=200, offset_id=offset):
            scanned += 1
            last = message.id
            item = describe_message(message, peer, title)
            if item and matches(item, data):
                items.append(item)
        return {'items': items, 'scanned': scanned, 'next_offset': last if scanned == 200 else 0}

    async def thumbnail(self, chat, mid):
        key = (str(chat), mid)
        if key in self.thumb_cache:
            return self.thumb_cache[key]
        self._require_auth()
        message = await self.client.get_messages(parse_peer(chat), ids=mid)
        if not message or not message.file:
            return None
        blob = await self.client.download_media(message, bytes, thumb=0)
        if blob and blob.startswith((b'\xff\xd8', b'\x89PNG')):
            if len(self.thumb_cache) > 180:
                self.thumb_cache.clear()
            self.thumb_cache[key] = blob
            return blob
        return None

    def enqueue(self, items):
        added, skipped = 0, 0
        for item in items:
            if item['source'] == 'telegram':
                self._require_auth()
            if self.store.add(item):
                added += 1
            else:
                skipped += 1
        return {'added': added, 'skipped': skipped}

    async def selected(self, data):
        ids = list(dict.fromkeys(int(x) for x in data.get('ids', [])))
        if not ids or len(ids) > 200:
            raise AppError('请一次选择 1–200 个媒体文件。')
        if self.mode == 'demo':
            items = [x for x in demo_items() if x['id'] in ids and str(x['chat_id']) == str(data['chat_id'])]
        else:
            self._require_auth()
            peer = parse_peer(data['chat_id'])
            title = next((x['title'] for x in self.dialogs_cache if str(x['id']) == str(peer)), str(peer))
            messages = await self.client.get_messages(peer, ids=ids)
            items = [describe_message(m, peer, title) for m in messages if m and m.file]
        if not items:
            raise AppError('没有找到可以下载的媒体文件。')
        return self.enqueue(items)

    async def links(self, data):
        self._require_auth()
        links = list(dict.fromkeys(x.strip() for x in str(data.get('links', '')).splitlines() if x.strip()))
        if not 1 <= len(links) <= 100:
            raise AppError('一次可添加 1–100 条消息链接，每行一条。')
        parsed = [parse_link(link) for link in links]
        added, skipped, failures = 0, 0, []
        for peer, mid in parsed:
            try:
                message = await self.client.get_messages(peer, ids=mid)
                if not message or not message.file:
                    failures.append(f'消息 {mid} 不包含可下载媒体。')
                    continue
                entity = await self.client.get_entity(peer)
                from telethon import utils
                cid = utils.get_peer_id(entity)
                item = describe_message(message, cid, getattr(entity, 'title', str(peer)))
                outcome = self.enqueue([item])
                added += outcome['added']
                skipped += outcome['skipped']
            except Exception:
                failures.append(f'消息 {mid} 读取失败，请确认已加入该对话并具有访问权限。')
        return {'added': added, 'skipped': skipped, 'failures': failures}

    async def bulk(self, data):
        limit = int(data.get('limit', 200))
        if not 1 <= limit <= 1000:
            raise AppError('单次扫描范围为最近 1–1000 条消息。')
        if self.mode == 'demo':
            return self.enqueue([x for x in demo_items() if str(x['chat_id']) == str(data.get('chat_id')) and matches(x, data)])
        self._require_auth()
        peer = parse_peer(data.get('chat_id', ''))
        entity = await self.client.get_entity(peer)
        from telethon import utils
        cid = utils.get_peer_id(entity)
        title = getattr(entity, 'title', str(peer))
        items, scanned = [], 0
        async for message in self.client.iter_messages(peer, limit=limit):
            scanned += 1
            item = describe_message(message, cid, title)
            if item and matches(item, data):
                items.append(item)
        result = self.enqueue(items)
        result['scanned'] = scanned
        return result

    async def save_rule(self, data):
        self._require_auth()
        peer = parse_peer(data.get('chat_id', ''))
        entity = await self.client.get_entity(peer)
        from telethon import utils
        data = {key: data.get(key, '') for key in ('id', 'name', 'kind', 'keyword', 'max_size')}
        data.update(id=data.get('id') or uuid.uuid4().hex[:12], chat_id=utils.get_peer_id(entity),
                    chat_title=getattr(entity, 'title', str(peer)), enabled=True, created=now())
        self.store.save_rule(data)
        return data

    async def _new_message(self, event):
        if self.auth['state'] != 'connected':
            return
        for rule in self.store.rules():
            if rule.get('enabled') and str(rule['chat_id']) == str(event.chat_id):
                item = describe_message(event.message, event.chat_id, rule['chat_title'])
                if item and matches(item, rule):
                    self.enqueue([item])

    def job_action(self, data):
        action = data.get('action')
        if action not in ('pause', 'resume', 'cancel', 'retry'):
            raise AppError('未知任务操作。')
        jobs = [self.store.get(data['id'])] if data.get('id') else self.store.rows(self.mode)
        changed = 0
        for job in jobs:
            state = job['status']
            if action == 'pause' and state in STATUS_ACTIVE:
                self.store.update(job['id'], status='paused', speed=0)
                changed += 1
            elif action in ('resume', 'retry') and state in ('paused', 'error', 'cancelled'):
                if job['source'] == 'telegram':
                    self._require_auth()
                self.store.update(job['id'], status='queued', speed=0, error='')
                changed += 1
            elif action == 'cancel' and state not in ('completed', 'cancelled'):
                self.store.update(job['id'], status='cancelled', speed=0)
                changed += 1
        return {'changed': changed}

    def _check_running(self, jid):
        if self.stopped or self.store.get(jid)['status'] != 'downloading':
            raise Interrupted()

    async def _worker(self):
        while not self.stopped:
            queued = [j for j in reversed(self.store.rows()) if j['status'] == 'queued']
            if not queued:
                await asyncio.sleep(.3)
                continue
            job = queued[0]
            jid = job['id']
            if not self.store.claim(jid):
                continue
            try:
                await self._download(job)
            except Interrupted:
                self.store.update(jid, speed=0)
            except asyncio.CancelledError:
                if self.store.get(jid)['status'] == 'downloading':
                    self.store.update(jid, status='paused', speed=0)
                raise
            except Exception as error:
                from telethon.errors import FloodWaitError
                if isinstance(error, FloodWaitError):
                    message = f'Telegram 要求等待 {error.seconds} 秒，稍后点击重试。'
                elif isinstance(error, AppError):
                    message = str(error)
                else:
                    message = '下载未完成。请确认网络、磁盘空间及媒体访问权限后重试。'
                self.store.update(jid, status='error', speed=0, error=message)

    async def _download(self, job):
        item, jid = json.loads(job['payload']), job['id']
        self._check_running(jid)
        directory = self.download_root / safe_name(item.get('chat_title') or str(item['chat_id']))
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f'{jid}_{safe_name(item["name"])}'
        if job['path']:
            target = Path(job['path'])
            # A changed download root does not discard partially completed jobs.
            target.parent.mkdir(parents=True, exist_ok=True)
        self.store.update(jid, path=str(target))
        partial = target.with_name(target.name + '.part')
        if target.exists():
            if target.stat().st_size == item['size']:
                self.store.update(jid, status='completed', downloaded=target.stat().st_size, speed=0)
                return
            raise AppError('目标文件已存在且大小不一致，请更换下载目录。')
        begin, start_bytes, last_update = time.monotonic(), 0, 0
        if item['source'] == 'demo':
            source = WEB / 'assets' / item['asset']
            if not source.resolve().is_relative_to((WEB / 'assets').resolve()):
                raise AppError('演示素材路径不正确。')
            offset = partial.stat().st_size if partial.exists() else 0
            if offset > source.stat().st_size:
                raise AppError('临时文件大小异常。')
            start_bytes = offset
            with source.open('rb') as input_file, partial.open('ab') as output_file:
                input_file.seek(offset)
                while chunk := input_file.read(16 * 1024):
                    self._check_running(jid)
                    output_file.write(chunk)
                    output_file.flush()
                    offset += len(chunk)
                    self.store.update(jid, downloaded=offset, speed=(offset - start_bytes) / max(.1, time.monotonic() - begin))
                    await asyncio.sleep(.04)
        else:
            self._require_auth()
            message = await self.client.get_messages(parse_peer(item['chat_id']), ids=item['id'])
            current = describe_message(message, item['chat_id']) if message and message.file else None
            if not current:
                raise AppError('消息已不存在或不包含可下载媒体。')
            if current['media_id'] != item['media_id'] or current['size'] != item['size']:
                raise AppError('消息中的媒体已变更，请重新选择该消息建立任务。')
            offset = ((partial.stat().st_size if partial.exists() else 0) // CHUNK) * CHUNK
            start_bytes = offset
            with partial.open('r+b' if partial.exists() else 'wb') as output_file:
                output_file.truncate(offset)
                output_file.seek(offset)
                stream = self.client.iter_download(message.media, offset=offset, request_size=CHUNK, file_size=item['size'])
                try:
                    async for chunk in stream:
                        self._check_running(jid)
                        output_file.write(chunk)
                        output_file.flush()
                        offset += len(chunk)
                        if time.monotonic() - last_update > .2:
                            self.store.update(jid, downloaded=offset, speed=(offset - start_bytes) / max(.1, time.monotonic() - begin))
                            last_update = time.monotonic()
                finally:
                    await stream.close()
        actual = partial.stat().st_size
        if item['size'] and actual != item['size']:
            raise AppError('文件大小与源媒体不一致，临时文件已保留，可点击重试。')
        with self.store.lock:
            self._check_running(jid)
            partial.replace(target)
            self.store.update(jid, status='completed', downloaded=actual, size=actual, speed=0)

    def settings(self):
        config = self.store.setting('credentials') or {}
        return {'download_root': str(self.download_root), 'api_id': config.get('api_id', ''),
                'has_api_hash': bool(config.get('api_hash')), 'proxy_host': config.get('proxy_host', '127.0.0.1'),
                'proxy_port': config.get('proxy_port', 7890), 'proxy_enabled': config.get('proxy_enabled', False)}

    def state(self):
        rows = self.store.rows(self.mode)
        for row in rows:
            row['chat_title'] = json.loads(row.pop('payload')).get('chat_title', '')
        return {'version': VERSION, 'mode': self.mode, 'auth': self.auth.copy(), 'jobs': rows,
                'settings': self.settings(), 'rules': self.store.rules(),
                'stats': {'total': len(rows), 'completed': sum(j['status'] == 'completed' for j in rows),
                          'active': sum(j['status'] in STATUS_ACTIVE for j in rows),
                          'bytes': sum(j['downloaded'] for j in rows), 'speed': sum(j['speed'] for j in rows)}}

    def set_settings(self, data):
        if 'download_root' in data:
            path = Path(str(data['download_root'])).expanduser()
            if not path.is_absolute():
                raise AppError('下载目录必须是完整路径。')
            path.mkdir(parents=True, exist_ok=True)
            self.download_root = path.resolve()
            self.store.save_setting('download_root', str(self.download_root))
        if data.get('mode') in ('demo', 'telegram'):
            self.mode = data['mode']
            self.store.save_setting('mode', self.mode)
        return self.settings()

    def open_folder(self, jid=None):
        folder = Path(self.store.get(jid)['path']).parent if jid and self.store.get(jid)['path'] else self.download_root
        folder.mkdir(parents=True, exist_ok=True)
        if os.name == 'nt':
            os.startfile(str(folder))
        return {'path': str(folder)}

    async def _shutdown(self):
        self.stopped = True
        self.worker.cancel()
        if self.qr_task:
            self.qr_task.cancel()
        if self.client:
            await self.client.disconnect()
        for job in self.store.rows():
            if job['status'] in STATUS_ACTIVE:
                self.store.update(job['id'], status='paused', speed=0)
        pending = [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    def close(self):
        if self.stopped:
            return
        try:
            self.run(self._shutdown(), 8)
        except Exception:
            self.stopped = True
        if self.server:
            self.server.shutdown()
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(3)
        if not self.thread.is_alive():
            self.loop.close()


def make_handler(app):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def _headers(self, code, mime, length, extra=None):
            self.send_response(code)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(length))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; media-src 'self' blob:; frame-ancestors 'none'; base-uri 'none'")
            if extra:
                for key, value in extra.items():
                    self.send_header(key, value)
            self.end_headers()

        def _json(self, value, code=200):
            data = json.dumps(value, ensure_ascii=False).encode('utf-8')
            self._headers(code, 'application/json; charset=utf-8', len(data))
            self.wfile.write(data)

        def _authorized(self, query):
            supplied = self.headers.get('X-Harbor-Token', '') or query.get('token', [''])[0]
            if not secrets.compare_digest(supplied, app.token):
                self._json({'error': '本地会话已失效，请重新打开软件。'}, 403)
                return False
            origin = self.headers.get('Origin')
            if origin and origin != f'http://127.0.0.1:{self.server.server_port}':
                self._json({'error': '来源不被允许。'}, 403)
                return False
            return True

        def do_GET(self):
            try:
                self._get()
            except (BrokenPipeError, ConnectionResetError):
                pass
            except AppError as e:
                self._json({'error': str(e)}, 400)
            except Exception:
                self._json({'error': '读取失败，请稍后重试。'}, 500)

        def _get(self):
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            path = unquote(parsed.path)
            if path.startswith('/api/'):
                if not self._authorized(query):
                    return
                if path == '/api/state':
                    return self._json(app.state())
                if path == '/api/dialogs':
                    return self._json({'items': app.run(app.dialogs())})
                if path == '/api/media':
                    return self._json(app.run(app.media({key: value[0] for key, value in query.items()})))
                if path == '/api/thumb':
                    blob = app.run(app.thumbnail(query['chat_id'][0], int(query['id'][0])))
                    if not blob:
                        self._headers(204, 'image/jpeg', 0)
                        return
                    self._headers(200, 'image/jpeg', len(blob))
                    self.wfile.write(blob)
                    return
                if path == '/api/file':
                    job = app.store.get(query['id'][0])
                    if job['status'] != 'completed':
                        raise AppError('文件尚未完成下载。')
                    file = Path(job['path'])
                    if not file.is_file():
                        raise AppError('本地文件已移动或删除。')
                    return self._file(file)
                return self._json({'error': '接口不存在'}, 404)
            file = WEB / ('index.html' if path == '/' else path.lstrip('/'))
            if not file.resolve().is_relative_to(WEB.resolve()) or not file.is_file():
                return self._json({'error': '资源不存在'}, 404)
            self._file(file)

        def _file(self, file):
            total = file.stat().st_size
            start, end, code = 0, total - 1, 200
            if self.headers.get('Range'):
                match = re.fullmatch(r'bytes=(\d*)-(\d*)', self.headers['Range'])
                if not match or not any(match.groups()) or total == 0:
                    self._headers(416, 'text/plain', 0, {'Content-Range': f'bytes */{total}'})
                    return
                if match[1]:
                    start = int(match[1])
                    end = min(total - 1, int(match[2])) if match[2] else total - 1
                else:
                    start = max(0, total - int(match[2]))
                if start >= total or start > end:
                    self._headers(416, 'text/plain', 0, {'Content-Range': f'bytes */{total}'})
                    return
                code = 206
            extra = {'Accept-Ranges': 'bytes'}
            if code == 206:
                extra['Content-Range'] = f'bytes {start}-{end}/{total}'
            mime = mimetypes.guess_type(str(file))[0] or 'application/octet-stream'
            if mime.startswith('text/') or mime == 'application/javascript':
                mime += '; charset=utf-8'
            remaining = max(0, end - start + 1)
            self._headers(code, mime, remaining, extra)
            with file.open('rb') as fp:
                fp.seek(start)
                while remaining:
                    chunk = fp.read(min(65536, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)

        def do_POST(self):
            try:
                parsed = urlparse(self.path)
                if not self._authorized(parse_qs(parsed.query)):
                    return
                length = int(self.headers.get('Content-Length', 0))
                if length > 2 * 1024 * 1024:
                    raise AppError('请求内容过大。')
                data = json.loads(self.rfile.read(length) or b'{}')
                if not isinstance(data, dict):
                    raise AppError('请求格式不正确。')
                routes = {'/api/connect': app.connect, '/api/password': app.password,
                          '/api/selected': app.selected, '/api/links': app.links,
                          '/api/bulk': app.bulk, '/api/rules': app.save_rule}
                if parsed.path in routes:
                    value = app.run(routes[parsed.path](data), 90 if parsed.path in ('/api/bulk', '/api/links') else 45)
                elif parsed.path == '/api/qr':
                    value = app.run(app.qr_login())
                elif parsed.path == '/api/disconnect':
                    value = app.run(app.disconnect())
                elif parsed.path == '/api/logout':
                    value = app.run(app.logout())
                elif parsed.path == '/api/jobs/action':
                    value = app.job_action(data)
                elif parsed.path == '/api/settings':
                    value = app.set_settings(data)
                elif parsed.path == '/api/open-folder':
                    value = app.open_folder(data.get('id'))
                elif parsed.path == '/api/rules/toggle':
                    rule = next((r for r in app.store.rules() if r['id'] == data.get('id')), None)
                    if not rule:
                        raise AppError('规则不存在。')
                    if data.get('enabled'):
                        app._require_auth()
                    rule['enabled'] = bool(data.get('enabled'))
                    app.store.save_rule(rule)
                    value = rule
                else:
                    return self._json({'error': '接口不存在'}, 404)
                self._json(value)
            except (AppError, ValueError, KeyError, TypeError) as e:
                self._json({'error': str(e) if isinstance(e, AppError) else '请检查输入格式。'}, 400)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception:
                self._json({'error': '操作未完成，请检查网络连接或稍后重试。'}, 500)
    return Handler


class DesktopBridge:
    def __init__(self, app):
        self.app = app

    def choose_folder(self):
        import webview
        result = self.app.window.create_file_dialog(webview.FileDialog.FOLDER)
        return result[0] if result else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--headless', action='store_true')
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--data-dir')
    args = parser.parse_args()
    executable_dir = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent
    root = Path(args.data_dir).resolve() if args.data_dir else executable_dir / 'data'
    app = Harbor(root)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), make_handler(app))
    app.server = server
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f'http://127.0.0.1:{server.server_port}/#session={app.token}'
    (root / 'runtime.json').write_text(json.dumps({'url': url, 'pid': os.getpid(), 'version': VERSION}), encoding='utf-8')
    try:
        if args.headless:
            if sys.stdout:
                print(f'TG Harbor ready at http://127.0.0.1:{server.server_port}', flush=True)
            while not app.stopped:
                time.sleep(.5)
        else:
            import webview
            webview.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER'] = True
            app.window = webview.create_window('星港 · Telegram 资源助手', url, width=1440, height=950,
                                               min_size=(1080, 720), background_color='#f7f8fc',
                                               js_api=DesktopBridge(app), text_select=True)
            app.window.events.closed += app.close
            webview.start(gui='edgechromium', storage_path=str(root / 'webview'), private_mode=False)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        (root / 'startup-error.txt').write_text(type(e).__name__ + ': ' + str(e), encoding='utf-8')
        if not args.headless:
            import webbrowser
            webbrowser.open(url)
            while not app.stopped:
                time.sleep(.5)
        else:
            raise
    finally:
        app.close()


if __name__ == '__main__':
    main()
