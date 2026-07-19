"""Bridge from this app's synchronous tool loop to MCP servers.

The engine's tool loop is synchronous — it calls `fn.invoke(dict)` — but MCP
speaks async over a subprocess (stdio). This module runs each MCP server on its
own asyncio loop in a daemon thread and keeps the session (and therefore the
browser's page state) alive across many tool calls. The tool wrappers block on a
thread-safe submit, so from the engine's side an MCP tool looks exactly like any
other LangChain tool.

Design notes / gotchas (these are load-bearing):
- LAZY START: importing this module, or resolving tools, must NEVER launch a
  browser. A server starts only on the first actual tool call (`_MCPServer.call`
  → `start`). `resolve_tools(["browser"])` just hands back lightweight wrappers.
- CURATED, not auto-generated: we expose a small, hand-written `browser` bundle
  rather than the Playwright server's full ~25-tool surface. Small local models
  mis-select from large tool sets — two clear tools beat twenty vague ones. This
  is the same lesson as the router: give the model less to get more.
- Node 18+ and `npx` are required (the server is `@playwright/mcp`, a Node
  package run via npx). If they're missing the tools return a friendly string
  instead of raising, so a run never crashes on a missing optional dependency.
- One browser at a time: this is a single-user local app on a 4GB-VRAM machine,
  so a single shared headless Chromium is the right footprint.
"""
import atexit
import concurrent.futures
import asyncio
import os
import shutil
import threading

_SERVERS = {}          # key -> _MCPServer   (process-wide singletons)
_LOCK = threading.Lock()


class MCPError(RuntimeError):
    pass


def node_available() -> bool:
    """True if `npx` is on PATH (needed to run the Node-based MCP server)."""
    return shutil.which("npx") is not None


def _text_of(resp) -> str:
    """Flatten an MCP CallToolResult into plain text for the model."""
    parts = []
    for block in getattr(resp, "content", []) or []:
        text = getattr(block, "text", None)
        if text is not None:
            parts.append(text)
        else:
            parts.append(f"[{getattr(block, 'type', 'non-text')} content omitted]")
    out = "\n".join(parts).strip()
    if getattr(resp, "isError", False):
        return f"[MCP tool error] {out or 'unknown error'}"
    return out or "[no text output]"


def _clip(text: str, limit: int = 6000) -> str:
    """Cap tool output — a full rendered page can blow a 7B's context."""
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n\n… [truncated, {len(text) - limit} more chars]"


class _MCPServer:
    """One MCP server: its own event loop + thread, session kept alive."""

    def __init__(self, key, command, args, env=None, start_timeout=180):
        self.key = key
        self.command = command
        self.args = args
        self.env = env
        self.start_timeout = start_timeout
        self._loop = None
        self._thread = None
        self._session = None
        self._stop = None            # asyncio.Event, created inside the loop
        self._ready = threading.Event()
        self._start_error = None
        self.tools = []              # tool specs from list_tools (names, schemas)

    # ----- lifecycle -----
    def start(self):
        with self._start_lock():
            if self._thread and self._thread.is_alive():
                if self._start_error:
                    raise MCPError(self._start_error)
                return
            self._ready.clear()
            self._start_error = None
            self._thread = threading.Thread(
                target=self._run, name=f"mcp-{self.key}", daemon=True)
            self._thread.start()
        if not self._ready.wait(self.start_timeout):
            raise MCPError(
                f"MCP server '{self.key}' did not become ready within "
                f"{self.start_timeout}s (first run downloads the browser).")
        if self._start_error:
            raise MCPError(self._start_error)

    def _start_lock(self):
        # A tiny per-server lock so two concurrent first-calls don't double-start.
        if not hasattr(self, "_slock"):
            self._slock = threading.Lock()
        return self._slock

    def _run(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._serve())
        except Exception as e:  # noqa: BLE001 - surfaced via _start_error
            self._start_error = self._start_error or f"{type(e).__name__}: {e}"
            self._ready.set()
        finally:
            try:
                self._loop.close()
            except Exception:  # noqa: BLE001
                pass
            self._session = None

    async def _serve(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        self._stop = asyncio.Event()
        params = StdioServerParameters(
            command=self.command, args=self.args, env=self.env)
        try:
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    listed = await session.list_tools()
                    self.tools = list(listed.tools)
                    self._session = session
                    self._ready.set()
                    await self._stop.wait()   # hold the session open
        except Exception as e:  # noqa: BLE001
            self._start_error = f"{type(e).__name__}: {e}"
            self._ready.set()

    def stop(self):
        loop, ev = self._loop, self._stop
        if loop and ev and not loop.is_closed():
            loop.call_soon_threadsafe(ev.set)

    # ----- calls -----
    def call(self, name, arguments=None, timeout=90) -> str:
        self.start()
        fut = asyncio.run_coroutine_threadsafe(
            self._call(name, arguments or {}), self._loop)
        try:
            return fut.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            fut.cancel()
            raise MCPError(f"MCP tool '{name}' timed out after {timeout}s")

    async def _call(self, name, arguments):
        resp = await self._session.call_tool(name, arguments)
        return _text_of(resp)

    def tool_names(self):
        return [t.name for t in self.tools]


def _playwright_server() -> _MCPServer:
    key = "playwright"
    with _LOCK:
        srv = _SERVERS.get(key)
        if srv is None:
            # --headless: no visible window (and no GPU contention with Fooocus).
            # --isolated: a throwaway profile, so browsing leaves nothing behind.
            # Version pin: 0.0.29 bundles Playwright 1.53, the last line that
            # still supports this machine's Node 18. Newer @playwright/mcp needs
            # Node 20+. Bump the pin if/when Node is upgraded.
            spec = os.environ.get("PLAYWRIGHT_MCP_SPEC", "@playwright/mcp@0.0.29")
            # --browser chromium: use Playwright's bundled Chromium build (which
            # we install), NOT the "chrome" channel it defaults to (that expects
            # a system Google Chrome at /opt/google/chrome and isn't present).
            args = ["-y", spec, "--headless", "--isolated", "--browser", "chromium"]
            srv = _MCPServer(key, "npx", args, env=os.environ.copy())
            _SERVERS[key] = srv
        return srv


# ---------------- curated browser tool bundle ----------------


def _norm_url(url: str) -> str:
    url = (url or "").strip()
    if url and not (url.startswith("http://") or url.startswith("https://")):
        url = "https://" + url
    return url


def _browser_open(url: str) -> str:
    """Open a URL in a REAL headless Chromium and return the rendered page content.

    Unlike read_webpage (a plain HTTP fetch), this executes the page's
    JavaScript first, so it can read single-page apps and content that only
    appears after scripts run. Pass a full URL like https://example.com. Needs
    internet. Returns the page's accessibility snapshot: a structured text view
    with headings, links and controls (each tagged with a [ref] you can act on
    later). The page stays open for a follow-up browser_snapshot.
    """
    if not node_available():
        return ("browser tool unavailable: Node.js/npx was not found. Install "
                "Node 18+ to use the real-browser tools; use read_webpage for a "
                "plain HTTP fetch instead.")
    url = _norm_url(url)
    if not url:
        return "browser_open needs a url (e.g. https://example.com)."
    srv = _playwright_server()
    try:
        # browser_navigate waits for load; its own result already includes a
        # fresh snapshot, but we take one explicitly so the format is stable
        # regardless of server version.
        srv.call("browser_navigate", {"url": url}, timeout=120)
        snap = srv.call("browser_snapshot", {}, timeout=60)
        return _clip(f"Rendered content of {url} (real browser):\n\n{snap}")
    except MCPError as e:
        return f"browser_open could not read {url}: {e}"


def _browser_snapshot() -> str:
    """Return an accessibility snapshot (structured text) of the page currently open.

    Call browser_open first. Use this to re-read the page, for example after it
    has changed. Returns the browser's structured view of the current page.
    """
    if not node_available():
        return "browser tool unavailable: Node.js/npx not found."
    srv = _playwright_server()
    try:
        return _clip(srv.call("browser_snapshot", {}, timeout=60))
    except MCPError as e:
        return f"browser_snapshot failed (did you browser_open a page first?): {e}"


def browser_tools():
    """The curated `browser` bundle as LangChain tools (lazy — no browser yet)."""
    from langchain_core.tools import StructuredTool
    return [
        StructuredTool.from_function(
            func=_browser_open, name="browser_open",
            description=_browser_open.__doc__),
        StructuredTool.from_function(
            func=_browser_snapshot, name="browser_snapshot",
            description=_browser_snapshot.__doc__),
    ]


def status() -> dict:
    """Cheap availability report for the UI — never starts a server."""
    srv = _SERVERS.get("playwright")
    return {
        "node": node_available(),
        "sdk": True,  # importing this module means the mcp SDK is present
        "playwright_running": bool(srv and srv._thread and srv._thread.is_alive()
                                   and not srv._start_error),
        "playwright_tools": srv.tool_names() if srv else [],
        "playwright_error": srv._start_error if srv else None,
    }


def shutdown_all():
    for srv in list(_SERVERS.values()):
        try:
            srv.stop()
        except Exception:  # noqa: BLE001
            pass


atexit.register(shutdown_all)
