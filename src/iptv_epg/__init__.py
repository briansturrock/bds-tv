__all__ = ["__version__"]

import os

__version__ = os.getenv("IPTV_EPG_VERSION", "0.10.2")
