from pathlib import Path
import math
import random
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).parent / 'web' / 'assets'
ROOT.mkdir(parents=True, exist_ok=True)
W, H = 1280, 760
rng = random.Random(7062)


def gradient(top, bottom):
    image = Image.new('RGB', (W, H))
    pixels = image.load()
    for y in range(H):
        t = y / (H - 1)
        for x in range(W):
            n = rng.randint(-3, 3)
            pixels[x, y] = tuple(max(0, min(255, round(a*(1-t)+b*t)+n)) for a,b in zip(top,bottom))
    return image


def save(image, name):
    image.save(ROOT / (name + '.png'), optimize=True)


night = gradient((23,29,59),(49,57,80))
d = ImageDraw.Draw(night)
d.ellipse((835,115,913,193),fill=(222,217,183))
for x in range(-20,W,75):
    height=rng.randint(140,340)
    d.rectangle((x,420-height,x+60,470),fill=(24,31,53))
    for xx in range(x+8,x+53,14):
        for yy in range(440-height,440,22):
            if rng.random()>.58:d.rectangle((xx,yy,xx+4,yy+8),fill=rng.choice([(183,150,124),(114,125,153),(77,91,126)]))
for y in range(480,H,4):
    for _ in range(15):
        x=rng.randrange(W)
        d.line((x,y,x+rng.randint(8,80),y),fill=(rng.randint(49,75),rng.randint(56,81),rng.randint(77,102)),width=1)
d.polygon(((0,670),(W,620),(W,H),(0,H)),fill=(22,30,48))
d.line((0,669,W,619),fill=(153,138,121),width=4)
save(night,'night')

coast=gradient((103,150,160),(218,213,193));d=ImageDraw.Draw(coast)
d.rectangle((0,380,W,H),fill=(60,114,132))
for y in range(400,H,7):
    for _ in range(14):
        x=rng.randrange(W);d.line((x,y,x+rng.randrange(15,110),y),fill=(105,157,168),width=1)
d.polygon(((0,500),(260,420),(385,456),(550,560),(630,H),(0,H)),fill=(207,195,169))
d.polygon(((0,508),(245,435),(382,463),(495,547),(570,H),(550,H),(472,554),(375,480),(240,451),(0,535)),fill=(218,222,207))
d.ellipse((897,101,959,163),fill=(235,232,211));save(coast,'coast')

dune=gradient((116,84,111),(237,181,136));d=ImageDraw.Draw(dune)
d.ellipse((890,190,1010,310),fill=(244,201,155))
d.polygon(((0,520),(330,379),(530,422),(780,488),(1070,370),(1280,480),(1280,H),(0,H)),fill=(160,109,114))
d.polygon(((0,720),(380,489),(655,635),(970,510),(1280,635),(1280,H),(0,H)),fill=(105,81,99))
for i in range(20):d.line((i*80,720-i*3,400+i*40,510+i*6),fill=(128,92,106),width=2)
save(dune,'dune')

shape=gradient((221,208,197),(213,185,168));d=ImageDraw.Draw(shape)
d.ellipse((150,95,730,675),fill=(103,107,129))
d.rectangle((550,300,1100,640),fill=(230,218,196))
d.ellipse((690,330,960,600),fill=(168,132,124))
d.polygon(((195,510),(420,170),(700,510)),fill=(221,186,147))
save(shape,'shape')

paper=gradient((239,235,221),(223,220,206));d=ImageDraw.Draw(paper)
d.rectangle((165,110,540,640),fill=(94,117,111))
d.rectangle((620,115,1110,145),fill=(64,78,74))
for y,width in [(220,345),(254,380),(288,340),(380,220),(411,360),(442,300),(550,240)]:d.rectangle((620,y,620+width,y+8),fill=(145,151,134))
d.ellipse((265,265,445,445),outline=(195,196,162),width=2)
d.line((240,400,470,275),fill=(195,196,162),width=2)
save(paper,'paper')

icon=Image.new('RGBA',(256,256),(0,0,0,0));d=ImageDraw.Draw(icon)
d.rounded_rectangle((4,4,252,252),radius=62,fill=(112,98,223))
d.line((61,182,61,92,128,55,195,92,195,182),fill='white',width=12,joint='curve')
d.line((61,130,128,168,195,130),fill='white',width=12,joint='curve')
d.line((128,55,128,168),fill='white',width=12)
icon.save(ROOT/'icon.png');icon.save(ROOT/'icon.ico',sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
(ROOT/'guide.txt').write_text('星港 · TG Harbor\n\n这是软件随附的本地演示资料。\n\n1. 浏览资源并选择媒体。\n2. 下载所选内容，在工作台查看任务。\n3. 完成后在本地资源库查看。\n4. 填写自己的 Telegram API ID 和 Hash，扫码授权后开始真实下载。\n\n演示资料不来自真实 Telegram 对话。\n',encoding='utf-8')
print('Original demo artwork generated')
