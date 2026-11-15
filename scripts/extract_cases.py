"""Rule-based extraction of visa cases from #статистика messages."""
import json, re, sys
from datetime import date
S = json.load(open(sys.argv[1], encoding='utf-8'))
C = {'IT': r'итал|italy|vms', 'ES': r'испан|bls', 'FR': r'франц|france', 'GR': r'грец|грек', 'HU': r'венгр',
     'DE': r'герман', 'BG': r'болгар', 'NL': r'нидерл', 'CH': r'швейц', 'CY': r'кипр', 'FI': r'финл'}
CITY = {'Москва': r'москв|мск', 'Санкт-Петербург': r'спб|петербург|питер', 'Екатеринбург': r'екатеринб',
        'Казань': r'казан', 'Новосибирск': r'новосиб', 'Краснодар': r'краснодар'}
MON = {'январ':1,'феврал':2,'март':3,'апрел':4,'ма[йя]':5,'июн':6,'июл':7,'август':8,'сентябр':9,'октябр':10,'ноябр':11,'декабр':12}
def dates(t, year):
    out = []
    for m in re.finditer(r'(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?', t):
        d, mo, y = int(m[1]), int(m[2]), m[3]
        y = int(y) + (2000 if y and len(y) == 2 else 0) if y else year
        try: out.append((m.start(), date(y, mo, d)))
        except ValueError: pass
    for m in re.finditer(r'(\d{1,2})\s+(' + '|'.join(MON) + r')\w*', t):
        mo = next(v for k, v in MON.items() if re.match(k, m[2]))
        try: out.append((m.start(), date(year, mo, int(m[1]))))
        except ValueError: pass
    return sorted(out)
cases = []
for m in S:
    t = m['text'].lower(); post = date(int(m['date'][6:10]), int(m['date'][3:5]), int(m['date'][:2]))
    country = next((k for k, v in C.items() if re.search(v, t)), None)
    city = next((k for k, v in CITY.items() if re.search(v, t)), None)
    outcome = 'refused' if re.search(r'отказ', t) and not re.search(r'без отказ|отказов не', t) else \
              'approved' if re.search(r'выдал|вклеил|одобр|дали|получ|готов', t) else None
    sub = re.search(r'(подач|подал|подавал|сдал|сдавал|био)', t)
    ds = [d for _, d in dates(t, post.year) if d <= post]
    submitted = None
    if sub:
        after = [d for p, d in dates(t, post.year) if p > sub.start() and d <= post]
        submitted = after[0] if after else None
    if submitted and submitted > post: submitted = submitted.replace(year=submitted.year - 1)
    decided = max(ds) if ds else None
    days = (decided - submitted).days if submitted and decided and decided > submitted else None
    mdays = re.search(r'(\d{2,3})\s*(?:календарн\w*\s*)?(?:дн|день)', t)
    if not days and mdays: days = int(mdays[1])
    multi = 'multiple' if re.search(r'мульт|многократ', t) else 'single' if re.search(r'однократ|под даты|строго', t) else None
    cases.append({'id': m['id'], 'posted': str(post), 'country': country, 'city': city, 'outcome': outcome,
                  'submitted': str(submitted) if submitted else None, 'processing_days': days, 'entries': multi,
                  'link': m['link'], 'text': m['text'][:600]})
json.dump(cases, open(sys.argv[2], 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
f = lambda k: sum(c[k] is not None for c in cases)
print(len(cases), {k: f(k) for k in ['country', 'city', 'outcome', 'submitted', 'processing_days', 'entries']})
full = [c for c in cases if c['country'] and c['outcome'] and c['processing_days']]
print('country+outcome+days:', len(full))
import collections, statistics
by = collections.defaultdict(list)
for c in full:
    if 3 <= c['processing_days'] <= 150: by[c['country']].append(c['processing_days'])
for k, v in sorted(by.items(), key=lambda x: -len(x[1])): print(k, len(v), 'median', statistics.median(v))
