# SPDX-License-Identifier: Apache-2.0
"""Authenticated, read-only access to raw SNL designs in a caller's process.

No pickle, Python evaluation, netlist transfer, or native ownership transfer.
The owner must use the same lock for edits, verification and destruction.
"""

from __future__ import annotations

import hmac
import inspect
import json
import os
from pathlib import Path
import secrets
import socket
import socketserver
import stat
import struct
import tempfile
import threading
import time
from uuid import uuid4

from .errors import ScopeError
from .design_reference import DesignReference, reference_from_design


PROTOCOL = "naja-scope-session-v1"
MAX_REQUEST = 1024 * 1024
MAX_RESPONSE = 8 * 1024 * 1024
READ_ONLY_TOOLS = frozenset({
    "status", "resolve", "find", "get_hierarchy", "get_drivers", "get_loads",
    "trace_cone", "get_source", "get_module_card", "get_stats", "get_intent",
})
# Serializes native inspection and process-global api.SESSION across bridges.
NATIVE_LOCK = threading.RLock()


def _receive(sock, maximum, deadline):
    def exact(size):
        result = bytearray()
        while len(result) < size:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Session request timed out")
            sock.settimeout(remaining)
            part = sock.recv(size - len(result))
            if not part:
                raise ScopeError("Session connection closed before a complete response")
            result.extend(part)
        return result

    size = struct.unpack("!I", exact(4))[0]
    if not 0 < size <= maximum:
        raise ScopeError("Session message exceeds its size limit")
    value = json.loads(exact(size))
    if not isinstance(value, dict):
        raise ScopeError("Session message must be a JSON object")
    return value


def _send(sock, value, maximum):
    data = json.dumps(value, allow_nan=False).encode("utf-8")
    if len(data) > maximum:
        raise ScopeError("Session response exceeds its size limit; use smaller query limits")
    sock.sendall(struct.pack("!I", len(data)) + data)


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = False
    daemon_threads = True

    def __init__(self, bridge):
        self.bridge = bridge
        self.slots = threading.BoundedSemaphore(8)
        super().__init__(("127.0.0.1", 0), _Handler)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


class _Handler(socketserver.BaseRequestHandler):
    def handle(self):
        self.request.settimeout(5)
        try:
            request = _receive(self.request, MAX_REQUEST, time.monotonic() + 5)
            reply = self.server.bridge._dispatch(request)
            _send(self.request, reply, MAX_RESPONSE)
        except (OSError, TypeError, ValueError, ScopeError):
            try:
                _send(self.request, {"error": "Invalid or incomplete session request"}, MAX_RESPONSE)
            except (OSError, ScopeError):
                pass


class SessionBridge:
    """Host caller-owned raw SNLDesign handles for read-only MCP inspection.

    Pass the owner's existing reentrant lock when another editor/verifier shares
    the universe. Otherwise hold bridge.lock around every native mutation.
    Closing stops this bridge only; it never resets or destroys the universe.
    """

    def __init__(self, *, lock=None, source_files=()):
        from najaeda import naja
        from .session import Session

        self.lock = lock if lock is not None else NATIVE_LOCK
        self.session_id = uuid4().hex
        self.pid = os.getpid()
        self._token = secrets.token_hex(32)
        self._universe = naja.NLUniverse.get()
        if self._universe is None:
            raise ScopeError("A bridge requires an existing Naja universe")
        if isinstance(source_files, (str, bytes)):
            raise TypeError("source_files must be a sequence of paths")
        self._metadata = Session()
        self._metadata._record_sources([os.fspath(path) for path in source_files])
        self._server = self._thread = None
        self._closed = False
        self._directory = None
        self.connection_file = None

    def _require_open(self):
        from najaeda import naja

        if self._closed or naja.NLUniverse.get() is not self._universe:
            raise ScopeError("The bound design session is closed or no longer valid")

    def _resolve(self, value):
        reference = DesignReference.model_validate(value)
        if reference.session_id != self.session_id:
            raise ScopeError("Design reference belongs to a different session")
        design = self._universe.getSNLDesign(reference.native_key())
        if design is None:
            raise ScopeError("Native design ID does not exist in this session")
        if reference_from_design(self.session_id, design) != reference:
            raise ScopeError("Native lookup returned a different design identity")
        return reference, design

    def design_reference(self, design):
        """Return native coordinates without registering or retaining a design."""
        with self.lock, NATIVE_LOCK:
            self._require_open()
            reference = reference_from_design(self.session_id, design)
            self._resolve(reference)
            return reference.model_dump()

    def start(self):
        self._require_open()
        if self._server is not None:
            return self
        server = _Server(self)
        directory = Path(tempfile.mkdtemp(prefix="naja-scope-session-"))
        connection = directory / "connection.json"
        try:
            with connection.open("x", encoding="utf-8") as stream:
                if os.name == "posix":
                    os.fchmod(stream.fileno(), 0o600)
                json.dump({"protocol": PROTOCOL, "host": "127.0.0.1",
                           "port": server.server_address[1], "token": self._token,
                           "session_id": self.session_id, "pid": self.pid}, stream)
            self._server, self._directory, self.connection_file = server, directory, connection
            self._thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.05),
                                            daemon=True, name="naja-scope-session")
            self._thread.start()
        except BaseException:
            server.server_close()
            connection.unlink(missing_ok=True)
            directory.rmdir()
            raise
        return self

    def _inspect(self):
        designs = []
        truncated = False
        for database in self._universe.getUserDBs():
            for library in database.getLibraries():
                if library.isPrimitives():
                    continue
                for design in library.getSNLDesigns():
                    if design.isPrimitive():
                        continue
                    if len(designs) == 200:
                        truncated = True
                        break
                    designs.append({"name": design.getName(),
                                    "reference": reference_from_design(
                                        self.session_id, design).model_dump()})
                if truncated:
                    break
            if truncated:
                break
        return {"session_id": self.session_id, "pid": self.pid,
                "design_addressing": "native-id-v1", "designs": designs,
                "designs_truncated": truncated}

    def _dispatch(self, request):
        token = request.get("token")
        if (not isinstance(token, str) or not token.isascii()
                or not hmac.compare_digest(token, self._token)):
            return {"error": "Session authentication failed"}
        if request.get("protocol") != PROTOCOL or request.get("session_id") != self.session_id:
            return {"error": "Session identity or protocol mismatch"}
        if not self.lock.acquire(blocking=False):
            return {"error": "Design session is busy; retry when the owner is idle"}
        try:
            if not NATIVE_LOCK.acquire(blocking=False):
                return {"error": "Native inspection is busy; retry when idle"}
            try:
                from . import api, snl

                self._require_open()
                operation = request.get("operation")
                if operation == "inspect":
                    return self._inspect()
                if operation == "select":
                    reference, _ = self._resolve(request.get("design"))
                    return {"session_id": self.session_id, "pid": self.pid,
                            "design": reference.model_dump()}
                if operation != "query" or request.get("tool") not in READ_ONLY_TOOLS:
                    raise ScopeError("Attached sessions allow only typed read-only inspection tools")
                reference, design = self._resolve(request.get("design"))
                arguments = request.get("arguments", {})
                if not isinstance(arguments, dict):
                    raise ScopeError("Query arguments must be a JSON object")
                function = getattr(api, request["tool"])
                inspect.signature(function).bind(**arguments)
                previous_top = self._universe.getTopDesign()
                target_db = design.getDB()
                previous_db_top = target_db.getTopDesign()
                # Native LogicCone changes top selection internally. The raw
                # binding cannot restore an unset top, so fail before mutation.
                if request["tool"] == "trace_cone" and (previous_top is None or previous_db_top is None):
                    raise ScopeError("trace_cone requires existing global and target-database tops; "
                                     "select them in the owner before tracing")
                previous_session = api.SESSION
                try:
                    api.SESSION = self._metadata
                    with snl.inspection_design(design):
                        result = function(**arguments)
                finally:
                    api.SESSION = previous_session
                    if previous_db_top is not None and target_db.getTopDesign() != previous_db_top:
                        self._universe.setTopDesign(previous_db_top)
                    if previous_top is not None and self._universe.getTopDesign() != previous_top:
                        self._universe.setTopDesign(previous_top)
                return {"session_id": self.session_id, "pid": self.pid,
                        "design": reference.model_dump(), "result": result}
            except ScopeError as error:
                return error.to_dict()
            except (RuntimeError, ReferenceError, TypeError, ValueError) as error:
                return {"error": f"Bound inspection failed: {error}"}
            finally:
                NATIVE_LOCK.release()
        finally:
            self.lock.release()

    def close(self):
        if not self.lock.acquire(blocking=False):
            raise ScopeError("Design session is busy; wait before closing its bridge")
        try:
            if not NATIVE_LOCK.acquire(blocking=False):
                raise ScopeError("Native inspection is busy; wait before closing its bridge")
            try:
                if self._closed:
                    return
                self._closed = True
            finally:
                NATIVE_LOCK.release()
        finally:
            self.lock.release()
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._thread.join(timeout=5)
        if self.connection_file is not None:
            self.connection_file.unlink(missing_ok=True)
            # Delete only our private connection directory, never caller data.
            try:
                self._directory.rmdir()
            except OSError:
                pass

    def __enter__(self):
        return self.start()

    def __exit__(self, *args):
        self.close()


class _Client:
    def __init__(self, connection_file, timeout):
        path = Path(connection_file).expanduser().resolve(strict=True)
        if path.stat().st_size > 8192:
            raise ScopeError("Invalid session connection file")
        if os.name == "posix":
            info = path.stat()
            if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
                raise ScopeError("Session connection file must be private and owned by this user")
        self.connection = json.loads(path.read_text())
        value = self.connection
        if (not isinstance(value, dict) or value.get("protocol") != PROTOCOL
                or value.get("host") != "127.0.0.1"
                or type(value.get("port")) is not int or not 0 < value["port"] < 65536
                or not isinstance(value.get("token"), str) or len(value["token"]) != 64
                or not isinstance(value.get("session_id"), str)
                or type(value.get("pid")) is not int or value["pid"] <= 0):
            raise ScopeError("Invalid local session connection settings")
        self.timeout = timeout

    def call(self, operation, **arguments):
        value = self.connection
        deadline = time.monotonic() + self.timeout
        try:
            with socket.create_connection((value["host"], value["port"]), timeout=self.timeout) as sock:
                _send(sock, {"protocol": PROTOCOL, "session_id": value["session_id"],
                             "token": value["token"], "operation": operation, **arguments}, MAX_REQUEST)
                reply = _receive(sock, MAX_RESPONSE, deadline)
        except TimeoutError as error:
            raise ScopeError("Attached query timed out; it may still be running in the owner. "
                             "Do not edit until the shared lock is available.") from error
        except (OSError, ValueError) as error:
            raise ScopeError("Attached session is unavailable; no local fallback was used") from error
        if "error" in reply:
            raise ScopeError(reply["error"], reply.get("suggestions"))
        if reply.get("session_id") != value["session_id"] or reply.get("pid") != value["pid"]:
            raise ScopeError("Attached session response identity mismatch")
        return reply


class SessionBinding:
    """One active borrowed design for one MCP server, separate from local state."""

    def __init__(self):
        self._operation = threading.Lock()
        self._client = None
        self._design = None

    def _acquire(self):
        if not self._operation.acquire(blocking=False):
            raise ScopeError("Another session operation is running; retry when idle")

    def attach(self, connection_file, design=None, timeout_seconds=30):
        self._acquire()
        try:
            if type(timeout_seconds) not in (int, float) or not 0 < timeout_seconds <= 300:
                raise ScopeError("Session timeout must be positive and at most 300 seconds")
            try:
                client = _Client(connection_file, timeout_seconds)
            except (OSError, ValueError) as error:
                raise ScopeError("Cannot read a valid private session connection file") from error
            info = client.call("inspect")
            if info.get("design_addressing") != "native-id-v1":
                raise ScopeError("The owner does not support native design references")
            selected = self._select(client, design) if design is not None else None
            self._client = client
            self._design = dict(selected) if selected is not None else None
            return {**info, "attached": True, "selected_design": selected}
        finally:
            self._operation.release()

    @staticmethod
    def _reference(client, design):
        try:
            reference = DesignReference.model_validate(design)
        except ValueError as error:
            raise ScopeError("Provide a native design reference with session, DB, library and design IDs") from error
        if reference.session_id != client.connection["session_id"]:
            raise ScopeError("Design reference belongs to a different session")
        return reference.model_dump()

    @classmethod
    def _select(cls, client, design):
        reference = cls._reference(client, design)
        reply = client.call("select", design=reference)
        if reply.get("design") != reference:
            raise ScopeError("Attached response identifies a different native design")
        return reference

    def select(self, design):
        self._acquire()
        try:
            if self._client is None:
                raise ScopeError("No attached session")
            selected = self._select(self._client, design)
            self._design = dict(selected)
            return {"session_id": self._client.connection["session_id"],
                    "pid": self._client.connection["pid"],
                    "attached": True, "selected_design": selected}
        finally:
            self._operation.release()

    def inspect(self):
        self._acquire()
        try:
            if self._client is None:
                return {"attached": False}
            return {**self._client.call("inspect"), "attached": True,
                    "selected_design": dict(self._design) if self._design is not None else None}
        finally:
            self._operation.release()

    def detach(self):
        self._acquire()
        try:
            self._client = self._design = None
            return {"attached": False, "caller_designs_preserved": True}
        finally:
            self._operation.release()

    def invoke(self, tool, arguments, local, design=None):
        self._acquire()
        try:
            if self._client is None:
                if design is not None:
                    raise ScopeError("A native design reference requires an attached session")
                with NATIVE_LOCK:
                    return local()
            if tool not in READ_ONLY_TOOLS:
                raise ScopeError("Attached session is read-only; detach before local loading, "
                                 "reset, export or Python execution")
            selected = design if design is not None else self._design
            if selected is None:
                raise ScopeError("Supply a native design reference or call set_session_design first")
            reference = self._reference(self._client, selected)
            reply = self._client.call("query", tool=tool, design=reference, arguments=arguments)
            if reply.get("design") != reference or not isinstance(reply.get("result"), dict):
                raise ScopeError("Attached query response does not match the requested native design")
            result = dict(reply["result"])
            result["binding"] = {"session_id": reply["session_id"], "pid": reply["pid"],
                                 "design": reference}
            return result
        finally:
            self._operation.release()


BINDING = SessionBinding()
