# review notes

six `gpt-6-luna` reviews ran on 20 october 2026. these are internal review notes, not a security audit. the linked reports have been shortened; they describe the original prototype, before the fixes, accounts and hosted deployment.

| area | what came up | what changed |
| --- | --- | --- |
| [backend](reviews/01-backend.md) | a lost submit response could make a retry consume another guess; missing answers looked like network failures | save signed bytes, hash and request id before submission; return a specific error for missing/mismatched answers |
| [contract](reviews/02-contract.md) | the same retry bug crossed the chain boundary; the referee could still strand a round | fixed retries in python; kept Move unchanged and reran 13 contract tests; documented referee limits |
| [setup](reviews/03-deployment.md) | a saved key was mistaken for a completed deployment | check the account, chain, module digest and referee key before starting; deploy only when requested |
| [usability](reviews/04-usability.md) | refresh lost drafts, retries got new ids and GET state could reveal an answer | preserve drafts and ids; make state reads read-only; add explicit recovery and spoken letter feedback |
| [writing](reviews/05-writing.md) | permanence and learning-passport wording overstated what the demo provides | name devnet, use round counters and explain what recovery sends |
| [features](reviews/06-feature-scope.md) | more game modes would add work before saved rounds were useful | keep the notebook, replay check and hints on the next list; accounts and short demo hosting were added afterward |

after those fixes, 39 python tests and four client tests passed. the review also passed 13 local Move tests. no new deployment or live round was run during that review.

accounts and hosting came later. the hosted deployment passed 87 python tests, including six postgres checks, and 13 client tests. a live win, early reveal, account signature checks and persistence after redeploy also passed. [validation](validation.md) keeps the separate runs and receipts clear.

still open: installed-wallet compatibility, fully locked transitive dependencies, wallet-signed game transactions and referee timeout/recovery. the hosted app has durable state and cross-instance locking, but still holds demo game keys and knows the answers.
