"""Compatibility entry point; implementation lives in proxy/subscription_proxy.py."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from proxy.subscription_proxy import app, main


if __name__ == "__main__":
    main()
