"""Async worker hosts: Service Bus consumers, the outbox relay loop, and the reconcile scheduler.

Runs in the Azure Postgres deployment. Local dev runs the same pipeline synchronously in the
api process (memory profile), so the worker is not used locally.
"""
