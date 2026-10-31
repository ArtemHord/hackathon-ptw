# Acme API

Last updated: 12 Oct 2026

## Rate limit
The Acme API allows 50 requests per second per API key. Requests over the limit get HTTP 429 with a `Retry-After` header.

## Authentication
- All requests use a bearer token: `Authorization: Bearer <token>`.
- Use a bearer token from `POST /v1/auth/token`.

## Endpoints
| Method | Path | Purpose |
|---|---|---|
| POST | /v1/auth/token | Exchange an API key for a bearer token |
| GET | /v1/projects | List projects of the account |
| POST | /v1/projects | Create a project |
| GET | /v1/events | List events, supports `since` and `limit` (max 100) |
| POST | /v1/webhooks | Register a webhook URL for events |

## Errors
JSON body `{"error": {"code": "...", "message": "..."}}`. Codes: 400 bad request, 401 invalid token, 404 not found, 429 rate limited.
