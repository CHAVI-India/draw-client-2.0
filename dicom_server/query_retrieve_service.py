"""
DICOM Query/Retrieve Service (SCU) implementation.
Provides C-FIND, C-MOVE, and C-GET operations to query and retrieve data from remote DICOM nodes.
"""

import logging
import time
import uuid
from datetime import datetime
from pathlib import Path

from pynetdicom import AE, evt, debug_logger
from pynetdicom.sop_class import (
    Verification,
    PatientRootQueryRetrieveInformationModelFind,
    StudyRootQueryRetrieveInformationModelFind,
    PatientStudyOnlyQueryRetrieveInformationModelFind,
    PatientRootQueryRetrieveInformationModelMove,
    StudyRootQueryRetrieveInformationModelMove,
    PatientStudyOnlyQueryRetrieveInformationModelMove,
    PatientRootQueryRetrieveInformationModelGet,
    StudyRootQueryRetrieveInformationModelGet,
)
from pydicom.dataset import Dataset

from django.utils import timezone
from django.db import transaction as db_transaction

from .models import (
    RemoteDicomNode,
    DicomQuery,
    DicomQueryResult,
    DicomRetrieveJob,
    DicomServerConfig
)

logger = logging.getLogger(__name__)


class DicomQueryRetrieveService:
    """
    DICOM Query/Retrieve Service Class User (SCU) implementation.
    Provides methods to query and retrieve DICOM data from remote nodes.
    """
    
    def __init__(self):
        """Initialize the Query/Retrieve service."""
        self.ae = None
        self._initialize_ae()
    
    def _initialize_ae(self):
        """Initialize the Application Entity for SCU operations."""
        try:
            # Get our local AE title from config
            config = DicomServerConfig.objects.get(pk=1)
            ae_title = config.ae_title
        except DicomServerConfig.DoesNotExist:
            ae_title = 'DRAW_SCU'
            logger.warning("DicomServerConfig not found, using default AE title: DRAW_SCU")
        
        self.ae = AE(ae_title=ae_title)
        
        # Add presentation context for C-ECHO (Verification)
        self.ae.add_requested_context(Verification)
        
        # Add presentation contexts for C-FIND
        self.ae.add_requested_context(PatientRootQueryRetrieveInformationModelFind)
        self.ae.add_requested_context(StudyRootQueryRetrieveInformationModelFind)
        self.ae.add_requested_context(PatientStudyOnlyQueryRetrieveInformationModelFind)
        
        # Add presentation contexts for C-MOVE
        self.ae.add_requested_context(PatientRootQueryRetrieveInformationModelMove)
        self.ae.add_requested_context(StudyRootQueryRetrieveInformationModelMove)
        self.ae.add_requested_context(PatientStudyOnlyQueryRetrieveInformationModelMove)
        
        # Add presentation contexts for C-GET
        self.ae.add_requested_context(PatientRootQueryRetrieveInformationModelGet)
        self.ae.add_requested_context(StudyRootQueryRetrieveInformationModelGet)
        
        logger.info(f"Query/Retrieve service initialized with AE title: {ae_title}")
    
    def test_connection(self, remote_node):
        """
        Test connection to a remote DICOM node using C-ECHO.
        
        Args:
            remote_node: RemoteDicomNode instance
        
        Returns:
            tuple: (success: bool, message: str)
        """
        try:
            # Check if node supports outgoing operations (Q/R)
            if not remote_node.outgoing_ae_title:
                # Node only supports incoming connections (C-STORE only)
                logger.info(f"Node {remote_node.name} is configured for incoming connections only (no Q/R support)")
                return False, "This node is configured for incoming connections only. Connection test requires Query/Retrieve capabilities."
            
            logger.info(f"Testing connection to {remote_node.name} ({remote_node.host}:{remote_node.port})")
            
            # Create association
            assoc = self.ae.associate(
                remote_node.host,
                remote_node.port,
                ae_title=remote_node.outgoing_ae_title,
                max_pdu=remote_node.max_pdu_size
            )
            
            if assoc.is_established:
                # Send C-ECHO
                status = assoc.send_c_echo()
                assoc.release()
                
                if status and status.Status == 0x0000:
                    remote_node.update_last_connection()
                    logger.info(f"Connection test successful: {remote_node.name}")
                    return True, "Connection successful"
                else:
                    logger.warning(f"C-ECHO failed for {remote_node.name}")
                    return False, "C-ECHO failed"
            else:
                logger.error(f"Failed to establish association with {remote_node.name}")
                return False, "Failed to establish association"
                
        except Exception as e:
            logger.error(f"Connection test failed for {remote_node.name}: {str(e)}")
            return False, f"Connection error: {str(e)}"
    
    def query(self, remote_node, query_level, query_params, user=None):
        """
        Perform C-FIND query on a remote DICOM node.
        
        Args:
            remote_node: RemoteDicomNode instance
            query_level: Query level ('PATIENT', 'STUDY', 'SERIES', 'IMAGE')
            query_params: Dictionary of DICOM tags to query
            user: User who initiated the query (optional)
        
        Returns:
            DicomQuery instance
        """
        # Create query record
        query_obj = DicomQuery.objects.create(
            query_id=uuid.uuid4(),
            remote_node=remote_node,
            query_level=query_level,
            query_parameters=query_params,
            initiated_by=user,
            status='pending'
        )
        
        try:
            logger.info(f"Starting C-FIND query {query_obj.query_id} on {remote_node.name}")
            query_obj.status = 'in_progress'
            query_obj.save()
            
            start_time = time.time()
            
            # Build query dataset
            ds = self._build_query_dataset(query_level, query_params)
            
            # Select appropriate SOP class based on remote node's model
            sop_class = self._get_find_sop_class(remote_node.query_retrieve_model)
            
            # Perform query
            results = []
            assoc = self.ae.associate(
                remote_node.host,
                remote_node.port,
                ae_title=remote_node.outgoing_ae_title,
                max_pdu=remote_node.max_pdu_size
            )
            
            if assoc.is_established:
                responses = assoc.send_c_find(ds, sop_class)
                
                for status, identifier in responses:
                    if status and status.Status in [0xFF00, 0xFF01]:  # Pending
                        if identifier:
                            results.append(identifier)
                            self._save_query_result(query_obj, identifier, query_level)
                    elif status and status.Status == 0x0000:  # Success
                        logger.info(f"Query completed successfully: {len(results)} results")
                    else:
                        logger.warning(f"Query returned status: 0x{status.Status:04X}")
                
                assoc.release()
                remote_node.update_last_connection()
            else:
                raise Exception("Failed to establish association")
            
            # Mark query as completed
            duration = time.time() - start_time
            query_obj.mark_completed(len(results), duration)
            
            logger.info(f"Query {query_obj.query_id} completed: {len(results)} results in {duration:.2f}s")
            return query_obj
            
        except Exception as e:
            logger.error(f"Query {query_obj.query_id} failed: {str(e)}")
            query_obj.mark_failed(str(e))
            raise
    
    def retrieve_move(self, remote_node, study_uid, series_uid=None, user=None):
        """
        Retrieve DICOM data using C-MOVE.
        
        Args:
            remote_node: RemoteDicomNode instance
            study_uid: Study Instance UID to retrieve
            series_uid: Series Instance UID (optional, for series-level retrieve)
            user: User who initiated the retrieve (optional)
        
        Returns:
            DicomRetrieveJob instance
        """
        # Determine retrieve level
        if series_uid:
            retrieve_level = 'SERIES'
        else:
            retrieve_level = 'STUDY'
        
        # Create retrieve job
        job = DicomRetrieveJob.objects.create(
            job_id=uuid.uuid4(),
            remote_node=remote_node,
            retrieve_method='C-MOVE',
            retrieve_level=retrieve_level,
            study_instance_uid=study_uid,
            series_instance_uid=series_uid or '',
            initiated_by=user,
            status='pending'
        )
        
        try:
            logger.info(f"Starting C-MOVE retrieve job {job.job_id}")
            job.mark_started()
            
            # Build move dataset
            ds = Dataset()
            ds.QueryRetrieveLevel = retrieve_level
            ds.StudyInstanceUID = study_uid
            if series_uid:
                ds.SeriesInstanceUID = series_uid
            
            # Get move destination AE title
            move_dest = remote_node.move_destination_ae
            if not move_dest:
                try:
                    config = DicomServerConfig.objects.get(pk=1)
                    move_dest = config.ae_title
                except DicomServerConfig.DoesNotExist:
                    move_dest = 'DRAW_SCP'
            
            # Select appropriate SOP class
            sop_class = self._get_move_sop_class(remote_node.query_retrieve_model)
            
            # Perform C-MOVE
            assoc = self.ae.associate(
                remote_node.host,
                remote_node.port,
                ae_title=remote_node.outgoing_ae_title,
                max_pdu=remote_node.max_pdu_size
            )
            
            if assoc.is_established:
                responses = assoc.send_c_move(ds, move_dest, sop_class)
                
                for status, identifier in responses:
                    if status:
                        # Update progress based on status
                        if hasattr(status, 'NumberOfRemainingSuboperations'):
                            remaining = status.NumberOfRemainingSuboperations
                            completed = status.NumberOfCompletedSuboperations
                            failed = status.NumberOfFailedSuboperations
                            
                            total = remaining + completed + failed
                            if job.total_instances == 0:
                                job.total_instances = total
                            
                            job.completed_instances = completed
                            job.failed_instances = failed
                            job.save()
                        
                        if status.Status == 0x0000:  # Success
                            logger.info(f"C-MOVE completed successfully")
                            break
                
                assoc.release()
                remote_node.update_last_connection()
            else:
                raise Exception("Failed to establish association")
            
            # Mark job as completed
            job.mark_completed()
            logger.info(f"Retrieve job {job.job_id} completed")
            return job
            
        except Exception as e:
            logger.error(f"Retrieve job {job.job_id} failed: {str(e)}")
            job.mark_failed(str(e))
            raise
    
    def retrieve_get(self, remote_node, study_uid, series_uid=None, user=None):
        """
        Retrieve DICOM data using C-GET.
        
        Args:
            remote_node: RemoteDicomNode instance
            study_uid: Study Instance UID to retrieve
            series_uid: Series Instance UID (optional, for series-level retrieve)
            user: User who initiated the retrieve (optional)
        
        Returns:
            DicomRetrieveJob instance
        """
        # Determine retrieve level
        if series_uid:
            retrieve_level = 'SERIES'
        else:
            retrieve_level = 'STUDY'
        
        # Create retrieve job
        job = DicomRetrieveJob.objects.create(
            job_id=uuid.uuid4(),
            remote_node=remote_node,
            retrieve_method='C-GET',
            retrieve_level=retrieve_level,
            study_instance_uid=study_uid,
            series_instance_uid=series_uid or '',
            initiated_by=user,
            status='pending'
        )
        
        try:
            logger.info(f"Starting C-GET retrieve job {job.job_id}")
            job.mark_started()
            
            # Build get dataset
            ds = Dataset()
            ds.QueryRetrieveLevel = retrieve_level
            ds.StudyInstanceUID = study_uid
            if series_uid:
                ds.SeriesInstanceUID = series_uid
            
            # Select appropriate SOP class
            sop_class = self._get_get_sop_class(remote_node.query_retrieve_model)
            
            # Perform C-GET
            assoc = self.ae.associate(
                remote_node.host,
                remote_node.port,
                ae_title=remote_node.outgoing_ae_title,
                max_pdu=remote_node.max_pdu_size
            )
            
            if assoc.is_established:
                responses = assoc.send_c_get(ds, sop_class)
                
                for status, identifier in responses:
                    if status:
                        # Update progress
                        if hasattr(status, 'NumberOfRemainingSuboperations'):
                            remaining = status.NumberOfRemainingSuboperations
                            completed = status.NumberOfCompletedSuboperations
                            failed = status.NumberOfFailedSuboperations
                            
                            total = remaining + completed + failed
                            if job.total_instances == 0:
                                job.total_instances = total
                            
                            job.completed_instances = completed
                            job.failed_instances = failed
                            job.save()
                        
                        if status.Status == 0x0000:  # Success
                            logger.info(f"C-GET completed successfully")
                            break
                
                assoc.release()
                remote_node.update_last_connection()
            else:
                raise Exception("Failed to establish association")
            
            # Mark job as completed
            job.mark_completed()
            logger.info(f"Retrieve job {job.job_id} completed")
            return job
            
        except Exception as e:
            logger.error(f"Retrieve job {job.job_id} failed: {str(e)}")
            job.mark_failed(str(e))
            raise
    
    # Helper Methods
    
    def _build_query_dataset(self, query_level, query_params):
        """Build DICOM dataset for C-FIND query."""
        ds = Dataset()
        ds.QueryRetrieveLevel = query_level
        
        # Add query parameters
        for tag, value in query_params.items():
            setattr(ds, tag, value)
        
        # Add return tags based on query level
        if query_level == 'PATIENT':
            ds.PatientID = query_params.get('PatientID', '')
            ds.PatientName = query_params.get('PatientName', '')
            ds.PatientBirthDate = query_params.get('PatientBirthDate', '')
            ds.PatientSex = query_params.get('PatientSex', '')
        
        elif query_level == 'STUDY':
            ds.PatientID = query_params.get('PatientID', '')
            ds.PatientName = query_params.get('PatientName', '')
            ds.StudyInstanceUID = query_params.get('StudyInstanceUID', '')
            ds.StudyDate = query_params.get('StudyDate', '')
            ds.StudyTime = query_params.get('StudyTime', '')
            ds.StudyDescription = query_params.get('StudyDescription', '')
            ds.AccessionNumber = query_params.get('AccessionNumber', '')
            ds.ModalitiesInStudy = query_params.get('ModalitiesInStudy', '')
            ds.NumberOfStudyRelatedSeries = ''
            ds.NumberOfStudyRelatedInstances = ''
        
        elif query_level == 'SERIES':
            ds.StudyInstanceUID = query_params.get('StudyInstanceUID', '')
            ds.SeriesInstanceUID = query_params.get('SeriesInstanceUID', '')
            ds.Modality = query_params.get('Modality', '')
            ds.SeriesNumber = query_params.get('SeriesNumber', '')
            ds.SeriesDescription = query_params.get('SeriesDescription', '')
            ds.NumberOfSeriesRelatedInstances = ''
        
        elif query_level == 'IMAGE':
            ds.StudyInstanceUID = query_params.get('StudyInstanceUID', '')
            ds.SeriesInstanceUID = query_params.get('SeriesInstanceUID', '')
            ds.SOPInstanceUID = query_params.get('SOPInstanceUID', '')
            ds.InstanceNumber = query_params.get('InstanceNumber', '')
        
        return ds
    
    def _save_query_result(self, query_obj, identifier, query_level):
        """Save a query result to the database."""
        try:
            # Extract common fields
            result_data = {
                'patient_id': getattr(identifier, 'PatientID', ''),
                'patient_name': str(getattr(identifier, 'PatientName', '')),
                'study_instance_uid': getattr(identifier, 'StudyInstanceUID', ''),
                'series_instance_uid': getattr(identifier, 'SeriesInstanceUID', ''),
                'modality': getattr(identifier, 'Modality', ''),
            }
            
            # Parse study date
            study_date = getattr(identifier, 'StudyDate', None)
            if study_date:
                try:
                    result_data['study_date'] = datetime.strptime(study_date, '%Y%m%d').date()
                except:
                    pass
            
            # Get descriptions
            result_data['study_description'] = getattr(identifier, 'StudyDescription', '')
            result_data['series_description'] = getattr(identifier, 'SeriesDescription', '')
            
            # Get number of instances
            num_instances = getattr(identifier, 'NumberOfSeriesRelatedInstances', None)
            if not num_instances:
                num_instances = getattr(identifier, 'NumberOfStudyRelatedInstances', None)
            if num_instances:
                try:
                    result_data['number_of_instances'] = int(num_instances)
                except:
                    pass
            
            # Convert dataset to JSON
            result_json = {}
            for elem in identifier:
                try:
                    result_json[elem.keyword] = str(elem.value)
                except:
                    pass
            
            # Create result record
            DicomQueryResult.objects.create(
                query=query_obj,
                result_data=result_json,
                **result_data
            )
            
        except Exception as e:
            logger.error(f"Failed to save query result: {str(e)}")
    
    def _get_find_sop_class(self, model):
        """Get appropriate C-FIND SOP class based on query/retrieve model."""
        if model == 'patient':
            return PatientRootQueryRetrieveInformationModelFind
        elif model == 'study':
            return StudyRootQueryRetrieveInformationModelFind
        elif model == 'patient_study':
            return PatientStudyOnlyQueryRetrieveInformationModelFind
        else:
            return StudyRootQueryRetrieveInformationModelFind
    
    def _get_move_sop_class(self, model):
        """Get appropriate C-MOVE SOP class based on query/retrieve model."""
        if model == 'patient':
            return PatientRootQueryRetrieveInformationModelMove
        elif model == 'study':
            return StudyRootQueryRetrieveInformationModelMove
        elif model == 'patient_study':
            return PatientStudyOnlyQueryRetrieveInformationModelMove
        else:
            return StudyRootQueryRetrieveInformationModelMove
    
    def _get_get_sop_class(self, model):
        """Get appropriate C-GET SOP class based on query/retrieve model."""
        if model == 'patient':
            return PatientRootQueryRetrieveInformationModelGet
        elif model == 'study':
            return StudyRootQueryRetrieveInformationModelGet
        else:
            return StudyRootQueryRetrieveInformationModelGet


# Singleton instance
_service_instance = None


def get_qr_service_instance():
    """Get the singleton Query/Retrieve service instance."""
    global _service_instance
    if _service_instance is None:
        _service_instance = DicomQueryRetrieveService()
    return _service_instance
