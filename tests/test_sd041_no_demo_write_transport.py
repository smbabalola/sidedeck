"""SD-041 guard: no HTTP transport for eToro Demo (or Real) writes exists in SideDeck."""
import ast
from pathlib import Path

from sidedeck.infrastructure import etoro_demo_client

SRC = Path(__file__).resolve().parents[1] / "src" / "sidedeck"
NETWORK_MODULES = {"urllib", "http", "requests", "httpx", "aiohttp", "socket", "websockets"}
WRITE_MARKERS = ("/execution/", "market-close-orders", "market-open-orders", "agent-portfolios")


def _imports(tree: ast.AST) -> set[str]:
    names = {alias.name.split(".")[0] for node in ast.walk(tree)
             if isinstance(node, ast.Import) for alias in node.names}
    return names | {node.module.split(".")[0] for node in ast.walk(tree)
                    if isinstance(node, ast.ImportFrom) and node.module}


def _strings(tree: ast.AST) -> list[str]:
    return [node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)]


def test_no_module_combines_network_access_with_etoro_write_paths():
    offenders = []
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if not _imports(tree) & NETWORK_MODULES:
            continue
        literals = " ".join(_strings(tree))
        if "etoro" in literals.lower() and any(m in literals for m in WRITE_MARKERS):
            offenders.append(str(path.relative_to(SRC)))
    assert offenders == []


def test_existing_etoro_client_remains_single_get_portfolio_read():
    assert etoro_demo_client.ALLOWED_PATHS == frozenset({"/api/v1/trading/info/demo/pnl"})
    methods = {node.name for node in ast.walk(ast.parse(Path(etoro_demo_client.__file__)
                                                        .read_text(encoding="utf-8")))
               if isinstance(node, ast.FunctionDef)}
    assert not methods & {"post", "put", "delete", "submit", "send_order", "close_position"}
