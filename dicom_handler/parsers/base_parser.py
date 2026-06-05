"""
Base Template Parser

Abstract base class defining the interface for vendor-specific template parsers.
"""

import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from typing import Dict


class BaseTemplateParser(ABC):
    """
    Abstract base class for vendor-specific template parsers.
    All vendor parsers should inherit from this class and implement the required methods.
    """
    
    @abstractmethod
    def can_parse(self, root: ET.Element) -> bool:
        """
        Check if this parser can handle the given XML root element.
        
        Args:
            root: XML root element
            
        Returns:
            True if this parser can handle the format, False otherwise
        """
        pass
    
    @abstractmethod
    def parse(self, root: ET.Element) -> Dict:
        """
        Parse the XML and extract structure information.
        
        Args:
            root: XML root element
            
        Returns:
            Dictionary with the following structure:
            {
                'template_info': {
                    'template_id': str,
                    'diagnosis': str,
                    'treatment_site': str,
                    'description': str,
                    'type': str,
                    'vendor': str
                },
                'structures': [
                    {
                        'id': str,
                        'name': str,
                        'original_name': str,
                        'volume_type': str,
                        'rt_roi_interpreted_type': str,
                        'color_string': str,
                        'dicom_color': str
                    },
                    ...
                ],
                'total_structures': int
            }
            
        Raises:
            ValueError: If parsing fails
        """
        pass
    
    @abstractmethod
    def get_vendor_name(self) -> str:
        """
        Return the vendor name for this parser.
        
        Returns:
            Vendor name (e.g., 'Varian Eclipse', 'RayStation', 'Pinnacle')
        """
        pass
    
    @abstractmethod
    def get_supported_formats(self) -> list:
        """
        Return list of supported format names.
        
        Returns:
            List of format names (e.g., ['Structure Template', 'Clinical Protocol'])
        """
        pass
