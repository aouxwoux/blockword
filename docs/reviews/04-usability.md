# usability review

shortened notes from the `gpt-6-luna` review on 20 october 2026. this was a source review plus the saved narrow-layout preview, not a live interaction, device or screen-reader test.

## findings in the original client

1. receipt refresh cleared an unfinished guess through the shared action helper.
2. resubmission generated a fresh request id, so a lost response could consume another attempt.
3. loading `GET /api/state` could submit a reveal for a finished round. the read-looking action could publish the answer and use test gas.
4. the board used grid semantics without grid keyboard navigation. letter results and keyboard feedback needed spoken meanings and a live announcement.
5. the unwrapped phone header was likely to overflow at 320 px. this was inferred from CSS, not measured in a browser.
6. fetch/JSON failures could surface raw browser errors without a useful recovery step.
7. “permanent” wording overstated resettable devnet history.

the follow-up preserved drafts and pending ids, made state reads read-only, added **check & finish verification**, used table semantics and spoken feedback, allowed header wrapping and clarified connection errors and devnet limits. [the summary](../review-summary.md) links the other findings.

the saved preview showed the result and proof panel fitting a narrow layout, but did not show the masthead or establish 320 px behaviour. focus outlines and reduced-motion support were present in the source. broad device and assistive-technology checks remain separate work.

later ideas: practice without transactions, a clearer pending/failed transaction timeline, and examples or related terms on the glossary card.
