#!/usr/bin/env python
"""
Check if DICOMSeries.instance_count field matches actual DICOMInstance count
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
print("CHECKING DICOMSeries.instance_count FIELD vs ACTUAL DICOMInstance COUNT")
print("="*80)
print()

# Get total actual instance count
total_actual_instances = DICOMInstance.objects.count()
print(f"Total DICOMInstance records in database: {total_actual_instances}")
print()

# Get all series
series_list = DICOMSeries.objects.all().order_by('series_instance_uid')
print(f"Total DICOMSeries records: {series_list.count()}")
print()

total_from_field = 0
total_actual = 0
mismatches = []

print("="*80)
print("SERIES-BY-SERIES COMPARISON")
print("="*80)

for idx, series in enumerate(series_list, 1):
    # Get the instance_count field value
    field_count = series.instance_count if series.instance_count is not None else 0
    
    # Get actual count from DICOMInstance table
    actual_count = DICOMInstance.objects.filter(series_instance_uid=series).count()
    
    total_from_field += field_count
    total_actual += actual_count
    
    match = "✅" if field_count == actual_count else "❌"
    
    print(f"\n{match} Series {idx}: {series.series_instance_uid[:50]}...")
    print(f"   DICOMSeries.instance_count field: {field_count}")
    print(f"   Actual DICOMInstance count:       {actual_count}")
    print(f"   Difference:                       {actual_count - field_count}")
    print(f"   series_files_fully_read:          {series.series_files_fully_read}")
    
    if field_count != actual_count:
        mismatches.append({
            'series_uid': series.series_instance_uid,
            'field_count': field_count,
            'actual_count': actual_count,
            'difference': actual_count - field_count
        })

print()
print("="*80)
print("SUMMARY")
print("="*80)
print(f"Sum of all DICOMSeries.instance_count fields: {total_from_field}")
print(f"Actual total DICOMInstance records:           {total_actual}")
print(f"Difference:                                   {total_actual - total_from_field}")
print()

if mismatches:
    print(f"❌ Found {len(mismatches)} series with MISMATCHED counts:")
    print()
    for m in mismatches:
        print(f"   Series: {m['series_uid'][:60]}...")
        print(f"      Field value: {m['field_count']}")
        print(f"      Actual count: {m['actual_count']}")
        print(f"      Difference: {m['difference']}")
        print()
else:
    print("✅ All series have matching instance counts!")

print("="*80)
