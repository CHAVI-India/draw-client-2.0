#!/usr/bin/env python
"""
Update SystemConfiguration with real DRAW API server settings
"""

import os
import sys
import django
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'draw_client.settings')
django.setup()

from dicom_handler.models import SystemConfiguration

def update_configuration():
    """
    Update SystemConfiguration with real API settings
    """
    config = SystemConfiguration.load()
    
    print("Current configuration:")
    print(f"  Base URL: {config.draw_base_url}")
    print(f"  Upload Endpoint: {config.draw_upload_endpoint}")
    print(f"  Bearer Token: {'Present' if config.draw_bearer_token else 'Missing'}")
    print(f"  Refresh Token: {'Present' if config.draw_refresh_token else 'Missing'}")
    
    print("\nPlease enter your real DRAW API server configuration:")
    
    # Get real API URL
    new_base_url = input("Enter DRAW API Base URL (e.g., https://draw.chavi.ai): ").strip()
    if new_base_url:
        config.draw_base_url = new_base_url
    
    # Optionally update endpoints (use defaults if not specified)
    upload_endpoint = input(f"Upload endpoint (current: {config.draw_upload_endpoint}): ").strip()
    if upload_endpoint:
        config.draw_upload_endpoint = upload_endpoint
    
    # Optionally update tokens
    update_tokens = input("Do you want to update bearer/refresh tokens? (y/n): ").strip().lower()
    if update_tokens == 'y':
        bearer_token = input("Enter bearer token: ").strip()
        if bearer_token:
            config.draw_bearer_token = bearer_token
        
        refresh_token = input("Enter refresh token: ").strip()
        if refresh_token:
            config.draw_refresh_token = refresh_token
    
    # Save configuration
    config.save()
    
    print("\nUpdated configuration:")
    print(f"  Base URL: {config.draw_base_url}")
    print(f"  Upload Endpoint: {config.draw_upload_endpoint}")
    print(f"  Bearer Token: {'Present' if config.draw_bearer_token else 'Missing'}")
    print(f"  Refresh Token: {'Present' if config.draw_refresh_token else 'Missing'}")
    
    print("\n✅ Configuration updated successfully!")

if __name__ == "__main__":
    update_configuration()
