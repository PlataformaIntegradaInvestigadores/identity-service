# profile_identity_backend

Servicio de autenticación e identidad (Django 5 + SimpleJWT + Gunicorn).

## Levantar local (Docker)

```bash
cp .env.example .env        # ajustar credenciales si hace falta
docker compose up -d --build
```

Healthcheck: `curl -f http://localhost:8002/health/live/`

## Stack

- Django 5, SimpleJWT, Gunicorn, PostgreSQL 16
- Settings module: `profile_identity_project.settings`
- Puerto 8002 · alias `profile-identity-web` en `centinela-net`

## Pruebas y lint

```bash
pytest --cov --cov-fail-under=0
ruff check . && black --check .
```

## Notas

- Secretos por env: `SECRET_KEY`, `JWT_SIGNING_KEY`, `MFA_SECRET_ENCRYPTION_KEY`.
- Migraciones aditivas; nunca modificar una migración aplicada.
