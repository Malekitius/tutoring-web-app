"""Settings for the local container deployment."""

from .settings import *

DEBUG = False
STATIC_ROOT = BASE_DIR / "collected_static"
MIDDLEWARE = [
    MIDDLEWARE[0],
    "whitenoise.middleware.WhiteNoiseMiddleware",
    *MIDDLEWARE[1:],
]
TUTOR_PDF_FONT = "Liberation Sans"
