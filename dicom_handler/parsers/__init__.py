"""
XML Template Parsers for various TPS vendors.

This package provides vendor-specific parsers for structure template XML files.
"""

from .base_parser import BaseTemplateParser
from .varian_parser import VarianEclipseParser
from .parser_factory import TemplateParserFactory

__all__ = [
    'BaseTemplateParser',
    'VarianEclipseParser',
    'TemplateParserFactory',
]
