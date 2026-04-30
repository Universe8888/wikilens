---
title: Project Database Choices (archived 2022)
tags: [stack, database, sqlite]
date: 2022-05-15
---

# Database Choices — 2022

## Current Stack

The project uses SQLite as its primary database. SQLite was chosen for its simplicity, zero-configuration deployment, and suitability for the current dataset size. No separate database server is required.

## Why SQLite

SQLite is embedded directly in the application process, eliminating network latency for database calls entirely. For a single-writer, read-heavy workload this is ideal.

## Backup Strategy

Backups are taken by copying the `.db` file to a backup directory. A cron job runs every 6 hours. No WAL archiving is configured.
