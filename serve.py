#!/usr/bin/env python3
"""
Simple HTTP server for the QGIS plugin and resource repositories.
For the Constructel internal network.

The network-level restriction is handled by the network infrastructure
and by Nginx in production (allow/deny directives in nginx.conf).

The resource-repo port wraps `git-http-backend` as a CGI so clients can
`git clone`, `git pull` AND `git push` against http://host:<resource-port>/.
Both smart (push/pull) and dumb HTTP protocols are served transparently.

Usage:
    python3 serve.py [--port 9080] [--resource-port 9082] [--bind 192.168.160.31]
"""

import argparse
import functools
import logging
import os
import shutil
import subprocess
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler, BaseHTTPRequestHandler
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("qgis-repo")

REPO_ROOT = Path(__file__).resolve().parent
RESOURCE_REPO_GIT = REPO_ROOT / "resource-repo.git"
GIT_HTTP_BACKEND = shutil.which("git-http-backend") or "/usr/lib/git-core/git-http-backend"


class QGISRepoHandler(SimpleHTTPRequestHandler):
    """Static HTTP handler with correct MIME types for QGIS repositories."""

    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".xml": "application/xml",
        ".zip": "application/zip",
        ".ini": "text/plain",
        ".qml": "application/xml",
        ".model3": "application/xml",
    }


class GitHttpBackendHandler(BaseHTTPRequestHandler):
    """Routes every request on the resource-repo port to git-http-backend.

    Serves the bare repo at RESOURCE_REPO_GIT at the URL root, so clients
    use http://host:<port>/ as the remote. Smart HTTP (push/pull) and dumb
    HTTP (fallback static objects) are both handled by git-http-backend.
    """

    server_version = "QGISRepoGit/1.0"

    def do_GET(self):
        self._dispatch()

    def do_POST(self):
        self._dispatch()

    def do_HEAD(self):
        self._dispatch()

    def _dispatch(self):
        if not RESOURCE_REPO_GIT.is_dir():
            self.send_error(500, f"Bare repo missing: {RESOURCE_REPO_GIT}")
            return
        if not os.path.isfile(GIT_HTTP_BACKEND):
            self.send_error(500, f"git-http-backend not found at {GIT_HTTP_BACKEND}")
            return

        raw_path = self.path
        if "?" in raw_path:
            path_info, query_string = raw_path.split("?", 1)
        else:
            path_info, query_string = raw_path, ""

        # git-http-backend expects PATH_INFO to include the repo directory
        # name, relative to GIT_PROJECT_ROOT. We set GIT_PROJECT_ROOT to the
        # bare repo's parent and prefix with "/resource-repo.git".
        full_path_info = "/" + RESOURCE_REPO_GIT.name + path_info

        env = {
            "GIT_PROJECT_ROOT": str(RESOURCE_REPO_GIT.parent),
            "GIT_HTTP_EXPORT_ALL": "1",
            "PATH_INFO": full_path_info,
            "QUERY_STRING": query_string,
            "REQUEST_METHOD": self.command,
            "CONTENT_TYPE": self.headers.get("Content-Type", ""),
            "CONTENT_LENGTH": self.headers.get("Content-Length", "") or "0",
            "REMOTE_ADDR": self.client_address[0],
            "SERVER_PROTOCOL": self.protocol_version,
            "GATEWAY_INTERFACE": "CGI/1.1",
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "HOME": os.environ.get("HOME", "/tmp"),
            "LANG": os.environ.get("LANG", "C.UTF-8"),
        }
        # Propagate relevant HTTP headers as HTTP_* env vars for git-http-backend.
        for header in ("Content-Encoding", "Accept-Encoding", "User-Agent", "Accept"):
            value = self.headers.get(header)
            if value:
                env["HTTP_" + header.upper().replace("-", "_")] = value

        try:
            length = int(env["CONTENT_LENGTH"] or "0")
        except ValueError:
            length = 0
        body = self.rfile.read(length) if length > 0 else b""

        try:
            proc = subprocess.Popen(
                [GIT_HTTP_BACKEND],
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except OSError as exc:
            self.send_error(500, f"failed to spawn git-http-backend: {exc}")
            return

        stdout, stderr = proc.communicate(body)
        if proc.returncode != 0:
            log.error("git-http-backend exit=%d stderr=%s", proc.returncode, stderr.decode("utf-8", "replace"))
            self.send_error(500, "git-http-backend failed")
            return
        if stderr:
            log.debug("git-http-backend stderr: %s", stderr.decode("utf-8", "replace"))

        # Parse CGI output: headers separated from body by blank line.
        sep_idx = stdout.find(b"\r\n\r\n")
        sep_len = 4
        if sep_idx < 0:
            sep_idx = stdout.find(b"\n\n")
            sep_len = 2
        if sep_idx < 0:
            self.send_error(500, "git-http-backend: malformed CGI output")
            return

        header_block = stdout[:sep_idx].decode("iso-8859-1")
        body_block = stdout[sep_idx + sep_len:]

        status_code = 200
        status_msg = "OK"
        out_headers: list[tuple[str, str]] = []
        for line in header_block.splitlines():
            if ":" not in line:
                continue
            k, v = line.split(":", 1)
            k, v = k.strip(), v.strip()
            if k.lower() == "status":
                parts = v.split(" ", 1)
                try:
                    status_code = int(parts[0])
                except ValueError:
                    status_code = 500
                status_msg = parts[1] if len(parts) > 1 else ""
            else:
                out_headers.append((k, v))

        self.send_response(status_code, status_msg)
        has_content_length = any(k.lower() == "content-length" for k, _ in out_headers)
        for k, v in out_headers:
            self.send_header(k, v)
        if not has_content_length:
            self.send_header("Content-Length", str(len(body_block)))
        self.end_headers()
        self.wfile.write(body_block)

    def log_message(self, format, *args):  # noqa: A002 (match base signature)
        log.info("git %s - %s", self.address_string(), format % args)


def main():
    parser = argparse.ArgumentParser(description="Serve QGIS repositories - Constructel")
    parser.add_argument("--port", type=int, default=9080, help="Port plugin repo (default: 9080)")
    parser.add_argument("--resource-port", type=int, default=9082, help="Port resource repo git smart HTTP (default: 9082)")
    parser.add_argument("--bind", default=os.environ.get("QGIS_REPO_BIND", "0.0.0.0"), help="Bind address (default: $QGIS_REPO_BIND or 0.0.0.0)")
    args = parser.parse_args()

    os.chdir(REPO_ROOT)

    plugin_handler = functools.partial(QGISRepoHandler, directory=str(REPO_ROOT))
    plugin_server = HTTPServer((args.bind, args.port), plugin_handler)

    resource_server = HTTPServer((args.bind, args.resource_port), GitHttpBackendHandler)

    log.info("Depot QGIS Constructel")
    log.info("  Plugin repo:        http://%s:%d/plugin-repo/plugins.xml", args.bind, args.port)
    log.info("  Resource repo git:  http://%s:%d/ (smart HTTP, push enabled)", args.bind, args.resource_port)
    log.info("  git-http-backend:   %s", GIT_HTTP_BACKEND)
    log.info("Ctrl+C pour arreter.")

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
