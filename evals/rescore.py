"""Rescore 'uncited' from exported briefs for a results file (used after a scorer fix): python -m evals.rescore evals/results/<file>.json"""
import json, re, sys
from pathlib import Path
path = Path(sys.argv[1]); data = json.loads(path.read_text())
for r in data["results"]:
    if not r.get("exported"): continue
    body = Path(r["exported"]).read_text().split("\n---\n")[0]
    r["uncited_final"] = len([l for l in body.split("\n") if l.strip() and not l.startswith(("#", ">", "_")) and not re.search(r"\[[cu]\d{2}\]", l)])
    r["checks"]["zero_uncited"] = r["uncited_final"] == 0; r["pass"] = all(r["checks"].values())
data["summary"]["passed"] = sum(r["pass"] for r in data["results"]); path.write_text(json.dumps(data, indent=2))
print(f"{data['summary']['passed']}/{data['summary']['total']} pass after rescore"); [print(f"  {r['id']} {'PASS' if r['pass'] else 'FAIL ' + str([k for k,v in r['checks'].items() if not v])}") for r in data["results"]]
