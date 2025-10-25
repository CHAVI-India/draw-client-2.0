#!/usr/bin/env python
"""
Incremental test script for task1_read_dicom_from_storage.py
Tests both implementations WITHOUT clearing the database.
This simulates real-world incremental runs where most files are already processed.

IMPORTANT: This test uses a SEPARATE TEST DATABASE that is automatically created
and destroyed. Your production database will NOT be affected.
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

# Now import Django models and test utilities
from dicom_handler.models import SystemConfiguration, Patient, DICOMStudy, DICOMSeries, DICOMInstance
from datetime import datetime, timedelta
from django.utils import timezone
from django.db import connection
from django.test.utils import setup_test_environment, teardown_test_environment
from django.db import connections
from django.conf import settings

# Global variable to track test database
_test_db_name = None

def create_test_database():
    """
    Create a separate test database for testing
    Returns the test database name
    """
    global _test_db_name
    
    print("\n" + "="*70)
    print("CREATING SEPARATE TEST DATABASE")
    print("="*70)
    
    # Setup test environment
    setup_test_environment()
    
    # Get the default database connection
    connection = connections['default']
    
    # Create test database
    _test_db_name = connection.creation.create_test_db(
        verbosity=1,
        autoclobber=True,  # Automatically remove old test database if exists
        keepdb=False
    )
    
    print(f"✓ Test database created: {_test_db_name}")
    print(f"✓ Production database is safe and untouched")
    print("="*70)
    
    return _test_db_name

def destroy_test_database():
    """
    Destroy the test database after testing
    """
    global _test_db_name
    
    if _test_db_name is None:
        return
    
    print("\n" + "="*70)
    print("DESTROYING TEST DATABASE")
    print("="*70)
    
    # Get the default database connection
    connection = connections['default']
    
    # Destroy test database
    connection.creation.destroy_test_db(_test_db_name, verbosity=1)
    
    # Teardown test environment
    teardown_test_environment()
    
    print(f"✓ Test database destroyed: {_test_db_name}")
    print(f"✓ Production database remains unchanged")
    print("="*70)
    
    _test_db_name = None

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

def test_study_date_filtering(original_date_filter):
    """
    Test study date-based filtering feature
    Prompts user for a cutoff date and compares results with filtering ON vs OFF
    
    Args:
        original_date_filter: Original date filter to restore after test
    """
    print("\n" + "="*70)
    print("STUDY DATE FILTERING TEST")
    print("="*70)
    
    from dicom_handler.export_services.task1_read_dicom_from_storage import read_dicom_from_storage
    from datetime import datetime
    
    config = SystemConfiguration.get_singleton()
    
    # Prompt user for cutoff date
    print("\nEnter the STUDY DATE cutoff for filtering.")
    print("Studies with DICOM Study Dates BEFORE this cutoff will be filtered out.")
    print("\nOptions:")
    print("  1. Enter number of days ago (e.g., 210 for 7 months)")
    print("  2. Enter specific date (YYYY-MM-DD format)")
    print("  3. Press Enter to use 7 months ago (210 days)")
    
    user_input = input("\nYour choice: ").strip()
    
    if not user_input:
        # Default: 7 months ago
        cutoff_date = timezone.now() - timedelta(days=210)
        print(f"Using default: 7 months ago")
    elif user_input.isdigit():
        # User entered number of days
        days = int(user_input)
        cutoff_date = timezone.now() - timedelta(days=days)
        print(f"Using: {days} days ago")
    else:
        # User entered a specific date
        try:
            parsed_date = datetime.strptime(user_input, '%Y-%m-%d')
            cutoff_date = timezone.make_aware(parsed_date)
            print(f"Using specific date: {user_input}")
        except ValueError:
            print(f"Invalid date format. Using default: 7 months ago")
            cutoff_date = timezone.now() - timedelta(days=210)
    
    # Set data_pull_start_datetime to year 2000 to allow all files through
    # This is the same approach used in the main incremental test
    very_old_date = timezone.make_aware(datetime(2000, 1, 1))
    config.data_pull_start_datetime = very_old_date
    config.save()
    
    print(f"\n📅 File modification time filter set to: {very_old_date.date()}")
    print(f"   (This ensures ALL files pass the modification time check)")
    print(f"\n📅 Study Date cutoff will be: {cutoff_date.date()}")
    print(f"   (We'll compare study dates against this cutoff)")
    
    # Store the cutoff_date for later use in study date comparison
    # We'll need to temporarily change data_pull_start_datetime before each test run
    study_date_cutoff = cutoff_date
    
    # Clear the database for a fresh run
    print("\n" + "-"*70)
    print("CLEARING DATABASE FOR FRESH TEST RUN")
    print("-"*70)
    
    initial_counts = {
        'patients': Patient.objects.count(),
        'studies': DICOMStudy.objects.count(),
        'series': DICOMSeries.objects.count(),
        'instances': DICOMInstance.objects.count()
    }
    
    print(f"\nBefore clearing:")
    print(f"  Patients: {initial_counts['patients']}")
    print(f"  Studies: {initial_counts['studies']}")
    print(f"  Series: {initial_counts['series']}")
    print(f"  Instances: {initial_counts['instances']}")
    
    # Delete all records
    DICOMInstance.objects.all().delete()
    DICOMSeries.objects.all().delete()
    DICOMStudy.objects.all().delete()
    Patient.objects.all().delete()
    
    print(f"\n✓ Database cleared - ready for fresh test run")
    
    # Store initial database state (should be 0 for all)
    initial_state = {
        'patients': Patient.objects.count(),
        'studies': DICOMStudy.objects.count(),
        'series': DICOMSeries.objects.count(),
        'instances': DICOMInstance.objects.count()
    }
    
    print(f"\nInitial database state (after clearing):")
    print(f"  Patients: {initial_state['patients']}")
    print(f"  Studies: {initial_state['studies']}")
    print(f"  Series: {initial_state['series']}")
    print(f"  Instances: {initial_state['instances']}")
    
    # ===== TEST 1: Filtering DISABLED =====
    print("\n" + "-"*70)
    print("TEST 1: Study Date Filtering DISABLED")
    print("-"*70)
    
    # For TEST 1: Keep data_pull_start_datetime at year 2000
    # This allows all files through (no filtering)
    config.study_date_based_filtering = False
    config.save()
    print(f"Study date filtering: {config.study_date_based_filtering}")
    print(f"Date filter: {config.data_pull_start_datetime.date()} (year 2000 - allows all files)")
    
    print("\nRunning task...")
    start_time = time.time()
    result_without_filter = read_dicom_from_storage()
    time_without_filter = time.time() - start_time
    
    print(f"\n⏱️  Processing time: {time_without_filter:.2f} seconds")
    print(f"✅ Status: {result_without_filter.get('status')}")
    print(f"📁 Processed files: {result_without_filter.get('processed_files', 0)}")
    print(f"⏭️  Skipped files: {result_without_filter.get('skipped_files', 0)}")
    print(f"❌ Error files: {result_without_filter.get('error_files', 0)}")
    
    state_without_filter = {
        'patients': Patient.objects.count(),
        'studies': DICOMStudy.objects.count(),
        'series': DICOMSeries.objects.count(),
        'instances': DICOMInstance.objects.count()
    }
    
    print(f"\nDatabase state after processing:")
    print(f"  Patients: {state_without_filter['patients']} (added: {state_without_filter['patients'] - initial_state['patients']})")
    print(f"  Studies: {state_without_filter['studies']} (added: {state_without_filter['studies'] - initial_state['studies']})")
    print(f"  Series: {state_without_filter['series']} (added: {state_without_filter['series'] - initial_state['series']})")
    print(f"  Instances: {state_without_filter['instances']} (added: {state_without_filter['instances'] - initial_state['instances']})")
    
    # ===== TEST 2: Filtering ENABLED =====
    print("\n" + "-"*70)
    print("TEST 2: Study Date Filtering ENABLED")
    print("-"*70)
    
    # Reset to initial state by deleting newly added records
    print("\nResetting database to initial state...")
    if state_without_filter['instances'] > initial_state['instances']:
        # Get newly added instances and delete them
        new_instances = DICOMInstance.objects.all()[initial_state['instances']:]
        new_instances.delete()
        
        # Clean up orphaned records
        DICOMSeries.objects.filter(dicominstance__isnull=True).delete()
        DICOMStudy.objects.filter(dicomseries__isnull=True).delete()
        Patient.objects.filter(dicomstudy__isnull=True).delete()
        
        print(f"✓ Database reset to initial state")
    
    # For TEST 2: Change data_pull_start_datetime to the study_date_cutoff
    # This will be used for study date comparison
    config.data_pull_start_datetime = study_date_cutoff
    config.study_date_based_filtering = True
    config.save()
    print(f"Study date filtering: {config.study_date_based_filtering}")
    print(f"Date filter changed to: {config.data_pull_start_datetime.date()}")
    print(f"Cutoff: Studies with dates before {study_date_cutoff.date()} will be filtered")
    
    print("\nRunning task...")
    start_time = time.time()
    result_with_filter = read_dicom_from_storage()
    time_with_filter = time.time() - start_time
    
    print(f"\n⏱️  Processing time: {time_with_filter:.2f} seconds")
    print(f"✅ Status: {result_with_filter.get('status')}")
    print(f"📁 Processed files: {result_with_filter.get('processed_files', 0)}")
    print(f"⏭️  Skipped files: {result_with_filter.get('skipped_files', 0)}")
    print(f"❌ Error files: {result_with_filter.get('error_files', 0)}")
    
    state_with_filter = {
        'patients': Patient.objects.count(),
        'studies': DICOMStudy.objects.count(),
        'series': DICOMSeries.objects.count(),
        'instances': DICOMInstance.objects.count()
    }
    
    print(f"\nDatabase state after processing:")
    print(f"  Patients: {state_with_filter['patients']} (added: {state_with_filter['patients'] - initial_state['patients']})")
    print(f"  Studies: {state_with_filter['studies']} (added: {state_with_filter['studies'] - initial_state['studies']})")
    print(f"  Series: {state_with_filter['series']} (added: {state_with_filter['series'] - initial_state['series']})")
    print(f"  Instances: {state_with_filter['instances']} (added: {state_with_filter['instances'] - initial_state['instances']})")
    
    # ===== COMPARISON =====
    print("\n" + "="*70)
    print("STUDY DATE FILTERING - COMPARISON RESULTS")
    print("="*70)
    
    print(f"\n{'Metric':<30} {'Without Filter':<20} {'With Filter':<20} {'Difference'}")
    print("-"*70)
    print(f"{'Processing Time':<30} {time_without_filter:.2f}s{'':<14} {time_with_filter:.2f}s{'':<14} {time_with_filter - time_without_filter:+.2f}s")
    print(f"{'Files Processed':<30} {result_without_filter.get('processed_files', 0):<20} {result_with_filter.get('processed_files', 0):<20} {result_with_filter.get('processed_files', 0) - result_without_filter.get('processed_files', 0):+d}")
    print(f"{'Files Skipped':<30} {result_without_filter.get('skipped_files', 0):<20} {result_with_filter.get('skipped_files', 0):<20} {result_with_filter.get('skipped_files', 0) - result_without_filter.get('skipped_files', 0):+d}")
    print(f"{'Instances Added to DB':<30} {state_without_filter['instances'] - initial_state['instances']:<20} {state_with_filter['instances'] - initial_state['instances']:<20} {(state_with_filter['instances'] - initial_state['instances']) - (state_without_filter['instances'] - initial_state['instances']):+d}")
    
    # Analysis
    print("\n" + "="*70)
    print("ANALYSIS")
    print("="*70)
    
    additional_skipped = result_with_filter.get('skipped_files', 0) - result_without_filter.get('skipped_files', 0)
    instances_filtered = (state_without_filter['instances'] - initial_state['instances']) - (state_with_filter['instances'] - initial_state['instances'])
    
    if additional_skipped > 0:
        print(f"\n✅ Study date filtering is working!")
        print(f"   {additional_skipped} additional files were skipped due to old study dates")
    
    if instances_filtered > 0:
        print(f"\n✅ Database contains fewer records with filtering enabled")
        print(f"   {instances_filtered} instances were filtered out based on study date")
    
    if additional_skipped == 0 and instances_filtered == 0:
        print(f"\n⚠️  No files were filtered by study date")
        print(f"   This could mean all studies in the test data are after {cutoff_date.date()}")
        print(f"   Or the DICOM files don't have study dates older than the cutoff")
        print(f"   Try using an older cutoff date to see the filtering effect")
    
    # Restore original configuration
    config.data_pull_start_datetime = original_date_filter
    config.study_date_based_filtering = False
    config.save()
    
    print(f"\n✅ Configuration restored:")
    print(f"   Date filter: {config.data_pull_start_datetime}")
    print(f"   Study date filtering: {config.study_date_based_filtering}")
    
    print("\n" + "="*70)
    print("STUDY DATE FILTERING TEST COMPLETED")
    print("="*70)

def main():
    """
    Main test function
    """
    print("="*70)
    print("DICOM FILE READER - INCREMENTAL RUN TEST")
    print("Using SEPARATE TEST DATABASE (production DB is safe)")
    print("="*70)
   
    # Create test database
    test_db_name = None
    try:
        # First, get the folder configuration from production database BEFORE creating test DB
        print("\n" + "="*70)
        print("READING PRODUCTION DATABASE CONFIGURATION")
        print("="*70)
        
        prod_config = SystemConfiguration.get_singleton()
        if not prod_config or not prod_config.folder_configuration:
            print("❌ No system configuration found in production database.")
            print("   Please configure the folder_configuration in System Configuration first.")
            return
        
        # Store the folder path from production
        folder_path = prod_config.folder_configuration
        date_filter = prod_config.data_pull_start_datetime or (timezone.now() - timedelta(days=30))
        study_date_filtering = prod_config.study_date_based_filtering
        
        print(f"✓ Read from production DB:")
        print(f"  - Folder: {folder_path}")
        print(f"  - Date filter: {date_filter}")
        print(f"  - Study date filtering: {study_date_filtering}")
        
        # Now create test database
        test_db_name = create_test_database()
        
        # Create system configuration in test database using production values
        print("\n" + "="*70)
        print("SETTING UP TEST CONFIGURATION")
        print("="*70)
        
        config = SystemConfiguration.objects.create(
            id=1,
            folder_configuration=folder_path,
            data_pull_start_datetime=date_filter,
            study_date_based_filtering=study_date_filtering
        )
        print("✓ Created test SystemConfiguration with production values")
        
        # Verify folder exists
        if not config.folder_configuration:
            print("❌ No folder configuration set.")
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
        original_study_filtering = config.study_date_based_filtering
       
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
        
        # Ask user if they want to run study date filtering test
        print("\n" + "="*70)
        print("ADDITIONAL TEST AVAILABLE")
        print("="*70)
        print("\nWould you like to run the Study Date Filtering test?")
        print("This will test the new study_date_based_filtering feature.")
        print("(Sets date filter to 5 weeks ago and compares results)")
        
        response = input("\nRun study date filtering test? (y/n): ").strip().lower()
        
        if response == 'y' or response == 'yes':
            test_study_date_filtering(original_date_filter)
        else:
            print("\nSkipping study date filtering test.")
        
        # Final restore
        config.refresh_from_db()
        config.data_pull_start_datetime = original_date_filter
        config.study_date_based_filtering = original_study_filtering
        config.save()
        print(f"\n✅ All settings restored to original values")
       
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Always destroy test database, even if test fails
        if test_db_name:
            destroy_test_database()
        
        print("\n" + "="*70)
        print("TEST COMPLETED")
        print("Your production database was NOT modified")
        print("="*70)

if __name__ == "__main__":
    main()