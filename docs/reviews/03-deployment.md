# setup and packaging review

shortened notes from the `gpt-6-luna` review on 20 october 2026. it inspected public source files and the then-current zip locally, without reading runtime keys or querying devnet. the inventory and readiness below refer to that version.

## findings

- **P2: the launcher trusted the presence of a key file.** deployment saves its key before funding, tests, publish and configuration. a later failure left that file behind, so the next launch could skip incomplete setup. check the saved manifest and live module/configuration instead. this was fixed with the read-only setup checker and explicit `-Deploy` option.
- **P2: saved receipts only prove the recorded run.** the readme, manifest and compiled digest agreed, but devnet can reset. check current bytecode, configuration and receipts before presenting the contract as live.
- **P3: direct python packages were pinned, transitive dependencies were not fully locked.** record the tested python/CLI versions and add a reproducible dependency lock for broader distribution. this remains open.
- **P3: local key protection depended on filesystem permissions.** `chmod(0o600)` could fail silently and didn't establish a windows ACL. keep local data private and use managed secrets for hosting. the later vercel demo uses hosting secrets and private postgres state; local credentials are still plaintext.

the original archive had 25 files and matched the inspected source. it excluded keys, sqlite data, the virtual environment and generated contract output. that was a historical inventory; the archive has since grown with accounts, hosting and docs.

at review time the app was a one-worker localhost demo and public hosting wasn't ready. the later deployment added an explicit HTTPS origin, secure cookies, postgres persistence and cross-instance locking. [hosting](../hosting.md) describes that setup; it still uses server-held demo wallets.

before another chain deployment, check the network, referee key, backups, compiled bytecode and a live round. changed immutable contract code needs a new address.
