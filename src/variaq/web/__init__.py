"""VariaQ optional local web UI (``pip install 'variaq[web]'``)."""


def web_dependencies_available() -> bool:
    try:
        import fastapi  # noqa: F401
        import jinja2  # noqa: F401
        import uvicorn  # noqa: F401
    except ImportError:
        return False
    return True
