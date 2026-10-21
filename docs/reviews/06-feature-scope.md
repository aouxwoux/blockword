# feature scope review

shortened notes from the `gpt-6-luna` review on 20 october 2026. this was a proposal for the original localhost prototype, not a list of completed features. [the current plan](../feature-plan.md) accounts for the later wallet-login and hosting work.

## fix the existing flow first

the review put lost-response retries, missing-answer recovery, draft preservation, read-only state and deployment checks ahead of new modes. those were bugs in the current experience. they have since been addressed; the [review summary](../review-summary.md) records the changes.

## suggested next features

| feature | first version | check before calling it done |
| --- | --- | --- |
| learning notebook | verified terms, definitions, outcomes and explorer links | entries survive reload; unfinished rounds stay out; unavailable devnet history is labelled |
| optional hint | one player-requested category clue with no guess cost | review every clue; it cannot print the answer or change the score |
| replay check | reconstruct the commitment and scoring from public events | an intact round passes; changing any proof input fails; missing history is distinct from a bad proof |

the original rough estimates were 3–5 days for the notebook, 2–4 for hints and 3–6 for replay, assuming one experienced developer and usable event retrieval. these were planning ranges, not deadlines. event availability and retention need checking before deciding the replay design.

## later decisions

wallet-signed games need player-controlled keys, rejection/pending recovery and full wallet tests. daily puzzles need a day boundary, commitment timing and an answer publication policy. four-board play needs a phone-layout prototype and measured storage, transaction and gas costs before any contract change.

the original review also deferred public hosting. a short vercel/neon demo now exists with persistence and locking; that does not make the trusted referee or server-held game keys suitable for competitive play.

no proposed notebook, hint or replay feature removes referee knowledge or guarantees that the answer stayed secret. avoid rewards, wagers and portable learning credentials. reuse the current Move events where possible, and only change the contract if those events cannot support the feature.
