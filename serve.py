#!/usr/bin/env python3
"""
Simple HTTP server for the QGIS plugin and resource repositories.
For the Constructel internal network.

The network-level restriction is handled by the network infrastructure
and by Nginx in production (allow/deny directives in nginx.conf).

Usage:
    python3 serve.py [--port 9080] [--resource-port 9081] [--bind 192.168.160.31]
"""

import argparse
import functools
import logging
import os
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

REPO_ROOT = Path(__file__).resolve().parent


class QGISRepoHandler(SimpleHTTPRequestHandler):
    """HTTP handler with correct MIME types for QGIS repositories."""

    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".xml": "application/xml",
        ".zip": "application/zip",
        ".ini": "text/plain",
        ".qml": "application/xml",
        ".model3": "application/xml",
    }


def main():
    parser = argparse.ArgumentParser(description="Serve QGIS repositories - Constructel")
    parser.add_argument("--port", type=int, default=9080, help="Port plugin repo (default: 9080)")
    parser.add_argument("--resource-port", type=int, default=9081, help="Port resource repo (default: 9081)")
    parser.add_argument("--bind", default=os.environ.get("QGIS_REPO_BIND", "0.0.0.0"), help="Bind address (default: $QGIS_REPO_BIND or 0.0.0.0)")
    args = parser.parse_args()

    os.chdir(REPO_ROOT)

    # Plugin repo server on main port
    plugin_handler = functools.partial(QGISRepoHandler, directory=str(REPO_ROOT))
    plugin_server = HTTPServer((args.bind, args.port), plugin_handler)

    # Resource sharing git bare repo on separate port (dumb HTTP protocol)
    resource_dir = str(REPO_ROOT / "resource-repo.git")
    resource_handler = functools.partial(QGISRepoHandler, directory=resource_dir)
    resource_server = HTTPServer((args.bind, args.resource_port), resource_handler)

    log = logging.getLogger("qgis-repo")
    log.info("Depot QGIS Constructel")
    log.info("  Plugin repo:   http://%s:%d/plugin-repo/plugins.xml", args.bind, args.port)
    log.info("  Resource repo (git): http://%s:%d/", args.bind, args.resource_port)
    log.info("Ctrl+C pour arreter.")

    # Run resource server in a background thread
    resource_thread = threading.Thread(target=resource_server.serve_forever, daemon=True)
    resource_thread.start()

    try:
        plugin_server.serve_forever()
    except KeyboardInterrupt:
        log.info("Arrete.")
        resource_server.shutdown()
        plugin_server.server_close()
        resource_server.server_close()


if __name__ == "__main__":
    main()
