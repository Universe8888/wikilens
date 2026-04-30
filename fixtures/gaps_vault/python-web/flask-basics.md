---
title: Flask Web Framework Basics
tags: [python, web, flask]
---

# Flask Web Framework Basics

Flask is a lightweight WSGI web framework for Python. It is designed to make getting started easy and quick, while still being able to scale to complex applications.

## Core Concepts

A Flask application is an instance of the `Flask` class. Routes are defined using the `@app.route()` decorator, which maps URL patterns to Python functions called **view functions**.

```python
from flask import Flask
app = Flask(__name__)

@app.route("/")
def index():
    return "Hello, World!"
```

## Request Handling

Flask provides a `request` object that contains all incoming request data, including form data, query string parameters, and JSON payloads. The `session` object enables storing user-specific data across requests using signed cookies.

## Templates

Flask uses Jinja2 as its templating engine. Templates are HTML files with special syntax for inserting dynamic content, looping over lists, and conditional rendering.

## WSGI and Synchronous Execution

Flask is built on WSGI, which means it handles one request at a time per thread by default. For simple applications this is fine, but high-traffic applications require either a multi-threaded or multi-process deployment behind a production WSGI server like Gunicorn.

The synchronous nature of standard Flask means that I/O-bound operations (database queries, external API calls) will block the entire thread until they complete. This is a significant difference from newer Python web frameworks that support asynchronous request handling natively.
