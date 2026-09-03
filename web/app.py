from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from web.routes import router as username_router

BASE_DIR = Path(__file__).parent.parent

app = FastAPI(
    title="Metis",
    description="OSINT Username Reconnaissance & Intelligence Service",
    version="1.0.0",
)

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static assets
static_dir = BASE_DIR / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Configure Jinja2 templates
templates_dir = BASE_DIR / "templates"
templates = Jinja2Templates(directory=str(templates_dir))

# Include API routes
app.include_router(username_router)


@app.get("/", response_class=HTMLResponse)
@app.head("/", response_class=HTMLResponse)
async def index(request: Request):
    """Serve the Metis interactive username search UI."""
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"app_name": "Metis"},
    )


@app.get("/health")
async def health():
    return {"status": "ok", "service": "metis"}
