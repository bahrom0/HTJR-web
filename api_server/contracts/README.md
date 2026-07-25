# API v1 contract

`openapi.v1.json` is the checked-in, deterministic contract for the same-origin
`/api/v1` API. It is generated from the FastAPI application and extended with
the spec-first resource operations required by Tajik HTR Studio.

Every operation has an `x-implementation-status` value:

- `live` means the path and method are currently registered by FastAPI.
- `planned` means the operation is a versioned client/server contract only; it
  must not be treated as runtime functionality until the real route exists.

The exporter never registers routes. It validates that all live operations are
still compatible with their checked-in path parameters, request bodies, and
successful responses. IDs use OpenAPI `uuid` format, timestamps use
`date-time`, and API failures use `ApiErrorEnvelope`.

From `api_server`:

```powershell
.\.venv-s11\Scripts\python.exe -m scripts.export_openapi_contract --check
```

After an intentional API contract change, regenerate and review the diff. The exporter
writes byte-identical snapshots to both `api_server/contracts/openapi.v1.json` and
`web_app/contracts/openapi.v1.json`, so Web and API cannot silently drift:

```powershell
.\.venv-s11\Scripts\python.exe -m scripts.export_openapi_contract --write
```
