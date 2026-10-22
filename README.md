# blockword

a small game that makes crypto terms easier to pick up. blockword gives you a five-letter word, six guesses, and a short explanation when the round ends. the guesses and final result are recorded on aptos devnet.

this is my take on **PS3: Wordle/Qwordle On-Chain**. i chose the wordle version and kept it to 22 terms. python runs the backend, scoring, storage, transactions and deployment scripts. the contract uses Move because that's what aptos runs.

## try it

**[open the demo](https://blockword-ps3-demo.vercel.app)**

the site and FastAPI backend run on vercel hobby. neon postgres stores profiles, game sessions, saved answers and transaction journals. 

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

- six guesses
- a separate answer and random 32-byte salt for every other round
- one aptos transaction per submitted guess
- saved game sessions and retries that reuse the same signed transaction. everything is backed up
- can link with wallet :3



## run locally
can run locally too, not sure if aptos contracts would work properly



