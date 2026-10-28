"""Local bearer grants: only hashes on the server, project/run scopes and explicit permissions."""

import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import HTTPException

PERMISSIONS = {"read", "run", "evidence", "raw", "admin"}


def private_read(path):
    path = Path(path)
    if path.is_symlink() or path.stat().st_mode & 0o077:
        raise ValueError("访问凭据文件必须为普通 0600 文件")
    return path.read_text()


def write_private(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise ValueError("拒绝符号链接凭据路径")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(value)


def issue(registry, destination, *, projects=None, permissions=None, runs=None, ttl=86400):
    projects = projects or ["*"]
    permissions = permissions or sorted(PERMISSIONS)
    if not set(permissions) <= PERMISSIONS or not permissions or not 1 <= ttl <= 31536000:
        raise ValueError("权限或有效期无效")
    for value in projects:
        if value != "*":
            UUID(value)
    for value in runs or []:
        UUID(value)
    path = Path(registry)
    data = json.loads(private_read(path)) if path.exists() else {"version": "e9-grants-1", "grants": []}
    value = "sim_" + secrets.token_urlsafe(32)
    grant = {
        "id": str(uuid4()),
        "sha256": hashlib.sha256(value.encode()).hexdigest(),
        "projects": projects,
        "runs": runs,
        "permissions": permissions,
        "expires_at": int(time.time()) + ttl,
        "revoked": False,
    }
    data["grants"].append(grant)
    if Path(destination).exists():
        raise ValueError("令牌文件已存在；请使用新路径，不覆盖既有凭据")
    write_private(destination, value + "\n")
    write_private(registry, json.dumps(data, indent=2) + "\n")
    return {k: v for k, v in grant.items() if k != "sha256"}


def bootstrap(directory):
    directory = Path(directory)
    registry, token = directory / "access-grants.json", directory / "operator.token"
    if not registry.exists() and not token.exists():
        issue(registry, token)
    if not registry.exists() or not token.exists():
        raise ValueError("访问凭据不完整；请使用 access 工具显式补齐")
    private_read(registry)
    private_read(token)
    return str(registry.resolve()), str(token.resolve())


def authenticate(header):
    if not header or not header.startswith("Bearer "):
        raise HTTPException(401, "需要访问令牌")
    supplied = header[7:]
    if not supplied.startswith("sim_") or len(supplied) > 256:
        raise HTTPException(401, "访问令牌无效或已过期")
    try:
        registry = os.environ.get("SIM_ACCESS_REGISTRY", ".local/access/access-grants.json")
        data = json.loads(private_read(registry))
        digest = hashlib.sha256(supplied.encode()).hexdigest()
        for grant in data["grants"]:
            if hmac.compare_digest(grant["sha256"], digest):
                if grant["revoked"] or grant["expires_at"] <= time.time():
                    break
                return grant
    except (OSError, ValueError, KeyError, TypeError):
        raise HTTPException(503, "访问控制未配置或不可用") from None
    raise HTTPException(401, "访问令牌无效或已过期")


def authorize(grant, permission, project=None, runs=()):
    if permission not in grant["permissions"]:
        raise HTTPException(403, "令牌没有该操作权限")
    if project and "*" not in grant["projects"] and str(project) not in grant["projects"]:
        raise HTTPException(403, "令牌无权访问该项目")
    if grant.get("runs") is not None and any(str(r) not in grant["runs"] for r in runs):
        raise HTTPException(403, "令牌无权访问该运行")


async def access_request(request):
    path, method = request.url.path, request.method
    if path == "/api/health" or path.startswith("/api/webhooks/"):
        return
    grant = authenticate(request.headers.get("authorization"))
    request.state.grant = grant
    parts = path.strip("/").split("/")
    project = request.query_params.get("project_id")
    runs = []
    if len(parts) > 2 and parts[1] == "projects":
        project = parts[2]
    if len(parts) > 2 and parts[1] == "runs":
        runs.append(parts[2])
    if request.query_params.get("other_run_id"):
        runs.append(request.query_params["other_run_id"])
    if method in {"POST", "PUT", "PATCH"}:
        raw = await request.body()
        if len(raw) > 160 * 1024:
            raise HTTPException(413, "请求超过 160 KiB")
        try:
            body = json.loads(raw) if raw else {}
        except ValueError:
            body = {}
        if isinstance(body, dict) and body.get("project_id"):
            if project and str(body["project_id"]) != project:
                raise HTTPException(403, "请求项目范围不一致")
            project = str(body["project_id"])
    permission = "read" if method == "GET" else "run"
    if (
        any(
            p
            in {
                "history",
                "manifest",
                "report",
                "compare",
                "findings",
                "checks",
                "timeline",
                "events",
                "console",
                "experiments",
            }
            for p in parts
        )
        and method == "GET"
        and path != "/api/console/catalog"
    ):
        permission = "evidence"
    if "raw-evidence" in parts:
        permission = "raw"
    if method == "DELETE" or any(p in {"reset", "retention", "emergency-stop", "resume"} for p in parts):
        permission = "admin"
    if path == "/api/projects" and method == "POST":
        permission = "admin"
        if "*" not in grant["projects"] or grant.get("runs") is not None:
            raise HTTPException(403, "创建项目需要全局管理权限")
    if grant.get("runs") is not None and method != "GET" and not path.endswith("/cancel"):
        raise HTTPException(403, "运行范围令牌不能新建或修改项目输入")
    if grant.get("runs") is not None and not runs and path not in {"/api/session", "/api/contracts/schema"}:
        raise HTTPException(403, "运行范围令牌仅可访问指定运行")
    authorize(grant, permission, project, runs)
    if parts[1:2] in [["runs"], ["experiments"]] and not project and len(parts) > 2:
        raise HTTPException(422, "需要明确 project_id")


def client_headers(path=None):
    token = private_read(path or os.environ.get("SIM_TOKEN_FILE", ".local/access/operator.token")).strip()
    return {"Authorization": "Bearer " + token}
