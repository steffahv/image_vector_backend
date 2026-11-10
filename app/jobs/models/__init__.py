"""SQLAlchemy tables for operations, in the `operations` PostgreSQL schema (VEC-41).

One file per table. See Modelo_relacional_VectorEdit §VIII and docs/base-de-datos.md.

- audit_entry.py: `audit_log` (AuditEntry), append-only log of security-relevant actions.
- object_copy.py: `object_copies` (ObjectCopy), checked copies of files at backup destinations.
- backup_run.py: `backup_runs` (BackupRun), global backup runs; no account data.
- job.py: `jobs` (Job), persistent queue (VEC-36).

- export.py: `exports` (Export), links a job and the final file in its workspace.

Import every table here: Alembic and other modules import from `app.jobs.models`.
"""

from app.jobs.models.audit_entry import AuditEntry, AuditResult
from app.jobs.models.backup_run import BackupRun, BackupStatus, BackupType
from app.jobs.models.export import Export, ExportStatus
from app.jobs.models.job import Job, JobStatus
from app.jobs.models.object_copy import ObjectCopy

__all__ = [
    "AuditEntry",
    "AuditResult",
    "BackupRun",
    "BackupStatus",
    "BackupType",
    "Export",
    "ExportStatus",
    "Job",
    "JobStatus",
    "ObjectCopy",
]
