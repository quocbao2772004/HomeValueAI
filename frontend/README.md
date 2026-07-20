# HomeValue AI Frontend

Static dashboard for the Vinhomes Hanoi valuation MVP. The UI does not keep its own market dataset or hard-code prices; it calls the FastAPI backend in this repository.

## Deployed Demo

- Web demo: https://solanai.us
- API service: https://apivinhomes.solanai.us
- Health check: https://apivinhomes.solanai.us/health

## Run Locally

Start the backend from the repository root:

```bash
python3 scripts/serve.py
```

Then serve the frontend:

```bash
python3 scripts/frontend_proxy.py
```

Open `http://127.0.0.1:2707`.

For the domain-style local service, run the frontend proxy on `http://127.0.0.1:2707` and the API on `http://127.0.0.1:1108`.

When opened from localhost on port `2707` or on deployed domains, the frontend uses same-origin `/api`. Other localhost ports keep the default `http://127.0.0.1:8000` for direct development.
