from django.apps import AppConfig
import logging

logger = logging.getLogger(__name__)


class DicomHandlerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'dicom_handler'
    
    def ready(self):
        """
        Called when Django starts up. Apply rt-utils patches here.
        """
        try:
            from dicom_handler.utils.rt_utils_patches import apply_rt_utils_patches
            apply_rt_utils_patches()
            logger.info("Successfully applied rt-utils patches for degenerate contour handling")
        except Exception as e:
            logger.error(f"Failed to apply rt-utils patches: {e}", exc_info=True)
