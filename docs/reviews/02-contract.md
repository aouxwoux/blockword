# contract review

shortened notes from the `gpt-6-luna` review on 20 october 2026. files reviewed: `game.move`, `proofs.py`, `chain.py` and the app's permit/retry calls. all 13 Move tests passed from a scratch copy with aptos CLI 9.6.0. this was not a security audit.

the main finding was in submission recovery: losing the response after the node accepted a guess could make the app sign the retry as a new attempt. saving signed bytes and the request mapping before submission fixes that without changing Move. [the backend report](01-backend.md) covers the failure.

the review found no direct signature-replay or score-forgery path in the inspected flow. start permits bind the domain, deployment, player, round and commitment. guess permits also bind attempt, word and feedback. rounds are sequential, guesses are limited to six and a finished round rejects more guesses. reveal checks the hash and scores every row before updating counters. duplicate-letter scoring consumes exact matches first; python uses the matching BCS field order.

stored words and feedback are five bytes per row, with at most six rows. `forfeit` needs the player's signer and only ends that player's round. counter overflow would require an impractical number of games for this prototype.

the referee still chooses answers, knows them and can withhold or issue bad feedback. reveal prevents bad feedback from settling as verified, but the round can remain stuck. there is no referee timeout or replacement path. server-held game keys and saved-answer recovery are also part of the demo's trust model.

the review did not require a Move change for PS3 wordle. competitive play would need referee recovery, key separation and player-controlled transaction signing.
