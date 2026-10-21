# backend review

shortened notes from the `gpt-6-luna` review on 20 october 2026. this describes the original version; see [the fixes](../review-summary.md) for current status.

## findings

- **high: a lost submit response could consume another guess.** `Chain.call()` could reach the node, then fail before returning the hash. the app only saved receipts afterward, so retrying found no request id and signed the same word as the next attempt. the old timeout test began after the hash had been saved and missed this case. save the signed transaction and request mapping before broadcast, then recover or rebroadcast those bytes.
- **medium: a missing answer looked like a network error.** recovery returned a generic 503 and told the player to refresh. a missing or wrong-round backup needs a specific error and the original data restored; refreshing cannot fix it.

sqlite used transactional writes and hashed session tokens. the process-local lock only covered one worker. tests covered pending-confirmation recovery, but not every failed/unknown lookup path.

the review ran 19 python tests; all passed, with one Starlette/httpx deprecation warning. it sent no chain transactions. the later fixes added journal-before-submit recovery, specific backup errors and, for hosting, postgres coordination.
