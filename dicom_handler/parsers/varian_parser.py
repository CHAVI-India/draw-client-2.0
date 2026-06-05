"""
Varian Eclipse Template Parser

Parser for Varian Eclipse XML files including Structure Templates and Clinical Protocols.
"""

import xml.etree.ElementTree as ET
import re
from typing import Dict, Optional, Tuple
from .base_parser import BaseTemplateParser


class VarianEclipseParser(BaseTemplateParser):
    """
    Parser for Varian Eclipse XML files.
    Supports both Structure Templates and Clinical Protocols.
    """
    
    # Color name to DICOM RGB mapping
    COLOR_MAP = {
        'Yellow': '255\\255\\0',
        'Cyan': '0\\255\\255',
        'Red': '255\\0\\0',
        'Green': '0\\255\\0',
        'Blue': '0\\0\\255',
        'Magenta': '255\\0\\255',
        'White': '255\\255\\255',
        'Black': '0\\0\\0',
        'Orange': '255\\165\\0',
        'Purple': '128\\0\\128',
        'Pink': '255\\192\\203',
        'Brown': '165\\42\\42',
        'Gray': '128\\128\\128',
        'Grey': '128\\128\\128',
    }
    
    # Volume type to RT ROI Interpreted Type mapping
    VOLUME_TYPE_TO_RT_ROI_MAP = {
        'ORGAN': 'ORGAN',
        'PTV': 'PTV',
        'CTV': 'CTV',
        'GTV': 'GTV',
        'EXTERNAL': 'EXTERNAL',
        'AVOIDANCE': 'AVOIDANCE',
        'CAVITY': 'CAVITY',
        'CONTRAST_AGENT': 'CONTRAST_AGENT',
        'BOLUS': 'BOLUS',
        'SUPPORT': 'SUPPORT',
        'FIXATION': 'FIXATION',
        'CONTROL': 'CONTROL',
        'DOSE_REGION': 'DOSE_REGION',
        'BODY': 'EXTERNAL',
    }
    
    def can_parse(self, root: ET.Element) -> bool:
        """Check if this is a Varian Eclipse XML file."""
        return root.tag in ['StructureTemplate', 'Protocol']
    
    def get_vendor_name(self) -> str:
        """Return vendor name."""
        return 'Varian Eclipse'
    
    def get_supported_formats(self) -> list:
        """Return supported format names."""
        return ['Structure Template', 'Clinical Protocol']
    
    def parse(self, root: ET.Element) -> Dict:
        """
        Parse Varian Eclipse XML and extract structure information.
        
        Args:
            root: XML root element
            
        Returns:
            Dictionary with template metadata and structures
            
        Raises:
            ValueError: If required elements are missing
        """
        # Extract template metadata from Preview element
        preview = root.find('.//Preview')
        template_info = {
            'template_id': preview.get('ID', '') if preview is not None else '',
            'diagnosis': preview.get('Diagnosis', '') if preview is not None else '',
            'treatment_site': preview.get('TreatmentSite', '') if preview is not None else '',
            'description': preview.get('Description', '') if preview is not None else '',
            'type': preview.get('Type', 'StructureTemplate') if preview is not None else 'StructureTemplate',
            'vendor': self.get_vendor_name()
        }
        
        # Extract structures
        structures = []
        structure_elements = root.findall('.//Structure')
        
        # Validate that structures were found
        if not structure_elements:
            raise ValueError(
                f"No structures found in {self.get_vendor_name()} XML file. "
                f"Please ensure this is a valid Structure Template or Clinical Protocol."
            )
        
        for struct_elem in structure_elements:
            structure_id = struct_elem.get('ID', '')
            structure_name = structure_id or struct_elem.get('Name', '')
            
            # Get VolumeType from Identification section
            volume_type_elem = struct_elem.find('.//VolumeType')
            volume_type = volume_type_elem.text if volume_type_elem is not None else None
            
            # Get color from ColorAndStyle
            color_elem = struct_elem.find('.//ColorAndStyle')
            color_string = color_elem.text if color_elem is not None else None
            
            # Parse color to DICOM format
            dicom_color = self._parse_color(color_string)
            
            # Map volume type to RT ROI Interpreted Type
            rt_roi_type = self._parse_volume_type(volume_type)
            
            structure_data = {
                'id': structure_id,
                'name': structure_name,
                'original_name': structure_name,
                'volume_type': volume_type,
                'rt_roi_interpreted_type': rt_roi_type,
                'color_string': color_string,
                'dicom_color': dicom_color,
            }
            
            structures.append(structure_data)
        
        return {
            'template_info': template_info,
            'structures': structures,
            'total_structures': len(structures)
        }
    
    def _parse_color(self, color_string: Optional[str]) -> Optional[str]:
        """
        Parse color string and convert to DICOM format (R\\G\\B).
        
        Args:
            color_string: Color string from XML (name, hex, or numeric)
            
        Returns:
            DICOM color string (R\\G\\B) or None if parsing fails
        """
        if not color_string:
            return None
        
        color_string = color_string.strip()
        
        # Handle hex color (#RRGGBB or RRGGBB)
        if color_string.startswith('#'):
            color_string = color_string[1:]
        
        if len(color_string) == 6 and all(c in '0123456789ABCDEFabcdef' for c in color_string):
            try:
                r = int(color_string[0:2], 16)
                g = int(color_string[2:4], 16)
                b = int(color_string[4:6], 16)
                return f"{r}\\{g}\\{b}"
            except ValueError:
                pass
        
        # Handle numeric format (concatenated RGB)
        num_str = re.sub(r'[^\d]', '', color_string)
        if num_str:
            if len(num_str) >= 3:
                try:
                    num = int(num_str)
                    # Extract RGB from concatenated number
                    b = num % 256
                    g = (num // 256) % 256
                    r = (num // 65536) % 256
                    return f"{r}\\{g}\\{b}"
                except:
                    pass
        
        # Handle named colors
        if color_string in self.COLOR_MAP:
            return self.COLOR_MAP[color_string]
        
        # Check case-insensitive match
        for name, rgb in self.COLOR_MAP.items():
            if name.lower() == color_string.lower():
                return rgb
        
        return None
    
    def _parse_volume_type(self, volume_type: Optional[str]) -> Optional[str]:
        """
        Map Varian VolumeType to DICOM RT ROI Interpreted Type.
        
        Args:
            volume_type: Volume type from XML
            
        Returns:
            RT ROI Interpreted Type or None
        """
        if not volume_type:
            return None
        
        volume_type_upper = volume_type.upper().strip()
        return self.VOLUME_TYPE_TO_RT_ROI_MAP.get(volume_type_upper)
    
    @staticmethod
    def validate_roi_label(label: str) -> Tuple[bool, str]:
        """
        Validate ROI label according to TG263 standard.
        
        Args:
            label: ROI label to validate
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not label:
            return False, "ROI Label cannot be empty"
        
        if len(label) > 16:
            return False, "ROI Label cannot exceed 16 characters as per TG263 standard"
        
        return True, ""
    
    @staticmethod
    def validate_dicom_color(color: str) -> Tuple[bool, str]:
        """
        Validate DICOM color format (R\\G\\B with values 0-255).
        
        Args:
            color: Color string to validate
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not color:
            return False, "Color cannot be empty"
        
        parts = color.strip().split('\\')
        if len(parts) != 3:
            return False, "Color must have exactly 3 RGB values separated by backslashes (e.g., '255\\0\\0')"
        
        try:
            for part in parts:
                value = int(part.strip())
                if value < 0 or value > 255:
                    return False, f"Each RGB value must be between 0 and 255. Invalid value: {value}"
        except ValueError:
            return False, "RGB values must be integers"
        
        return True, ""
