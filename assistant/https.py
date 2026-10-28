"""Verified HTTPS context for requests to OpenAI from installed Python builds."""

import ssl

import certifi


def verified_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    context.load_verify_locations(cafile=certifi.where())
    return context
