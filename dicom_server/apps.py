from django.apps import AppConfig
from django.db import connection
from django.db.utils import OperationalError
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
        
        # Skip if running migrations or if database is not ready
        if 'migrate' in sys.argv or 'makemigrations' in sys.argv:
            return
        
        # Defer database access until after startup using a thread
        # This prevents accessing DB during app initialization
        import threading
        
        def initialize_service():
            # Wait a moment for Django to fully initialize
            import time
            time.sleep(1)
            
            try:
                # Check if database tables exist before accessing
                from django.db import connection
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT EXISTS (SELECT FROM information_schema.tables "
                        "WHERE table_name='dicom_server_dicomserverconfig')"
                    )
                    tables_exist = cursor.fetchone()[0]
                
                if not tables_exist:
                    logger.info("DICOM server tables not yet created. Skipping auto-start.")
                    return
                
                from .service_manager import cleanup_stale_status, auto_start_service
                
                # Clean up any stale service status from previous runs
                cleanup_stale_status()
                
                # Auto-start service if configured
                auto_start_service()
                
            except OperationalError as e:
                logger.warning(f"Database not ready for DICOM server initialization: {str(e)}")
            except Exception as e:
                logger.error(f"Error in DICOM server app ready: {str(e)}")
        
        # Start initialization in background thread
        thread = threading.Thread(target=initialize_service, daemon=True)
        thread.start()
