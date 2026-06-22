---
name: deterministic tarball builds + content-vs-rawbytes identity
description: why re-running a tarball builder yields different raw .tar.gz bytes even when contents are identical, and how to test/guard correctly
---

When a script builds a `.tar.gz` with `tarfile.open(fileobj=buf, mode="w:gz")`, the
outer gzip wrapper writes the **current time** into the gzip header `mtime` field. So
two runs that produce byte-identical tar CONTENT (same members, with member
`mtime/uid/gid/uname` pinned) still emit **different raw `.tar.gz` bytes** — the
difference is only the gzip-header timestamp (and any embedded source filename).

**Why this bites:** a fail-closed "don't overwrite an existing tarball with different
bytes" guard that compares `out.read_bytes() != new_bytes` will then fire on EVERY
re-run, because the raw bytes never match across processes. It looks like a
non-determinism bug in the build logic, but the tar payload is fully deterministic —
only the gzip envelope differs.

**How to apply:**
- To check whether two tarballs have the same *content*, compare their **decompressed
  members** (extract each member and diff), NOT the raw `.tar.gz` bytes. A member-level
  diff that says SAME while a raw-sha diff says DIFFER is this exact effect.
- A raw-byte overwrite guard on such artifacts is inherently fail-closed on re-run;
  that is acceptable (it protects frozen artifacts) but don't claim the build is
  "byte-deterministic" — it isn't, because of the gzip timestamp.
- If you actually need reproducible raw bytes, build gzip explicitly with a pinned
  timestamp and no filename:
  `with gzip.GzipFile(filename="", fileobj=buf, mode="wb", compresslevel=9, mtime=0) as gz:`
  then `with tarfile.open(fileobj=gz, mode="w") as tar: ...`.
- Frozen, already-validated tarballs whose recorded shas include a timestamped gzip
  header will NOT reproduce from a later (even deterministic) rebuild — leave them
  frozen and let the guard refuse the differing rebuild.
