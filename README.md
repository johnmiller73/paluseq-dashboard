# PALUSEQ drug resistance markers dashboard (DRC) – demo

> **Demonstration data – not real.** Every number in this repository is synthetic. It was generated
> to look like PALUSEQ antimalarial drug-resistance marker surveillance so that the dashboard's
> features can be shown. These are not PALUSEQ results and must not be cited or used for any decision.

**Live demo:** https://johnmiller73.github.io/paluseq-dashboard/ (once GitHub Pages is switched on, see below)

## What's here

| Path | What it is |
|---|---|
| `index.html` | The dashboard: a single static page (d3.js), served by GitHub Pages |
| `data/demo-data.js` | Synthetic data the page loads (963 rows: 107 markers × 9 provinces) |
| `data/paluseq_demo_synthetic.csv` | The same synthetic data as CSV |
| `openhexa/pipeline.py` | OpenHEXA pipeline that loads a PALUSEQ summaries workbook into the workspace database |
| `superset/paluseq_superset_dashboard.zip` | Apache Superset dashboard bundle (import via Dashboards → Import) |
| `superset/build_dashboard.py` | Optional script that builds the same Superset dashboard through its REST API |

## The dashboard

- Headline figures: provinces covered, markers monitored, samples carrying a WHO-validated k13 mutation,
  highest provincial prevalence of a validated k13 marker
- Heatmap of partner-drug markers (crt, mdr1, dhfr, dhps) by province
- Heatmap of WHO-listed k13 mutations detected, on a 0–5% colour scale
- Grouped bars for key SP and chloroquine/amodiaquine markers
- Filterable, sortable detail table (drug, province, detected only)

Hover over any cell or bar for mutant / genotyped counts. Prevalence = mutant samples ÷ samples genotyped.

## Switch on GitHub Pages

Settings → Pages → *Build and deployment*: Source **Deploy from a branch**, Branch **main**, folder **/ (root)** → Save.
The site appears at `https://<your-username>.github.io/paluseq-dashboard/` after a minute or two.
(GitHub Pages on a free account needs the repository to be public.)

To view it locally, just open `index.html` in a browser (it needs internet access to load d3 from jsDelivr).

## Using real data

1. Run the OpenHEXA pipeline on a PALUSEQ summaries workbook; it writes the table
   `paluseq_marker_prevalence` to the workspace database.
2. Export that table (province rows) as JSON and replace the array in `data/demo-data.js`,
   or point Superset at the table using the bundle in `superset/`.
3. Remove the "demonstration data" notices from `index.html` and this README.

Keep real surveillance data out of a public repository unless your data-sharing agreements allow it.

## About the synthetic data

Sample counts were drawn at random (150–900 per province and marker, ~6% not genotyped) and mutant counts
were drawn around marker frequencies of a realistic order of magnitude, with random province-to-province
variation. Rare k13 mutations appear in only a few provinces at low frequency. Province names are real;
the numbers, the report date and any patterns between provinces are not.
