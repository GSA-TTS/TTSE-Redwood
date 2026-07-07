# Dataproduct Schemas

This directory contains canonical schema contracts aligned to the multi-dataproduct ADR.

## Structure

- `schema/dataproduct.schema.json`: canonical definition schema for a dataproduct.
- `schema/dataproduct-request.schema.json`: request payload schema for sender or receiver-triggered requests.

Committed examples are maintained under `examples/`:
- `examples/definitions/*.json`: sanitized sample dataproduct definitions.
- `examples/requests/*.json`: sanitized sample request payloads.

## Intended Runtime Mapping

- `dataproduct_id` maps to a runtime definition source (registry/config store).
- request payload (`DATAPRODUCT_REQUEST_JSON`) is validated against `dataproduct-request.schema.json`.
- request `dataproduct_id` resolves to the selected definition and then to `extraction.template_id`.
- existing template allow-list validation remains an outer control.

## Notes

- Sample examples use placeholder emails and synthetic values and are safe to commit.
- Keep ids and versions stable; publish a new version for breaking contract changes.
