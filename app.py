#!/usr/bin/env python3
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional
from urllib.error import HTTPError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen


class FusionConfigError(RuntimeError):
    pass


class FusionClient:
    def __init__(self) -> None:
        self.base_url = os.getenv("FUSION_BASE_URL", "https://yach-vika.zhiyinlou.com/fusion/v1")
        self.token = os.getenv("FUSION_TOKEN")
        self.datasheet_id = os.getenv("FUSION_DATASHEET_ID", "dstjpwCCYCubQ53M9M")
        self.view_id = os.getenv("FUSION_VIEW_ID", "viw1vsFKMMcvp")
        self.field_key = os.getenv("FUSION_FIELD_KEY", "name")

        if not self.token:
            raise FusionConfigError("Missing FUSION_TOKEN. Please set it in your environment.")

    def _request(self, method: str, path: str, *, params: Optional[Dict[str, str]] = None, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"
        if params:
            url = f"{url}?{urlencode(params)}"

        data = None
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")

        req = Request(url=url, method=method, headers=headers, data=data)
        try:
            with urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8") or "{}"
                return json.loads(raw)
        except HTTPError as err:
            body = err.read().decode("utf-8", errors="ignore")
            try:
                parsed = json.loads(body) if body else {}
            except json.JSONDecodeError:
                parsed = {"message": body}
            return {
                "success": False,
                "status": err.code,
                "error": parsed,
            }

    def list_records(self) -> Dict[str, Any]:
        return self._request(
            "GET",
            f"datasheets/{self.datasheet_id}/records",
            params={
                "viewId": self.view_id,
                "fieldKey": self.field_key,
            },
        )

    def create_record(self, fields: Dict[str, Any]) -> Dict[str, Any]:
        return self._request(
            "POST",
            f"datasheets/{self.datasheet_id}/records",
            params={"fieldKey": self.field_key},
            payload={"records": [{"fields": fields}]},
        )

    def update_record(self, record_id: str, fields: Dict[str, Any]) -> Dict[str, Any]:
        return self._request(
            "PATCH",
            f"datasheets/{self.datasheet_id}/records",
            params={"fieldKey": self.field_key},
            payload={"records": [{"recordId": record_id, "fields": fields}]},
        )

    def delete_record(self, record_id: str) -> Dict[str, Any]:
        return self._request(
            "DELETE",
            f"datasheets/{self.datasheet_id}/records",
            params={"recordIds": record_id},
        )


class TicketAPIHandler(BaseHTTPRequestHandler):
    client: FusionClient

    def _send(self, code: int, payload: Dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _parse_json(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length > 0 else b"{}"
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._send(200, {"ok": True})
            return
        if parsed.path == "/api/tickets":
            self._send(200, self.client.list_records())
            return
        self._send(404, {"message": "Not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/api/tickets":
            self._send(404, {"message": "Not found"})
            return

        body = self._parse_json()
        fields = body.get("fields")
        if not isinstance(fields, dict):
            self._send(400, {"message": "Body must be: { \"fields\": { ... } }"})
            return

        self._send(200, self.client.create_record(fields))

    def do_PATCH(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/tickets/"):
            self._send(404, {"message": "Not found"})
            return

        record_id = parsed.path.rsplit("/", 1)[-1]
        body = self._parse_json()
        fields = body.get("fields")
        if not isinstance(fields, dict):
            self._send(400, {"message": "Body must be: { \"fields\": { ... } }"})
            return

        self._send(200, self.client.update_record(record_id, fields))

    def do_DELETE(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/tickets/"):
            self._send(404, {"message": "Not found"})
            return
        record_id = parsed.path.rsplit("/", 1)[-1]
        self._send(200, self.client.delete_record(record_id))


def run() -> None:
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8080"))
    client = FusionClient()

    TicketAPIHandler.client = client

    server = ThreadingHTTPServer((host, port), TicketAPIHandler)
    print(f"Ticket sync API running at http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    run()
