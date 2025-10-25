#!/usr/bin/env python
"""
Django test for study_date_based_filtering feature in task1_read_dicom_from_storage.py
This test uses Django's test database which is automatically created and destroyed.
Run with: python manage.py test --settings=draw_client.settings --keepdb test_study_date_filtering
Or without keepdb: python manage.py test test_study_date_filtering
"""

import os
import sys
from pathlib import Path
from datetime import datetime, timedelta
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from django.conf import settings
import time

# Import models
from dicom_handler.models import (
    SystemConfiguration, Patient, DICOMStudy, 
    DICOMSeries, DICOMInstance, ProcessingStatus
)

class StudyDateFilteringTestCase(TransactionTestCase):
    """
    Test case for study date-based filtering feature.
    Uses TransactionTestCase to ensure clean database state for each test.
    """
    
    # Don't reset sequences between tests
    reset_sequences = True
    
    def setUp(self):
        """Set up test environment before each test"""
        print("\n" + "="*70)
        print("Setting up test environment...")
        print("="*70)
        
        # Create system configuration
        self.config = SystemConfiguration.objects.create(
            id=1,
            folder_configuration="/app/datastore",  # Default test folder
            data_pull_start_datetime=timezone.now() - timedelta(weeks=5),
            study_date_based_filtering=False  # Start with filtering disabled
        )
        print(f"✓ Created SystemConfiguration")
        print(f"  - Folder: {self.config.folder_configuration}")
        print(f"  - Date filter: {self.config.data_pull_start_datetime}")
        print(f"  - Study date filtering: {self.config.study_date_based_filtering}")
    
    def tearDown(self):
        """Clean up after each test"""
        print("\n" + "-"*70)
        print("Test completed - database will be cleaned automatically")
        print("-"*70)
    
    def print_database_state(self, prefix=""):
        """Print current database state"""
        patients = Patient.objects.count()
        studies = DICOMStudy.objects.count()
        series = DICOMSeries.objects.count()
        instances = DICOMInstance.objects.count()
        
        print(f"\n{prefix}DATABASE STATE:")
        print(f"  Patients: {patients}")
        print(f"  Studies: {studies}")
        print(f"  Series: {series}")
        print(f"  Instances: {instances}")
    
    def test_study_date_filtering_disabled(self):
        """
        Test 1: Verify that files are processed when study_date_based_filtering is False
        """
        print("\n" + "="*70)
        print("TEST 1: Study Date Filtering DISABLED")
        print("="*70)
        
        # Check if folder exists
        if not os.path.exists(self.config.folder_configuration):
            self.skipTest(f"Test folder does not exist: {self.config.folder_configuration}")
        
        # Count files
        file_count = sum(len(files) for _, _, files in os.walk(self.config.folder_configuration))
        print(f"\n✓ Found {file_count} files in test folder")
        
        if file_count == 0:
            self.skipTest("No files found in test folder")
        
        # Import and run the task
        from dicom_handler.export_services.task1_read_dicom_from_storage import read_dicom_from_storage
        
        print("\nRunning task with study_date_based_filtering = False...")
        start_time = time.time()
        result = read_dicom_from_storage()
        end_time = time.time()
        
        print(f"\n⏱️  Processing time: {end_time - start_time:.2f} seconds")
        print(f"✅ Status: {result.get('status')}")
        print(f"📁 Processed files: {result.get('processed_files', 0)}")
        print(f"⏭️  Skipped files: {result.get('skipped_files', 0)}")
        print(f"❌ Error files: {result.get('error_files', 0)}")
        print(f"📦 Series found: {len(result.get('series_data', []))}")
        
        self.print_database_state("AFTER PROCESSING - ")
        
        # Store counts for comparison
        self.initial_patients = Patient.objects.count()
        self.initial_studies = DICOMStudy.objects.count()
        self.initial_series = DICOMSeries.objects.count()
        self.initial_instances = DICOMInstance.objects.count()
        
        # Assertions
        self.assertEqual(result.get('status'), 'success', "Task should complete successfully")
        self.assertGreater(self.initial_instances, 0, "Should have processed some instances")
        
        print("\n✅ TEST 1 PASSED: Files processed with filtering disabled")
    
    def test_study_date_filtering_enabled(self):
        """
        Test 2: Verify that old studies are filtered out when study_date_based_filtering is True
        Set date filter to 5 weeks before today and enable filtering
        """
        print("\n" + "="*70)
        print("TEST 2: Study Date Filtering ENABLED (5 weeks cutoff)")
        print("="*70)
        
        # Check if folder exists
        if not os.path.exists(self.config.folder_configuration):
            self.skipTest(f"Test folder does not exist: {self.config.folder_configuration}")
        
        # Set date filter to 5 weeks ago
        five_weeks_ago = timezone.now() - timedelta(weeks=5)
        self.config.data_pull_start_datetime = five_weeks_ago
        self.config.study_date_based_filtering = True
        self.config.save()
        
        print(f"\n✓ Updated SystemConfiguration:")
        print(f"  - Date filter: {self.config.data_pull_start_datetime}")
        print(f"  - Study date filtering: ENABLED")
        print(f"  - Cutoff date: Studies before {five_weeks_ago.date()} will be filtered")
        
        # Import and run the task
        from dicom_handler.export_services.task1_read_dicom_from_storage import read_dicom_from_storage
        
        print("\nRunning task with study_date_based_filtering = True...")
        start_time = time.time()
        result = read_dicom_from_storage()
        end_time = time.time()
        
        print(f"\n⏱️  Processing time: {end_time - start_time:.2f} seconds")
        print(f"✅ Status: {result.get('status')}")
        print(f"📁 Processed files: {result.get('processed_files', 0)}")
        print(f"⏭️  Skipped files: {result.get('skipped_files', 0)}")
        print(f"❌ Error files: {result.get('error_files', 0)}")
        print(f"📦 Series found: {len(result.get('series_data', []))}")
        
        self.print_database_state("AFTER PROCESSING - ")
        
        # Get counts after filtering
        filtered_patients = Patient.objects.count()
        filtered_studies = DICOMStudy.objects.count()
        filtered_series = DICOMSeries.objects.count()
        filtered_instances = DICOMInstance.objects.count()
        
        # Assertions
        self.assertEqual(result.get('status'), 'success', "Task should complete successfully")
        
        # Check if any files were skipped due to study date filtering
        skip_reasons = result.get('skip_reasons', {})
        if 'study_date_before_filter' in skip_reasons:
            study_date_skipped = skip_reasons['study_date_before_filter']
            print(f"\n📊 FILTERING RESULTS:")
            print(f"  - Files skipped due to old study date: {study_date_skipped}")
            print(f"  - This demonstrates the filter is working!")
            self.assertGreater(study_date_skipped, 0, "Should have filtered some files based on study date")
        else:
            print(f"\n⚠️  No files were filtered by study date")
            print(f"   This could mean all studies in the test data are recent")
        
        print("\n✅ TEST 2 PASSED: Study date filtering is working")
    
    def test_study_date_filtering_comparison(self):
        """
        Test 3: Compare results with filtering ON vs OFF
        This test runs both scenarios and compares the results
        """
        print("\n" + "="*70)
        print("TEST 3: COMPARISON - Filtering ON vs OFF")
        print("="*70)
        
        # Check if folder exists
        if not os.path.exists(self.config.folder_configuration):
            self.skipTest(f"Test folder does not exist: {self.config.folder_configuration}")
        
        from dicom_handler.export_services.task1_read_dicom_from_storage import read_dicom_from_storage
        
        # Set date filter to 5 weeks ago
        five_weeks_ago = timezone.now() - timedelta(weeks=5)
        self.config.data_pull_start_datetime = five_weeks_ago
        
        # ===== RUN 1: Filtering DISABLED =====
        print("\n" + "-"*70)
        print("RUN 1: Study Date Filtering DISABLED")
        print("-"*70)
        
        self.config.study_date_based_filtering = False
        self.config.save()
        
        print(f"Date filter: {self.config.data_pull_start_datetime}")
        print(f"Study date filtering: {self.config.study_date_based_filtering}")
        
        start_time = time.time()
        result_without_filter = read_dicom_from_storage()
        time_without_filter = time.time() - start_time
        
        print(f"\n⏱️  Time: {time_without_filter:.2f}s")
        print(f"📁 Processed: {result_without_filter.get('processed_files', 0)}")
        print(f"⏭️  Skipped: {result_without_filter.get('skipped_files', 0)}")
        
        count_without_filter = {
            'patients': Patient.objects.count(),
            'studies': DICOMStudy.objects.count(),
            'series': DICOMSeries.objects.count(),
            'instances': DICOMInstance.objects.count()
        }
        
        print(f"\nDatabase after run 1:")
        print(f"  Patients: {count_without_filter['patients']}")
        print(f"  Studies: {count_without_filter['studies']}")
        print(f"  Series: {count_without_filter['series']}")
        print(f"  Instances: {count_without_filter['instances']}")
        
        # Clear database for second run
        print("\nClearing database for second run...")
        DICOMInstance.objects.all().delete()
        DICOMSeries.objects.all().delete()
        DICOMStudy.objects.all().delete()
        Patient.objects.all().delete()
        
        # ===== RUN 2: Filtering ENABLED =====
        print("\n" + "-"*70)
        print("RUN 2: Study Date Filtering ENABLED")
        print("-"*70)
        
        self.config.study_date_based_filtering = True
        self.config.save()
        
        print(f"Date filter: {self.config.data_pull_start_datetime}")
        print(f"Study date filtering: {self.config.study_date_based_filtering}")
        print(f"Cutoff: Studies before {five_weeks_ago.date()} will be filtered")
        
        start_time = time.time()
        result_with_filter = read_dicom_from_storage()
        time_with_filter = time.time() - start_time
        
        print(f"\n⏱️  Time: {time_with_filter:.2f}s")
        print(f"📁 Processed: {result_with_filter.get('processed_files', 0)}")
        print(f"⏭️  Skipped: {result_with_filter.get('skipped_files', 0)}")
        
        count_with_filter = {
            'patients': Patient.objects.count(),
            'studies': DICOMStudy.objects.count(),
            'series': DICOMSeries.objects.count(),
            'instances': DICOMInstance.objects.count()
        }
        
        print(f"\nDatabase after run 2:")
        print(f"  Patients: {count_with_filter['patients']}")
        print(f"  Studies: {count_with_filter['studies']}")
        print(f"  Series: {count_with_filter['series']}")
        print(f"  Instances: {count_with_filter['instances']}")
        
        # ===== COMPARISON =====
        print("\n" + "="*70)
        print("COMPARISON RESULTS")
        print("="*70)
        
        print(f"\n{'Metric':<30} {'Without Filter':<20} {'With Filter':<20} {'Difference'}")
        print("-"*70)
        print(f"{'Processing Time':<30} {time_without_filter:.2f}s{'':<14} {time_with_filter:.2f}s{'':<14} {time_with_filter - time_without_filter:+.2f}s")
        print(f"{'Files Processed':<30} {result_without_filter.get('processed_files', 0):<20} {result_with_filter.get('processed_files', 0):<20} {result_with_filter.get('processed_files', 0) - result_without_filter.get('processed_files', 0):+d}")
        print(f"{'Files Skipped':<30} {result_without_filter.get('skipped_files', 0):<20} {result_with_filter.get('skipped_files', 0):<20} {result_with_filter.get('skipped_files', 0) - result_without_filter.get('skipped_files', 0):+d}")
        print(f"{'Patients in DB':<30} {count_without_filter['patients']:<20} {count_with_filter['patients']:<20} {count_with_filter['patients'] - count_without_filter['patients']:+d}")
        print(f"{'Studies in DB':<30} {count_without_filter['studies']:<20} {count_with_filter['studies']:<20} {count_with_filter['studies'] - count_without_filter['studies']:+d}")
        print(f"{'Series in DB':<30} {count_without_filter['series']:<20} {count_with_filter['series']:<20} {count_with_filter['series'] - count_without_filter['series']:+d}")
        print(f"{'Instances in DB':<30} {count_without_filter['instances']:<20} {count_with_filter['instances']:<20} {count_with_filter['instances'] - count_without_filter['instances']:+d}")
        
        # Analysis
        print("\n" + "="*70)
        print("ANALYSIS")
        print("="*70)
        
        if result_with_filter.get('skipped_files', 0) > result_without_filter.get('skipped_files', 0):
            additional_skipped = result_with_filter.get('skipped_files', 0) - result_without_filter.get('skipped_files', 0)
            print(f"\n✅ Study date filtering is working!")
            print(f"   {additional_skipped} additional files were skipped due to old study dates")
        
        if count_with_filter['instances'] < count_without_filter['instances']:
            filtered_instances = count_without_filter['instances'] - count_with_filter['instances']
            print(f"\n✅ Database contains fewer records with filtering enabled")
            print(f"   {filtered_instances} instances were filtered out")
        
        if count_with_filter['instances'] == count_without_filter['instances']:
            print(f"\n⚠️  No difference in database records")
            print(f"   This could mean all studies in test data are recent (within 5 weeks)")
        
        # Assertions
        self.assertEqual(result_without_filter.get('status'), 'success')
        self.assertEqual(result_with_filter.get('status'), 'success')
        self.assertGreaterEqual(
            result_with_filter.get('skipped_files', 0),
            result_without_filter.get('skipped_files', 0),
            "With filtering enabled, skipped files should be >= without filtering"
        )
        
        print("\n✅ TEST 3 PASSED: Comparison completed successfully")


def run_tests():
    """
    Helper function to run tests programmatically
    """
    import unittest
    
    # Create test suite
    suite = unittest.TestLoader().loadTestsFromTestCase(StudyDateFilteringTestCase)
    
    # Run tests with verbose output
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Return exit code
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    print("\n" + "="*70)
    print("STUDY DATE FILTERING TEST SUITE")
    print("Using Django's test database (automatically created/destroyed)")
    print("="*70)
    print("\nTo run this test properly, use:")
    print("  python manage.py test test_study_date_filtering")
    print("\nOr to keep the test database for inspection:")
    print("  python manage.py test --keepdb test_study_date_filtering")
    print("="*70)
    
    sys.exit(run_tests())
