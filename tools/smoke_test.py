"""Hit every source once for one occupation. Run: python -m tools.smoke_test [soc]"""
import sys, os
from dotenv import load_dotenv; load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
from .fred import fred_series; from .bls import bls_occupation; from .polymarket import polymarket_search; from .manifold import manifold_search
from .metaculus import metaculus_search; from .exposure import aioe_lookup, anthropic_index, onet_task_diff; from .epoch import epoch_recent; from .occupations import search_occupations; from .onet_ws import onet_occupation

soc = sys.argv[1] if len(sys.argv) > 1 else "11-2021"
print(f"occupation search 'product manager' → {[ (o['soc'], o['title'], o['exact']) for o in search_occupations('product manager', 3)]}")
for name, res in [
    ("FRED UNRATE", fred_series("UNRATE")), ("BLS OES", bls_occupation(soc)),
    ("Polymarket", polymarket_search("AGI", 3)), ("Manifold", manifold_search("AGI by 2030", 3)), ("Metaculus", metaculus_search("artificial general intelligence", 3)),
    ("AIOE", aioe_lookup(soc)), ("Anthropic Index", anthropic_index(soc)), ("O*NET tasks", onet_task_diff(soc)), ("Epoch", epoch_recent()), ("O*NET WS", onet_occupation(soc + ".00" if len(soc) == 7 else soc)),
]:
    status = "OK " if res.ok else "ERR"
    print(f"[{status}] {name:16} cards={len(res.cards):2d} unknowns={len(res.unknowns)} {('— '+res.error) if res.error else ''}")
    for c in res.cards[:2]: print(f"        · {c.claim[:110]}  [{c.value}] {c.source} {c.as_of or ''}")
