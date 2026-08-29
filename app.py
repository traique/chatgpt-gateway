from fastapi.responses import RedirectResponse

from faable.app import app


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url="/auth", status_code=307)


__all__ = ["app"]
