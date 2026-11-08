#!/usr/bin/env python
"""Throwaway READ-stage test: feed the 6105 discovery survivors (from scandir-rs Ext
mtime-at-discovery) into the REAL process_single_file from task1, /mnt/share, no DB."""
import os, json, time
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'draw_client.settings')
import django; django.setup()
from django.utils import timezone
from datetime import timedelta
from dicom_handler.export_services.task1_read_dicom_from_storage import process_single_file

FOLDER = "/mnt/share"
rel = json.load(open("/tmp/survivors.json"))
paths = [p if p.startswith("/") else os.path.join(FOLDER, p) for p in rel]

now = timezone.now()
date_filter = now - timedelta(days=7)
ten_min_ago = now - timedelta(minutes=10)
STUDY_DATE_FILTERING = False
EXCL_LOCALIZER = True
EXCL_SECONDARY = True
SIZE_CAP = 30 * 1024 * 1024  # 30 MB guard against stray videos

stats = {}
skipped_big = 0
t0 = time.perf_counter()
for p in paths:
    try:
        if os.path.getsize(p) > SIZE_CAP:
            skipped_big += 1
            continue
    except OSError:
        continue
    r = process_single_file((p, os.path.dirname(p), date_filter, now, ten_min_ago,
                             STUDY_DATE_FILTERING, EXCL_LOCALIZER, EXCL_SECONDARY))
    key = r['status'] if r['status'] != 'skipped' else 'skipped:' + r.get('reason', '?')
    key = key if r['status'] != 'error' else 'error:' + r.get('reason', '?')
    stats[key] = stats.get(key, 0) + 1
dt = time.perf_counter() - t0

print(f"FEED stage: {len(paths)} survivors, skipped >30MB: {skipped_big}")
print(f"process_single_file pass time: {dt:.2f}s\n")
print("Outcome breakdown:")
for k, v in sorted(stats.items(), key=lambda x: -x[1]):
    print(f"  {k:32s} {v}")
