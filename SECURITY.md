# Security Policy

## Supported versions

Only the latest release gets fixes. This is a small single-purpose tool, there
are no maintenance branches.

| Version | Supported |
| --- | --- |
| 3.x | yes |
| 2.x and earlier | no |

## Reporting

Report privately through
[GitHub Security Advisories](https://github.com/jslay88/qbt_migrate/security/advisories/new)
rather than opening a public issue.

Include the version, your platform, and what an attacker would be able to do.

## Scope

`qbt_migrate` reads and rewrites `.fastresume` files on the machine it runs on.
It makes no network calls and takes no untrusted remote input, so the realistic
surface is:

* Parsing untrusted `.fastresume` or `.torrent` files, which are bencoded and
  handled by [bencode.py](https://pypi.org/project/bencode.py/)
* Path handling, where a crafted path could cause a write outside the intended
  directory
* The published Docker image and its base

Data loss from a mistaken invocation is a bug, not a vulnerability. Open a
normal issue for that.
