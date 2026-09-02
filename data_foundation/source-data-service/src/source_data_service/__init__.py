"""Source data service for ai_stock.

The service owns provider raw-interface ingestion, source build lineage,
data gap repair planning, and source readiness evaluation. Models must read
canonical source tables only, never provider raw tables directly.
"""

__all__ = ["__version__"]
__version__ = "0.1.0-ds7"
