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


AUTHENTICATED_CLIENTS = {Path("infrastructure/etoro_demo_client.py"),            # GET /pnl only
                         Path("infrastructure/etoro_demo_write_transport.py"),   # C7, locked
                         Path("application/sd050_msft_instrument_lookup.py"),    # 1 GET, owner-authorized
                         Path("application/sd058_eligibility_diagnostic.py"),    # 1 POST, owner-authorized diagnostic only
                         Path("application/sd077_data_authorization.py"),        # SD-077 host allowlist
                         Path("application/sd120_etoro_five_minute.py")}        # GET-only, signed and budgeted


def test_only_reviewed_modules_can_send_authenticated_etoro_requests():
    found = set()
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        literals = " ".join(_strings(tree))
        if _imports(tree) & NETWORK_MODULES and ("x-user-key" in literals
                                                 or "public-api.etoro.com" in literals):
            found.add(path.relative_to(SRC))
    assert found == AUTHENTICATED_CLIENTS


def test_write_transport_is_locked_and_never_constructed_in_src():
    from sidedeck.infrastructure import etoro_demo_write_transport as transport
    assert transport.NETWORK_TRANSPORT_ENABLED is False
    callers = []
    for path in SRC.rglob("*.py"):
        if path.relative_to(SRC) == Path("infrastructure/etoro_demo_write_transport.py"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == "EtoroDemoHttpTransport":
                callers.append(str(path.relative_to(SRC)))
            if isinstance(node, ast.Attribute) and node.attr in ("EtoroDemoHttpTransport",
                                                                  "NETWORK_TRANSPORT_ENABLED"):
                callers.append(str(path.relative_to(SRC)))
    assert callers == []


def test_existing_etoro_client_remains_single_get_portfolio_read():
    assert etoro_demo_client.ALLOWED_PATHS == frozenset({"/api/v1/trading/info/demo/pnl"})
    methods = {node.name for node in ast.walk(ast.parse(Path(etoro_demo_client.__file__)
                                                        .read_text(encoding="utf-8")))
               if isinstance(node, ast.FunctionDef)}
    assert not methods & {"post", "put", "delete", "submit", "send_order", "close_position"}


def test_production_transport_factory_has_exactly_one_reviewed_caller():
    from sidedeck.infrastructure import etoro_demo_write_transport as transport
    assert transport.network_transport_enabled() is False
    callers = set()
    for path in SRC.rglob("*.py"):
        if path.relative_to(SRC) == Path("infrastructure/etoro_demo_write_transport.py"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = {"production_transport_factory", "network_transport_enabled",
                 "ProductionTransportFactory"}
        for node in ast.walk(tree):
            hit = ((isinstance(node, ast.Attribute) and node.attr in names)
                   or (isinstance(node, ast.ImportFrom)
                       and any(a.name in names or a.name == "*" for a in node.names)
                       and (node.module or "").endswith("etoro_demo_write_transport"))
                   or (isinstance(node, ast.Constant) and node.value in names))
            if hit:
                callers.add(str(path.relative_to(SRC)).replace("\\", "/"))
    assert callers == {"application/sd054_pilot_operator.py"}
