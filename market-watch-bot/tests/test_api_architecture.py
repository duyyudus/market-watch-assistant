from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from api_server.app.db import session as session_module


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0
        self.closed = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1

    async def close(self) -> None:
        self.closed += 1


class FakeSessionContext:
    def __init__(self, session: FakeSession) -> None:
        self.session = session

    async def __aenter__(self) -> FakeSession:
        return self.session

    async def __aexit__(self, *_exc_info: object) -> None:
        await self.session.close()


@pytest.mark.asyncio
async def test_api_session_dependency_commits_once_after_success(monkeypatch) -> None:
    fake_session = FakeSession()

    def fake_factory() -> FakeSessionContext:
        return FakeSessionContext(fake_session)

    monkeypatch.setattr(session_module, "get_session_factory", lambda _request: fake_factory)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))

    dependency = session_module.get_session(request)
    yielded = await anext(dependency)

    assert yielded is fake_session
    with pytest.raises(StopAsyncIteration):
        await dependency.asend(None)
    assert fake_session.commits == 1
    assert fake_session.rollbacks == 0
    assert fake_session.closed == 1


@pytest.mark.asyncio
async def test_api_session_dependency_rolls_back_unhandled_exception(monkeypatch) -> None:
    fake_session = FakeSession()

    def fake_factory() -> FakeSessionContext:
        return FakeSessionContext(fake_session)

    monkeypatch.setattr(session_module, "get_session_factory", lambda _request: fake_factory)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))

    dependency = session_module.get_session(request)
    yielded = await anext(dependency)

    assert yielded is fake_session
    with pytest.raises(RuntimeError, match="boom"):
        await dependency.athrow(RuntimeError("boom"))
    assert fake_session.commits == 0
    assert fake_session.rollbacks == 1
    assert fake_session.closed == 1


def test_api_server_does_not_import_bot_worker_modules() -> None:
    api_root = Path(__file__).parents[1] / "api_server"
    offenders: list[str] = []
    for path in sorted(api_root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            if any(name == "bot_worker" or name.startswith("bot_worker.") for name in names):
                offenders.append(str(path.relative_to(api_root.parent)))

    assert offenders == []
