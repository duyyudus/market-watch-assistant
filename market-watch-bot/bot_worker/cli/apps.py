from __future__ import annotations

import typer

_CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}

app = typer.Typer(
    no_args_is_help=True,
    help="Market watch bot CLI",
    context_settings=_CONTEXT_SETTINGS,
)
source_app = typer.Typer(no_args_is_help=True, context_settings=_CONTEXT_SETTINGS)
worker_app = typer.Typer(no_args_is_help=True, context_settings=_CONTEXT_SETTINGS)
job_app = typer.Typer(no_args_is_help=True, context_settings=_CONTEXT_SETTINGS)
pipeline_app = typer.Typer(no_args_is_help=True, context_settings=_CONTEXT_SETTINGS)
news_app = typer.Typer(no_args_is_help=True, context_settings=_CONTEXT_SETTINGS)
event_app = typer.Typer(no_args_is_help=True, context_settings=_CONTEXT_SETTINGS)
watchlist_app = typer.Typer(no_args_is_help=True, context_settings=_CONTEXT_SETTINGS)
alert_app = typer.Typer(no_args_is_help=True, context_settings=_CONTEXT_SETTINGS)
alert_channel_app = typer.Typer(no_args_is_help=True, context_settings=_CONTEXT_SETTINGS)
alert_policy_app = typer.Typer(no_args_is_help=True, context_settings=_CONTEXT_SETTINGS)
digest_app = typer.Typer(no_args_is_help=True, context_settings=_CONTEXT_SETTINGS)
retention_app = typer.Typer(no_args_is_help=True, context_settings=_CONTEXT_SETTINGS)
health_app = typer.Typer(no_args_is_help=True, context_settings=_CONTEXT_SETTINGS)
embedding_app = typer.Typer(no_args_is_help=True, context_settings=_CONTEXT_SETTINGS)
market_app = typer.Typer(no_args_is_help=True, context_settings=_CONTEXT_SETTINGS)
catalyst_app = typer.Typer(no_args_is_help=True, context_settings=_CONTEXT_SETTINGS)
llm_app = typer.Typer(no_args_is_help=True, context_settings=_CONTEXT_SETTINGS)

app.add_typer(source_app, name="source")
app.add_typer(worker_app, name="worker")
app.add_typer(job_app, name="job")
app.add_typer(pipeline_app, name="pipeline")
app.add_typer(news_app, name="news")
app.add_typer(event_app, name="event")
app.add_typer(watchlist_app, name="watchlist")
app.add_typer(alert_app, name="alert")
alert_app.add_typer(alert_channel_app, name="channel")
alert_app.add_typer(alert_policy_app, name="policy")
app.add_typer(digest_app, name="digest")
app.add_typer(retention_app, name="retention")
app.add_typer(health_app, name="health")
app.add_typer(embedding_app, name="embedding")
app.add_typer(market_app, name="market")
app.add_typer(catalyst_app, name="catalyst")
app.add_typer(llm_app, name="llm")
