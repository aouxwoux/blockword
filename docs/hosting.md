# hosting

live site: **https://blockword-ps3-demo.vercel.app**

vercel hobby runs the page and python API. neon postgres holds private state; aptos devnet runs the contract. no paid plan was selected. the page is public, and account endpoints require wallet login.

## database expiry

the database came from neon's claimable-project flow with postgres only. it required no account or payment details and expires at **2026-10-24 17:46:59 UTC / 24 october, 11:16 pm IST**. its limits are 100 MB storage and 1 GB transfer. the app will stop working normally when the database expires.

to keep it, claim the project into a neon account before expiry, update the rotated `DATABASE_URL` in vercel, redeploy and check a round. claiming alone isn't enough because it rotates credentials. no ownership transfer has been started. a replacement database starts empty unless the data is migrated.

## app and storage

`app.py` exports the same FastAPI app used locally. `vercel.json` selects FastAPI and limits requests to 60 seconds. postgres stores game keys, answers, signed transaction journals, profiles, challenges, sessions and history. these survive app instances and redeployments while the database exists.

local runs use sqlite without `DATABASE_URL`. vercel refuses that fallback. this demo uses a dedicated database.

short SQL transactions take a postgres transaction advisory lock for challenges, profiles and links. a separate transaction lock puts game requests, including operator funding, in order across instances. game journal writes commit separately before broadcast, so another instance can recover the same signed bytes after a lost response.

lock acquisition times out after ten seconds. the game lock has a two-minute idle transaction timeout to release locks left by an interrupted runtime. use the same coordination for every process sharing the database. don't run a separate local game server with the same operator key alongside the demo.

## configuration

| variable | value or purpose |
| --- | --- |
| `DATABASE_URL` | private postgres connection URL |
| `BLOCKWORD_OPERATOR_KEY` | private devnet operator/referee key |
| `BLOCKWORD_PUBLIC_ORIGIN` | `https://blockword-ps3-demo.vercel.app` |
| `BLOCKWORD_DATA_DIR` | `/tmp/blockword-data`; hosted game state is in postgres |

secrets were sent through CLI stdin and stored in vercel. the source zip excludes environment files, runtime data and vercel's local configuration. management credentials stay outside the deliverable folder. don't send real assets to demo accounts.

startup checks the recorded chain id, bytecode, operator address and referee key. it sends no transactions. a devnet reset or unavailable dependency can stop startup, so open the site before presenting.

the public HTTPS origin is explicit. host and cross-site mutation checks stay enabled; cookies are Secure, HttpOnly and SameSite=Strict. forwarded headers cannot rewrite login messages. the code can fall back to vercel's assigned URL inside vercel, but this deployment only enables the published canonical origin.

## checks and limits

a browser win, HTTP round with request replays, early reveal, live signature checks, linked history and persistence after redeploy all passed. [validation](validation.md) links the receipts. installed-wallet compatibility is still unverified; game play doesn't require an extension.

the service caps demo wallets at 12 and rounds per wallet at 20. login rate limits use direct peer addresses, so proxy users may share them. `/healthz` checks process liveness, not continuous chain availability.

`render.yaml` is an unused alternative, not the live setup.

references: [vercel FastAPI](https://vercel.com/docs/frameworks/backend/fastapi), [vercel and sqlite](https://vercel.com/kb/guide/is-sqlite-supported-in-vercel), [neon claimable projects](https://neon.com/claimable-neon), [neon connection pooling](https://neon.com/docs/connect/connection-pooling).
