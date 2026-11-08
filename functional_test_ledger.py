#!/usr/bin/env python
"""Functional test for ExcludedFilePaths ledger + scandir-rs Ext scan in task1.
Runs read_dicom_from_storage() twice over the datastore with an early pull date so all
files are in-window; verifies run 2 skips already-imported (instance_path) AND
already-excluded (ledger) files without re-reading them. Dev DB only."""
import os, logging, collections
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'draw_client.settings')
import django; django.setup()
from datetime import datetime, timezone as pytz
from django.utils import timezone
from dicom_handler.models import (SystemConfiguration, Patient, DICOMStudy, DICOMSeries,
                                  DICOMInstance, ExcludedFilePaths)
from dicom_handler.export_services.task1_read_dicom_from_storage import read_dicom_from_storage

# quiet the noise (pydicom warnings + task INFO spam)
for n in ('dicom_handler', 'pydicom'):
    logging.getLogger(n).setLevel(logging.ERROR)

DATASTORE = "/mnt/share/dicom_processing_test/datastore"

def reset_config():
    c = SystemConfiguration.get_singleton()
    c.folder_configuration = DATASTORE
    c.data_pull_start_datetime = datetime(2020, 1, 1, tzinfo=pytz.utc)
    c.study_date_based_filtering = False
    c.exclude_localizer_series = True
    c.exclude_secondary_capture = True
    c.save()

def wipe():
    DICOMInstance.objects.all().delete()
    DICOMSeries.objects.all().delete()
    DICOMStudy.objects.all().delete()
    Patient.objects.all().delete()
    ExcludedFilePaths.objects.all().delete()

def run(label):
    import time
    reset_config()
    t = time.time()
    res = read_dicom_from_storage()
    dt = time.time() - t
    reasons = collections.Counter(ExcludedFilePaths.objects.values_list('reason', flat=True))
    print(f"\n=== {label} ===  ({dt:.1f}s)")
    print(f"  processed={res.get('processed_files')} skipped={res.get('skipped_files')} "
          f"errors={res.get('error_files')} status={res.get('status')}")
    print(f"  DICOMInstance rows={DICOMInstance.objects.count()}")
    print(f"  ExcludedFilePaths rows={ExcludedFilePaths.objects.count()}  by reason={dict(reasons)}")
    return res, dt

if __name__ == "__main__":
    print("Cleaning DB for a clean functional test...")
    wipe()

    r1, d1 = run("RUN 1 (cold): import + record rejections")
    # undo the auto-advance so RUN 2 uses the same early window -> exercises the ledger,
    # not the mtime window. Imported rows stay (exercise instance_path exclusion).
    print("\nRe-setting pull date (undo auto-advance) + clearing checkpoint, keeping imported rows...")
    reset_config()
    from dicom_handler.export_services.task1_read_dicom_from_storage import clear_checkpoint
    clear_checkpoint()

    r2, d2 = run("RUN 2 (warm): same window -> nothing should be re-read")

    print("\n" + "="*60)
    print("VERDICT")
    print("="*60)
    rej1 = ExcludedFilePaths.objects.count()
    reprocessed = r2.get('processed_files', 0)
    print(f"Rejections recorded by RUN 1 : {rej1}")
    print(f"Files (re)processed by RUN 2 : {reprocessed}")
    print("OK: ledger + instance_path prevented re-read" if reprocessed == 0
          else "CHECK: RUN 2 reprocessed files that should have been skipped")
