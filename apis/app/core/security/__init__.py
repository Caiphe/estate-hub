"""Security primitives: passwords, access tokens, refresh tokens, and CSRF tokens.

These modules are pure functions over explicit inputs. They never depend on FastAPI,
database sessions, Redis, or cookies, and they never log secret or token values.
"""
