"""Fetch freely licensed images from Wikimedia Commons into src_img/<batch>/ (run by .github/workflows/fetch-commons.yml).
Request file src_img/requests/<batch>.txt, one entry per line:
  search: <query>            files found by Commons search (namespace File)
  cat: <Category:Name>       files in the category (and its direct subcategories)
  file: <File:Name.jpg>      one file at full width
  width: <px>                thumb width for the lines that follow (default 480)
  video: <File:Name.webm> | <a>-<b>   a silent H.264 clip of seconds a..b (at most 1080 lines), plus its still and licence
  audio: <File:Name.ogg> | <a>-<b>   a sound file cut to a..b, as 48 kHz FLAC
  tiles: <usgs-imagery|usgs-topo> <z> <lat0> <lon0> <lat1> <lon1>   public-domain USGS map tiles stitched into one image
  frames: <File:Name.webm> | <s>      a contact sheet: one small frame every s seconds, row by row (frame k at about k*s + s/2), plus the duration
Videos found by search: or cat: get only their still frame and licence.
Writes <batch>/<n>_<name>.jpg, <batch>/v<n>_<name>_<a>-<b>.mp4 and <batch>/meta.json (title, license, artist, credit, date, description, page url)."""
import json, os, re, sys, time, urllib.parse, urllib.request
API = 'https://commons.wikimedia.org/w/api.php'
UA = 'UnfrozenMusicBot/1.0 (https://github.com/Sangre-De-Drago/unfrozen-media; image research for a music blog)'
def get(params):
    params = dict(params, format='json', formatversion='2')
    req = urllib.request.Request(API + '?' + urllib.parse.urlencode(params), headers={'User-Agent': UA})
    for k in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as r: return json.load(r)
        except Exception as e:
            print('retry', e, file=sys.stderr); time.sleep(2 + 3 * k)
    return {}
def strip(html): return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', html or '')).strip()[:400]
def info(titles, width):
    out = []
    for i in range(0, len(titles), 40):
        d = get({'action': 'query', 'titles': '|'.join(titles[i:i + 40]), 'prop': 'imageinfo', 'iiprop': 'url|size|mime|extmetadata', 'iiurlwidth': width})
        for p in d.get('query', {}).get('pages', []):
            ii = (p.get('imageinfo') or [{}])[0]; em = ii.get('extmetadata', {}); mime = ii.get('mime', '')
            if not ii or not (mime.startswith('image/') or mime.startswith('video/') or mime.startswith('audio/') or mime == 'application/ogg'): continue
            out.append(dict(title=p['title'], mime=mime, duration=ii.get('duration'), thumb=ii.get('thumburl') or ii.get('url'), orig=ii.get('url'), w=ii.get('width'), h=ii.get('height'),
                            page=ii.get('descriptionurl'), license=strip(em.get('LicenseShortName', {}).get('value')),
                            artist=strip(em.get('Artist', {}).get('value')), credit=strip(em.get('Credit', {}).get('value')),
                            date=strip(em.get('DateTimeOriginal', {}).get('value')), desc=strip(em.get('ImageDescription', {}).get('value'))))
    return out
def search(q, n=60):
    d = get({'action': 'query', 'list': 'search', 'srsearch': q, 'srnamespace': 6, 'srlimit': n}); return [x['title'] for x in d.get('query', {}).get('search', [])]
def cat(c, n=200):
    t = []; subs = [c]
    d = get({'action': 'query', 'list': 'categorymembers', 'cmtitle': c, 'cmtype': 'subcat', 'cmlimit': 50})
    subs += [x['title'] for x in d.get('query', {}).get('categorymembers', [])]
    for s in subs:
        d = get({'action': 'query', 'list': 'categorymembers', 'cmtitle': s, 'cmtype': 'file', 'cmlimit': 200})
        t += [x['title'] for x in d.get('query', {}).get('categorymembers', [])]
        if len(t) >= n: break
    return t[:n], subs
def best_source(title):
    """a video's transcode of at most 1080 lines (largest), else the original"""
    d = get({'action': 'query', 'titles': title, 'prop': 'videoinfo', 'viprop': 'url|size|mime|derivatives|dimensions'})
    pages = d.get('query', {}).get('pages', [])
    vi = (pages[0].get('videoinfo') or [{}])[0] if pages else {}
    der = [x for x in vi.get('derivatives', []) if x.get('height') and x['height'] <= 1080 and 'video' in x.get('type', '')]
    if vi.get('url') and vi.get('height') and vi['height'] <= 1080: der.append(dict(src=vi['url'], height=vi['height'] + 0.5, type='video/original'))
    der.sort(key=lambda x: (x['height'], 'mp4' in x.get('type', '')))
    return der[-1]['src'] if der else vi.get('url')
def clip(title, rng, root, n):
    """cut [a, b] seconds of a Commons video to a silent H.264 mp4 of at most 1080 lines"""
    import subprocess, tempfile
    src = best_source(title)
    if not src: return dict(title=title, error='no source')
    tmp = tempfile.mktemp(suffix=os.path.splitext(urllib.parse.urlparse(src).path)[1] or '.webm')
    req = urllib.request.Request(src, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=600) as r, open(tmp, 'wb') as f:
        while True:
            b = r.read(1 << 20)
            if not b: break
            f.write(b)
    a, b = (rng.split('-') + [''])[:2] if rng else ('0', '60')
    name = re.sub(r'[^A-Za-z0-9._-]+', '_', title[5:])[:70]; fn = os.path.join(root, 'v%03d_%s_%s-%s.mp4' % (n, os.path.splitext(name)[0], a, b))
    for crf in (18, 22, 26):
        cmd = ['ffmpeg', '-y', '-loglevel', 'error', '-ss', a, '-i', tmp] + (['-t', str(float(b) - float(a))] if b else []) + \
              ['-an', '-vf', "scale=-2:'min(1080,ih)'", '-c:v', 'libx264', '-preset', 'slow', '-crf', str(crf), '-pix_fmt', 'yuv420p', '-movflags', '+faststart', fn]
        subprocess.run(cmd, check=True)
        if os.path.getsize(fn) < 90e6: break
    os.remove(tmp)
    return dict(title=title, clip=os.path.basename(fn), source=src, range=rng)
def frames(title, step, root, n):
    """a contact sheet of a Commons video: one 320 px frame every <step> seconds (at most 48), with the time on each; returns its duration"""
    import subprocess, tempfile
    src = best_source(title)
    if not src: return dict(title=title, error='no source')
    tmp = tempfile.mktemp(suffix=os.path.splitext(urllib.parse.urlparse(src).path)[1] or '.webm')
    req = urllib.request.Request(src, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=600) as r, open(tmp, 'wb') as f:
        while True:
            b = r.read(1 << 20)
            if not b: break
            f.write(b)
    dur = float(subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', tmp], capture_output=True, text=True).stdout.strip() or 0)
    step = max(float(step or 5), dur / 48.0)
    name = re.sub(r'[^A-Za-z0-9._-]+', '_', title[5:])[:70]; fn = os.path.join(root, 'f%03d_%s.jpg' % (n, os.path.splitext(name)[0]))
    subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-i', tmp, '-vf',
                    "fps=1/%.3f,scale=320:-2,tile=6x8" % step,
                    '-frames:v', '1', '-q:v', '4', fn], check=True)
    os.remove(tmp)
    return dict(title=title, sheet=os.path.basename(fn), duration=round(dur, 2), step=round(step, 2), source=src)
def audio(title, rng, root, n):
    """a Commons sound file (original), cut to seconds a..b and stored as 48 kHz FLAC"""
    import subprocess, tempfile
    d = get({'action': 'query', 'titles': title, 'prop': 'imageinfo', 'iiprop': 'url|mime'})
    pages = d.get('query', {}).get('pages', []); ii = (pages[0].get('imageinfo') or [{}])[0] if pages else {}
    src = ii.get('url')
    if not src: return dict(title=title, error='no source')
    tmp = tempfile.mktemp(suffix=os.path.splitext(urllib.parse.urlparse(src).path)[1] or '.ogg')
    req = urllib.request.Request(src, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=600) as r, open(tmp, 'wb') as f: f.write(r.read())
    a, b = (rng.split('-') + [''])[:2] if rng else ('0', '')
    name = re.sub(r'[^A-Za-z0-9._-]+', '_', title[5:])[:70]; fn = os.path.join(root, 'a%03d_%s.flac' % (n, os.path.splitext(name)[0]))
    cmd = ['ffmpeg', '-y', '-loglevel', 'error', '-ss', a or '0', '-i', tmp] + (['-t', str(float(b) - float(a or 0))] if b else []) + ['-ar', '48000', '-c:a', 'flac', fn]
    subprocess.run(cmd, check=True); os.remove(tmp)
    return dict(title=title, audio=os.path.basename(fn), source=src, range=rng)
TILESETS = {'usgs-imagery': 'https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/tile/{z}/{y}/{x}',
            'usgs-topo': 'https://basemap.nationalmap.gov/arcgis/rest/services/USGSTopo/MapServer/tile/{z}/{y}/{x}'}
def tiles(spec, root, n):
    """public-domain USGS National Map tiles stitched into one image: '<set> <z> <lat0> <lon0> <lat1> <lon1>'"""
    import math, io
    from PIL import Image
    ts, z, la0, lo0, la1, lo1 = spec.split(); z = int(z); la0, lo0, la1, lo1 = map(float, (la0, lo0, la1, lo1))
    def xy(lat, lon):
        k = 2 ** z; x = (lon + 180) / 360 * k; y = (1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * k; return x, y
    x0, y0 = xy(max(la0, la1), min(lo0, lo1)); x1, y1 = xy(min(la0, la1), max(lo0, lo1))
    tx0, ty0, tx1, ty1 = int(x0), int(y0), int(x1), int(y1)
    img = Image.new('RGB', ((tx1 - tx0 + 1) * 256, (ty1 - ty0 + 1) * 256)); miss = 0
    for ty in range(ty0, ty1 + 1):
        for tx in range(tx0, tx1 + 1):
            url = TILESETS[ts].format(z=z, x=tx, y=ty)
            try:
                req = urllib.request.Request(url, headers={'User-Agent': UA})
                with urllib.request.urlopen(req, timeout=60) as r: t = Image.open(io.BytesIO(r.read())).convert('RGB')
                img.paste(t, ((tx - tx0) * 256, (ty - ty0) * 256))
            except Exception as e: miss += 1
            time.sleep(0.05)
    fn = os.path.join(root, 'm%03d_%s_z%d.jpg' % (n, ts, z)); img.save(fn, quality=92)
    return dict(tiles=spec, file=os.path.basename(fn), origin_tile=[tx0, ty0], z=z, missing=miss,
                credit='USGS The National Map (public domain)')
def main(batch):
    root = os.path.join('src_img', batch); os.makedirs(root, exist_ok=True)
    width = 480; seen = []; meta = []; cats = {}; clips = []
    for line in open(os.path.join('src_img', 'requests', batch + '.txt'), encoding='utf-8'):
        line = line.strip()
        if not line or line.startswith('#') or ':' not in line: continue
        kind, val = [s.strip() for s in line.split(':', 1)]
        if kind == 'width': width = int(val); continue
        if kind == 'video':
            t, _, rng = [s.strip() for s in val.partition('|')]
            try: c = clip(t, rng, root, len(clips))
            except Exception as e: c = dict(title=t, error=str(e))
            c['from'] = line; clips.append(c); titles = [t]
        elif kind == 'frames':
            t, _, step = [s.strip() for s in val.partition('|')]
            try: c = frames(t, step, root, len(clips))
            except Exception as e: c = dict(title=t, error=str(e))
            c['from'] = line; clips.append(c); titles = [t]
        elif kind == 'audio':
            t, _, rng = [s_.strip() for s_ in val.partition('|')]
            try: c = audio(t, rng, root, len(clips))
            except Exception as e: c = dict(title=t, error=str(e))
            c['from'] = line; clips.append(c); titles = [t]
        elif kind == 'tiles':
            try: c = tiles(val, root, len(clips))
            except Exception as e: c = dict(tiles=val, error=str(e))
            c['from'] = line; clips.append(c); continue
        elif kind == 'search': titles = search(val)
        elif kind == 'cat': titles, subs = cat(val); cats[val] = subs
        elif kind == 'file': titles = [val]
        else: continue
        new = [t for t in titles if t not in seen]; seen += new
        for m in info(new, width): m['width_req'] = width; m['from'] = line; meta.append(m)
    for n, m in enumerate(meta):
        if not m.get('thumb') or (not m['mime'].startswith('image/') and m['thumb'] == m['orig']): m['error'] = 'no still'; continue
        name = re.sub(r'[^A-Za-z0-9._-]+', '_', m['title'][5:])[:80]; ext = os.path.splitext(urllib.parse.urlparse(m['thumb']).path)[1].lower() or '.jpg'
        fn = os.path.join(root, '%03d_%s%s' % (n, os.path.splitext(name)[0], ext))
        try:
            req = urllib.request.Request(m['thumb'], headers={'User-Agent': UA})
            with urllib.request.urlopen(req, timeout=120) as r, open(fn, 'wb') as f: f.write(r.read())
            m['file'] = os.path.basename(fn)
        except Exception as e: m['error'] = str(e)
        time.sleep(0.3)
    json.dump(dict(meta=meta, categories=cats, clips=clips), open(os.path.join(root, 'meta.json'), 'w'), indent=1, ensure_ascii=False)
    print(batch, len(meta), 'files')
if __name__ == '__main__':
    for b in sys.argv[1:]: main(b)
