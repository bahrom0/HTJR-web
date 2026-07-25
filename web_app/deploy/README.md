# Same-origin reverse-proxy contract

The browser has one public origin. The proxy must preserve these paths:

- `/api/v1/*` forwards to the FastAPI process.
- `/events/*` forwards to the same FastAPI process with response buffering disabled.
- every other path serves the production `web_app/dist` directory and falls back to
  `index.html` for client-side routes.

`Caddyfile.example` is an executable reference configuration. Set:

- `HTR_PUBLIC_ORIGIN` to the real HTTPS domain (or `localhost` for a local-only check);
- `HTR_API_UPSTREAM` to the private API listener, normally `127.0.0.1:8000`;
- `HTR_WEB_ROOT` to the absolute production `dist` directory.

Feature code must continue to use relative `/api/v1` and `/events` URLs. A local Caddy
check does not prove public HTTPS; external DNS, certificate and another-device evidence
belong to the release verification session.
