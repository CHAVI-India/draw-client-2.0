"""
DICOM SCP (Service Class Provider) implementation using pynetdicom.
This module handles incoming DICOM connections and operations.
"""

import os
import logging
import threading
import time
from datetime import datetime
from pathlib import Path

from pynetdicom import AE, evt, StoragePresentationContexts, AllStoragePresentationContexts
from pynetdicom.sop_class import (
    Verification,
    CTImageStorage,
    MRImageStorage,
    RTStructureSetStorage,
    RTPlanStorage,
    RTDoseStorage,
    SecondaryCaptureImageStorage,
    PatientRootQueryRetrieveInformationModelFind,
    StudyRootQueryRetrieveInformationModelFind,
    PatientRootQueryRetrieveInformationModelMove,
    StudyRootQueryRetrieveInformationModelMove,
    PatientRootQueryRetrieveInformationModelGet,
    StudyRootQueryRetrieveInformationModelGet,
)
from pydicom import dcmread
from pydicom.uid import (
    ImplicitVRLittleEndian,
    ExplicitVRLittleEndian,
    ExplicitVRBigEndian,
    JPEGBaseline8Bit as JPEGBaseline,
    JPEGLosslessSV1 as JPEGLossless,
    JPEG2000Lossless,
    RLELossless,
)

from django.utils import timezone
from django.db import transaction as db_transaction

from .models import DicomServerConfig, RemoteDicomNode, DicomTransaction, DicomServiceStatus

logger = logging.getLogger(__name__)


class DicomSCPService:
    """
    DICOM SCP Service implementation using pynetdicom.
    Handles all DICOM operations including C-STORE, C-ECHO, C-FIND, C-MOVE, C-GET.
    """
    
    def __init__(self):
        self.ae = None
        self.server_thread = None
        self._is_running = False
        self.config = None
        self.service_status = None
        self._config_last_updated = None
        
    def initialize(self):
        """
        Initialize the DICOM SCP service with configuration from database.
        """
        try:
            from dicom_handler.models import SystemConfiguration
            
            self.config = DicomServerConfig.objects.get(pk=1)
            self.service_status, created = DicomServiceStatus.objects.get_or_create(pk=1)
            
            # Override storage path with SystemConfiguration folder_configuration
            system_config = SystemConfiguration.objects.get(pk=1)
            if system_config.folder_configuration:
                self.config.storage_root_path = system_config.folder_configuration
            
            # Set logging level
            log_level = getattr(logging, self.config.logging_level, logging.INFO)
            logger.setLevel(log_level)
            
            # Create Application Entity
            self.ae = AE(ae_title=self.config.ae_title)
            
            # Configure supported SOP classes
            self._configure_sop_classes()
            
            # Configure transfer syntaxes
            self._configure_transfer_syntaxes()
            
            # Set network parameters
            self.ae.maximum_pdu_size = self.config.max_pdu_size
            self.ae.network_timeout = self.config.network_timeout
            self.ae.acse_timeout = self.config.acse_timeout
            self.ae.dimse_timeout = self.config.dimse_timeout
            self.ae.maximum_associations = self.config.max_associations
            
            # Performance optimization: Enable connection reuse
            # This allows multiple C-STORE operations on a single association
            self.ae.require_called_aet = False  # More lenient for connection reuse
            
            self._config_last_updated = self.config.updated_at
            logger.info(f"DICOM SCP initialized: {self.config.ae_title} on {self.config.host}:{self.config.port}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize DICOM SCP: {str(e)}")
            return False
    
    def refresh_config(self, force=False):
        """
        Refresh configuration from database if it has been updated.
        This allows hot-reloading of certain settings without service restart.
        
        Args:
            force: If True, refresh regardless of update timestamp
            
        Returns:
            bool: True if config was refreshed, False otherwise
        """
        try:
            # Check if config has been updated in database
            latest_config = DicomServerConfig.objects.get(pk=1)
            
            if force or (self._config_last_updated and latest_config.updated_at > self._config_last_updated):
                logger.info("Configuration has been updated, refreshing...")
                self.config = latest_config
                self._config_last_updated = latest_config.updated_at
                
                # Update logging level
                log_level = getattr(logging, self.config.logging_level, logging.INFO)
                logger.setLevel(log_level)
                
                logger.info("Configuration refreshed successfully")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Failed to refresh configuration: {str(e)}")
            return False
    
    def get_fresh_config(self):
        """
        Get fresh configuration from database.
        Use this for critical settings that need to be always up-to-date.
        
        Returns:
            DicomServerConfig: Fresh configuration object from database
        """
        try:
            return DicomServerConfig.objects.get(pk=1)
        except Exception as e:
            logger.error(f"Failed to get fresh config: {str(e)}")
            return self.config  # Fallback to cached config
    
    def _configure_sop_classes(self):
        """
        Configure supported SOP classes based on configuration.
        """
        # Verification SOP Class (C-ECHO)
        if self.config.enable_c_echo:
            self.ae.add_supported_context(Verification)
        
        # Storage SOP Classes - Add ALL storage contexts for C-GET/C-MOVE compatibility
        # This ensures the SCP can send back any type of DICOM file during retrieve operations
        if self.config.enable_c_get or self.config.enable_c_move:
            # Add all storage presentation contexts to support any DICOM file type
            for context in AllStoragePresentationContexts:
                self.ae.add_supported_context(context.abstract_syntax)
            
            # For C-GET: Enable SCP/SCU role negotiation on storage contexts
            # C-GET requires the server to act as Storage SCU to send files back
            # on the same association (unlike C-MOVE which creates a new association)
            if self.config.enable_c_get:
                for cx in self.ae.supported_contexts:
                    # Only set roles for storage contexts, not QR contexts
                    if cx.abstract_syntax not in [
                        PatientRootQueryRetrieveInformationModelFind,
                        StudyRootQueryRetrieveInformationModelFind,
                        PatientRootQueryRetrieveInformationModelMove,
                        StudyRootQueryRetrieveInformationModelMove,
                        PatientRootQueryRetrieveInformationModelGet,
                        StudyRootQueryRetrieveInformationModelGet,
                        Verification
                    ]:
                        cx.scp_role = True
                        cx.scu_role = False
        else:
            # If not using C-GET/C-MOVE, only add specific storage contexts based on config
            if self.config.support_ct_image_storage:
                self.ae.add_supported_context(CTImageStorage)
                
            if self.config.support_mr_image_storage:
                self.ae.add_supported_context(MRImageStorage)
                
            if self.config.support_rt_structure_storage:
                self.ae.add_supported_context(RTStructureSetStorage)
                
            if self.config.support_rt_plan_storage:
                self.ae.add_supported_context(RTPlanStorage)
                
            if self.config.support_rt_dose_storage:
                self.ae.add_supported_context(RTDoseStorage)
                
            if self.config.support_secondary_capture:
                self.ae.add_supported_context(SecondaryCaptureImageStorage)
        
        # Query/Retrieve SOP Classes
        if self.config.enable_c_find:
            self.ae.add_supported_context(PatientRootQueryRetrieveInformationModelFind)
            self.ae.add_supported_context(StudyRootQueryRetrieveInformationModelFind)
        
        if self.config.enable_c_move:
            self.ae.add_supported_context(PatientRootQueryRetrieveInformationModelMove)
            self.ae.add_supported_context(StudyRootQueryRetrieveInformationModelMove)
        
        if self.config.enable_c_get:
            self.ae.add_supported_context(PatientRootQueryRetrieveInformationModelGet)
            self.ae.add_supported_context(StudyRootQueryRetrieveInformationModelGet)
    
    def _configure_transfer_syntaxes(self):
        """
        Configure supported transfer syntaxes based on configuration.
        """
        transfer_syntaxes = []
        
        if self.config.support_implicit_vr_little_endian:
            transfer_syntaxes.append(ImplicitVRLittleEndian)
        
        if self.config.support_explicit_vr_little_endian:
            transfer_syntaxes.append(ExplicitVRLittleEndian)
        
        if self.config.support_explicit_vr_big_endian:
            transfer_syntaxes.append(ExplicitVRBigEndian)
        
        if self.config.support_jpeg_baseline:
            transfer_syntaxes.append(JPEGBaseline)
        
        if self.config.support_jpeg_lossless:
            transfer_syntaxes.append(JPEGLossless)
        
        if self.config.support_jpeg2000_lossless:
            transfer_syntaxes.append(JPEG2000Lossless)
        
        if self.config.support_rle_lossless:
            transfer_syntaxes.append(RLELossless)
        
        # Apply transfer syntaxes to all supported contexts
        if transfer_syntaxes:
            for context in self.ae.supported_contexts:
                context.transfer_syntax = transfer_syntaxes
    
    def start(self):
        """
        Start the DICOM SCP service.
        """
        if self._is_running:
            logger.warning("DICOM SCP service is already running")
            return False
        
        if not self.initialize():
            logger.error("Failed to initialize DICOM SCP service")
            return False
        
        try:
            # Create storage directory if it doesn't exist
            os.makedirs(self.config.storage_root_path, exist_ok=True)
            
            # Set up event handlers
            handlers = self._get_event_handlers()
            
            # Start the server in a separate thread
            self.server_thread = threading.Thread(
                target=self._run_server,
                args=(handlers,),
                daemon=True
            )
            self.server_thread.start()
            
            # Update service status
            self._is_running = True
            self.service_status.is_running = True
            self.service_status.service_started_at = timezone.now()
            self.service_status.process_id = os.getpid()
            self.service_status.save()
            
            # Update config last_service_start without triggering updated_at
            from django.db.models import F
            DicomServerConfig.objects.filter(pk=1).update(
                last_service_start=timezone.now()
            )
            
            logger.info(f"DICOM SCP service started on {self.config.host}:{self.config.port}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start DICOM SCP service: {str(e)}")
            self._is_running = False
            return False
    
    def stop(self):
        """
        Stop the DICOM SCP service.
        """
        if not self._is_running:
            logger.warning("DICOM SCP service is not running")
            return False
        
        try:
            self._is_running = False
            
            # Shutdown the AE
            if self.ae:
                self.ae.shutdown()
            
            # Wait for server thread to finish
            if self.server_thread and self.server_thread.is_alive():
                self.server_thread.join(timeout=5)
            
            # Update service status
            self.service_status.is_running = False
            self.service_status.service_stopped_at = timezone.now()
            self.service_status.active_connections = 0
            self.service_status.save()
            
            # Update config
            self.config.last_service_stop = timezone.now()
            self.config.save()
            
            logger.info("DICOM SCP service stopped")
            return True
            
        except Exception as e:
            logger.error(f"Failed to stop DICOM SCP service: {str(e)}")
            return False
    
    def restart(self):
        """
        Restart the DICOM SCP service.
        Reloads configuration from database before restarting.
        """
        logger.info("Restarting DICOM SCP service...")
        self.stop()
        time.sleep(2)
        
        # Reload configuration from database
        if not self.initialize():
            logger.error("Failed to reload configuration during restart")
            return False
        
        return self.start()
    
    def _run_server(self, handlers):
        """
        Run the DICOM SCP server (blocking call).
        """
        try:
            self.ae.start_server(
                (self.config.host, self.config.port),
                block=True,
                evt_handlers=handlers
            )
        except Exception as e:
            logger.error(f"DICOM SCP server error: {str(e)}")
            self._is_running = False
    
    def _get_event_handlers(self):
        """
        Get event handlers for DICOM operations.
        """
        handlers = []
        
        # Association handlers
        handlers.append((evt.EVT_CONN_OPEN, self._handle_connection_open))
        handlers.append((evt.EVT_CONN_CLOSE, self._handle_connection_close))
        # Note: EVT_REQUESTED is a notification event, not intervention - cannot reject here
        # Validation moved to EVT_ACCEPTED for proper handling
        handlers.append((evt.EVT_ACCEPTED, self._handle_association_accepted))
        handlers.append((evt.EVT_REJECTED, self._handle_association_rejected))
        handlers.append((evt.EVT_RELEASED, self._handle_association_released))
        handlers.append((evt.EVT_ABORTED, self._handle_association_aborted))
        
        # Service handlers
        if self.config.enable_c_echo:
            handlers.append((evt.EVT_C_ECHO, self._handle_c_echo))
        
        if self.config.enable_c_store:
            handlers.append((evt.EVT_C_STORE, self._handle_c_store))
        
        if self.config.enable_c_find:
            handlers.append((evt.EVT_C_FIND, self._handle_c_find))
        
        if self.config.enable_c_move:
            handlers.append((evt.EVT_C_MOVE, self._handle_c_move))
        
        if self.config.enable_c_get:
            handlers.append((evt.EVT_C_GET, self._handle_c_get))
        
        return handlers
    
    def _validate_calling_ae(self, calling_ae_title):
        """
        Validate calling AE title against allowed list using unified RemoteDicomNode model.
        """
        if not self.config.require_calling_ae_validation:
            return True
        
        # Allow empty AE title if validation is disabled
        if not calling_ae_title or calling_ae_title.strip() == '':
            if not self.config.require_calling_ae_validation:
                return True
            logger.debug("Empty calling AE title, checking if validation required")
        
        try:
            remote_node = RemoteDicomNode.objects.filter(
                incoming_ae_title=calling_ae_title,
                allow_incoming=True,
                is_active=True
            ).first()
            
            if remote_node:
                # Update last incoming connection time
                remote_node.update_last_incoming_connection()
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error validating calling AE: {str(e)}")
            return False
    
    def _validate_remote_ip(self, remote_ip):
        """
        Validate remote IP address against allowed list.
        """
        if not self.config.require_ip_validation:
            return True
        
        if not self.config.allowed_ip_addresses:
            return True
        
        allowed_ips = [ip.strip() for ip in self.config.allowed_ip_addresses.split(',')]
        
        # Simple IP matching (can be enhanced with CIDR support)
        for allowed_ip in allowed_ips:
            if allowed_ip in remote_ip or remote_ip.startswith(allowed_ip.split('/')[0]):
                return True
        
        return False
    
    def _log_transaction(self, transaction_type, status, event, **kwargs):
        """
        Log DICOM transaction to database asynchronously using Celery.
        Non-blocking operation - queues the write to a background worker.
        """
        try:
            from .tasks import log_dicom_transaction_async
            
            transaction_data = {
                'transaction_type': transaction_type,
                'status': status,
                'calling_ae_title': event.assoc.requestor.ae_title if hasattr(event, 'assoc') else 'UNKNOWN',
                'called_ae_title': self.config.ae_title,
                'remote_ip': event.assoc.requestor.address if hasattr(event, 'assoc') else '0.0.0.0',
                'remote_port': event.assoc.requestor.port if hasattr(event, 'assoc') else 0,
            }
            transaction_data.update(kwargs)
            
            # Queue the database write to Celery worker (non-blocking)
            log_dicom_transaction_async.delay(transaction_data)
            
        except Exception as e:
            logger.error(f"Failed to queue transaction log: {str(e)}")
    
    # Event Handlers
    
    def _handle_connection_open(self, event):
        """Handle connection open event."""
        if self.config.log_connection_attempts:
            # event.address is a tuple (ip, port)
            address_info = event.address if isinstance(event.address, tuple) else (event.address, 'unknown')
            logger.info(f"Connection opened from {address_info[0]}:{address_info[1]}")
        
        # Update active connections
        self.service_status.total_connections += 1
        self.service_status.active_connections += 1
        self.service_status.last_connection_at = timezone.now()
        self.service_status.save()
    
    def _handle_connection_close(self, event):
        """Handle connection close event."""
        if self.config.log_connection_attempts:
            # event.address is a tuple (ip, port)
            address_info = event.address if isinstance(event.address, tuple) else (event.address, 'unknown')
            logger.info(f"Connection closed from {address_info[0]}:{address_info[1]}")
        
        # Update active connections
        self.service_status.active_connections = max(0, self.service_status.active_connections - 1)
        self.service_status.save()
    
    def _handle_association_requested(self, event):
        """
        Handle association requested event (NOTIFICATION EVENT).
        Note: This is a notification event in pynetdicom, not an intervention event.
        Return values are ignored. Validation is performed in EVT_ACCEPTED handler.
        """
        calling_ae = event.assoc.requestor.ae_title
        remote_ip = event.assoc.requestor.address
        
        logger.debug(f"Association requested from {calling_ae} ({remote_ip})")
    
    def _handle_association_accepted(self, event):
        """
        Handle association accepted event.
        Perform validation here since EVT_REQUESTED is a notification event.
        If validation fails, abort the association.
        """
        calling_ae = event.assoc.requestor.ae_title
        remote_ip = event.assoc.requestor.address
        
        # Validate calling AE title
        if not self._validate_calling_ae(calling_ae):
            logger.warning(f"Association validation failed: Calling AE '{calling_ae}' not authorized - aborting")
            self._log_transaction(
                'ASSOCIATION',
                'REJECTED',
                event,
                error_message=f"Calling AE '{calling_ae}' not authorized"
            )
            # Abort the association
            event.assoc.abort()
            return
        
        # Validate remote IP
        if not self._validate_remote_ip(remote_ip):
            logger.warning(f"Association validation failed: Remote IP '{remote_ip}' not authorized - aborting")
            self._log_transaction(
                'ASSOCIATION',
                'REJECTED',
                event,
                error_message=f"Remote IP '{remote_ip}' not authorized"
            )
            # Abort the association
            event.assoc.abort()
            return
        
        logger.info(f"Association accepted from {calling_ae} ({remote_ip})")
        
        self._log_transaction(
            'ASSOCIATION',
            'SUCCESS',
            event
        )
    
    def _handle_association_rejected(self, event):
        """Handle association rejected event."""
        logger.warning(f"Association rejected from {event.assoc.requestor.address}")
        
        self._log_transaction(
            'ASSOCIATION',
            'REJECTED',
            event
        )
    
    def _handle_association_released(self, event):
        """Handle association released event."""
        logger.debug(f"Association released from {event.assoc.requestor.ae_title}")
    
    def _handle_association_aborted(self, event):
        """Handle association aborted event."""
        logger.warning(f"Association aborted from {event.assoc.requestor.ae_title}")
        
        self._log_transaction(
            'ASSOCIATION',
            'ABORTED',
            event
        )
        
        self.service_status.total_errors += 1
        self.service_status.save()
    
    def _handle_c_echo(self, event):
        """
        Handle C-ECHO request (verification).
        C-ECHO is always allowed regardless of AE validation settings,
        as it's used for connectivity testing.
        """
        calling_ae = event.assoc.requestor.ae_title
        remote_ip = event.assoc.requestor.address
        
        logger.info(f"C-ECHO request from {calling_ae} ({remote_ip})")
        
        self._log_transaction(
            'C-ECHO',
            'SUCCESS',
            event
        )
        
        return 0x0000  # Success
    
    def _handle_c_store(self, event):
        """
        Handle C-STORE request (receive DICOM file).
        This is implemented in a separate file for better organization.
        """
        from .handlers.c_store_handler import handle_c_store
        return handle_c_store(self, event)
    
    def _handle_c_find(self, event):
        """
        Handle C-FIND request (query).
        This is implemented in a separate file for better organization.
        """
        from .handlers.c_find_handler import handle_c_find
        return handle_c_find(self, event)
    
    def _handle_c_move(self, event):
        """
        Handle C-MOVE request (retrieve).
        This is implemented in a separate file for better organization.
        """
        from .handlers.c_move_handler import handle_c_move
        return handle_c_move(self, event)
    
    def _handle_c_get(self, event):
        """
        Handle C-GET request (retrieve).
        This is implemented in a separate file for better organization.
        """
        from .handlers.c_get_handler import handle_c_get
        return handle_c_get(self, event)

    @property
    def is_running(self):
        """
        Check if the service is currently running.
        """
        return self._is_running


# Global service instance
_service_instance = None


def get_service_instance():
    """
    Get or create the global DICOM SCP service instance.
    """
    global _service_instance
    if _service_instance is None:
        _service_instance = DicomSCPService()
    return _service_instance
