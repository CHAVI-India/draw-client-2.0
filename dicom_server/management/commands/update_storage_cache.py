"""
Management command to update the DICOM storage cache.
This command calculates the actual storage usage and updates the cached value.
Can be run manually or scheduled via cron for periodic updates.
"""
from django.core.management.base import BaseCommand
from dicom_server.models import DicomServerConfig


class Command(BaseCommand):
    help = 'Update the cached storage usage for DICOM server'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force update even if cache is not stale',
        )

    def handle(self, *args, **options):
        self.stdout.write('Updating DICOM storage cache...')
        
        try:
            config = DicomServerConfig.objects.get(pk=1)
        except DicomServerConfig.DoesNotExist:
            self.stdout.write(self.style.ERROR('DICOM server configuration not found'))
            return
        
        force = options.get('force', False)
        
        if not force and not config.should_update_storage_cache(max_age_minutes=5):
            self.stdout.write(self.style.WARNING(
                f'Cache is still fresh (last updated: {config.cached_storage_last_updated}). '
                'Use --force to update anyway.'
            ))
            return
        
        self.stdout.write('Calculating storage usage (this may take a while)...')
        storage_gb = config.update_storage_cache()
        
        self.stdout.write(self.style.SUCCESS(
            f'Storage cache updated successfully: {storage_gb} GB used'
        ))
        self.stdout.write(f'Cache timestamp: {config.cached_storage_last_updated}')
