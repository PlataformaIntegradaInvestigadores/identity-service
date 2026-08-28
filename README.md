# Centinela — identity-service

Servicio de autenticación e identidad: login/JWT, sesiones, MFA (TOTP), bloqueo por intentos fallidos, perfiles de usuario/empresa y sincronización con el monolito legado.

Parte del org multi-repo `PlataformaIntegradaInvestigadores`. Comparte el puerto interno 8002 con `search-bff-service` (que mapea al host en 8004); este servicio publica 8002 directo. En producción se accede a través de `gateway-service`.

## Stack

- Django 5 + Django REST Framework + Gunicorn
- `djangorestframework-simplejwt` (JWT), `pyotp` + `qrcode` (MFA/TOTP), `cryptography` (cifrado de secretos MFA)
- PostgreSQL 16
- `prometheus-client` (métricas)

## Estructura del proyecto

```
identity/
  application/use_cases.py      # Casos de uso de negocio
  domain/{events,exceptions,policies}.py
  infrastructure/legacy_event_handlers.py
  migrations/
  management/commands/          # import_legacy_identity, retry_legacy_sync_outbox, sync_company_identities
  tests/
  models.py, views.py, serializers.py, urls.py, admin.py
  auth_sessions.py, authentication_backends.py, mfa_services.py, login_lockout.py
  legacy_sync.py, company_profiles.py, profile_services.py
  security_events.py, metrics.py, middleware.py, exception_handlers.py
profile_identity_project/       # settings, urls, wsgi/asgi
```

Nota: la app mezcla capas explícitas (`application/`, `domain/`, `infrastructure/`) con módulos planos de responsabilidad única (auth, MFA, lockout, sync) — no sigue el layout Clean/Hexagonal completo que sí usan `social-service` y `search-service`.

## Requisitos previos

- Docker y Docker Compose (recomendado), o Python 3.11 + PostgreSQL si se corre sin Docker.

## Levantar en local

### Con Docker (recomendado)
```bash
cp .env.example .env        # ajustar credenciales si hace falta
docker compose up -d --build
```
Healthcheck: `curl -f http://localhost:8002/health/live/`

### Sin Docker (desarrollo)
```bash
python -m venv venv
venv\Scripts\activate  # En Linux/Mac: source venv/bin/activate
pip install -r requirements.txt
USE_SQLITE_FOR_TESTS=True python manage.py migrate
python manage.py runserver 8002
```
`USE_SQLITE_FOR_TESTS=True` evita depender de un Postgres real para desarrollo/tests locales (ver `profile_identity_project/settings.py`).

## Variables de entorno

Ver `.env.example` / `.env_produccion.example`. Variables clave:

| Variable | Descripción |
|---|---|
| `SECRET_KEY` / `JWT_SIGNING_KEY` / `MFA_SECRET_ENCRYPTION_KEY` | Secretos criptográficos — nunca reutilizar entre entornos |
| `JWT_ACCESS_TOKEN_MINUTES` / `JWT_REFRESH_TOKEN_DAYS` / `JWT_ALGORITHM` | Configuración de tokens JWT |
| `MFA_ENFORCEMENT_MODE`, `MFA_TOTP_*`, `MFA_LOCKOUT_*` | Política de MFA (TOTP) |
| `AUTH_PASSWORD_LOCKOUT_*` | Bloqueo por intentos fallidos de contraseña |
| `LEGACY_SYNC_*`, `COMPANY_PROFILE_SERVICE_URL` | Sincronización con el sistema legado y perfiles de empresa |
| `DB_NAME` / `DB_USER` / `DB_PASSWORD` / `DB_HOST` / `DB_PORT` | Conexión a PostgreSQL |
| `USE_SQLITE_FOR_TESTS` | `True` para correr tests/desarrollo sin Postgres real |

## Tests

```bash
USE_SQLITE_FOR_TESTS=True pytest --cov --cov-report=term
```

Cobertura mínima exigida en CI: **90%** (`--cov-fail-under=90` en `.github/workflows/ci.yml`). Estado actual: 92%, 103 tests.

## CI/CD

GitHub Actions (`.github/workflows/ci.yml`): tests unitarios → build de imagen Docker → deploy automático a staging (`develop` branch, runner self-hosted `ticcd`) con healthcheck y rollback automático.

## Convenciones

- Branches: `feature/*` → `develop`, `hotfix/*` → `main`.
- Commits: [Conventional Commits](https://www.conventionalcommits.org/), inglés, con el *por qué* en el cuerpo.
- Migraciones: siempre aditivas — nunca modificar una migración ya aplicada.
