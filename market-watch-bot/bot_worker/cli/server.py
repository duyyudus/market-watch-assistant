from __future__ import annotations

import typer

from bot_worker.cli.apps import server_app


@server_app.command("start")
def start_server(
    host: str = typer.Option("0.0.0.0", help="Bind socket to this host"),
    port: int = typer.Option(8000, help="Bind socket to this port"),
    reload: bool = typer.Option(False, help="Enable auto-reload on code change"),
):
    """Start the FastAPI application server."""
    import uvicorn

    typer.echo(f"Starting API server on {host}:{port}...")
    uvicorn.run("api_server.app.main:app", host=host, port=port, reload=reload)
