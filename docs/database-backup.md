# PostgreSQL backup and isolated restore

These scripts provide a local, manual foundation for database recovery. They do not establish an operational backup program by themselves.

## Connection safety

Use a PostgreSQL service definition and password file so credentials are not printed or placed in process command lines. For example, configure a non-production service in `~/.pg_service.conf`, put its password in a mode-0600 `PGPASSFILE`, and export only their paths/names:

```sh
export PGSERVICE=capstone-staging
export PGPASSFILE=/secure/path/pgpass
```

Alternatively, explicitly set at least `PGHOST` and `PGUSER`. The database name is always a required simple name containing only letters, digits, `_`, and `-`. Put host aliases and other connection options in the service definition: the scripts reject URIs and libpq `key=value` strings in `--database`. Do not put passwords in shell history or arguments.

## Create a backup

```sh
scripts/backup_database.sh --database capstone --output /secure/backups/capstone-2026-09-09.dump
```

The script uses `pg_dump` custom format, a mode-077 umask, a private `mktemp` directory that is removed on failure, and a SHA-256 sidecar. Same-filesystem hard links publish the completed files without replacing an existing path, including when two writers race. Choose an existing trusted directory on storage that is not served by the application; the filesystem must support hard links.

## Restore in isolation

Create a new empty database using separately authorized administration procedures, select a service that cannot reach production, then run:

```sh
export PGSERVICE=capstone-restore-isolated
scripts/restore_database.sh --database capstone_restore_20260909 --backup /secure/backups/capstone-2026-09-09.dump
```

The restore verifies the checksum and refuses a target containing user objects. It never selects a production database automatically and never passes `--clean`, `--create`, or a drop option. The actual restore uses `pg_restore --exit-on-error --single-transaction`.

Both scripts hash file contents through standard input. This avoids GNU `sha256sum` filename escaping changing the parsed digest when a parent directory contains a carriage return or backslash. The checksum still has to match before any database query or restore is attempted.

After restore, compare schema migration state and agreed read-only invariants such as user, problem, submission, contest-submission, and score-ledger counts. Application-level consistency checks and a controlled test login/query should be part of a rehearsal. Destroying the isolated database is a separate, explicitly approved operation.

## Work still required for operations

No scheduled job, external/off-host or encrypted storage, monitoring, owner/on-call assignment, or retention deletion is installed by these files. RPO, RTO, backup frequency, retention duration, and recovery responsibility still require an operator decision and measurement. Until that approval exists, retain backups without an automatic deletion command. Database-resident problem/test snapshots are included in a full database dump, but external files, executable images/digests, configuration and encrypted-secret recovery need a coordinated recovery inventory. An isolated script test is not proof of full production disaster recovery.

## Automated isolated verification

`backend/tests/test_backup_live.py` is opt-in with `RUN_SANDBOX_INTEGRATION=1`. It refuses to operate unless the calling runner and PostgreSQL have the dedicated audit Compose labels and PostgreSQL has the bounded audit resource configuration. It creates uniquely named fixture databases, runs the actual backup and restore scripts with real PostgreSQL tools, compares two related tables including Korean text, and tests overwrite, non-empty target and invalid-checksum refusal. Normal and carriage-return directory paths are covered. Cleanup drops only fixture-created database names and removes only its explicitly named temporary files; it never selects an existing application database as a target. Latest outcomes are recorded in [the remediation status](audit-remediation-status.md).
