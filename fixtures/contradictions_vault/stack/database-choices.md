---
title: Project Database Choices
tags: [stack, database, postgresql, sqlite]
date: 2024-04-01
---

# Database Choices

## Current Stack (2024)

As of April 2024, the project uses PostgreSQL 16 as the primary database. The migration from SQLite was completed in March 2024 after the dataset grew beyond SQLite's practical limits for concurrent writes.

## Why PostgreSQL

PostgreSQL was chosen for its ACID compliance, strong support for JSON columns, and mature tooling ecosystem. Connection pooling via PgBouncer keeps latency under 5ms at p95 for standard queries.

## Backup Strategy

Nightly logical backups run via pg_dump to an off-site object store. Point-in-time recovery is enabled with a 7-day WAL retention window.
