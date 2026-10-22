# Security

* No MCP tool accepts a password, writes files, runs commands or syncs data in bulk.
* The Screener.in password is stored only in the operating-system keyring and sent only to
  Screener's own login form over HTTPS. The session cookie is kept in the keyring too.
* The only host contacted is `https://www.screener.in`.
* Report a vulnerability privately via GitHub's "Report a vulnerability" (Security tab) on this
  repository. Please don't open a public issue for security problems.
