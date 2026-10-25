"""/docs: Swagger UI behind the API token (owner decision 2026-10-25).

The page itself is an empty shell: it asks for the token once (remembered in this browser),
then fetches /openapi.json and makes every "Try it out" request with an X-API-Token header.
The token never goes into a URL, so it never lands in Cloud Run's request logs."""

SWAGGER_UI = "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.33.1"

DOCS_HTML = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Chongqing Family Translator: API</title>
<link rel="stylesheet" href="{SWAGGER_UI}/swagger-ui.css">
</head>
<body>
<div id="swagger-ui"></div>
<script src="{SWAGGER_UI}/swagger-ui-bundle.js"></script>
<script>
async function load() {{
  let token = "";
  try {{ token = localStorage.getItem("apiToken") || ""; }} catch {{}}
  for (;;) {{
    if (!token) token = (prompt("API token") || "").trim();
    if (!token) return;
    const r = await fetch("/openapi.json", {{ headers: {{ "X-API-Token": token }} }});
    if (r.ok) {{
      try {{ localStorage.setItem("apiToken", token); }} catch {{}}
      SwaggerUIBundle({{
        spec: await r.json(),
        dom_id: "#swagger-ui",
        requestInterceptor: (req) => {{ req.headers["X-API-Token"] = token; return req; }},
      }});
      return;
    }}
    token = "";
    alert("That token didn't work.");
  }}
}}
load();
</script>
</body>
</html>
"""
