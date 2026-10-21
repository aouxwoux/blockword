# player accounts

i wanted a name and saved history to come back to. wallet-message login proves control of an address without giving the app that wallet's private key.

## how it works

the server creates a five-minute challenge bound to the app origin, wallet address, devnet chain id, browser cookie and expiry. it checks the full Ed25519-signed message, including the nonce. either supported nonce/message field order is accepted; the bytes still have to match.

a challenge can be used once, including when two verification requests arrive together. the server checks the current authentication key against devnet and supports rotated Ed25519 keys. an unfunded address is accepted only if it is derived from the signing key.

profiles keep an editable name. sessions expire after 24 hours; token hashes stay in the database and the browser gets an HttpOnly, SameSite=Strict cookie, also Secure over HTTPS. signing in again rotates this browser's session. the panel can revoke one session or sign out everywhere. login with a rotated key revokes older-key sessions; a key rotation alone does not immediately end web sessions.

## login and game wallets

login signs a message, sends no transaction and costs no gas. game transactions still use the separate server-held demo wallet shown on the board. the account panel shows the external wallet used for login.

linking this browser's history associates its verified rounds with the profile. it doesn't move assets or transfer control of the demo key. a linked demo history cannot silently be reassigned to someone else.

## account panel

1. open the app with a compatible Aptos Wallet Standard wallet using a standard Ed25519 account.
2. choose **player account**, select the wallet and switch it to devnet.
3. read and approve the sign-in message.
4. save a name and choose whether to link this browser's demo history.
5. view saved rounds or revoke sessions in the panel.

there is no wallet prompt on page load. keyless, generalized single-key, multisig and mobile deep-link login aren't supported. installed-extension login still needs an end-to-end compatibility check; the API and browser code were tested with real signatures and a mock wallet respectively.

## API

| method | path | use |
| --- | --- | --- |
| GET | `/api/auth/config` | network, key scheme and expiry periods |
| POST | `/api/auth/challenge` | create a challenge for `wallet_address` |
| POST | `/api/auth/verify` | check `challenge_id`, `public_key`, `signature` and `full_message` |
| GET | `/api/account/me` | read the profile |
| PATCH | `/api/account/me` | save `display_name` |
| GET | `/api/account/sessions` | list active sessions |
| DELETE | `/api/account/sessions/{id}` | revoke a session |
| POST | `/api/auth/logout` | end this session |
| POST | `/api/auth/logout-all` | end all player sessions |
| POST | `/api/account/link-demo` | link this browser's demo history |
| GET | `/api/account/rounds?limit=20&offset=0` | read saved verified rounds |

auth uses cookies. responses omit session tokens, challenge-binding tokens, game keys and answer backups. account login needs read access to devnet, not a deployer key. the wallet uses `aptos:signMessage` with optional envelope fields disabled; the server includes origin, wallet, network, nonce and expiry in the message itself. this is not the full SIWA/keyless flow.

## storage and limits

sqlite stores local data; `DATABASE_URL` selects postgres for the hosted app. the migration preserves existing sessions. upserts keep history links intact.

explicit game actions and recovery save rounds after reading verified chain state. page loads don't archive new history. **check & finish verification** can save an existing completed round; rounds replaced before this feature aren't rebuilt from an indexer.

saved history is a database copy of the chain result, not an independent proof. someone controlling the database can edit it, and a devnet reset can remove the original record. history queries are private to the linked profile.

challenge requests are limited to 10 per minute per direct peer address, verification to 20 and profile changes to 30. a challenge stops after five invalid signatures. forwarded IP headers are ignored, so proxy users may share a limit. hosted state survives app instances and redeployments while the database exists; its current expiry is **24 october 2026 at 17:46:59 UTC**.

the account-feature suite passed 63 python and 13 client tests. the hosted build later passed 87 python tests, including real postgres checks, and the same 13 client tests. [validation](validation.md) links the live signature, history and persistence receipts.

wallet discovery uses the unmodified Apache-2.0 `@wallet-standard/app` 1.1.1 package, vendored with its license and integrity hash. there is no frontend build step or CDN dependency.

references: [Petra message signing](https://petra.app/docs/signing-a-message), [aptos account authentication and rotation](https://aptos.dev/network/blockchain/accounts), [wallet-standard message contract](https://github.com/aptos-labs/wallet-standard/blob/main/src/features/aptosSignMessage.ts).
