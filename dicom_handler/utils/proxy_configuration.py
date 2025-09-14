import os
import logging
from typing import Dict
from urllib.request import getproxies

logger = logging.getLogger(__name__)

def get_proxy_settings() -> Dict[str, str]:
    """
    Get proxy settings from environment variables, system configuration, and Docker settings.
    Returns a dictionary suitable for use with the requests library.
    
    Sources of proxy settings (in order of precedence):
    1. Docker environment variables (HTTP_PROXY, HTTPS_PROXY, NO_PROXY)
    2. System proxy settings (via urllib.request.getproxies())
    
    Returns:
        Dict containing proxy settings or empty dict if no proxies configured
    """
    proxies = {}
    
    # Try environment variables (including those from .env.docker)
    http_proxy = os.getenv('HTTP_PROXY')
    https_proxy = os.getenv('HTTPS_PROXY')
    no_proxy = os.getenv('NO_PROXY')
    
    if http_proxy:
        proxies['http'] = http_proxy
        logger.info(f"Using HTTP proxy: {http_proxy}")
    if https_proxy:
        proxies['https'] = https_proxy
        logger.info(f"Using HTTPS proxy: {https_proxy}")
    if no_proxy:
        proxies['no_proxy'] = no_proxy
        logger.info(f"Proxy exclusions: {no_proxy}")
            
    # If no environment variables set, try system proxy settings
    if not proxies:
        system_proxies = getproxies()
        if system_proxies:
            proxies.update(system_proxies)
            logger.info(f"Using system proxy settings: {system_proxies}")
            
    if not proxies:
        logger.info("No proxy configuration found")
            
    return proxies

def get_session_with_proxy():
    """
    Create and return a requests Session object with proxy configuration.
    This is useful for making multiple requests with the same proxy settings.
    
    Returns:
        requests.Session: Session object configured with proxy settings
    """
    import requests
    session = requests.Session()
    session.proxies.update(get_proxy_settings())
    return session 