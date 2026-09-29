# Slate Ping Explorer

An interactive dashboard of Slate CRM **Ping** data (page views on apply.dal.ca, www.dal.ca and virtualtour.dal.ca). It's a static site: plain HTML, one JSON data file, and two vendored JavaScript libraries. No build step, no server code.

```
index.html                     the dashboard
data/ping_dashboard_data.json  aggregated data the page loads
vendor/                        d3 v7.9.0 and d3-sankey 0.12.3 (ISC / BSD licences included)
scripts/build_data.py          rebuilds the JSON from a new Slate Ping export
.nojekyll                      tells GitHub Pages to serve files as-is
```

## Publish on GitHub Pages

1. Create a repository and add these files at its root (or in a `/docs` folder).
2. In the repository, go to **Settings → Pages**.
3. Under **Build and deployment**, choose **Deploy from a branch**, then pick `main` and `/ (root)` (or `/docs`).
4. Save. The site appears at `https://<user-or-org>.github.io/<repo>/` within a minute or two.

> **Visibility:** a GitHub Pages site is public on the internet unless your organization uses GitHub Enterprise Cloud with *private Pages* (access limited to repo members). The repository can be private while the site is still public. The page carries a `noindex` tag so search engines skip it, but anyone with the link can open it. See "What's in the data" below before publishing.

## Preview locally

The page loads its data with `fetch`, so it needs a web server. Double-clicking `index.html` won't work.

```bash
cd slate-ping-explorer
python3 -m http.server 8000
# open http://localhost:8000
```

## Refresh with a new export

1. In Slate, run the Ping query and export CSV with these columns, in this order:
   `Ping Referrer, Ping URL, Ping Timestamp, Ping Duration (seconds), Ping IP Address, Ping Identity, Ping UTM Campaign, Ping UTM Content, Ping UTM Medium, Ping UTM Source, Ping UTM Term`
2. Rebuild the data file (Python 3 with pandas and numpy; about 4 GB of free memory for ~2M rows):

   ```bash
   pip install pandas numpy
   python3 scripts/build_data.py "path/to/Pings Query.csv"
   ```

3. Commit the updated `data/ping_dashboard_data.json` and push. Pages redeploys automatically.

**Never commit the raw CSV.** The included `.gitignore` blocks `*.csv`. It holds IP addresses and full URLs, and once Person Reference IDs are added, row-level personal data.

## What's in the data

`ping_dashboard_data.json` holds **aggregates only**: counts by day or week, page section, arrival channel, program page, campaign and hour of day. It has no IP addresses, no person IDs and no row-level records. It does include internal operational detail, such as program-level interest, campaign names and volumes, and the application-funnel reach. Decide whether that's fine to publish before you make the site public.

## Method notes

- **Visit**: consecutive page views from one IP with gaps under 30 minutes. IP is a stand-in for a person until the Person Reference ID is added.
- **Sections** are assigned from the URL path; **channels** from the referrer host plus UTM fields. Both rule sets are in `scripts/build_data.py` and are easy to edit.
- **Hide staff tools & bots** removes Slate reader and staff pages, IPs where 20%+ of views are staff pages, and crawler-like IPs.
