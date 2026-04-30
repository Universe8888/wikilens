---
title: FastAPI Overview
tags: [python, web, fastapi, async]
---

# FastAPI Overview

FastAPI is a modern, high-performance Python web framework for building APIs. It is built on top of Starlette (an ASGI framework) and Pydantic (data validation). Its standout features are automatic OpenAPI documentation generation and native support for Python's `async`/`await` syntax.

## Key Features

**Type hints throughout**: FastAPI uses Python type annotations to declare request parameters, response shapes, and dependencies. Pydantic models handle automatic validation and serialization.

**Automatic documentation**: FastAPI generates interactive Swagger UI and ReDoc documentation from the type annotations and docstrings, with no manual schema writing required.

**ASGI foundation**: Unlike WSGI frameworks (Flask, Django without Channels), FastAPI is built on ASGI and can handle many concurrent connections in a single process, making it well-suited for I/O-bound workloads.

## Comparison with Flask and Django

Flask and Django are mature WSGI frameworks with synchronous execution models. FastAPI's async-first design means concurrent requests do not block each other while waiting for database queries or external API calls.

However, "async" in FastAPI refers specifically to Python's `async`/`await` mechanism. The difference between synchronous and asynchronous request handling in Python web frameworks — why async helps for I/O-bound tasks but not CPU-bound tasks, and how the event loop interacts with thread pools for synchronous code paths — is a nuanced topic that is not covered in detail here.

## Dependencies

FastAPI's dependency injection system uses function parameters with type annotations. Dependencies can be async functions, and FastAPI resolves them automatically at request time.
