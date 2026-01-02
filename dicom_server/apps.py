from django.apps import AppConfig
import logging

logger = logging.getLogger(__name__)


class DicomServerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'dicom_server'
    
    def ready(self):
        """
        Called when Django starts up.
        Handles cleanup and auto-start of DICOM service.
        """
        # Only run in the main process, not in management commands or migrations
        import sys
        if 'runserver' not in sys.argv and 'gunicorn' not in sys.argv[0]:
            return
        
        try:
            from .service_manager import cleanup_stale_status, auto_start_service
            
            # Clean up any stale service status from previous runs
            cleanup_stale_status()
            
            # Auto-start service if configured
            auto_start_service()
            
        except Exception as e:
            logger.error(f"Error in DICOM server app ready: {str(e)}")
