"""Static code-impact analysis over a repository.

The Python analyzer is real: it parses the sample repository with :mod:`ast`,
builds a module import graph and a function call graph, and derives
    direct impact   = files listed on the change,
    indirect impact = modules that import them (transitively, depth-limited).

``CodeAnalyzer`` is the extension point: JavaAnalyzer / CSharpAnalyzer are
declared with the same contract so another language can be added without
touching the agent.
"""
from __future__ import annotations

import ast
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from app.config import BACKEND_DIR
from app.logging import get_logger

logger = get_logger("ecr.code")

SAMPLE_REPO_PATH = BACKEND_DIR / "app" / "seed" / "sample_repo"

# Repository path prefix -> component id
PATH_COMPONENT_MAP: dict[str, str] = {
    "portal/": "CMP-001",
    "gateway/": "CMP-002",
    "infra/": "CMP-002",
    "payment/service.py": "CMP-003",
    "payment/validator.py": "CMP-004",
    "payment/currency.py": "CMP-005",
    "payment/": "CMP-003",
    "currency/": "CMP-005",
    "order/": "CMP-006",
    "refund/": "CMP-007",
    "schema/": "CMP-008",
    "user/": "CMP-009",
    "auth/": "CMP-010",
    "notification/": "CMP-011",
    "invoice/": "CMP-012",
    "reporting/": "CMP-013",
    "fraud/": "CMP-014",
    "ledger/": "CMP-015",
    "inventory/": "CMP-016",
    "shipping/": "CMP-017",
    "catalog/": "CMP-018",
    "promotion/": "CMP-019",
    "loyalty/": "CMP-020",
    "subscription/": "CMP-021",
    "wallet/": "CMP-022",
    "chargeback/": "CMP-023",
    "payout/": "CMP-024",
    "tax_engine/": "CMP-025",
    "kyc/": "CMP-026",
    "consent/": "CMP-027",
    "audit/": "CMP-028",
    "search/": "CMP-029",
    "mobile_bff/": "CMP-030",
    "broker/": "CMP-031",
    "support/": "CMP-032",
    "warehouse/": "CMP-033",
    "giftcard/": "CMP-034",
    "returns/": "CMP-035",
}

# Fallback for files that do not exist in the sample repository
KEYWORD_COMPONENT_MAP: dict[str, str] = {
    "portal": "CMP-001",
    "ui": "CMP-001",
    "gateway": "CMP-002",
    "validator": "CMP-004",
    "validation": "CMP-004",
    "currency": "CMP-005",
    "fx": "CMP-005",
    "payment": "CMP-003",
    "order": "CMP-006",
    "checkout": "CMP-006",
    "refund": "CMP-007",
    "schema": "CMP-008",
    "migration": "CMP-008",
    "database": "CMP-008",
    "user": "CMP-009",
    "profile": "CMP-009",
    "auth": "CMP-010",
    "notification": "CMP-011",
    "email": "CMP-011",
    "template": "CMP-011",
    "invoice": "CMP-012",
    "report": "CMP-013",
    "fraud": "CMP-014",
    "ledger": "CMP-015",
}

API_ROUTE_HINTS = ("ROUTES", "router", "endpoint")


@dataclass(slots=True)
class ModuleInfo:
    module: str
    path: str
    functions: list[str] = field(default_factory=list)
    classes: list[str] = field(default_factory=list)
    imports: dict[str, list[str]] = field(default_factory=dict)  # module -> symbols
    calls: dict[str, list[str]] = field(default_factory=dict)  # function -> called names
    routes: list[str] = field(default_factory=list)
    constants: list[str] = field(default_factory=list)


class CodeAnalyzer(ABC):
    """Contract for a per-language static analyzer."""

    language: str = "unknown"
    extensions: tuple[str, ...] = ()

    @abstractmethod
    def parse(self, root: Path) -> dict[str, ModuleInfo]: ...


class PythonASTAnalyzer(CodeAnalyzer):
    language = "python"
    extensions = (".py",)

    def parse(self, root: Path) -> dict[str, ModuleInfo]:
        modules: dict[str, ModuleInfo] = {}
        for path in sorted(root.rglob("*.py")):
            rel = path.relative_to(root).as_posix()
            module_name = rel[:-3].replace("/", ".")
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
            except SyntaxError as exc:  # pragma: no cover - sample repo is valid
                logger.warning("code.parse_failed", file=rel, error=str(exc))
                continue
            info = ModuleInfo(module=module_name, path=rel)
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    info.functions.append(node.name)
                    info.calls[node.name] = sorted(
                        {
                            _call_name(child)
                            for child in ast.walk(node)
                            if isinstance(child, ast.Call) and _call_name(child)
                        }
                    )
                elif isinstance(node, ast.ClassDef):
                    info.classes.append(node.name)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    info.imports.setdefault(node.module, []).extend(
                        alias.name for alias in node.names
                    )
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        info.imports.setdefault(alias.name, [])
                elif isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name) and target.id.isupper():
                            info.constants.append(target.id)
                            if any(hint in target.id for hint in ("ROUTE", "ENDPOINT")) and isinstance(
                                node.value, ast.Dict
                            ):
                                info.routes.extend(
                                    key.value
                                    for key in node.value.keys
                                    if isinstance(key, ast.Constant) and isinstance(key.value, str)
                                )
            modules[module_name] = info
        return modules


class JavaAnalyzer(CodeAnalyzer):  # pragma: no cover - extension point
    """Placeholder for a JavaParser/tree-sitter based analyzer."""

    language = "java"
    extensions = (".java",)

    def parse(self, root: Path) -> dict[str, ModuleInfo]:
        return {}


class CSharpAnalyzer(CodeAnalyzer):  # pragma: no cover - extension point
    """Placeholder for a Roslyn based analyzer."""

    language = "csharp"
    extensions = (".cs",)

    def parse(self, root: Path) -> dict[str, ModuleInfo]:
        return {}


class CodeAnalysisService:
    """Repository-level analysis with an import-graph based impact walk."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or SAMPLE_REPO_PATH
        self.analyzers: list[CodeAnalyzer] = [PythonASTAnalyzer(), JavaAnalyzer(), CSharpAnalyzer()]
        self.modules: dict[str, ModuleInfo] = {}
        self.importers: dict[str, set[str]] = {}
        self._load()

    # -- loading ----------------------------------------------------------
    def _load(self) -> None:
        if not self.root.exists():
            logger.warning("code.repo_missing", path=str(self.root))
            return
        for analyzer in self.analyzers:
            self.modules.update(analyzer.parse(self.root))
        for module, info in self.modules.items():
            for imported in info.imports:
                if imported in self.modules:
                    self.importers.setdefault(imported, set()).add(module)
        logger.info("code.repo_loaded", modules=len(self.modules), edges=len(self.importers))

    # -- helpers ----------------------------------------------------------
    @staticmethod
    def component_for_path(file_path: str) -> str | None:
        normalised = file_path.replace("\\", "/").lstrip("./").lower()
        for prefix, component in PATH_COMPONENT_MAP.items():
            if normalised.startswith(prefix) or f"/{prefix}" in normalised:
                return component
        for keyword, component in KEYWORD_COMPONENT_MAP.items():
            # Only at the start of a path segment or name part: "order/api.py" and
            # "order_total.py" match, but "event_recorder.py" is not the order service.
            if re.search(rf"(?:^|[/_.\-]){re.escape(keyword)}", normalised):
                return component
        return None

    def module_for_path(self, file_path: str) -> str | None:
        normalised = file_path.replace("\\", "/").lstrip("./")
        if normalised.endswith(".py"):
            candidate = normalised[:-3].replace("/", ".")
            if candidate in self.modules:
                return candidate
            for module in self.modules:
                if module.endswith(candidate.split(".")[-1]):
                    if self.modules[module].path == normalised:
                        return module
        return None

    def dependents(self, modules: Iterable[str], max_depth: int = 2) -> dict[str, int]:
        """Modules that (transitively) import the given ones."""
        distances: dict[str, int] = {}
        frontier = [m for m in modules if m in self.modules]
        seen = set(frontier)
        depth = 0
        while frontier and depth < max_depth:
            depth += 1
            nxt: list[str] = []
            for module in frontier:
                for importer in self.importers.get(module, set()):
                    if importer in seen:
                        continue
                    seen.add(importer)
                    distances[importer] = depth
                    nxt.append(importer)
            frontier = nxt
        return distances

    # -- public API -------------------------------------------------------
    def analyze_change(
        self, changed_files: Iterable[str], *, keywords: Iterable[str] = ()
    ) -> dict[str, Any]:
        """Return the raw code-impact facts for the Code Impact Agent."""
        files = [f for f in changed_files if f]
        resolved_modules: list[str] = []
        unresolved: list[str] = []
        for file_path in files:
            module = self.module_for_path(file_path)
            if module:
                resolved_modules.append(module)
            else:
                unresolved.append(file_path)

        # Keyword-driven discovery only when the ECR lists no files at all. Declared
        # files that are not in this repository belong to another codebase (e.g. the
        # rail onboard software); searching this repository for their keywords would
        # report unrelated modules as directly changed.
        if not resolved_modules and not files:
            for module, info in self.modules.items():
                haystack = f"{module} {' '.join(info.functions)} {' '.join(info.constants)}".lower()
                if any(kw.lower() in haystack for kw in keywords):
                    resolved_modules.append(module)

        direct_components = {
            comp
            for comp in (self.component_for_path(f) for f in files)
            if comp
        }
        direct_components |= {
            comp
            for comp in (self.component_for_path(self.modules[m].path) for m in resolved_modules)
            if comp
        }

        dependents = self.dependents(resolved_modules, max_depth=2)
        indirect_components = {
            comp
            for comp in (self.component_for_path(self.modules[m].path) for m in dependents)
            if comp
        } - direct_components

        symbols: list[dict[str, Any]] = []
        apis: list[str] = []
        db_entities: list[str] = []
        for module in resolved_modules:
            info = self.modules[module]
            component = self.component_for_path(info.path) or ""
            for function in info.functions:
                symbols.append(
                    {
                        "file": info.path,
                        "symbol": function,
                        "kind": "function",
                        "component": component,
                        "calls": info.calls.get(function, []),
                    }
                )
            apis.extend(info.routes)
            if "schema" in module or "TRANSACTION_COLUMNS" in info.constants:
                db_entities.extend(info.constants)

        # routes exposed by dependent modules are part of the API surface too
        for module in dependents:
            apis.extend(self.modules[module].routes)

        analysed = len(resolved_modules)
        total = max(len(self.modules), 1)
        return {
            "resolved_modules": resolved_modules,
            "unresolved_files": unresolved,
            "direct_files": [self.modules[m].path for m in resolved_modules] or files,
            "dependent_modules": dependents,
            "dependent_files": [self.modules[m].path for m in dependents],
            "direct_components": sorted(direct_components),
            "indirect_components": sorted(indirect_components),
            "symbols": symbols,
            "apis": sorted(set(apis)),
            "database_entities": sorted(set(db_entities)),
            "change_surface": round(min(1.0, (analysed + 0.5 * len(dependents)) / total), 3),
            "repository": str(self.root),
            "analyzers": [a.language for a in self.analyzers if a.language == "python"],
            "modules_indexed": len(self.modules),
        }

    def stats(self) -> dict[str, Any]:
        return {
            "repository": str(self.root),
            "modules": len(self.modules),
            "import_edges": sum(len(v) for v in self.importers.values()),
            "languages": [a.language for a in self.analyzers],
        }


def _call_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


@lru_cache
def get_code_analysis_service() -> CodeAnalysisService:
    return CodeAnalysisService()
