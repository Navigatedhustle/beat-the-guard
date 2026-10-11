# Sources for booth stats

Checked 2026-09-23. Every figure in `app/stats.json` and in the mission takeaways must appear here, with the exact source. Don't add a number without a primary or first-hand source.

## EDUCAUSE: The Impact of AI on Work in Higher Education (2026)
Survey of 1,960 staff, administrators, and faculty across 1,800+ institutions, fielded fall 2025. Partners: EDUCAUSE, NACUBO, CUPA-HR, AIR.
- Report: https://www.educause.edu/research/2026/the-impact-of-ai-on-work-in-higher-education (the site blocks automated fetch, so figures were verified via the coverage below)
- Coverage quoting the figures: https://www.insidehighered.com/news/workplace/staff-issues/2026/01/13/data-shows-ai-disconnect-higher-ed-workforce
  - "56 percent of respondents reported using AI tools that are not provided by their institutions for work-related tasks"
  - "94 percent of higher education workers use AI tools", "only 54 percent are aware of their institution's AI use policies and guidelines"
  - "30 percent of cybersecurity and privacy professionals reported that they are not aware of policies"

## IBM: Cost of a Data Breach Report 2026
Study of 602 organizations breached between March 2025 and February 2026.
- Press release: https://newsroom.ibm.com/2026-07-29-ibm-study-one-in-four-malicious-breaches-are-ai-enabled,-costing-companies-6-million-on-average
  - "One in four malicious breaches were AI-enabled", "cost an average of $6 million", "global breach average of $4.99 million"
- Report page: https://www.ibm.com/reports/data-breach ($4.99M, "a 12% increase over last year")
- IBM X-Force analysis: https://www.ibm.com/think/x-force/2026-cost-of-a-data-breach-ai-adversaries-enterprise-risk
  - "the vast majority (92%) lacked proper AI access controls" (organizations reporting an AI-related breach)
  - "only 40% of organizations reported using access controls on AI models and data"
  - prompt injection attacks "led to average losses of … USD 5.89 million"

## EDUCAUSE: 2026 Top 10
- https://www.educause.edu/research-and-publications/research/top-10-it-issues-technologies-and-trends/2026
- https://er.educause.edu/articles/2025/10/2026-educause-top-10-making-connections
  - #1 Collaborative Cybersecurity, #5 Knowledge Management for Safer AI

## First-hand: over-blocking test (this project)
- `scripts/overblock_test.py`, results in `docs/overblock_test.json` (Sept 23, 2026). 48 requests: 6 missions × (2 compliant record wordings + 2 pending wordings, each leaving a different requirement open) × 2 request phrasings (formal and casual).
  - 24/24 fully compliant → YES
  - 24/24 one-requirement-pending → CONDITIONAL
  - An earlier 12-case run was also 12/12. Re-run before quoting if missions change.

## Deliberately not used
- "43% of incidents involve shadow AI" and "68% had no AI governance policy" (IBM 2026). These appeared only in secondary blogs and couldn't be confirmed on an IBM page.
