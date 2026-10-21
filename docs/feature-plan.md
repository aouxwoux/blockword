# what i'd build next

wallet login, profiles and linked round history are already in the backend. public hosting is also done for this short demo. the earlier review proposed these before they existed; this is the remaining list.

| idea | first version | how i'd check it |
| --- | --- | --- |
| term notebook | turn saved verified rounds into a glossary with definitions, outcomes and explorer links | entries survive reload; unfinished rounds stay out; missing devnet history is labelled unavailable |
| replay checker | read the public events, recompute the commitment and score every guess without asking the live referee | the recorded round passes; changing the answer, salt, guess or feedback fails |
| optional hint | one category clue per round, requested by the player, with no attempt cost | it doesn't change the score or print the answer; review all 22 clues for accidental giveaways |

i'd start with the notebook. the saved-history API is there, but it needs a better browsing view. check event retrieval and retention before building replay around it. hints can wait until the clues are useful.

## later

- wallet-signed game transactions: players keep the game key. login alone doesn't do this. it needs pending-transaction recovery and full rounds tested with the wallet.
- daily puzzles: decide the day boundary, commitment publication and answer reveal policy first.
- four-board play: try the phone layout and measure transaction/gas costs before changing the contract.

referee outages, answer backups and operator/referee key separation still need work. none of the features above stops the referee from leaking an answer or withholding a signature. i'd keep rewards and wagers out of this project.

the [original scope review](reviews/06-feature-scope.md) explains where these ideas came from.
