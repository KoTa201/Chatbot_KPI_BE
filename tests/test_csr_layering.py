import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _python_files(folder: str) -> list[Path]:
    return sorted((PROJECT_ROOT / folder).glob("*.py"))


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_controllers_do_not_import_repositories():
    violations = [
        path.relative_to(PROJECT_ROOT).as_posix()
        for path in _python_files("controller")
        if "from repository." in _read(path) or "import repository." in _read(path)
    ]
    assert violations == []


def test_services_do_not_import_controllers_or_routers():
    violations = [
        path.relative_to(PROJECT_ROOT).as_posix()
        for path in _python_files("service")
        if any(token in _read(path) for token in ("from controller.", "import controller.", "from router.", "import router."))
    ]
    assert violations == []


def test_repositories_do_not_import_upper_layers():
    violations = [
        path.relative_to(PROJECT_ROOT).as_posix()
        for path in _python_files("repository")
        if any(token in _read(path) for token in ("from service.", "import service.", "from controller.", "import controller.", "from router.", "import router."))
    ]
    assert violations == []


def test_target_services_do_not_use_direct_db_operations():
    targets = [
        PROJECT_ROOT / "service" / "chatService.py",
        PROJECT_ROOT / "service" / "ingestionLogService.py",
        PROJECT_ROOT / "service" / "kpiGroupService.py",
        PROJECT_ROOT / "service" / "schedulerJobService.py",
        PROJECT_ROOT / "service" / "TrackeringestionService.py",
    ]
    forbidden_patterns = (
        r"\.[A-Za-z_]*execute\(",
        r"\.[A-Za-z_]*commit\(",
        r"\.[A-Za-z_]*flush\(",
        r"\.[A-Za-z_]*refresh\(",
        r"\bselect\(",
        r"\btext\(",
    )
    violations = []
    for path in targets:
        for line_number, line in enumerate(_read(path).splitlines(), start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            for pattern in forbidden_patterns:
                if re.search(pattern, line):
                    violations.append(
                        f"{path.relative_to(PROJECT_ROOT).as_posix()}:{line_number} matches {pattern}"
                    )
    assert violations == []
