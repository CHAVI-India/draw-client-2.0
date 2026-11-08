#!/usr/bin/env python
"""Throwaway discovery benchmark on /mnt/share: scandir-rs Ext (mtime-at-discovery)
vs os.walk + per-file os.stat. Read-only, no DB.
"""
import os, time, sys
from datetime import datetime, timedelta
from scandir_rs import Scandir, Walk, ReturnType

FOLDER = "/mnt/share"
NOW_EPOCH = time.time()
TEN_MIN_AGO = NOW_EPOCH - 10*60
# current pull window from DB (now - 7d). Use a fixed epoch for the two approaches.
DATE_FILTER_EPOCH = NOW_EPOCH - 7*24*60*60

def optimized_scandir(folder, skip_hidden):
    """mtime filter done AT DISCOVERY via scandir Ext. No os.stat."""
    t0 = time.perf_counter()
    survivors = {}
    total = skipped_recent = skipped_olddate = 0
    for entry in Scandir(folder, return_type=ReturnType.Ext, skip_hidden=skip_hidden):
        if not entry.is_file:
            continue
        total += 1
        mt = entry.mtime
        if mt > TEN_MIN_AGO:
            skipped_recent += 1; continue
        if mt < DATE_FILTER_EPOCH:
            skipped_olddate += 1; continue
        survivors[entry.path] = mt
    return dict(total=total, survivors=survivors, skipped_recent=skipped_recent,
                skipped_olddate=skipped_olddate, secs=time.perf_counter()-t0)

def baseline_walk(folder):
    """Current model: Walk enumerates paths, then os.stat per file to filter."""
    t0 = time.perf_counter()
    all_files = []
    for root, dirs, files in Walk(folder):
        for f in files:
            all_files.append(os.path.join(root, f) if root else f)
    t_enum = time.perf_counter() - t0
    t1 = time.perf_counter()
    survivors = {}
    skipped_recent = skipped_olddate = 0
    for p in all_files:
        try:
            mt = os.stat(os.path.join(folder, p) if not p.startswith(folder) else p).st_mtime
        except OSError:
            continue
        if mt > TEN_MIN_AGO:
            skipped_recent += 1; continue
        if mt < DATE_FILTER_EPOCH:
            skipped_olddate += 1; continue
        survivors[p] = mt
    t_stat = time.perf_counter() - t1
    return dict(total=len(all_files), survivors=survivors, skipped_recent=skipped_recent,
                skipped_olddate=skipped_olddate, enum_secs=t_enum, stat_secs=t_stat,
                secs=t_enum+t_stat)

print("=== OPTIMIZED (scandir-rs Ext, skip_hidden=False) ===", flush=True)
o = optimized_scandir(FOLDER, skip_hidden=False)
print(f"total_files={o['total']}  time={o['secs']:.2f}s")
print(f"  skip_recent(<10min)={o['skipped_recent']}  skip_olddate={o['skipped_olddate']}  SURVIVORS->dcmread={len(o['survivors'])}", flush=True)

print("\n=== OPTIMIZED (scandir-rs Ext, skip_hidden=True) ===", flush=True)
oh = optimized_scandir(FOLDER, skip_hidden=True)
print(f"total_files={oh['total']}  time={oh['secs']:.2f}s  SURVIVORS={len(oh['survivors'])} "
      f"(pruned {o['total']-oh['total']} hidden entries)", flush=True)

print("\n=== BASELINE (os.walk enum + per-file os.stat) ===", flush=True)
b = baseline_walk(FOLDER)
print(f"total_files={b['total']}  enum={b['enum_secs']:.2f}s  os.stat_pass={b['stat_secs']:.2f}s  TOTAL={b['secs']:.2f}s")
print(f"  skip_recent={b['skipped_recent']}  skip_olddate={b['skipped_olddate']}  SURVIVORS={len(b['survivors'])}", flush=True)

# correctness: survivor sets must match (ignoring hidden prune which is a deliberate behavior change)
same = set(o['survivors']) == set(b['survivors'])
print(f"\nCORRECTNESS: optimized(non-hidden) survivor set == baseline survivor set: {same}")
if not same:
    print("  only-in-optimized:", len(set(o['survivors'])-set(b['survivors'])),
          " only-in-baseline:", len(set(b['survivors'])-set(o['survivors'])))

# save survivor list for the dcmread stage
import json
with open("/tmp/survivors.json","w") as f:
    json.dump(list(o['survivors'].keys())[:200000], f)
print(f"\nSURVIVOR paths saved (up to 200k) for the read/dcmread stage: {min(len(o['survivors']),200000)}")
