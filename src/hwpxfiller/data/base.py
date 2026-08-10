"""Legacy import facade for :mod:`hwpxfiller.domain.data_source`."""

from __future__ import annotations

from hwpxfiller.domain.data_source import (
    Record,
    SUPPORTED_DATA_FILE_EXTENSIONS,
    DataSource,
)

__all__ = ["Record", "SUPPORTED_DATA_FILE_EXTENSIONS", "DataSource"]
