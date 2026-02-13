"""
AceCPAs Backend - FastAPI Main Application
Entry point for the API server.
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.routers import deals, upload, open_items, files, mapper, consolidation, ebitda


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    # Startup
    settings = get_settings()
    print(f"🚀 Starting AceCPAs Backend in {settings.environment} mode")
    yield
    # Shutdown
    print("👋 Shutting down AceCPAs Backend")


# Create FastAPI application
app = FastAPI(
    title="AceCPAs Backend API",
    description="Multi-tenant Financial Intelligence Platform API",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS Configuration
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",  # Next.js dev
        "http://localhost:3001",
        "https://*.vercel.app",   # Vercel deployments
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    import traceback
    error_msg = "".join(traceback.format_exception(None, exc, exc.__traceback__))
    print(f"CRITICAL ERROR: {error_msg}")  # Print to console
    return JSONResponse(
        status_code=500,
        content={"detail": f"Internal Server Error: {str(exc)}", "trace": error_msg},
    )


# Include routers
app.include_router(upload.router, tags=["Upload"])
app.include_router(deals.router, prefix="/deals", tags=["Deals"])
app.include_router(open_items.router, tags=["Open Items"])
app.include_router(files.router, prefix="/api/v1", tags=["Files"])
app.include_router(mapper.router, tags=["Mapper"])
app.include_router(consolidation.router, prefix="/api/consolidation", tags=["Consolidation"])
app.include_router(ebitda.router, prefix="/api/ebitda", tags=["EBITDA"])


# Health check endpoint
@app.get("/health", tags=["Health"])
async def health_check():
    """Health check endpoint for load balancers."""
    return {
        "status": "healthy",
        "version": "0.1.0",
        "environment": settings.environment,
    }


@app.get("/", tags=["Root"])
async def root():
    """Root endpoint with API info."""
    return {
        "name": "AceCPAs Backend API",
        "version": "0.1.0",
        "docs": "/docs",
        "health": "/health",
    }
