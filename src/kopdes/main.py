from __future__ import annotations

import sys
from pathlib import Path

from kopdes.bootstrap import build_application


def main() -> int:
    config_path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    context = build_application(config_path)
    context.window.show()
    return context.app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
