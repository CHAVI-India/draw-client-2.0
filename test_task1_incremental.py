#!/usr/bin/env python
"""
Incremental test script for task1_read_dicom_from_storage.py
Tests both implementations WITHOUT clearing the database.
This simulates real-world incremental runs where most files are already processed.
"""

import os
import sys
import django
from pathlib import Path
import time

# Add the project root to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'draw_client.settings')
django.setup()

# Now import Django models
from dicom_handler.models import SystemConfiguration, Patient, DICOMStudy, DICOMSeries, DICOMInstance
from datetime import datetime
from django.utils import timezone
from django.db import connection

def print_database_state():
    """
    Print current state of the database
    """
    print("\n" + "="*50)
    print("CURRENT DATABASE STATE")
    print("="*50)
    
    patients = Patient.objects.all()
    studies = DICOMStudy.objects.all()
    series = DICOMSeries.objects.all()
    instances = DICOMInstance.objects.all()
    
    print(f"Patients: {patients.count()}")
    print(f"Studies: {studies.count()}")
    print(f"Series: {series.count()}")
    print(f"Instances: {instances.count()}")
    print("="*50)

def get_query_count():
    """Get number of database queries executed"""
    return len(connection.queries)

def reset_query_count():
    """Reset the query counter"""
    connection.queries_log.clear()

def test_implementation(implementation_name, module_path, original_date_filter):
    """
    Test a specific implementation WITHOUT clearing database
    
    Args:
        implementation_name: Name of the implementation (for display)
        module_path: Python module path to import from
        original_date_filter: Original date filter to restore after test
    """
    print("\n" + "="*70)
    print(f"TESTING: {implementation_name} (Incremental Run)")
    print("="*70)
    
    # Import the specific implementation
    if implementation_name == "ORIGINAL":
        from dicom_handler.export_services.task1_read_dicom_from_storage_original import read_dicom_from_storage
    else:
        from dicom_handler.export_services.task1_read_dicom_from_storage import read_dicom_from_storage
    
    # Show current database state
    print_database_state()
    
    # Temporarily set date filter to a very old date to process all files
    config = SystemConfiguration.get_singleton()
    from datetime import datetime
    config.data_pull_start_datetime = timezone.make_aware(datetime(2000, 1, 1))
    config.save()
    print(f"\n📅 Temporarily set date filter to: {config.data_pull_start_datetime}")
    print("   (This ensures all files will be checked for processing)\n")
    
    # Reset query counter
    reset_query_count()
    initial_query_count = get_query_count()
    
    # Run the function
    print(f"Running {implementation_name} implementation on existing database...")
    start_time = time.time()
    result = read_dicom_from_storage()
    end_time = time.time()
    
    # Restore original date filter
    config.data_pull_start_datetime = original_date_filter
    config.save()
    
    processing_time = end_time - start_time
    final_query_count = get_query_count()
    total_queries = final_query_count - initial_query_count
    
    # Display results
    print(f"\n" + "-"*70)
    print(f"RESULTS - {implementation_name}")
    print("-"*70)
    print(f"⏱️  Processing time: {processing_time:.2f} seconds")
    print(f"📊 Database queries: {total_queries}")
    print(f"✅ Status: {result.get('status', 'Unknown')}")
    print(f"📁 Processed files: {result.get('processed_files', 0)}")
    print(f"⏭️  Skipped files: {result.get('skipped_files', 0)}")
    print(f"❌ Error files: {result.get('error_files', 0)}")
    print(f"📦 Series found: {len(result.get('series_data', []))}")
    
    if result.get('status') == 'error':
        print(f"❌ Error message: {result.get('message', 'No message')}")
    
    # Show database state after processing
    print_database_state()
    
    return {
        'name': implementation_name,
        'time': processing_time,
        'queries': total_queries,
        'status': result.get('status'),
        'processed': result.get('processed_files', 0),
        'skipped': result.get('skipped_files', 0),
        'errors': result.get('error_files', 0),
        'series': len(result.get('series_data', []))
    }

def print_comparison(results):
    """
    Print comparison table of both implementations
    """
    print("\n" + "="*70)
    print("INCREMENTAL RUN PERFORMANCE COMPARISON")
    print("="*70)
    
    if len(results) != 2:
        print("Need both implementations to compare")
        return
    
    original = results[0]
    optimized = results[1]
    
    print(f"\n{'Metric':<25} {'Original':<20} {'Optimized':<20} {'Improvement'}")
    print("-"*70)
    
    # Time comparison
    time_improvement = ((original['time'] - optimized['time']) / original['time'] * 100) if original['time'] > 0 else 0
    print(f"{'Processing Time':<25} {original['time']:.2f}s{'':<14} {optimized['time']:.2f}s{'':<14} {time_improvement:+.1f}%")
    
    # Query comparison
    query_improvement = ((original['queries'] - optimized['queries']) / original['queries'] * 100) if original['queries'] > 0 else 0
    print(f"{'Database Queries':<25} {original['queries']:<20} {optimized['queries']:<20} {query_improvement:+.1f}%")
    
    # Files processed
    print(f"{'Files Processed':<25} {original['processed']:<20} {optimized['processed']:<20}")
    print(f"{'Files Skipped':<25} {original['skipped']:<20} {optimized['skipped']:<20}")
    print(f"{'Files with Errors':<25} {original['errors']:<20} {optimized['errors']:<20}")
    print(f"{'Series Found':<25} {original['series']:<20} {optimized['series']:<20}")
    
    print("\n" + "="*70)
    print("INCREMENTAL RUN ANALYSIS:")
    print("="*70)
    
    if time_improvement > 0:
        print(f"✅ Optimized version is {time_improvement:.1f}% faster!")
        print(f"   Time saved: {original['time'] - optimized['time']:.2f}s")
    elif time_improvement < 0:
        print(f"⚠️  Optimized version is {abs(time_improvement):.1f}% slower")
    else:
        print("⚠️  Both versions have similar performance")
    
    if query_improvement > 0:
        print(f"✅ Optimized version uses {query_improvement:.1f}% fewer database queries!")
        print(f"   Queries saved: {original['queries'] - optimized['queries']}")
    elif query_improvement < 0:
        print(f"⚠️  Optimized version uses {abs(query_improvement):.1f}% more database queries")
    
    # Highlight the key benefit for incremental runs
    if original['skipped'] > 0:
        print(f"\n💡 KEY INSIGHT:")
        print(f"   With {original['skipped']} files already in database,")
        print(f"   the optimized version's path-based filtering provides")
        print(f"   significant performance gains on incremental runs.")
    
    print("="*70)

def main():
    """
    Main test function
    """
    print("="*70)
    print("DICOM FILE READER - INCREMENTAL RUN TEST")
    print("Testing on existing database WITHOUT clearing data")
    print("="*70)
    
    try:
        # Check system configuration
        config = SystemConfiguration.get_singleton()
        if not config or not config.folder_configuration:
            print("❌ No system configuration found. Please configure the system first.")
            return
        
        print(f"\n✓ Configured folder: {config.folder_configuration}")
        print(f"✓ Date filter: {config.data_pull_start_datetime}")
        
        # Check if folder exists
        if not os.path.exists(config.folder_configuration):
            print(f"❌ Folder does not exist: {config.folder_configuration}")
            return
        
        # Count files in folder
        file_count = sum(len(files) for _, _, files in os.walk(config.folder_configuration))
        print(f"✓ Found {file_count} files in configured folder")
        
        if file_count == 0:
            print("⚠️  No files found. Please add DICOM files to test.")
            return
        
        # Show current database state
        print_database_state()
        
        # Enable query logging
        from django.conf import settings
        settings.DEBUG = True
        
        # Save original date filter to restore after tests
        original_date_filter = config.data_pull_start_datetime
        
        results = []
        
        # Test original implementation
        result1 = test_implementation("ORIGINAL", "task1_read_dicom_from_storage_original", original_date_filter)
        results.append(result1)
        
        # Test optimized implementation
        result2 = test_implementation("OPTIMIZED", "task1_read_dicom_from_storage", original_date_filter)
        results.append(result2)
        
        # Ensure date filter is restored
        config.refresh_from_db()
        print(f"\n✅ Date filter restored to: {config.data_pull_start_datetime}")
        
        # Print comparison
        print_comparison(results)
        
        print(f"\n" + "="*70)
        print("INCREMENTAL TEST COMPLETED")
        print("="*70)
        
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
