"""FastAPI web layer for the Bank Ledger Dashboard.

A thin JSON API over the existing services (src/services/*) plus a single-page
Tabulator.js frontend. The heavy lifting stays in the service layer; this layer
only caches state and shuttles JSON.
"""
