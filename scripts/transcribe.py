import sys, json
from pywhispercpp.model import Model
m = Model(sys.argv[1], n_threads=4, print_progress=False, print_realtime=False)
out = {}
for w in sys.argv[2:]:
    segs = m.transcribe(w, language='en', max_len=42, split_on_word=True, token_timestamps=True)
    out[w] = [(s.t0/100, s.t1/100, s.text.strip()) for s in segs]
    print("==", w)
    for a,b,t in out[w]: print(f"{a:6.2f}-{b:6.2f}  {t}")
json.dump(out, open('segs_en.json','w'), ensure_ascii=False, indent=1)
