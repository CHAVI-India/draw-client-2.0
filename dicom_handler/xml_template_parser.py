"""
XML Template Parser - Legacy Wrapper

This module provides backward compatibility with the old XMLTemplateParser interface.
It now delegates to the vendor-specific parser factory.

For new code, use: from dicom_handler.parsers import TemplateParserFactory
"""

from dicom_handler.parsers import TemplateParserFactory


class XMLTemplateParser:
    """
    Legacy wrapper for XML template parsing.
    Delegates to TemplateParserFactory for vendor-specific parsing.
    
    This class maintains backward compatibility with existing code.
    """
    
    @staticmethod
    def parse_xml_file(file_content: str) -> dict:
        """
        Parse XML template file and extract structure information.
        Delegates to TemplateParserFactory.
        
        Args:
            file_content: XML file content as string
            
        Returns:
            Dictionary with template metadata and list of structures
            
        Raises:
            ValueError: If XML format is invalid or unsupported
        """
        return TemplateParserFactory.parse_xml_file(file_content)
    
    @staticmethod
    def validate_roi_label(label: str) -> tuple:
        """
        Validate ROI label according to TG263 standard.
        Delegates to TemplateParserFactory.
        
        Args:
            label: ROI label to validate
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        return TemplateParserFactory.validate_roi_label(label)
    
    @staticmethod
    def validate_dicom_color(color: str) -> tuple:
        """
        Validate DICOM color format (R\\G\\B with values 0-255).
        Delegates to TemplateParserFactory.
        
        Args:
            color: Color string to validate
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        return TemplateParserFactory.validate_dicom_color(color)
