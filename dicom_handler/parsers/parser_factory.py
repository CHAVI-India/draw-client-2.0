"""
Template Parser Factory

Factory class to detect XML format and route to the appropriate vendor-specific parser.
"""

import xml.etree.ElementTree as ET
from typing import Dict, List
from .base_parser import BaseTemplateParser
from .varian_parser import VarianEclipseParser


class TemplateParserFactory:
    """
    Factory class for creating and managing vendor-specific template parsers.
    Automatically detects the XML format and routes to the appropriate parser.
    """
    
    # Registry of available parsers
    _parsers: List[BaseTemplateParser] = [
        VarianEclipseParser(),
        # Add more parsers here as they are implemented:
        # RayStationParser(),
        # PinnacleParser(),
        # MonacoParser(),
    ]
    
    @classmethod
    def parse_xml_file(cls, file_content: str) -> Dict:
        """
        Parse XML template file using the appropriate vendor-specific parser.
        
        Args:
            file_content: XML file content as string
            
        Returns:
            Dictionary with template metadata and list of structures
            
        Raises:
            ValueError: If XML format is invalid or unsupported
        """
        # Parse XML
        try:
            root = ET.fromstring(file_content)
        except ET.ParseError as e:
            raise ValueError(f"Invalid XML format: {str(e)}")
        
        # Try each parser to find one that can handle this format
        for parser in cls._parsers:
            if parser.can_parse(root):
                try:
                    return parser.parse(root)
                except Exception as e:
                    raise ValueError(
                        f"Error parsing {parser.get_vendor_name()} XML: {str(e)}"
                    )
        
        # No parser could handle this format
        supported_vendors = cls.get_supported_vendors()
        raise ValueError(
            f"Unsupported XML format. Root element is '{root.tag}'. "
            f"Currently supported vendors: {', '.join(supported_vendors)}. "
            f"Please ensure you are uploading a valid structure template XML file."
        )
    
    @classmethod
    def get_supported_vendors(cls) -> List[str]:
        """
        Get list of supported vendor names.
        
        Returns:
            List of vendor names
        """
        return [parser.get_vendor_name() for parser in cls._parsers]
    
    @classmethod
    def get_supported_formats(cls) -> Dict[str, List[str]]:
        """
        Get dictionary of supported formats by vendor.
        
        Returns:
            Dictionary mapping vendor names to list of supported formats
        """
        return {
            parser.get_vendor_name(): parser.get_supported_formats()
            for parser in cls._parsers
        }
    
    @classmethod
    def register_parser(cls, parser: BaseTemplateParser):
        """
        Register a new parser.
        
        Args:
            parser: Parser instance to register
        """
        if not isinstance(parser, BaseTemplateParser):
            raise TypeError("Parser must inherit from BaseTemplateParser")
        cls._parsers.append(parser)
    
    @classmethod
    def validate_roi_label(cls, label: str) -> tuple:
        """
        Validate ROI label (delegates to Varian parser for now).
        
        Args:
            label: ROI label to validate
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        # Use Varian parser's validation (TG263 standard)
        return VarianEclipseParser.validate_roi_label(label)
    
    @classmethod
    def validate_dicom_color(cls, color: str) -> tuple:
        """
        Validate DICOM color format (delegates to Varian parser for now).
        
        Args:
            color: Color string to validate
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        # Use Varian parser's validation
        return VarianEclipseParser.validate_dicom_color(color)
