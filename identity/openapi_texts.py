"""Textos de la documentación OpenAPI. Sin imports de DRF: lo carga settings."""

TAG_AUTH = "Autenticación"
TAG_MFA = "MFA"
TAG_USERS = "Usuarios"
TAG_PROFILE = "Perfil"
TAG_GROUPS = "Grupos"

SPECTACULAR_TAGS = [
    {
        "name": TAG_AUTH,
        "description": "Registro de cuentas, inicio de sesión, renovación y cierre "
        "de sesión.",
    },
    {
        "name": TAG_MFA,
        "description": "Verificación en dos pasos (TOTP): alta, confirmación, "
        "verificación al iniciar sesión y estado.",
    },
    {
        "name": TAG_USERS,
        "description": "Consulta y edición de las cuentas de investigadores.",
    },
    {
        "name": TAG_PROFILE,
        "description": "Información de perfil: sobre mí, disciplinas y contacto.",
    },
    {
        "name": TAG_GROUPS,
        "description": "Grupos de investigación: creación, membresía y "
        "administración. Las rutas con prefijo `/test/` son las que consume el "
        "frontend para los grupos del usuario autenticado.",
    },
]

SPECTACULAR_DESCRIPTION = """
Servicio de **identidad y autenticación** de la plataforma Centinela: cuentas de
investigadores y empresas, sesiones con JWT, verificación en dos pasos (MFA),
perfiles y grupos de investigación.

### Cómo autenticarse

1. `POST /token/` (investigador) o `POST /companies/token/` (empresa) con
   usuario y contraseña.
2. Según la cuenta, la respuesta es una de estas:
   * **Sesión iniciada**: trae `access` (JWT). El `refresh` se entrega en una
     cookie `HttpOnly` y no aparece en el cuerpo.
   * **`mfa_required`**: la cuenta tiene MFA activo. Enviar el
     `mfa_challenge` y el código de la app autenticadora a `POST /auth/mfa/verify/`.
   * **`mfa_enrollment_required`**: la cuenta debe activar MFA. Usar
     `POST /auth/mfa/setup/` y `POST /auth/mfa/confirm/`.
3. Enviar el JWT en cada petición protegida: `Authorization: Bearer <access>`
   (botón **Authorize**).
4. Renovar con `POST /token/refresh/`; toma el `refresh` de la cookie si no va
   en el cuerpo.

### Convenciones

* Detrás del gateway todas las rutas cuelgan de `/api/identity`.
* Los errores de autenticación y permisos responden `{"detail": "..."}`.
* Tras varios intentos fallidos la cuenta se bloquea temporalmente y el error
  es genérico a propósito.
"""
