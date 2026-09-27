# India — AI Regulatory & Policy Corpus for Sandbox Training

Compiled 2026-09-26 · v1 downloads 2026-09-26 · v2 downloads 2026-09-27 · **COMPLETE**.

See `India_AI_Regulatory_Landscape.md` for the full annotated register.

## Files 

| # | File | Size | Source | Notes |
|---|---|---|---|---|
| 01 | IndiaAI Governance Guidelines (MeitY, Nov 2025) | 2.7 MB | PIB | canonical PDF |
| 02 | B6GA DPR — Bharat 6G Roadmap 2030 | 61 MB | B6GA | v2 fresh (v1 was 50 MB partial) |
| 03 | B6GA Brochure | 78 MB | B6GA | v2 fresh (v1 was 58 MB partial) |
| 04 | B6GA IPR Policy 2025 | 349 KB | B6GA | v1 |
| 05 | B6GA Annual Report 2025-26 | 11 MB | B6GA | v1 |
| 06 | B6GA Annual Report 2024-25 | 67 MB | B6GA | v1 |
| 07 | B6GA Annual Report 2023-24 | 14 MB | B6GA | v1 |
| 08 | B6GA MoA & Rules | 389 KB | B6GA | v1 |
| 09 | B6GA Apex Council MoC Outcome (Dec 2025) | 18 MB | B6GA | v1 |
| 10 | DPDP Act 2023 (eGazette, Act No. 22 of 2023) | 178 KB | eGazette | v2 |
| 11 | IT (Intermediary) Amendment Rules 2026 (SGI) | 218 KB | MeitY | v2 |
| 12 | TRAI AI & Big Data in Telecom — Recommendations (20 Jul 2023) | 1.0 MB | TRAI | v2 |
| 12a | TRAI Press Release No. 62/2023 (AI/BigData recs) | 119 KB | TRAI | v2 |
| 13 | TRAI TCCCPR Third Amendment 2026 — draft consultation (Mar 2026) | 3.1 MB | TRAI | v2 · replace when TRAI notifies final |
| 14 | TRAI recommendations landing page (HTML) | 335 KB | TRAI | v1 |
| 15a | Telecommunications Act 2023 (eGazette, Act No. 44 of 2023) | 206 KB | eGazette | v2 |
| 16 | BharatGen home (HTML) | 311 KB | bharatgen.com | v1 |
| 17 | Bhashini government initiative (HTML) | 89 KB | newkerala.com | v1 |
| 18 | MeitY IndiaAI Governance PIB press release (HTML) | 118 KB | PIB | v1 |

**Coverage across the six thematic areas:**

| Theme | Files |
|---|---|
| 1. AI in 6G / 5G — telecom stack | 02, 03, 04, 05, 06, 07, 08, 09, 12, 12a, 13, 14, 15a |
| 2. Multilingual LLM | 16, 17 |
| 3. RAG / grounding / SGI labelling | 01, 11 |
| 4. Data privacy — DPDP | 10 (with sectoral overlays in 12, 15a) |
| 5. Cross-border data usage | 10 (DPDP §16 blacklist), 12, 15a |
| 6. KSA gap-register crosswalk | see `India_AI_Regulatory_Landscape.md` §6 |

## Item 13 — planned replacement

Item 13 is currently the **draft (March 2026 consultation)** of the TRAI
TCCCPR Third Amendment because the final notified version was not on
TRAI's website as of 2026-09-27. When TRAI publishes the notified final
regulation (likely under
<https://www.trai.gov.in/release-publication/regulations>), download it
and replace `13_TRAI_TCCCPR_Third_Amendment_Draft_Mar2026.pdf` with
`13_TRAI_TCCCPR_Third_Amendment_Final_2026.pdf`.

## Next steps for the RAG index

1. **Extract text** from every PDF for the vector store:

   ```bash
   cd pdfs
   for f in *.pdf; do
     pdftotext -layout "$f" "${f%.pdf}.txt"
   done
   ```

2. **Attach metadata** — for each doc, record: `title`, `issuer`
   (MeitY / TRAI / DoT / B6GA / eGazette / PIB), `date`, `theme`
   (from the table above), and the source URL from
   `India_AI_Regulatory_Landscape.md` §7.
3. **Chunk clause-wise** for the Acts (10, 11, 15a) — Indian statute
   text is section-numbered; preserve section boundaries.
4. **Feed the KSA gap-register crosswalk** (§6 of the master `.md`) as
   a structured JSON overlay so the RAG can surface India-analogue
   citations when the KSA-side queries hit gap themes.
