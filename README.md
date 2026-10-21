# blockword

i wanted a small game that makes crypto terms easier to pick up. blockword gives you a five-letter word, six guesses, and a short explanation when the round ends. the guesses and final result are recorded on aptos devnet.

this is my take on **PS3: Wordle/Qwordle On-Chain**. i chose the wordle version and kept it to 22 terms. python runs the backend, scoring, storage, transactions and deployment scripts. the contract uses Move because that's what aptos runs.

## try it

**[open the demo](https://blockword-ps3-demo.vercel.app)**

the site and FastAPI backend run on vercel hobby. neon postgres stores profiles, game sessions, saved answers and transaction journals. no paid plan was selected.

the temporary database expires on **24 october 2026 at 11:16 pm IST** (17:46:59 UTC). the app needs that database. to keep the demo running, claim it and update the rotated credentials, or move the data to another database. details are in [hosting](docs/hosting.md).

start a round, open the word list and try a guess. finish the puzzle or choose **reveal & end round**, then open the final receipt. you don't need a wallet extension to play. wallet login is optional; installed-wallet compatibility still needs a manual check.

## deployment stack

| part | what i used |
| --- | --- |
| frontend | plain HTML, CSS and javascript, served by the same app; no frontend build step |
| backend | python 3.12 + FastAPI, using the official aptos python SDK for transactions |
| web hosting | vercel hobby, deployed through the vercel CLI; `app.py` is the entrypoint and `vercel.json` configures the python function |
| database | neon postgres for hosted sessions, profiles, saved answers and transaction journals; sqlite for local runs |
| blockchain | an immutable Move module on aptos devnet, published with the python deployment script and aptos CLI |
| login | Aptos Wallet Standard message signing, checked by the python backend; separate from game transaction signing |

the browser calls the FastAPI API on vercel. the API saves private state in neon and submits game transactions to aptos devnet. the website and contract are deployed separately. [hosting notes](docs/hosting.md) cover secrets, startup and database renewal.

## deployed contract

the hosted app reuses the original immutable devnet contract. its bytecode, chain id and referee key were checked again before the website was deployed.

<!-- deployment:start -->
**network:** Aptos devnet (chain ID 249)  
**module:** `0xd55b539adc2512a21d5e16b1757c99dd8f183dd4579fa4ad6fa609147312df8e::game`  
**contract address:** `0xd55b539adc2512a21d5e16b1757c99dd8f183dd4579fa4ad6fa609147312df8e`  
**verified:** 2026-10-20T05:47:37.277834+00:00

[view the contract](https://explorer.aptoslabs.com/account/0xd55b539adc2512a21d5e16b1757c99dd8f183dd4579fa4ad6fa609147312df8e/modules?network=devnet)

- publish transaction: `0x61ba797dba907e730ae043edbfa7ab87a70167005efa3c4cb1b21e385a72cfa5`
- referee configuration: `0xeb56dbf79f8320d0b36a207765ecc95271db36dc66efc1b0558a3b1a683ed3db`

the deployment script read the address and bytecode back from the fullnode. receipts are in `deployment.json`.
<!-- deployment:end -->

devnet uses test APT and can reset. if the module disappears, run deployment again. there are no entry fees, rewards or real-money deposits.

## what it does

- six guesses, repeated-letter scoring, a word list and an on-screen keyboard.
- a separate answer and random 32-byte salt for each round, committed before the first guess.
- one aptos transaction per submitted guess, with an explorer link.
- signature, player, round and attempt checks in Move. at reveal, the contract checks the commitment and scores every guess again before counting the result.
- saved game sessions and retries that reuse the same signed transaction. the journal is committed before submission, so losing a response does not require signing another guess.
- a definition after each round, plus wins and verified-round counts under the demo account.
- optional wallet-message login, editable profiles, revocable sessions and private history for linked demo accounts.

wallet login identifies a player. game transactions still use a separate wallet held by the server. qwordle, keyless/multisig login and wallet-signed game transactions are not implemented. see [player accounts](docs/player-accounts.md).

## run locally

you need python 3.12+, git, [aptos CLI](https://aptos.dev/build/cli/install-cli) 9.6.0 and an internet connection.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python scripts/check_deployment.py
python -m uvicorn blockword.app:app --host 127.0.0.1 --port 8000
```

open **http://127.0.0.1:8000**. on mac/linux, activate with `source .venv/bin/activate`.

the setup check only reads the deployment. a fresh checkout won't have the matching private operator key, so it will stop there. run `python scripts/deploy.py` to create your own devnet deployment, then repeat the check. pass `--aptos /path/to/aptos` if the CLI isn't on your PATH.

the first deployment creates an account, requests test APT, runs the Move tests, compiles and publishes the module, sets the referee key and updates `deployment.json` and this readme. the same key reuses the existing immutable module while it remains on devnet. changed contract code needs a new address.

on windows, the shortcut is:

```powershell
.\run.ps1
# to deploy first:
# .\run.ps1 -Deploy -AptosPath 'C:\path\to\aptos.exe'
```

the launcher checks the account, module, bytecode, chain id and referee key each time. it only deploys when `-Deploy` is passed.

### local data

without `DATABASE_URL`, the app uses sqlite in `.local/`. `BLOCKWORD_DATA_DIR` changes that directory; deployment and the app must use the same path.

this workspace keeps its runtime data outside the source folder. to use that existing local setup:

```powershell
$env:BLOCKWORD_DATA_DIR = (Resolve-Path ../../work/blockword-data).Path
```

that path is specific to this workspace. the source zip has no keys, database or environment files. another machine needs its own operator key and deployment.

keep the data directory private. local wallet/referee keys are plaintext credentials. losing the saved answer can leave a round unable to verify. don't send real assets to demo wallets.

### playing and recovery

1. start a round. the service creates a temporary wallet and adds 0.05 devnet APT from the operator account.
2. guess from the word list. green is the right spot, amber is another spot and grey means no unused copy of that letter remains.
3. solve it in six guesses, or reveal and end the round.
4. read the definition and open the verification receipt.

loading the page only reads state. **check & finish verification** checks saved requests and can send the answer if the round has ended. it keeps an unsubmitted draft. a missing answer backup needs the original data restored; refreshing cannot recreate it.

the first round needs funding, commitment, guess and reveal transactions. ending early adds a forfeit transaction. the service caps funding at 12 wallets and play at 20 rounds per wallet. wallets get another 0.05 test APT below a 0.03 balance; game transactions reserve up to 20,000 gas units.

run one worker locally. local host/origin checks allow localhost; the hosted app uses its configured public HTTPS origin and a postgres lock across instances. `render.yaml` is an unused hosting alternative. [hosting notes](docs/hosting.md) cover the live setup.

## how verification works

```text
python picks an answer + random salt
    -> signed commitment is recorded on aptos
    -> each guess includes signed feedback, up to six guesses
    -> Move checks the reveal hash and scores every guess again
    -> the verified result updates the account counters and emits an event
```

the commitment is SHA3-256 over a BCS structure with a domain tag, deployment address, player, round, answer and salt. permits bind the same identity fields to the exact payload; guess permits also include the attempt number. both scoring implementations consume exact matches before misplaced letters.

each player has `Game` and `Passport` resources. `RoundOpened`, `GuessRecorded` and `RoundVerified` events retain the recorded sequence when a new game replaces the current resource. the reveal event includes the answer and salt.

## limitations

- **temporary database:** the current neon database expires on **24 october 2026 at 11:16 pm IST**. the app depends on it; keeping the demo needs a claimed or replacement database and updated credentials.
- **resettable chain:** this is aptos devnet, not mainnet. a reset can remove the contract and receipts. startup checks can then fail until deployment is restored.
- **trusted referee:** python knows the answer and signs feedback. it can leak an answer, favour a player, withhold feedback or go offline. Move catches incorrect feedback at reveal, but cannot force the referee to finish a round. there is no timeout or replacement path.
- **server-held game keys:** wallet login only identifies a profile. the server still holds the demo game keys and signs transactions. operator/referee key separation and player-signed games need more work. losing the saved answer can leave a round unable to verify.
- **small-demo capacity:** game requests share a postgres lock, with a ten-second acquisition timeout. vercel requests are configured for at most 60 seconds. cold starts and chain confirmation can add delays. the app caps funding at 12 demo wallets and play at 20 rounds per wallet; it has not been load-tested for a large audience.
- **limited wallet coverage:** login supports standard Ed25519 accounts. keyless, multisig and mobile deep-link login are not supported. installed-wallet compatibility has not been checked end to end.
- **limited game scope:** 22 terms, one board and six guesses. no qwordle, daily puzzle, offline mode or rewards. game actions need the backend and devnet to be available.
- **history is a copy:** saved rounds in postgres come from verified chain state, but the history API is not an independent replay verifier. database access can change those copies, and account counters do not prove learning.

live feedback is provisional until final verification. this is a short demo with internal reviews and automated checks, not an independently audited competitive game. stronger secret storage, referee recovery and broader wallet/device testing would be needed for a public release beyond the demo.

## checks

```powershell
python -m pytest -q
node --test tests/client.test.cjs tests/accounts-client.test.cjs
aptos move test --package-dir contract --named-addresses blockword=0xcafe
```

for postgres integration checks, set `BLOCKWORD_TEST_DATABASE_URL` to a disposable database. those six tests skip when it is unset.

with the app running, `python scripts/smoke.py` plays a round using public feedback, retries each guess with the same request id and checks the receipts and final game resource against the fullnode.

the hosted deployment passed **87 python tests**, including six real postgres checks, and **13 client tests**. the contract review passed **13 Move tests**. live checks covered a win, an early reveal, account signatures, private history and persistence after redeployment. an installed wallet extension has not been tested end to end. [validation](docs/validation.md) has the dates and evidence; [review notes](docs/review-summary.md) track the earlier findings and fixes.

## files worth opening

| file | what's there |
| --- | --- |
| `blockword/app.py` | game routes and recovery |
| `blockword/game.py` | vocabulary and scoring |
| `blockword/proofs.py` | BCS encoding and signed permits |
| `blockword/chain.py` | aptos transactions and confirmation |
| `blockword/store.py`, `blockword/database.py` | sqlite/postgres storage and locking |
| `blockword/accounts.py`, `blockword/account_api.py` | wallet login, profiles, sessions and history |
| `contract/sources/game.move` | contract rules, events and tests |
| `static/` | browser client; no build step |
| `scripts/` | deployment, setup checks and live smoke test |
| `deployment.json`, `verification.json` | original devnet receipts |
| `docs/hosted-*-verification.json` | hosted demo checks |
| `docs/demo.md` | presentation walkthrough |

[next ideas](docs/feature-plan.md): a term notebook, an independent replay check and optional hints.
