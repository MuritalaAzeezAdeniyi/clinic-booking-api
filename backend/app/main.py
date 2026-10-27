from fastapi import FastAPI, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.database import init_db

app = FastAPI(title="Clinic Booking API")


@app.on_event("startup")
def startup_event():
    init_db()


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(request, exc: RequestValidationError):
    loc = exc.errors()
    field_name = "request"
    if loc:
        last_loc = loc[0].get("loc", [])
        if last_loc:
            field_name = str(last_loc[-1])

    return JSONResponse(
        status_code=400,
        content={"error": f"{field_name} is required" if field_name != "request" else "invalid request"},
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request, exc: StarletteHTTPException):
    detail = exc.detail
    if exc.status_code == 404:
        detail = "not found"
    return JSONResponse(status_code=exc.status_code, content={"error": str(detail)})


@app.exception_handler(Exception)
async def unknown_exception_handler(request, exc: Exception):
    return JSONResponse(status_code=500, content={"error": "internal server error"})


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/manual-error")
def manual_error():
    raise HTTPException(status_code=401, detail="bad creds")


@app.get("/requires-name")
def requires_name(name: str = Query(...)):
    return {"name": name}
