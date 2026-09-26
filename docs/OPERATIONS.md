# TradeHub production operations

TradeHub is intentionally safe-by-default. Production deployment does not imply live trading: keep `TRADING_MODE=dry_run`, `RISK_CAPITAL_MODE=simulation`, and live execution disabled unless the owner explicitly changes those controls separately.

## Persistent state

Docker Compose defines two named volumes that must survive container replacement and application upgrades:

- `tradehub-db` mounts `/var/lib/postgresql/data` in PostgreSQL and contains the TradeHub database.
- `tradehub-secrets` mounts `/data` in the application and contains Robinhood OAuth/account state written by the application. Treat this volume as sensitive credential material.

Do not remove either volume during routine upgrades. In particular, do not use `docker compose down -v` in production.

## Clean-clone deployment

1. Clone the repository and enter its directory.
2. Copy `.env.example` to `.env`.
3. Set a strong `POSTGRES_PASSWORD` and configure the required Robinhood MCP values. Do not commit `.env`.
4. Confirm the safety values remain `TRADING_MODE=dry_run`, `RISK_CAPITAL_MODE=simulation`, and live execution disabled.
5. Validate configuration with `docker compose config`.
6. Build with `docker compose build --pull`.
7. Start with `docker compose up -d`.
8. Check `docker compose ps`, then call `/health` and `/ready`. `/ready` must not report a degraded Robinhood connection when Robinhood MCP is expected to be available.
9. Run the smoke-test checklist below before considering the deployment healthy.

The Compose file requires `POSTGRES_PASSWORD`; deployment fails closed if it is absent.

## Upgrade and restart

Before an upgrade, take both backups described below. Then:

```bash
git fetch --all --prune
git pull --ff-only
docker compose config
docker compose build --pull
docker compose up -d --remove-orphans
docker compose ps
```

Do not add `-v` to `docker compose down`. A normal `docker compose restart app` or `docker compose up -d --force-recreate app` preserves named volumes.

After an upgrade, verify `/health`, `/ready`, scanner history, and dry-run/simulation safety settings.

## PostgreSQL backup and restore

Create a logical database backup outside the container/volume:

```bash
mkdir -p backups
docker compose exec -T db pg_dump -U tradehub -d tradehub -Fc > backups/tradehub-$(date +%Y%m%d-%H%M%S).dump
```

Verify the backup is non-empty and store a protected copy off-host.

Restore only during a maintenance window. Stop application writers, recreate/empty the target database as appropriate, and restore:

```bash
docker compose stop app
docker compose exec -T db pg_restore -U tradehub -d tradehub --clean --if-exists < backups/tradehub.dump
docker compose start app
```

For a new empty database, omit `--clean`. Always test restores in a non-production environment first.

## Robinhood auth/account-state backup and restore

The `tradehub-secrets` volume contains sensitive OAuth/account state. Back it up without printing its contents:

```bash
mkdir -p backups
docker run --rm \
  -v tradehub_tradehub-secrets:/source:ro \
  -v "$PWD/backups:/backup" \
  alpine:3.22 \
  sh -c 'tar -C /source -czf /backup/tradehub-secrets-$(date +%Y%m%d-%H%M%S).tgz .'
```

The Compose project prefix can change the actual Docker volume name. Confirm it first with `docker volume ls` or `docker compose volumes` where supported.

Restore with the application stopped:

```bash
docker compose stop app
docker run --rm \
  -v tradehub_tradehub-secrets:/target \
  -v "$PWD/backups:/backup:ro" \
  alpine:3.22 \
  sh -c 'rm -rf /target/* /target/.[!.]* /target/..?* 2>/dev/null || true; tar -C /target -xzf /backup/tradehub-secrets.tgz; chown -R 10001:10001 /target; chmod 700 /target'
docker compose start app
```

Protect these archives as credentials. Never commit them, attach them to issues, or paste their contents into logs. After restore, verify `/ready`; reauthenticate Robinhood if the restored OAuth state is expired or rejected.

## Smoke-test checklist

A release is healthy only after all applicable checks pass:

- `docker compose config` succeeds from the deployment checkout.
- `docker compose ps` shows PostgreSQL healthy and the application running.
- `/health` succeeds.
- `/ready` succeeds, or intentionally reports the documented Robinhood degraded/auth-required state when credentials need operator action.
- Scanner history can be read without server errors.
- A scanner run can be created and advances beyond discovery/prefilter when Robinhood MCP is connected.
- A per-symbol option/deep-scan failure is recorded without terminating the entire scan.
- Frontend scanner views render running, failed, empty, and successful results without exposing secrets or account numbers.
- `TRADING_MODE=dry_run` remains in effect.
- `RISK_CAPITAL_MODE=simulation` remains in effect.
- Live execution remains disabled and manual approval/risk-manager controls remain intact.
- A recent PostgreSQL backup and Robinhood-state backup exist, and the restore procedure has been exercised in a non-production environment.
