#!/usr/bin/env python3
"""Publish the experience build as a GitHub release.

Does the whole chain with one token:
  1. GET /user                      -> who the token belongs to
  2. create <owner>/ios-on-rmx3366  -> only if it does not exist yet
  3. create (or reuse) the release  -> tag from --tag
  4. upload every asset             -> zip, system.apfs.001/.002, SHA256SUMS.txt

Token lookup order: --token, $GH_TOKEN, $GITHUB_TOKEN, ./.token.txt.
A classic token with the `repo` scope is required; fine-grained tokens cannot
create a new repository.  The token is never written to .git/config or to disk
by this script -- it lives in memory for the run only.

Usage
-----
    python tools/publish_release.py --owner <you> --dir release --tag exp-v1
    python tools/publish_release.py --owner <you> --dir release --dry-run
"""
import argparse
import http.client
import json
import os
import sys
import time
from urllib.parse import quote

API_HOST = "api.github.com"
UPLOAD_HOST = "uploads.github.com"
UA = "ios-on-rmx3366-publish-tool"
REPO_DEFAULT = "ios-on-rmx3366"
MIB = 1024 * 1024


def log(msg):
    print(msg, flush=True)


# ---------------------------------------------------------------- token


def read_token(explicit):
    if explicit:
        return explicit.strip()
    for var in ("GH_TOKEN", "GITHUB_TOKEN"):
        val = os.environ.get(var)
        if val:
            return val.strip()
    for cand in (".token.txt", os.path.join(os.path.dirname(__file__), "..", ".token.txt")):
        if os.path.exists(cand):
            with open(cand, encoding="utf-8") as f:
                return f.read().strip()
    return None


# ---------------------------------------------------------------- http


def api(method, path, token, body=None, timeout=120, host=API_HOST):
    conn = http.client.HTTPSConnection(host, timeout=timeout)
    headers = {
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": UA,
    }
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    try:
        conn.request(method, path, body=data, headers=headers)
        resp = conn.getresponse()
        raw = resp.read()
        status = resp.status
    finally:
        conn.close()
    try:
        parsed = json.loads(raw) if raw else {}
    except Exception:
        parsed = {"raw": raw[:500].decode("utf-8", "replace")}
    return status, parsed


class ProgressFile:
    """Wrap a file so the upload can report progress while http.client streams it."""

    def __init__(self, fh, total, label):
        self.fh = fh
        self.total = total
        self.label = label
        self.done = 0
        self._next = 128 * MIB

    def read(self, n=-1):
        buf = self.fh.read(n)
        if buf:
            self.done += len(buf)
            if self.done >= self._next:
                log("      %s  %.1f / %.1f MB  (%d%%)" % (
                    self.label, self.done / MIB, self.total / MIB, self.done * 100 // self.total))
                self._next += 128 * MIB
        return buf


def upload_asset(owner, repo, release_id, path, token, tries=3):
    name = os.path.basename(path)
    size = os.path.getsize(path)
    if size > 2 * 1024 * 1024 * 1024:
        raise SystemExit("%s is %.2f GiB: GitHub rejects assets over 2 GiB" % (name, size / 1024 / 1024 / 1024))
    path_q = "/repos/%s/%s/releases/%d/assets?name=%s" % (owner, repo, release_id, quote(name))
    last = None
    for attempt in range(1, tries + 1):
        log("    uploading %s (%.1f MB, attempt %d)" % (name, size / MIB, attempt))
        conn = http.client.HTTPSConnection(UPLOAD_HOST, timeout=None)
        conn.blocksize = 4 * MIB
        try:
            with open(path, "rb") as fh:
                body = ProgressFile(fh, size, name)
                conn.request("POST", path_q, body=body, headers={
                    "Authorization": "Bearer " + token,
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                    "User-Agent": UA,
                    "Content-Type": "application/octet-stream",
                    "Content-Length": str(size),
                })
                resp = conn.getresponse()
                raw = resp.read()
                status = resp.status
        except Exception as error:                     # network hiccup, retry
            last = error
            log("      %s: %s" % (type(error).__name__, error))
            time.sleep(3)
            continue
        finally:
            conn.close()
        if status in (201, 200):
            try:
                info = json.loads(raw)
                log("      ok: %s (%s)" % (info.get("name"), info.get("state")))
            except Exception:
                log("      ok")
            return True
        msg = raw[:300].decode("utf-8", "replace")
        last = msg
        log("      HTTP %d: %s" % (status, msg))
        if status == 422 and "already_exists" in msg:
            log("      asset already exists - delete it on the release page or rerun with --force-delete")
            return False
        time.sleep(3)
    log("    FAILED %s: %s" % (name, last))
    return False


# ---------------------------------------------------------------- main


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default="release", help="folder with the assets from make_release.py")
    ap.add_argument("--owner", help="GitHub user/org (default: whoever the token belongs to)")
    ap.add_argument("--repo", default=REPO_DEFAULT)
    ap.add_argument("--tag", default="exp-v1")
    ap.add_argument("--name", default="iOS 体验版 exp-v1 - 中文界面 / 无定时 / 无日志")
    ap.add_argument("--notes", default=None, help="markdown file for the release body")
    ap.add_argument("--private", action="store_true", help="create the repo as private")
    ap.add_argument("--token", default=None)
    ap.add_argument("--dry-run", action="store_true", help="print the plan, touch nothing")
    ap.add_argument("--skip-upload", action="store_true", help="create repo + release only")
    args = ap.parse_args()

    token = read_token(args.token)
    if not token and not args.dry_run:
        raise SystemExit("no token: pass --token, set GH_TOKEN, or write .token.txt")
    if token:
        log("token: %s... (%d chars)" % (token[:7], len(token)))

    folder = os.path.abspath(args.dir)
    assets = []
    if os.path.isdir(folder):
        for name in sorted(os.listdir(folder)):
            if os.path.isfile(os.path.join(folder, name)):
                assets.append(os.path.join(folder, name))
    if not assets:
        raise SystemExit("no assets in %s - run tools/make_release.py first" % folder)

    log("assets:")
    for a in assets:
        log("    %-36s %8.1f MB" % (os.path.basename(a), os.path.getsize(a) / MIB))

    if args.dry_run:
        log("")
        log("dry run: would verify the token, create %s/%s (public=%s), release %s, upload %d assets"
            % (args.owner or "<token owner>", args.repo, not args.private, args.tag, len(assets)))
        return 0

    status, me = api("GET", "/user", token)
    if status != 200:
        raise SystemExit("token rejected (HTTP %d): %s" % (status, me))
    owner = args.owner or me.get("login")
    log("owner: %s (token scopes: %s)" % (owner, "see X-OAuth-Scopes header if classic"))

    status, repo = api("GET", "/repos/%s/%s" % (owner, args.repo), token)
    if status == 200:
        log("repo exists: %s" % repo.get("html_url"))
    elif status == 404:
        log("creating repo %s/%s ..." % (owner, args.repo))
        status, repo = api("POST", "/user/repos" if owner == me.get("login") else "/orgs/%s/repos" % owner, token, {
            "name": args.repo,
            "description": "iOS 16.5 on realme RMX3366 (Snapdragon 870 / kona): port notes, tools and a one-click build.",
            "private": bool(args.private),
            "has_issues": True,
            "has_wiki": False,
        })
        if status not in (201, 200):
            raise SystemExit("create repo failed (HTTP %d): %s" % (status, repo))
        log("repo created: %s" % repo.get("html_url"))
    else:
        raise SystemExit("cannot read repo (HTTP %d): %s" % (status, repo))

    body = ""
    if args.notes and os.path.exists(args.notes):
        with open(args.notes, encoding="utf-8") as f:
            body = f.read()

    status, rel = api("GET", "/repos/%s/%s/releases/tags/%s" % (owner, args.repo, args.tag), token)
    if status == 200:
        log("release %s already exists: %s" % (args.tag, rel.get("html_url")))
    else:
        log("creating release %s ..." % args.tag)
        status, rel = api("POST", "/repos/%s/%s/releases" % (owner, args.repo), token, {
            "tag_name": args.tag,
            "name": args.name,
            "body": body or "See README and docs/ for the full notes.",
            "draft": False,
            "prerelease": True,
        })
        if status not in (201, 200):
            raise SystemExit("create release failed (HTTP %d): %s" % (status, rel))
        log("release created: %s" % rel.get("html_url"))

    if args.skip_upload:
        log("skipping upload as requested")
        return 0

    release_id = rel["id"]
    existing = {a["name"] for a in rel.get("assets", [])}
    ok = True
    for path in assets:
        name = os.path.basename(path)
        if name in existing:
            log("    %s already uploaded, skipping" % name)
            continue
        if not upload_asset(owner, args.repo, release_id, path, token):
            ok = False

    log("")
    log("release: %s" % rel.get("html_url"))
    if ok:
        log("all assets uploaded.")
        log("")
        log("next: delete .token.txt and revoke the token at https://github.com/settings/tokens")
    else:
        log("some assets failed - rerun to retry the missing ones.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
