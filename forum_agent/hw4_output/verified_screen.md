# Final output: eligibility screen, independently verified

Posting: fictional, 10 numbered lines (in `claims_answer_key.json`). Synthetic candidate: needs visa sponsorship (on F-1 OPT), based in Boston and willing to relocate, 6 years of product management in payments, MBA.

**Verdict: STOP: line 7 rules out visa sponsorship, and the candidate needs it. Other hard requirements (lines 4, 5) are met.**

Each claim below was checked by another student's agent (offer 232260, delivery 232694), and my agent checked that delivery against verdicts it sealed before asking (SHA-256 `99691223c9e9d99b2d79fe5ed3c7ff0f1d25b50a6a72272dbdeed628c26d3168`).

| Claim | Expected | Provider said | Lines cited | Match | Deciding line cited |
|---|---|---|---|---|---|
| C1. The role requires at least 5 years of product management experience in fintech or payments. | SUPPORTED | SUPPORTED | 4 | yes | yes |
| C2. The employer will sponsor an employment visa for this role. | NOT_SUPPORTED | NOT_SUPPORTED | 7 | yes | yes |
| C3. The role is fully remote. | NOT_SUPPORTED | NOT_SUPPORTED | 2 | yes | yes |
| C4. A bachelor's degree is required. | SUPPORTED | SUPPORTED | 5 | yes | yes |
| C5. Experience with SQL is a requirement for the role. | NOT_SUPPORTED | NOT_SUPPORTED | 6 | yes | yes |
| C6. The highest possible yearly pay, salary plus bonus, is $198,000. | SUPPORTED | SUPPORTED | 9 | yes | yes |
| C7. The role includes equity or stock options. | NOT_ADDRESSED | NOT_ADDRESSED | none | yes | yes |
| C8. A candidate who needs visa sponsorship cannot be hired for this role. | SUPPORTED | SUPPORTED | 7, 8 | yes | yes |

Result: 8 of 8 verdicts match; both deliberately false claims caught: yes; every cited line exists: yes.

The screen's STOP rests on line 7, and the provider's verdicts on C2 and C8 come from that same line, so the verdict now carries an independent check.
