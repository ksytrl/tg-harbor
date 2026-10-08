import asyncio
import hashlib
import json
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import AppError, CHUNK, Harbor, Store, WEB, demo_items, make_handler, matches, parse_link, protects, safe_name
from http.server import ThreadingHTTPServer


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def until(check, seconds=8):
    limit=time.monotonic()+seconds
    while time.monotonic()<limit:
        value=check()
        if value:return value
        time.sleep(.03)
    raise AssertionError('Condition did not become true')


class FakeStream:
    def __init__(self, owner, offset):self.owner=owner;self.offset=offset;self.closed=False
    def __aiter__(self):return self
    async def __anext__(self):
        await asyncio.sleep(.03)
        if self.offset>=len(self.owner.content):raise StopAsyncIteration
        chunk=self.owner.content[self.offset:self.offset+CHUNK]
        self.offset+=len(chunk)
        return chunk
    async def close(self):self.closed=True


class FakeClient:
    def __init__(self, content, mid='44'):
        self.content=content;self.offsets=[];self.streams=[]
        self.message=SimpleNamespace(id=42,file=SimpleNamespace(name='sample.bin',ext='.bin',size=len(content),duration=0),
            video=None,video_note=None,photo=None,audio=None,voice=None,document=SimpleNamespace(id=int(mid)),
            media='fixture',date=__import__('datetime').datetime.now(__import__('datetime').timezone.utc),raw_text='fixture')
    async def get_messages(self, *args, **kwargs):return self.message
    def iter_download(self,media,offset,**kwargs):
        self.offsets.append(offset);stream=FakeStream(self,offset);self.streams.append(stream);return stream
    async def disconnect(self):pass


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.app=Harbor(Path(self.temp.name))
    def tearDown(self):
        self.app.close();self.app.store.db.close();self.temp.cleanup()

    def test_message_links_public_private_and_forum(self):
        self.assertEqual(parse_link('https://t.me/example_channel/123?single'),('example_channel',123))
        self.assertEqual(parse_link('t.me/c/1234567890/22/333'),(-1001234567890,333))
        self.assertEqual(parse_link('https://t.me/s/example_channel/99'),('example_channel',99))
        for value in ['https://evil.test/foo/123','t.me/+invite','t.me/example_channel','t.me/example_channel/0','https://t.me@example.com/x/4']:
            with self.subTest(value=value),self.assertRaises(AppError):parse_link(value)

    def test_names_cannot_escape_directory_or_use_windows_devices(self):
        for value in ['../../secret.exe',r'..\..\secret.exe','NUL.txt','COM1','', 'a'*300+'.png']:
            name=safe_name(value)
            self.assertNotIn('/',name);self.assertNotIn('\\',name)
            self.assertLessEqual(len(name),150)
            self.assertFalse(name.startswith('..'))
        self.assertEqual(safe_name('NUL.txt'),'_NUL.txt')

    def test_composed_media_filters(self):
        item={'kind':'video','name':'City.mp4','caption':'Night','size':3*1024*1024,'date':'2026-10-08T12:00:00Z'}
        self.assertTrue(matches(item,{'kind':'video','keyword':'night','max_size':4,'date_from':'2026-10-08'}))
        for options in [{'kind':'image'},{'keyword':'missing'},{'max_size':2},{'date_to':'2026-10-07'}]:
            self.assertFalse(matches(item,options))

    def test_demo_download_is_an_actual_file_and_deduplicates(self):
        item=demo_items()[0]
        result=self.app.enqueue([item,item]);self.assertEqual(result,{'added':1,'skipped':1})
        job=until(lambda:next((j for j in self.app.store.rows() if j['status']=='completed'),None))
        self.assertEqual(digest(job['path']),digest(WEB/'assets'/item['asset']))
        self.assertFalse(Path(job['path']+'.part').exists())

    def test_pause_resume_keeps_partial_and_completes_without_corruption(self):
        item=demo_items()[0]
        jid=self.app.store.add(item)
        until(lambda:self.app.store.get(jid)['downloaded']>0)
        self.app.job_action({'id':jid,'action':'pause'})
        time.sleep(.2)
        job=self.app.store.get(jid)
        self.assertEqual(job['status'],'paused');self.assertGreater(job['downloaded'],0)
        partial=Path(job['path']+'.part');self.assertTrue(partial.exists())
        self.app.job_action({'id':jid,'action':'resume'})
        until(lambda:self.app.store.get(jid)['status']=='completed')
        self.assertEqual(digest(job['path']),digest(WEB/'assets'/item['asset']))

    def real_item(self, content):
        return {'source':'telegram','chat_id':-1001234567890,'id':42,'chat_title':'Fixture','name':'sample.bin',
                'kind':'file','size':len(content),'media_id':'44','date':'2026-10-08T00:00:00Z','caption':''}

    def test_telegram_stream_resume_aligns_offset_and_closes_stream(self):
        content=bytes(range(256))*(CHUNK//256*3)+b'end'
        self.app.client=FakeClient(content);self.app.auth['state']='connected'
        item=self.real_item(content)
        jid=self.app.store.add(item);self.app.store.update(jid,status='paused')
        target=Path(self.temp.name)/'downloads'/'Fixture'/f'{jid}_sample.bin'
        target.parent.mkdir(parents=True,exist_ok=True)
        Path(str(target)+'.part').write_bytes(content[:CHUNK+111])
        self.app.store.update(jid,path=str(target),downloaded=CHUNK+111)
        self.app.job_action({'id':jid,'action':'resume'})
        until(lambda:self.app.store.get(jid)['status']=='completed')
        self.assertEqual(self.app.client.offsets,[CHUNK])
        self.assertEqual(target.read_bytes(),content)
        self.assertTrue(all(s.closed for s in self.app.client.streams))

    def test_changed_remote_file_is_not_mixed_with_partial(self):
        content=b'fixture';self.app.client=FakeClient(content,mid='55');self.app.auth['state']='connected'
        jid=self.app.store.add(self.real_item(content))
        job=until(lambda:self.app.store.get(jid) if self.app.store.get(jid)['status']=='error' else None)
        self.assertIn('已变更',job['error']);self.assertFalse(Path(job['path']).exists())

    def test_real_jobs_require_authorization(self):
        with self.assertRaises(AppError):self.app.enqueue([self.real_item(b'test')])
        self.assertEqual(self.app.store.rows(),[])

    def test_mode_isolation_and_credential_redaction(self):
        self.app.store.add(demo_items()[0])
        self.app.store.save_setting('credentials',{'api_id':'123','api_hash':'encrypted-sensitive'})
        state=self.app.state()
        self.assertNotIn('encrypted-sensitive',json.dumps(state))
        self.app.set_settings({'mode':'telegram'})
        self.assertEqual(self.app.state()['jobs'],[])

    def test_windows_credentials_round_trip(self):
        plain='0'*32;cipher=protects(plain)
        self.assertNotEqual(cipher,plain)
        self.assertEqual(protects(cipher,decrypt=True),plain)

    def test_restart_restores_active_tasks_as_paused(self):
        self.app.close()
        jid=self.app.store.add(demo_items()[0]);self.app.store.update(jid,status='downloading',downloaded=17)
        self.app.store.db.close()
        self.app=Harbor(Path(self.temp.name))
        self.assertEqual(self.app.store.get(jid)['status'],'paused')
        self.assertEqual(self.app.store.get(jid)['downloaded'],17)


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        cls.app=Harbor(Path(cls.temp.name))
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(cls.app))
        cls.app.server=cls.server
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.base=f'http://127.0.0.1:{cls.server.server_port}'
    @classmethod
    def tearDownClass(cls):
        cls.app.close();cls.server.server_close();cls.app.store.db.close();cls.temp.cleanup()
    def request(self,path,body=None,headers=None):
        data=json.dumps(body).encode() if body is not None else None
        req=urllib.request.Request(self.base+path,data=data,headers=headers or {})
        return urllib.request.urlopen(req,timeout=8)
    def test_capability_required_and_cross_origin_blocked(self):
        with self.assertRaises(urllib.error.HTTPError) as e:self.request('/api/state')
        self.assertEqual(e.exception.code,403)
        with self.assertRaises(urllib.error.HTTPError) as e:self.request('/api/state',headers={'X-Harbor-Token':self.app.token,'Origin':'https://evil.test'})
        self.assertEqual(e.exception.code,403)
        with self.request('/api/state',headers={'X-Harbor-Token':self.app.token}) as response:
            self.assertEqual(json.load(response)['mode'],'demo')
    def test_asset_traversal_and_range_semantics(self):
        with self.assertRaises(urllib.error.HTTPError):self.request('/%2e%2e/app.py')
        with self.request('/assets/wave.mp4',headers={'Range':'bytes=2-19'}) as response:
            self.assertEqual(response.status,206)
            self.assertEqual(response.read(),(WEB/'assets/wave.mp4').read_bytes()[2:20])
        with self.assertRaises(urllib.error.HTTPError) as e:self.request('/assets/wave.mp4',headers={'Range':'bytes=99999999999-'})
        self.assertEqual(e.exception.code,416)
    def test_invalid_credentials_rejected_before_network(self):
        with self.assertRaises(urllib.error.HTTPError) as e:self.request('/api/connect',{'api_id':'invalid'}, {'X-Harbor-Token':self.app.token})
        self.assertEqual(e.exception.code,400)
        self.assertEqual(self.app.auth['state'],'disconnected')


if __name__=='__main__':unittest.main(verbosity=2)
