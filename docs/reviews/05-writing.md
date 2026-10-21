# writing review

shortened notes from the `gpt-6-luna` review on 20 october 2026. it covered the readme, walkthrough, validation notes, browser copy and API errors.

the main issue was wording that promised more than the app did. “permanent” didn't fit devnet, “learning passport” sounded like a credential and some recovery messages hid whether an action sent a transaction. the follow-up changed those to devnet records, round counters and an explicit verification action.

other useful changes were to name python as the answer/feedback service, explain what Move checks, distinguish missing data from a network timeout and give letter feedback a spoken meaning. a counter does not prove learning, and signed feedback is provisional until reveal.

## voice for the repo

- use plain lowercase prose and short comments that explain a reason or a gotcha.
- skip comments that just repeat the next line of code.
- keep identifiers, commands, addresses and protocol names exact.
- give the next step in an error, especially if retrying could send a transaction.
- keep dates and receipts with test/deployment claims. first-person project rationale is fine; don't invent a personal testing history or describe model reviews as independent human review.
- say test APT and devnet where it matters. the server funds demo wallets; players aren't receiving money or a learning credential.

the current docs use this voice. the game interface keeps its existing labels and layout.
