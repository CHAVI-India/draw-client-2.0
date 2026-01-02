#!/usr/bin/env python
"""
Test script for DICOM SCP service.
Tests C-ECHO, C-STORE, and C-FIND operations.
"""

import sys
import os
from pynetdicom import AE, debug_logger
from pynetdicom.sop_class import (
    Verification,
    CTImageStorage,
    MRImageStorage,
    PatientRootQueryRetrieveInformationModelFind,
)
from pydicom import dcmread
from pydicom.dataset import Dataset

# Enable debug logging
# debug_logger()


def test_c_echo(host='127.0.0.1', port=11112, ae_title='DRAW_SCP'):
    """
    Test C-ECHO (verification/ping).
    """
    print(f"\n{'='*60}")
    print("Testing C-ECHO (Verification)")
    print(f"{'='*60}")
    
    ae = AE(ae_title='TEST_SCU')
    ae.add_requested_context(Verification)
    
    print(f"Connecting to {host}:{port} (AE Title: {ae_title})...")
    assoc = ae.associate(host, port, ae_title=ae_title)
    
    if assoc.is_established:
        print("✓ Association established")
        
        # Send C-ECHO
        status = assoc.send_c_echo()
        
        if status:
            print(f"✓ C-ECHO successful (Status: 0x{status.Status:04X})")
        else:
            print("✗ C-ECHO failed")
        
        assoc.release()
        print("✓ Association released")
        return True
    else:
        print("✗ Association rejected or aborted")
        return False


def test_c_store(dicom_file, host='127.0.0.1', port=11112, ae_title='DRAW_SCP'):
    """
    Test C-STORE (send DICOM file).
    """
    print(f"\n{'='*60}")
    print("Testing C-STORE (Send DICOM File)")
    print(f"{'='*60}")
    
    if not os.path.exists(dicom_file):
        print(f"✗ File not found: {dicom_file}")
        return False
    
    print(f"Reading DICOM file: {dicom_file}")
    try:
        ds = dcmread(dicom_file)
        print(f"✓ File loaded successfully")
        print(f"  Patient ID: {getattr(ds, 'PatientID', 'N/A')}")
        print(f"  Study UID: {getattr(ds, 'StudyInstanceUID', 'N/A')[:40]}...")
        print(f"  SOP Class: {getattr(ds, 'SOPClassUID', 'N/A')}")
    except Exception as e:
        print(f"✗ Error reading file: {str(e)}")
        return False
    
    ae = AE(ae_title='TEST_SCU')
    ae.add_requested_context(CTImageStorage)
    ae.add_requested_context(MRImageStorage)
    
    print(f"Connecting to {host}:{port} (AE Title: {ae_title})...")
    assoc = ae.associate(host, port, ae_title=ae_title)
    
    if assoc.is_established:
        print("✓ Association established")
        
        # Send C-STORE
        status = assoc.send_c_store(ds)
        
        if status and status.Status == 0x0000:
            print(f"✓ C-STORE successful (Status: 0x{status.Status:04X})")
        else:
            print(f"✗ C-STORE failed (Status: 0x{status.Status:04X if status else 'None'})")
        
        assoc.release()
        print("✓ Association released")
        return True
    else:
        print("✗ Association rejected or aborted")
        return False


def test_c_find(host='127.0.0.1', port=11112, ae_title='DRAW_SCP'):
    """
    Test C-FIND (query for studies).
    """
    print(f"\n{'='*60}")
    print("Testing C-FIND (Query Studies)")
    print(f"{'='*60}")
    
    ae = AE(ae_title='TEST_SCU')
    ae.add_requested_context(PatientRootQueryRetrieveInformationModelFind)
    
    print(f"Connecting to {host}:{port} (AE Title: {ae_title})...")
    assoc = ae.associate(host, port, ae_title=ae_title)
    
    if assoc.is_established:
        print("✓ Association established")
        
        # Create query dataset
        ds = Dataset()
        ds.QueryRetrieveLevel = 'STUDY'
        ds.PatientID = ''
        ds.StudyInstanceUID = ''
        ds.StudyDate = ''
        
        print("Sending C-FIND query...")
        responses = assoc.send_c_find(ds, PatientRootQueryRetrieveInformationModelFind)
        
        count = 0
        for (status, identifier) in responses:
            if status and status.Status in [0xFF00, 0xFF01]:  # Pending
                count += 1
                if identifier:
                    print(f"\n  Result {count}:")
                    print(f"    Patient ID: {getattr(identifier, 'PatientID', 'N/A')}")
                    print(f"    Study UID: {getattr(identifier, 'StudyInstanceUID', 'N/A')[:40]}...")
                    print(f"    Study Date: {getattr(identifier, 'StudyDate', 'N/A')}")
        
        if count > 0:
            print(f"\n✓ C-FIND successful - Found {count} studies")
        else:
            print("\n✓ C-FIND successful - No studies found")
        
        assoc.release()
        print("✓ Association released")
        return True
    else:
        print("✗ Association rejected or aborted")
        return False


def main():
    """
    Main test function.
    """
    print("\n" + "="*60)
    print("DICOM SCP Service Test Suite")
    print("="*60)
    
    # Configuration
    host = '127.0.0.1'
    port = 11112
    ae_title = 'DRAW_SCP'
    
    # Test C-ECHO
    echo_result = test_c_echo(host, port, ae_title)
    
    # Test C-STORE (if DICOM file provided)
    if len(sys.argv) > 1:
        dicom_file = sys.argv[1]
        store_result = test_c_store(dicom_file, host, port, ae_title)
    else:
        print("\n" + "="*60)
        print("Skipping C-STORE test (no DICOM file provided)")
        print("Usage: python test_dicom_server.py <path-to-dicom-file>")
        print("="*60)
        store_result = None
    
    # Test C-FIND
    find_result = test_c_find(host, port, ae_title)
    
    # Summary
    print("\n" + "="*60)
    print("Test Summary")
    print("="*60)
    print(f"C-ECHO: {'✓ PASS' if echo_result else '✗ FAIL'}")
    if store_result is not None:
        print(f"C-STORE: {'✓ PASS' if store_result else '✗ FAIL'}")
    print(f"C-FIND: {'✓ PASS' if find_result else '✗ FAIL'}")
    print("="*60 + "\n")


if __name__ == '__main__':
    main()
