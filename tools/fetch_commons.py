"""Fetch freely licensed images from Wikimedia Commons into src_img/<batch>/ (run by .github/workflows/fetch-commons.yml).
Request file src_img/requests/<batch>.txt, one entry per line:
  search: <query>            files found by Commons search (namespace File)
  cat: <Category:Name>       files in the category (and its direct subcategories)
  file: <File:Name.jpg>      one file at full width
  width: <px>                thumb width for the lines that follow (default 480)
Writes <batch>/<n>_<name>.jpg and <batch>/meta.json (title, license, artist, credit, date, description, page url)."""
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
            ii = (p.get('imageinfo') or [{}])[0]; em = ii.get('extmetadata', {})
            if not ii or not ii.get('mime', '').startswith('image/'): continue
            out.append(dict(title=p['title'], thumb=ii.get('thumburl') or ii.get('url'), orig=ii.get('url'), w=ii.get('width'), h=ii.get('height'),
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
def main(batch):
    root = os.path.join('src_img', batch); os.makedirs(root, exist_ok=True)
    width = 480; seen = []; meta = []; cats = {}
    for line in open(os.path.join('src_img', 'requests', batch + '.txt'), encoding='utf-8'):
        line = line.strip()
        if not line or line.startswith('#') or ':' not in line: continue
        kind, val = [s.strip() for s in line.split(':', 1)]
        if kind == 'width': width = int(val); continue
        if kind == 'search': titles = search(val)
        elif kind == 'cat': titles, subs = cat(val); cats[val] = subs
        elif kind == 'file': titles = [val]
        else: continue
        new = [t for t in titles if t not in seen]; seen += new
        for m in info(new, width): m['width_req'] = width; m['from'] = line; meta.append(m)
    for n, m in enumerate(meta):
        name = re.sub(r'[^A-Za-z0-9._-]+', '_', m['title'][5:])[:80]; ext = os.path.splitext(urllib.parse.urlparse(m['thumb']).path)[1].lower() or '.jpg'
        fn = os.path.join(root, '%03d_%s%s' % (n, os.path.splitext(name)[0], ext))
        try:
            req = urllib.request.Request(m['thumb'], headers={'User-Agent': UA})
            with urllib.request.urlopen(req, timeout=120) as r, open(fn, 'wb') as f: f.write(r.read())
            m['file'] = os.path.basename(fn)
        except Exception as e: m['error'] = str(e)
        time.sleep(0.3)
    json.dump(dict(meta=meta, categories=cats), open(os.path.join(root, 'meta.json'), 'w'), indent=1, ensure_ascii=False)
    print(batch, len(meta), 'files')
if __name__ == '__main__':
    for b in sys.argv[1:]: main(b)
