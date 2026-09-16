#!/usr/bin/env python3
import logging
import os
import sys
from pathlib import Path
# 没111


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python main3.py <port>")
    port = int(sys.argv[1])
    root = Path(__file__).resolve().parent
    os.chdir(root)
    sys.path.insert(0, str(root / "src"))
    log_dir = root / "logs"
    log_dir.mkdir(exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(
                log_dir / "agent.log",
                encoding="utf-8",
            ),
        ],
    )

    from agent.server import serve

    logging.info("listening on 0.0.0.0:%d", port)
    serve(port)


if __name__ == "__main__":
    main()
