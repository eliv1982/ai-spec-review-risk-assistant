# Project Scope

## Goal

Build a production-style MVP for reviewing technical specifications, project requirements, feature requests, automation briefs and business requirements.

## Core Functionality

- create and store documents
- run an LLM review with strict structured output
- deterministic validation and quality control
- manual-review workflow with `needs_review` and reason codes
- document, review and audit views
- JSON export
- SQLite persistence
- Docker-based reproducible startup
- automated tests and 10 test documents

## In Scope

- FastAPI backend
- SQLAlchemy 2
- SQLite
- Pydantic v2
- OpenAI structured outputs
- React/Vite frontend
- audit logging
- safe fallback when the model fails or returns invalid output

## Out of Scope

- authentication and roles
- PDF, DOCX and OCR
- RAG and vector databases
- document version comparison
- generation of a rewritten specification
- messaging integrations
- multi-user collaboration
- production deployment; deployment is optional after the local MVP is complete

## Quality Principles

- the backend makes the final `needs_review` decision
- LLM output is never trusted without schema and business-rule validation
- failures produce a safe review result and an audit record
- secrets must never be committed
- scope expansion requires an explicit decision
