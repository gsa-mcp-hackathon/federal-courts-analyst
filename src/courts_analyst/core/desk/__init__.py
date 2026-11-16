"""The request desk: a sandboxed write workflow on top of the analyst (ADR 0013).

``models`` (records and views), ``store`` (the SQLite desk store, separate
from the read-only official data), ``status`` (allowed transitions),
``gate`` (the verification gate), ``inquiries`` (which revisions can go to
the statistics office), ``hooks`` (how the read tools see office responses)
and ``service`` (the guarded entry points the adapters call).
"""
