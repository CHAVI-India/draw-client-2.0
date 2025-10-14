#!/usr/bin/env python
"""
Diagnostic script to check instance count discrepancies
"""
import os
import sys
import django

# Setup Django
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'draw_client.settings')
django.setup()

from dicom_handler.models import DICOMSeries, DICOMInstance

print("="*80)
print("INSTANCE COUNT VERIFICATION")
print("="*80)
print()

series_list = DICOMSeries.objects.all().order_by('series_instance_uid')

total_series_instance_count = 0
total_actual_instance_count = 0
mismatches = []

for series in series_list:
    # Get the instance_count field from the series
    series_instance_count = series.instance_count or 0
    
    # Get actual count from DICOMInstance table
    actual_instance_count = DICOMInstance.objects.filter(
        series_instance_uid=series
    ).count()
    
    total_series_instance_count += series_instance_count
    total_actual_instance_count += actual_instance_count
    
    match_status = "✅" if series_instance_count == actual_instance_count else "❌"
    
    print(f"{match_status} Series: {series.series_instance_uid[:30]}...")
    print(f"   series.instance_count field: {series_instance_count}")
    print(f"   Actual DICOMInstance count:  {actual_instance_count}")
    print(f"   series_files_fully_read:     {series.series_files_fully_read}")
    
    if series_instance_count != actual_instance_count:
        mismatches.append({
            'series_uid': series.series_instance_uid,
            'series_count': series_instance_count,
            'actual_count': actual_instance_count,
            'difference': actual_instance_count - series_instance_count
        })
    print()

print("="*80)
print("SUMMARY")
print("="*80)
print(f"Total series.instance_count sum:  {total_series_instance_count}")
print(f"Total actual DICOMInstance count: {total_actual_instance_count}")
print(f"Difference:                       {total_actual_instance_count - total_series_instance_count}")
print()

if mismatches:
    print(f"⚠️  Found {len(mismatches)} series with mismatched counts:")
    for m in mismatches:
        print(f"   - {m['series_uid'][:40]}... : series_count={m['series_count']}, actual={m['actual_count']}, diff={m['difference']}")
else:
    print("✅ All series have matching instance counts!")
