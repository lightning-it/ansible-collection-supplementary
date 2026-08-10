"""Stage one immutable collection candidate in a native Nexus Galaxy v3 repository.

The Nexus username and password are read exclusively from the environment.  The
script never prints either value and refuses redirects so credentials cannot be
forwarded to an unexpected origin.  A successful invocation always downloads
the stored bytes again and compares their SHA-256 digest with the local file.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from types import TracebackType
from typing import BinaryIO, Protocol, cast

API_VERSION = "lit.mlx90.nexus-stage/v1"
KIND = "NexusGalaxyV3Stage"
ARTIFACT_SUFFIX = "/api/v3/plugin/ansible/content/published/collections/artifacts/"
REPOSITORY_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,126}\Z")
ARTIFACT_RE = re.compile(
    r"[a-z0-9_]+-[a-z0-9_]+-(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\."
    r"(?:0|[1-9][0-9]*)(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?\.tar\.gz\Z"
)
DIGEST_RE = re.compile(r"[0-9a-f]{64}\Z")
MAX_CANDIDATE_BYTES = 256 * 1024 * 1024
MAX_ERROR_BYTES = 16 * 1024
REQUEST_TIMEOUT_SECONDS = 120


class StageError(ValueError):
    """The staging contract was not satisfied."""


class HttpResponse(Protocol):
    def getcode(self) -> int:
        ...

    def read(self, amount: int = -1) -> bytes:
        ...

    def __enter__(self) -> HttpResponse:
        ...

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(  # type: ignore[override]
        self,
        req: urllib.request.Request,
        fp: BinaryIO,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> None:
        del req, fp, code, msg, headers, newurl
        return None


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def has_symlink_component(path: Path) -> bool:
    absolute = path if path.is_absolute() else Path.cwd() / path
    if ".." in absolute.parts:
        return True
    current = Path(absolute.anchor)
    for component in absolute.parts[1:]:
        current /= component
        if current.is_symlink():
            # macOS exposes /var as the platform-owned alias for /private/var.
            if current == Path("/var") and current.resolve(strict=True) == Path("/private/var"):
                continue
            return True
    return False


def require_candidate(path: Path) -> tuple[int, str]:
    if has_symlink_component(path) or not path.is_file():
        raise StageError("candidate must be a regular non-symlink file")
    if ARTIFACT_RE.fullmatch(path.name) is None:
        raise StageError("candidate name is not a canonical collection artifact")
    size = path.stat().st_size
    if size <= 0 or size > MAX_CANDIDATE_BYTES:
        raise StageError("candidate size is outside the bounded publication contract")
    return size, sha256(path)


def repository_url(value: str, repository: str) -> str:
    if REPOSITORY_RE.fullmatch(repository) is None:
        raise StageError("Nexus repository name is invalid")
    if value != value.strip():
        raise StageError("Nexus repository URL must be canonical")
    parsed = urllib.parse.urlsplit(value)
    decoded_path = urllib.parse.unquote(parsed.path)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or decoded_path != parsed.path
        or "//" in parsed.path
        or "\\" in parsed.path
        or any(part in {".", ".."} for part in parsed.path.split("/"))
    ):
        raise StageError("Nexus repository URL must be credential-free HTTPS")
    expected_suffix = f"/repository/{repository}"
    normalized_path = parsed.path.rstrip("/")
    if not normalized_path.endswith(expected_suffix):
        raise StageError("Nexus repository URL does not match the configured repository")
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, normalized_path, "", ""))


def artifact_url(base_url: str, artifact_name: str) -> str:
    if ARTIFACT_RE.fullmatch(artifact_name) is None:
        raise StageError("artifact name is invalid")
    return base_url + ARTIFACT_SUFFIX + urllib.parse.quote(artifact_name, safe="")


class NexusClient:
    def __init__(self, username: str, password: str) -> None:
        if not username or username != username.strip() or ":" in username:
            raise StageError("Nexus username is missing or invalid")
        if not password:
            raise StageError("Nexus password is missing")
        credential = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
        self._authorization = f"Basic {credential}"
        self._opener = urllib.request.build_opener(
            _RejectRedirects(),
            urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        )

    def _open(self, request: urllib.request.Request) -> HttpResponse:
        try:
            return cast(HttpResponse, self._opener.open(request, timeout=REQUEST_TIMEOUT_SECONDS))
        except urllib.error.HTTPError:
            raise
        except (OSError, urllib.error.URLError) as exc:
            raise StageError("Nexus request failed") from exc

    def readback(self, url: str, destination: Path) -> int | None:
        request = urllib.request.Request(  # noqa: S310 -- exact credential-free HTTPS URL.
            url,
            headers={"Accept": "application/octet-stream", "Authorization": self._authorization},
            method="GET",
        )
        try:
            response = self._open(request)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            exc.read(MAX_ERROR_BYTES)
            raise StageError(f"unexpected Nexus readback status: {exc.code}") from exc
        with response, destination.open("wb") as output:
            status = response.getcode()
            if status != 200:
                raise StageError(f"unexpected Nexus readback status: {status}")
            size = 0
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_CANDIDATE_BYTES:
                    raise StageError("Nexus readback exceeds the bounded candidate size")
                output.write(chunk)
        return size

    def upload(self, url: str, candidate: Path) -> None:
        request = urllib.request.Request(  # noqa: S310 -- exact credential-free HTTPS URL.
            url,
            data=candidate.read_bytes(),
            headers={
                "Accept": "application/json",
                "Authorization": self._authorization,
                "Content-Type": "application/gzip",
            },
            method="PUT",
        )
        try:
            response = self._open(request)
        except urllib.error.HTTPError as exc:
            exc.read(MAX_ERROR_BYTES)
            raise StageError(f"unexpected Nexus upload status: {exc.code}") from exc
        with response:
            status = response.getcode()
            if status not in {200, 201, 202, 204}:
                raise StageError(f"unexpected Nexus upload status: {status}")


class StageClient(Protocol):
    def readback(self, url: str, destination: Path) -> int | None:
        ...

    def upload(self, url: str, candidate: Path) -> None:
        ...


def stage(
    candidate: Path,
    base_url: str,
    repository: str,
    username: str,
    password: str,
    output: Path,
    *,
    client: StageClient | None = None,
) -> dict[str, object]:
    size, local_digest = require_candidate(candidate)
    normalized_url = repository_url(base_url, repository)
    remote_url = artifact_url(normalized_url, candidate.name)
    nexus = client or NexusClient(username, password)

    if output.exists() or output.is_symlink() or has_symlink_component(output.parent):
        raise StageError("Nexus staging output must start absent below a non-symlink parent")
    output.parent.mkdir(parents=True, exist_ok=True)
    readback = output.parent / f".{candidate.name}.nexus-readback"
    if readback.exists() or readback.is_symlink():
        raise StageError("Nexus readback destination already exists")
    uploaded = False
    try:
        remote_size = nexus.readback(remote_url, readback)
        if remote_size is None:
            nexus.upload(remote_url, candidate)
            uploaded = True
            remote_size = nexus.readback(remote_url, readback)
        if remote_size is None:
            raise StageError("Nexus artifact is absent after upload")
        if remote_size != size or sha256(readback) != local_digest:
            raise StageError("Nexus readback bytes differ from the exact local candidate")
    finally:
        if readback.exists() and not readback.is_symlink():
            readback.unlink()

    payload: dict[str, object] = {
        "apiVersion": API_VERSION,
        "kind": KIND,
        "repository": {
            "format": "ansiblegalaxy",
            "name": repository,
            "type": "hosted",
            "url": normalized_url,
        },
        "artifact": {
            "name": candidate.name,
            "sha256": f"sha256:{local_digest}",
            "size": size,
            "url": remote_url,
        },
        "readback": {
            "sha256": f"sha256:{local_digest}",
            "size": size,
            "verified": True,
        },
        "uploaded": uploaded,
    }
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--repository-url", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    try:
        payload = stage(
            args.candidate,
            args.repository_url,
            args.repository,
            os.environ.get("NEXUS_GALAXY_USERNAME", ""),
            os.environ.get("NEXUS_GALAXY_PASSWORD", ""),
            args.output,
        )
    except StageError as exc:
        parser.error(str(exc))
    artifact = payload["artifact"]
    assert isinstance(artifact, dict)
    print(f"Verified native Nexus Galaxy v3 readback for {artifact['name']} ({artifact['sha256']}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
