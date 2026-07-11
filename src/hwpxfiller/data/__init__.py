from __future__ import annotations

from .base import DataSource, Record
from .excel import ExcelDataSource
from .factory import make_source, source_for_path

__all__ = ["DataSource", "Record", "ExcelDataSource", "source_for_path", "make_source"]
