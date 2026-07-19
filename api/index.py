"""Vercel serverless entrypoint.

Re-exports the existing FastAPI app unchanged so behaviour on Vercel is
identical to local dev (`python run.py`) - same routes, same security
middleware, same static-file serving via StaticFiles. Vercel's Python
runtime auto-detects the module-level ``app`` ASGI object.
"""
from app.main import app  # noqa: F401
