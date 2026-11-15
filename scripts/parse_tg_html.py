"""Parse Telegram Desktop HTML export into JSONL (no author names kept)."""
import sys, glob, json, re, html
from bs4 import BeautifulSoup
src, out = sys.argv[1], sys.argv[2]
CH = sys.argv[3] if len(sys.argv) > 3 else 'schengen_chat'
files = sorted(glob.glob(src + '/messages*.html'), key=lambda p: int(re.findall(r'messages(\d*)', p)[0] or 1))
n = 0
with open(out, 'w', encoding='utf-8') as f:
    for p in files:
        soup = BeautifulSoup(open(p, encoding='utf-8').read(), 'html.parser')
        for m in soup.select('div.message.default'):
            mid = int(m['id'].replace('message', ''))
            d = m.select_one('div.date.details')
            t = m.select_one('div.text')
            if not t: continue
            for br in t.find_all('br'): br.replace_with('\n')
            text = t.get_text().strip()
            if not text: continue
            r = m.select_one('div.reply_to a')
            reply = int(re.findall(r'\d+', r['href'])[0]) if r else None
            f.write(json.dumps({'id': mid, 'date': d['title'][:19] if d else None, 'reply_to': reply, 'text': text,
                                'link': f'https://t.me/{CH}/{mid}'}, ensure_ascii=False) + '\n'); n += 1
print(n)
