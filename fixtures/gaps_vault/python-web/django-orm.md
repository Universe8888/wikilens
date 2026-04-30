---
title: Django ORM
tags: [python, web, django, database]
---

# Django ORM

The Django Object-Relational Mapper (ORM) is Django's built-in database abstraction layer. It allows developers to interact with database tables using Python objects rather than raw SQL queries.

## Models

In Django, a **model** is a Python class that inherits from `django.db.models.Model`. Each attribute of the class corresponds to a database column.

```python
from django.db import models

class Article(models.Model):
    title = models.CharField(max_length=200)
    body = models.TextField()
    published = models.DateTimeField(auto_now_add=True)
```

## Querysets

Django ORM queries return **QuerySets** — lazy, chainable objects that translate method calls into SQL. QuerySets are only evaluated (executed against the database) when iterated, sliced, or converted to a list.

```python
# Returns all articles; no DB hit yet.
articles = Article.objects.filter(title__contains="Python")
# Evaluated here:
for article in articles:
    print(article.title)
```

## Select Related and Prefetch Related

For queries involving foreign keys, `select_related()` performs a SQL JOIN to retrieve related objects in a single query. `prefetch_related()` performs separate queries and joins them in Python, which is more efficient for many-to-many relationships.

## Synchronous Architecture

The Django ORM is synchronous by design. All database queries block the executing thread until the database returns results. Django 4.1 introduced async ORM support, but the synchronous path remains the default.

Modern Python web frameworks designed for async from the ground up handle database access differently, using async-compatible database drivers and non-blocking query execution. The trade-offs between synchronous Django ORM patterns and async database access are a common architectural decision point.
