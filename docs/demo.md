# showing the demo

[open blockword](https://blockword-ps3-demo.vercel.app) before screen sharing so the app and database can wake up. the temporary database expires on **24 october 2026 at 11:16 pm IST**. no wallet extension is needed for the game.

my opening: "i wanted crypto terms to feel less like homework, so i made a word game. each guess gets recorded on aptos devnet."

1. show the word list. there are 22 five-letter terms.
2. start a round and open **answer committed**. the chain gets a hash; the answer and random salt stay in the backend until reveal.
3. submit a guess, explain the colours and open **guess recorded** to show the transaction.
4. finish the puzzle, or use **reveal & end round** if time is short. read the answer's definition.
5. open **round verified**. Move checked the commitment and every feedback row before updating the counters.

my closing: "python runs the app and signs the feedback. Move checks the round rules and final result. the referee still knows the answer, and the demo wallets are held by the server."

wallet login is optional. the live API was checked with a real Ed25519 signature, but an installed extension has not been tested end to end. skip that part unless it has been checked in the browser being used for the presentation.

## likely questions

**why use a chain?** the guesses, commitment and verified result can be inspected outside the app. the browser cannot silently rewrite those records while they remain available on devnet.

**is the answer secret?** the chain holds a salted commitment until reveal. a plain hash of one of 22 words would be easy to brute-force. the service knows the answer and could leak it.

**why isn't it all python?** aptos runs Move contracts. python handles the backend, scoring, storage, SDK calls and scripts.

**where is qwordle?** i chose the wordle branch of PS3. four-board play isn't in this build.

**what's next?** a notebook for completed terms, a replay checker and optional hints. wallet-signed game transactions and referee recovery need separate work.

## receipts to keep handy

- `../deployment.json`: address, publish/configuration transactions and bytecode hash.
- `hosted-game-verification.json`: completed hosted round and fullnode checks.
- `hosted-account-verification.json`: live signature and profile checks.
- `hosted-history-verification.json`: linked history and early reveal.
- `hosted-persistence-verification.json`: saved state after redeploy.
- `hosted-demo.png`: the browser's verified result.

devnet can reset. check the explorer before presenting; redeploy and rerun the smoke test if the module has disappeared. [hosting](hosting.md) explains the database expiry.
