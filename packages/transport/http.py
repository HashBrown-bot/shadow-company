"""Exact-origin, pinned-IP HTTP for explicit local examples; no proxies or redirects."""

import http.client
import ipaddress
import json
import os
import socket
from urllib.parse import urlsplit


class BoundaryError(RuntimeError):
    pass


class SafeHTTP:
    def __init__(self, policy=None):
        # Operator policy only: never read an allowlist from an uploaded contract.
        self.policy = (
            policy
            if policy is not None
            else json.loads(
                os.environ.get(
                    "EXAMPLE_OUTBOUND_POLICY",
                    '{"http://127.0.0.1:8000":["127.0.0.1"],"http://127.0.0.1:8001":["127.0.0.1"],"http://127.0.0.1:8002":["127.0.0.1"],"http://127.0.0.1:8003":["127.0.0.1"]}',
                )
            )
        )

    def resolve(self, origin):
        parsed = urlsplit(origin)
        if (
            origin not in self.policy
            or parsed.scheme != "http"
            or parsed.username
            or parsed.password
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            raise BoundaryError("出站 origin 不在操作员批准的示例范围")
        port = parsed.port
        # No arbitrary localhost management ports, even if a contract requests them.
        if port not in {8000, 8001, 8002, 8003}:
            raise BoundaryError("示例端口未批准")
        try:
            addresses = {
                item[4][0] for item in socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
            }
        except OSError:
            raise BoundaryError("目标 DNS 无法解析") from None
        approved = set(self.policy[origin])
        if not addresses or not addresses <= approved:
            raise BoundaryError("DNS 解析结果超出已批准 IP")
        for addr in addresses:
            ip = ipaddress.ip_address(addr)
            if (
                ip.is_link_local
                or ip.is_multicast
                or ip.is_unspecified
                or (not ip.is_loopback and not ip.is_private)
            ):
                raise BoundaryError("禁止元数据地址与非隔离网络")
        return parsed, sorted(addresses)[0]

    def request(self, method, origin, path, *, headers=None, body=None, timeout=5):
        if (
            not path.startswith("/")
            or path.startswith("//")
            or any(c in path for c in ["\\", "\r", "\n", "#", "%", ".."])
        ):
            raise BoundaryError("接口路径不允许")
        parsed, ip = self.resolve(origin)
        # Connect to the validated numeric IP, not a second DNS lookup; Host preserves origin semantics.
        connection = http.client.HTTPConnection(ip, parsed.port, timeout=timeout)
        data = body if isinstance(body, bytes) else (json.dumps(body).encode() if body is not None else None)
        request_headers = dict(headers or {}) | {"Host": parsed.netloc, "Content-Type": "application/json"}
        try:
            connection.request(method, path, body=data, headers=request_headers)
            response = connection.getresponse()
            raw = response.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise BoundaryError("响应超过 1 MiB 限制")
            if 300 <= response.status < 400:
                raise BoundaryError("出站重定向被拒绝")
            try:
                payload = json.loads(raw)
            except (ValueError, UnicodeDecodeError):
                raise BoundaryError("目标响应不是 JSON") from None
            return {"status": response.status, "headers": dict(response.getheaders()), "body": payload}
        except TimeoutError:
            raise BoundaryError("transport_read_timeout") from None
        except (OSError, http.client.HTTPException):
            raise BoundaryError("示例服务网络请求失败") from None
        finally:
            connection.close()
