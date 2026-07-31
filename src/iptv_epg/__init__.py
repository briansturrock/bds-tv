__all__ = ["__version__"]

import os

__version__ = os.getenv("IPTV_EPG_VERSION", "1.1.0-sonarr.1")
